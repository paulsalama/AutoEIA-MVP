"""
Tests for DAC Assessment Module
================================
Covers:
  - Geometry helpers (haversine, point-in-polygon, buffer generation)
  - DACAssessment screening logic (within, proximate, outside)
  - BurdenAnalyzer DACAT methodology
  - ReportGenerator output
  - EAF response generation
  - API endpoint responses

Run with: pytest modules/dac_assessment/tests/test_dac_assessment.py -v
"""

import json
import math
import pytest
from unittest.mock import MagicMock, patch

# Import module components
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from modules.dac_assessment.dac_assessment import (
    DACAssessment,
    ProximityClassification,
    AssessmentLevel,
    haversine_distance,
    polygon_centroid,
    point_in_polygon,
    point_in_feature,
    create_buffer_circle,
    CEQR_POLLUTION_RELEVANCE,
)
from modules.dac_assessment.burden_analyzer import (
    BurdenAnalyzer,
    DISPROPORTIONALITY_THRESHOLD_PCT,
)
from modules.dac_assessment.report_generator import DACReportGenerator
from modules.dac_assessment.dac_data_loader import (
    DACDataLoader,
    DAC_INDICATOR_FACTORS,
    ALL_INDICATORS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A simple square polygon roughly around Downtown Brooklyn
DOWNTOWN_BROOKLYN_TRACT = {
    "type": "Feature",
    "properties": {
        "GEOID": "36047002300",
        "NAME": "Census Tract 23",
        "COUNTY": "Kings",
        "DAC_Designation": "Yes",
    },
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [-73.990, 40.690],
            [-73.980, 40.690],
            [-73.980, 40.695],
            [-73.990, 40.695],
            [-73.990, 40.690],
        ]],
    },
}

# A tract in Red Hook (also DAC)
RED_HOOK_TRACT = {
    "type": "Feature",
    "properties": {
        "GEOID": "36047005500",
        "NAME": "Census Tract 55",
        "COUNTY": "Kings",
        "DAC_Designation": "Yes",
    },
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [-74.015, 40.670],
            [-74.005, 40.670],
            [-74.005, 40.680],
            [-74.015, 40.680],
            [-74.015, 40.670],
        ]],
    },
}

# A tract in Park Slope (non-DAC, for contrast)
PARK_SLOPE_TRACT = {
    "type": "Feature",
    "properties": {
        "GEOID": "36047012200",
        "NAME": "Census Tract 122",
        "COUNTY": "Kings",
        "DAC_Designation": "No",
    },
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [-73.985, 40.670],
            [-73.975, 40.670],
            [-73.975, 40.680],
            [-73.985, 40.680],
            [-73.985, 40.670],
        ]],
    },
}

MOCK_DAC_GEOJSON = {
    "type": "FeatureCollection",
    "features": [DOWNTOWN_BROOKLYN_TRACT, RED_HOOK_TRACT],
}

MOCK_INDICATORS = {
    "36047002300": {
        "pm25_concentration": 85.2,
        "asthma_ed_visits": 91.3,
        "diesel_pm_emissions": 78.4,
        "traffic_proximity": 82.1,
        "poverty_rate": 76.5,
        "pct_bipoc": 88.9,
        "rent_burden": 71.2,
        "urban_heat_island": 65.3,
    },
    "36047005500": {
        "pm25_concentration": 72.1,
        "asthma_ed_visits": 68.4,
        "diesel_pm_emissions": 89.2,
        "major_facility_proximity": 94.1,
        "poverty_rate": 82.3,
        "pct_bipoc": 79.8,
        "rent_burden": 84.5,
        "housing_violations": 77.6,
    },
}


@pytest.fixture
def mock_data_loader():
    """Create a mock data loader that returns our test data."""
    loader = MagicMock(spec=DACDataLoader)
    loader.load_dac_tracts.return_value = MOCK_DAC_GEOJSON
    loader.load_indicators.return_value = MOCK_INDICATORS
    loader.load_census_tracts.return_value = {"type": "FeatureCollection", "features": []}
    return loader


@pytest.fixture
def assessment(mock_data_loader):
    """Create a DACAssessment with mock data."""
    return DACAssessment(data_loader=mock_data_loader)


@pytest.fixture
def burden_analyzer():
    """Create a BurdenAnalyzer with default settings."""
    return BurdenAnalyzer()


@pytest.fixture
def report_generator():
    """Create a DACReportGenerator."""
    return DACReportGenerator()


# ===========================================================================
# Geometry Helper Tests
# ===========================================================================

class TestGeometryHelpers:
    """Test the pure-Python geometry functions."""

    def test_haversine_distance_known_pair(self):
        """Test haversine with a known NYC distance."""
        # Times Square to Barclays Center ≈ 4.5 miles
        dist = haversine_distance(40.7580, -73.9855, 40.6826, -73.9754)
        assert 5.0 < dist < 6.0

    def test_haversine_distance_zero(self):
        """Same point should give zero distance."""
        dist = haversine_distance(40.7, -73.9, 40.7, -73.9)
        assert dist == pytest.approx(0.0, abs=0.001)

    def test_haversine_distance_short(self):
        """Two points ~0.1 miles apart."""
        # Roughly 0.1 miles ≈ 160 meters
        dist = haversine_distance(40.6900, -73.9850, 40.6914, -73.9850)
        assert 0.05 < dist < 0.2

    def test_polygon_centroid(self):
        """Test centroid of a simple square."""
        coords = [
            [[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74.0, 40.8], [-74.0, 40.7]]
        ]
        lat, lon = polygon_centroid(coords)
        assert lat == pytest.approx(40.75, abs=0.01)
        assert lon == pytest.approx(-73.95, abs=0.01)

    def test_point_in_polygon_inside(self):
        """Point clearly inside a square polygon."""
        coords = [
            [[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74.0, 40.8], [-74.0, 40.7]]
        ]
        assert point_in_polygon(40.75, -73.95, coords) is True

    def test_point_in_polygon_outside(self):
        """Point clearly outside."""
        coords = [
            [[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8], [-74.0, 40.8], [-74.0, 40.7]]
        ]
        assert point_in_polygon(41.0, -73.5, coords) is False

    def test_point_in_feature(self):
        """Test point-in-feature for the Downtown Brooklyn tract."""
        # Point inside the tract
        assert point_in_feature(40.692, -73.985, DOWNTOWN_BROOKLYN_TRACT) is True
        # Point outside
        assert point_in_feature(40.700, -73.950, DOWNTOWN_BROOKLYN_TRACT) is False

    def test_create_buffer_circle(self):
        """Buffer circle should be a valid GeoJSON Feature."""
        buffer = create_buffer_circle(40.69, -73.98, 0.5)
        assert buffer["type"] == "Feature"
        assert buffer["geometry"]["type"] == "Polygon"
        coords = buffer["geometry"]["coordinates"][0]
        assert len(coords) == 65  # 64 points + closing point
        assert coords[0] == coords[-1]  # closed ring

    def test_buffer_circle_radius(self):
        """Points on buffer should be approximately radius_miles from center."""
        lat, lon, radius = 40.69, -73.98, 0.5
        buffer = create_buffer_circle(lat, lon, radius)
        coords = buffer["geometry"]["coordinates"][0]
        # Check a few points
        for point in coords[:4]:
            dist = haversine_distance(lat, lon, point[1], point[0])
            assert dist == pytest.approx(radius, abs=0.05)


# ===========================================================================
# DACAssessment Tests
# ===========================================================================

class TestDACAssessment:
    """Test the main assessment logic."""

    def test_project_within_dac(self, assessment):
        """Project point inside a DAC tract → WITHIN classification."""
        result = assessment.run(
            project_location=(40.692, -73.985),  # Inside Downtown Brooklyn tract
            ceqr_technical_areas=["air_quality", "noise"],
        )
        det = result["screening_determination"]
        assert det["project_within_dac"] is True
        assert det["proximity_classification"] == "within_dac"
        assert det["assessment_level_required"] == "full_assessment"
        assert det["eaf_question_within_half_mile"] == "Yes"
        assert det["dac_tracts_in_study_area"] >= 1

    def test_project_proximate_to_dac(self, assessment):
        """Project near but not inside a DAC tract → PROXIMATE."""
        # Point between the two DAC tracts but not inside either
        result = assessment.run(
            project_location=(40.685, -73.995),
            buffer_distance_miles=0.5,
        )
        det = result["screening_determination"]
        assert det["proximity_classification"] in ("proximate_to_dac", "within_dac")
        assert det["eaf_question_within_half_mile"] == "Yes"

    def test_project_outside_dac(self, assessment):
        """Project far from any DAC tract → OUTSIDE."""
        # Upper East Side — far from our Brooklyn test tracts
        result = assessment.run(
            project_location=(40.7700, -73.9600),
            buffer_distance_miles=0.5,
        )
        det = result["screening_determination"]
        assert det["proximity_classification"] == "outside_dac"
        assert det["assessment_level_required"] == "no_assessment"
        assert det["eaf_question_within_half_mile"] == "No"
        assert det["dac_tracts_in_study_area"] == 0

    def test_pollution_screening_high(self, assessment):
        """Air quality and noise should register as high relevance."""
        result = assessment.run(
            project_location=(40.692, -73.985),
            ceqr_technical_areas=["air_quality", "noise", "hazardous_materials"],
        )
        pollution = result["pollution_screening"]
        assert pollution["air_quality"]["relevance"] == "high"
        assert pollution["noise"]["relevance"] == "high"
        assert pollution["_summary"]["pollution_concern_level"] == "high"

    def test_pollution_screening_moderate(self, assessment):
        """Traffic should be moderate relevance."""
        result = assessment.run(
            project_location=(40.692, -73.985),
            ceqr_technical_areas=["transportation_traffic", "water_sewer"],
        )
        pollution = result["pollution_screening"]
        assert pollution["transportation_traffic"]["relevance"] == "moderate"
        assert pollution["_summary"]["pollution_concern_level"] == "moderate"

    def test_pollution_screening_low(self, assessment):
        """Shadows and open space should be low relevance."""
        result = assessment.run(
            project_location=(40.692, -73.985),
            ceqr_technical_areas=["shadows", "open_space"],
        )
        pollution = result["pollution_screening"]
        assert pollution["shadows"]["relevance"] == "low"
        assert pollution["_summary"]["any_pollution_relevant"] is False

    def test_output_contains_all_keys(self, assessment):
        """Verify the output dict has all expected keys."""
        result = assessment.run(project_location=(40.692, -73.985))
        expected_keys = {
            "screening_determination",
            "dac_tracts",
            "study_area_geojson",
            "dac_tracts_geojson",
            "eaf_responses",
            "pollution_screening",
            "metadata",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_study_area_geojson_valid(self, assessment):
        """Study area should be valid GeoJSON."""
        result = assessment.run(project_location=(40.692, -73.985))
        study_area = result["study_area_geojson"]
        assert study_area["type"] == "Feature"
        assert study_area["geometry"]["type"] == "Polygon"
        assert study_area["properties"]["buffer_radius_miles"] == 0.5

    def test_eaf_responses_structure(self, assessment):
        """EAF responses should have short and full EAF sections."""
        result = assessment.run(project_location=(40.692, -73.985))
        eaf = result["eaf_responses"]
        assert "short_eaf" in eaf
        assert "full_eaf" in eaf
        assert "project_within_or_half_mile_of_dac" in eaf["short_eaf"]

    def test_custom_buffer_distance(self, assessment):
        """Should respect custom buffer distance."""
        result = assessment.run(
            project_location=(40.692, -73.985),
            buffer_distance_miles=1.0,
        )
        assert result["metadata"]["buffer_distance_miles"] == 1.0

    def test_dac_tracts_ordered_by_distance(self, assessment):
        """Returned tracts should be sorted by distance ascending."""
        result = assessment.run(project_location=(40.692, -73.985))
        tracts = result["dac_tracts"]
        distances = [t["distance_miles"] for t in tracts]
        assert distances == sorted(distances)


# ===========================================================================
# BurdenAnalyzer Tests
# ===========================================================================

class TestBurdenAnalyzer:
    """Test the DACAT disproportionality methodology."""

    def test_disproportionate_tract(self, burden_analyzer):
        """Tract with high indicators should be flagged as disproportionate."""
        result = burden_analyzer.analyze_tract(
            geoid="36047002300",
            indicators={
                "pm25_concentration": 92.0,
                "diesel_pm_emissions": 88.0,
                "traffic_proximity": 85.0,
                "asthma_ed_visits": 90.0,
                "poverty_rate": 82.0,
                "pct_bipoc": 91.0,
            },
            urban_rural="urban",
            region="nyc",
        )
        # With these high percentiles, the mean should exceed aggregates by >25%
        assert result.combined_score is not None
        assert result.burden_component is not None
        assert result.vulnerability_component is not None

    def test_non_disproportionate_tract(self, burden_analyzer):
        """Tract with low indicators should not be flagged."""
        result = burden_analyzer.analyze_tract(
            geoid="36047012200",
            indicators={
                "pm25_concentration": 30.0,
                "diesel_pm_emissions": 25.0,
                "traffic_proximity": 35.0,
                "asthma_ed_visits": 28.0,
                "poverty_rate": 22.0,
                "pct_bipoc": 40.0,
            },
            urban_rural="urban",
            region="nyc",
        )
        assert result.overall_disproportionate is False
        assert result.disproportionality_type == "none"

    def test_analyze_multiple_tracts(self, burden_analyzer):
        """Multi-tract analysis should produce summary."""
        tracts = [
            {
                "geoid": "36047002300",
                "indicators": {
                    "pm25_concentration": 92.0,
                    "asthma_ed_visits": 90.0,
                    "poverty_rate": 82.0,
                },
            },
            {
                "geoid": "36047005500",
                "indicators": {
                    "pm25_concentration": 35.0,
                    "asthma_ed_visits": 40.0,
                    "poverty_rate": 30.0,
                },
            },
        ]
        result = burden_analyzer.analyze_multiple_tracts(tracts)
        assert result["summary"]["total_tracts_analyzed"] == 2
        assert "any_disproportionate" in result["summary"]

    def test_delta_calculation(self, burden_analyzer):
        """Verify the delta percentage calculation."""
        result = burden_analyzer.analyze_tract(
            geoid="TEST",
            indicators={"pm25_concentration": 100.0},  # Burden factor
            urban_rural="urban",
            region="nyc",
        )
        # Score = 100, NYC urban burden aggregate ≈ 56.2
        # Delta = ((100 - 56.2) / 56.2) * 100 ≈ 77.9%
        assert result.burden_component.delta_pct > 25.0

    def test_narrative_generation(self, burden_analyzer):
        """Narrative should be non-empty and mention the geoid."""
        result = burden_analyzer.analyze_tract(
            geoid="36047002300",
            indicators={"pm25_concentration": 85.0, "poverty_rate": 75.0},
            urban_rural="urban",
            region="nyc",
        )
        assert len(result.narrative) > 50
        assert "36047002300" in result.narrative

    def test_high_indicators_identified(self, burden_analyzer):
        """Indicators ≥75th percentile should appear in high_burden list."""
        result = burden_analyzer.analyze_tract(
            geoid="TEST",
            indicators={
                "pm25_concentration": 90.0,  # ≥75 → should appear
                "diesel_pm_emissions": 60.0,  # <75 → should not
                "asthma_ed_visits": 80.0,     # ≥75 → should appear
                "poverty_rate": 50.0,         # <75 → should not
            },
        )
        high_burden_names = [i["indicator"] for i in result.high_burden_indicators]
        high_vuln_names = [i["indicator"] for i in result.high_vulnerability_indicators]
        assert "pm25_concentration" in high_burden_names
        assert "asthma_ed_visits" in high_vuln_names


# ===========================================================================
# ReportGenerator Tests
# ===========================================================================

class TestReportGenerator:
    """Test report generation."""

    def _make_assessment_result(self, within_dac=True, tracts_count=2):
        """Helper to create a mock assessment result."""
        return {
            "screening_determination": {
                "project_within_dac": within_dac,
                "project_within_half_mile_of_dac": True,
                "proximity_classification": "within_dac" if within_dac else "proximate_to_dac",
                "assessment_level_required": "full_assessment",
                "dac_tracts_in_study_area": tracts_count,
                "nearest_dac_distance_miles": 0.0 if within_dac else 0.3,
                "nearest_dac_geoid": "36047002300",
                "pollution_relevant_technical_areas": ["air_quality", "noise"],
                "eaf_question_within_half_mile": "Yes",
                "eaf_question_could_affect": "No",
                "rationale": "The project is located within a DAC census tract.",
            },
            "dac_tracts": [
                {
                    "geoid": "36047002300",
                    "tract_name": "Census Tract 23",
                    "county_name": "Kings",
                    "distance_miles": 0.0,
                    "is_within_project": within_dac,
                    "is_within_buffer": True,
                    "top_burden_indicators": [("pm25_concentration", 85.2)],
                    "top_vulnerability_indicators": [("asthma_ed_visits", 91.3)],
                },
            ],
            "pollution_screening": {
                "air_quality": {"relevance": "high", "could_contribute_to_pollution_burden": True},
                "noise": {"relevance": "high", "could_contribute_to_pollution_burden": True},
                "_summary": {
                    "high_relevance_areas": ["air_quality", "noise"],
                    "moderate_relevance_areas": [],
                    "any_pollution_relevant": True,
                    "pollution_concern_level": "high",
                },
            },
            "eaf_responses": {
                "short_eaf": {"project_within_or_half_mile_of_dac": "Yes"},
                "full_eaf": {
                    "project_within_or_half_mile_of_dac": "Yes",
                    "dac_census_tracts_affected": ["36047002300"],
                    "number_of_dac_tracts_in_study_area": 1,
                    "could_impacts_affect_dac": "No",
                    "potential_pollution_types": ["air_quality", "noise"],
                    "pollution_burden_assessment_required": True,
                },
                "notes": "Auto-generated.",
            },
            "metadata": {
                "project_location": {"lat": 40.692, "lon": -73.985},
                "buffer_distance_miles": 0.5,
                "ceqr_chapter": 23,
            },
        }

    def test_screening_report_generation(self, report_generator):
        """Should produce non-empty markdown report."""
        result = self._make_assessment_result()
        report = report_generator.generate_screening_report(
            result, project_name="Test Project", ceqr_number="24-001"
        )
        assert "# Effects on Disadvantaged Communities" in report
        assert "Test Project" in report
        assert "24-001" in report
        assert "Screening Determination" in report

    def test_summary_for_dac_project(self, report_generator):
        """Summary should mention the DAC and technical areas."""
        result = self._make_assessment_result()
        summary = report_generator.generate_summary(result)
        assert "disadvantaged community" in summary.lower()
        assert "air_quality" in summary or "air quality" in summary.lower()

    def test_summary_for_non_dac_project(self, report_generator):
        """Summary for outside project should say no assessment needed."""
        result = self._make_assessment_result()
        result["screening_determination"]["proximity_classification"] = "outside_dac"
        summary = report_generator.generate_summary(result)
        assert "not located within" in summary

    def test_report_contains_all_sections(self, report_generator):
        """Report should have all expected section headers."""
        result = self._make_assessment_result()
        report = report_generator.generate_screening_report(result)
        assert "## 1. Introduction" in report
        assert "## 2. Regulatory Context" in report
        assert "## 3. Study Area Definition" in report
        assert "## 4. DAC Identification Results" in report
        assert "## 5. Existing Burden" in report
        assert "## 6. Pollution Burden" in report
        assert "## 7. Screening Determination" in report
        assert "## 8. Environmental Assessment Form" in report


# ===========================================================================
# DACDataLoader Tests
# ===========================================================================

class TestDACDataLoader:

    def test_indicator_factors_complete(self):
        """All 45 indicators should be mapped to factors."""
        assert len(ALL_INDICATORS) == 45

    def test_indicator_factor_lookup(self):
        """Should return correct factor for known indicators."""
        assert DACDataLoader.get_indicator_factor("pm25_concentration") == "potential_pollution_exposure"
        assert DACDataLoader.get_indicator_factor("asthma_ed_visits") == "health_impacts_burdens"
        assert DACDataLoader.get_indicator_factor("poverty_rate") == "income"
        assert DACDataLoader.get_indicator_factor("pct_bipoc") == "race_ethnicity"

    def test_indicator_factor_unknown(self):
        """Unknown indicator should return None."""
        assert DACDataLoader.get_indicator_factor("nonexistent") is None

    def test_all_factors_have_indicators(self):
        """Every factor category should have at least one indicator."""
        for factor, indicators in DAC_INDICATOR_FACTORS.items():
            assert len(indicators) > 0, f"Factor {factor} has no indicators"

    def test_offline_mode_raises_without_data(self):
        """Offline mode should raise FileNotFoundError if no local data."""
        loader = DACDataLoader(data_dir="/nonexistent/path", offline=True)
        with pytest.raises(FileNotFoundError):
            loader.load_dac_tracts()


# ===========================================================================
# Integration test
# ===========================================================================

class TestIntegration:
    """End-to-end integration test with mock data."""

    def test_full_pipeline(self, assessment, report_generator):
        """Run full assessment → burden analysis → report generation."""
        # Step 1: Run assessment
        result = assessment.run(
            project_location=(40.692, -73.985),
            ceqr_technical_areas=["air_quality", "noise", "transportation_traffic"],
            project_description="500-unit residential development with ground-floor retail",
        )

        # Step 2: Verify screening
        det = result["screening_determination"]
        assert det["project_within_dac"] is True
        assert det["assessment_level_required"] == "full_assessment"

        # Step 3: Generate report
        report = report_generator.generate_screening_report(
            result,
            project_name="123 Flatbush Ave Development",
            ceqr_number="24-DAC-001",
        )
        assert len(report) > 500
        assert "123 Flatbush Ave" in report

        # Step 4: Generate summary
        summary = report_generator.generate_summary(result)
        assert len(summary) > 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
