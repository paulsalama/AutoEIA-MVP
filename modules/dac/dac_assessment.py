"""
DAC Assessment — Core Analysis Engine
======================================
Implements the CEQR Chapter 23 screening workflow:

  1. LOCATE: Place project on map, generate ½-mile study area buffer
  2. IDENTIFY: Find DAC census tracts that intersect the study area
  3. CLASSIFY: Determine relationship (within DAC, proximate, or outside)
  4. SCREEN: Assess which CEQR technical areas could create pollution burden
  5. DETERMINE: Generate screening-level finding for EAF / determination of significance

This is a SCREENING module. It does not perform the full DACAT disproportionality
calculation (which requires comparing subject DAC to statewide/regional non-DAC
aggregate denominators). That is a Tier 2 analysis handled by burden_analyzer.py
when full indicator data is available.

Per CEQR Ch. 23 Section 320:
  - Study area = ½ mile from project area
  - If within or within ½ mile of DAC: "Is the project located within, or within
    ½-mile of, a disadvantaged community? Yes/No"
  - If >½ mile from DAC: "Could impacts from the project affect a disadvantaged
    community? Yes/No"
"""

import json
import math
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

try:
    from .dac_data_loader import DACDataLoader
except ImportError:
    # Loaded directly by AutoEIA module_loader (importlib, not package import)
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).parent))
    from dac_data_loader import DACDataLoader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ProximityClassification(str, Enum):
    """Project's spatial relationship to nearest DAC tract."""
    WITHIN = "within_dac"
    PROXIMATE = "proximate_to_dac"        # within ½ mile but not inside
    EXTENDED_PROXIMITY = "extended_proximity"  # > ½ mile but potential impact
    OUTSIDE = "outside_dac"               # no DAC tracts affected

class AssessmentLevel(str, Enum):
    """Required level of DAC analysis."""
    FULL_ASSESSMENT = "full_assessment"   # within or proximate → EIS-level analysis
    SCREENING_ONLY = "screening_only"     # extended proximity → narrative only
    NO_ASSESSMENT = "no_assessment"       # no DACs affected

class PollutionRelevance(str, Enum):
    """Whether a CEQR technical area could contribute to pollution burden."""
    HIGH = "high"       # direct pollution nexus (air, noise, hazmat)
    MODERATE = "moderate"  # indirect or cumulative (traffic, water/sewer)
    LOW = "low"         # minimal pollution pathway (land use, shadows)
    NONE = "none"


@dataclass
class DACTractResult:
    """Analysis results for a single DAC census tract."""
    geoid: str
    tract_name: str = ""
    county_name: str = ""
    distance_miles: float = 0.0
    is_within_project: bool = False
    is_within_buffer: bool = False
    indicator_count: int = 0
    top_burden_indicators: list = field(default_factory=list)
    top_vulnerability_indicators: list = field(default_factory=list)
    combined_score_percentile: Optional[float] = None
    burden_component_percentile: Optional[float] = None
    vulnerability_component_percentile: Optional[float] = None
    geometry: Optional[dict] = None  # GeoJSON geometry for mapping


@dataclass
class ScreeningDetermination:
    """The module's output determination."""
    project_within_dac: bool
    project_within_half_mile_of_dac: bool
    proximity_classification: str
    assessment_level_required: str
    dac_tracts_in_study_area: int
    nearest_dac_distance_miles: Optional[float]
    nearest_dac_geoid: Optional[str]
    pollution_relevant_technical_areas: list
    eaf_question_within_half_mile: str  # "Yes" or "No"
    eaf_question_could_affect: str       # "Yes" or "No" (for > ½ mile)
    rationale: str


# ---------------------------------------------------------------------------
# CEQR technical area → pollution relevance mapping
# ---------------------------------------------------------------------------

CEQR_POLLUTION_RELEVANCE = {
    # High: Direct air/noise/contamination pathway
    "air_quality": PollutionRelevance.HIGH,
    "noise": PollutionRelevance.HIGH,
    "hazardous_materials": PollutionRelevance.HIGH,
    "stationary_source_air": PollutionRelevance.HIGH,
    "mobile_source_air": PollutionRelevance.HIGH,
    "industrial_source_air": PollutionRelevance.HIGH,

    # Moderate: Indirect or cumulative pollution pathway
    "transportation_traffic": PollutionRelevance.MODERATE,
    "water_sewer": PollutionRelevance.MODERATE,
    "solid_waste": PollutionRelevance.MODERATE,
    "energy": PollutionRelevance.MODERATE,
    "construction": PollutionRelevance.MODERATE,
    "greenhouse_gas": PollutionRelevance.MODERATE,

    # Low: Minimal direct pollution pathway
    "land_use_zoning": PollutionRelevance.LOW,
    "socioeconomic": PollutionRelevance.LOW,
    "community_facilities": PollutionRelevance.LOW,
    "open_space": PollutionRelevance.LOW,
    "shadows": PollutionRelevance.LOW,
    "historic_cultural": PollutionRelevance.LOW,
    "urban_design_visual": PollutionRelevance.LOW,
    "natural_resources": PollutionRelevance.LOW,
    "neighborhood_character": PollutionRelevance.LOW,
    "public_health": PollutionRelevance.LOW,
}


# ---------------------------------------------------------------------------
# Geometry Helpers (pure Python — no GDAL/shapely dependency for MVP)
# ---------------------------------------------------------------------------

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points in miles.
    Uses the Haversine formula.
    """
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def polygon_centroid(coordinates: list) -> tuple:
    """
    Approximate centroid of a GeoJSON polygon (first ring only).
    Returns (lat, lon).
    """
    ring = coordinates[0] if coordinates else []
    if not ring:
        return (0.0, 0.0)
    n = len(ring)
    avg_lon = sum(p[0] for p in ring) / n
    avg_lat = sum(p[1] for p in ring) / n
    return (avg_lat, avg_lon)


def multipolygon_centroid(coordinates: list) -> tuple:
    """Approximate centroid of a GeoJSON MultiPolygon."""
    all_points = []
    for polygon in coordinates:
        ring = polygon[0] if polygon else []
        all_points.extend(ring)
    if not all_points:
        return (0.0, 0.0)
    n = len(all_points)
    return (sum(p[1] for p in all_points) / n, sum(p[0] for p in all_points) / n)


def feature_centroid(feature: dict) -> tuple:
    """Get approximate centroid (lat, lon) from a GeoJSON feature."""
    geom = feature.get("geometry", {})
    geom_type = geom.get("type", "")
    coords = geom.get("coordinates", [])

    if geom_type == "Point":
        return (coords[1], coords[0])
    elif geom_type == "Polygon":
        return polygon_centroid(coords)
    elif geom_type == "MultiPolygon":
        return multipolygon_centroid(coords)
    else:
        return (0.0, 0.0)


def point_in_polygon(lat: float, lon: float, polygon_coords: list) -> bool:
    """
    Ray-casting point-in-polygon test.
    polygon_coords is a GeoJSON polygon coordinate array (list of rings).
    """
    ring = polygon_coords[0] if polygon_coords else []
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]  # lon, lat
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_feature(lat: float, lon: float, feature: dict) -> bool:
    """Check if a point is inside a GeoJSON feature's geometry."""
    geom = feature.get("geometry", {})
    geom_type = geom.get("type", "")
    coords = geom.get("coordinates", [])

    if geom_type == "Polygon":
        return point_in_polygon(lat, lon, coords)
    elif geom_type == "MultiPolygon":
        return any(point_in_polygon(lat, lon, poly) for poly in coords)
    return False


def create_buffer_circle(lat: float, lon: float, radius_miles: float,
                         num_points: int = 64) -> dict:
    """
    Create a GeoJSON polygon approximating a circle buffer.
    Returns a GeoJSON Feature with the buffer polygon.
    """
    coords = []
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        # Approximate lat/lon offset
        dlat = (radius_miles / 69.0) * math.cos(angle)
        dlon = (radius_miles / (69.0 * math.cos(math.radians(lat)))) * math.sin(angle)
        coords.append([lon + dlon, lat + dlat])
    coords.append(coords[0])  # close the ring

    return {
        "type": "Feature",
        "properties": {
            "buffer_radius_miles": radius_miles,
            "center_lat": lat,
            "center_lon": lon,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [coords],
        },
    }


# ---------------------------------------------------------------------------
# Main Assessment Class
# ---------------------------------------------------------------------------

class DACAssessment:
    """
    Orchestrates the CEQR Chapter 23 Disadvantaged Communities screening.

    Usage:
        assessment = DACAssessment()
        result = assessment.run(
            project_location=(40.6782, -73.9442),  # lat, lon
            ceqr_technical_areas=["air_quality", "noise", "transportation_traffic"],
            project_description="Mixed-use development with 500 residential units",
        )
    """

    def __init__(self, data_loader: Optional[DACDataLoader] = None):
        self.data_loader = data_loader or DACDataLoader()
        self._dac_tracts = None

    def run(
        self,
        project_location: tuple,
        project_polygon: Optional[dict] = None,
        project_description: str = "",
        ceqr_technical_areas: Optional[list] = None,
        buffer_distance_miles: float = 0.5,
    ) -> dict:
        """
        Execute the full screening assessment.

        Args:
            project_location: (latitude, longitude) of project centroid
            project_polygon: Optional GeoJSON polygon of project boundary
            project_description: Text description of proposed action
            ceqr_technical_areas: List of CEQR technical areas with potential impacts
            buffer_distance_miles: Study area buffer (default 0.5 per Ch. 23 §320)

        Returns:
            dict with keys:
                - screening_determination: ScreeningDetermination
                - dac_tracts: list of DACTractResult
                - study_area_geojson: GeoJSON Feature of buffer polygon
                - dac_tracts_geojson: GeoJSON FeatureCollection of affected DAC tracts
                - eaf_responses: dict of pre-filled EAF answers
                - pollution_screening: dict of technical area relevance
        """
        lat, lon = project_location
        ceqr_areas = ceqr_technical_areas or []

        logger.info(
            f"Running DAC assessment for location ({lat}, {lon}) "
            f"with {buffer_distance_miles} mile buffer"
        )

        # Step 1: Load data
        dac_geojson = self.data_loader.load_dac_tracts()
        dac_features = dac_geojson.get("features", [])
        indicators = self.data_loader.load_indicators()

        # Step 2: Create study area buffer
        study_area = create_buffer_circle(lat, lon, buffer_distance_miles)

        # Step 3: Find DAC tracts within study area
        affected_tracts = self._identify_affected_tracts(
            lat, lon, dac_features, buffer_distance_miles, indicators
        )

        # Step 4: Classify proximity
        proximity = self._classify_proximity(lat, lon, affected_tracts, dac_features)

        # Step 5: Screen pollution relevance
        pollution_screening = self._screen_pollution_relevance(ceqr_areas)

        # Step 6: Generate determination
        determination = self._generate_determination(
            lat, lon, proximity, affected_tracts, pollution_screening, buffer_distance_miles
        )

        # Step 7: Generate EAF responses
        eaf_responses = self._generate_eaf_responses(
            determination, affected_tracts, pollution_screening
        )

        # Step 8: Build output GeoJSON
        dac_tracts_geojson = self._build_output_geojson(affected_tracts, dac_features)

        return {
            "screening_determination": asdict(determination),
            "dac_tracts": [asdict(t) for t in affected_tracts],
            "study_area_geojson": study_area,
            "dac_tracts_geojson": dac_tracts_geojson,
            "eaf_responses": eaf_responses,
            "pollution_screening": pollution_screening,
            "metadata": {
                "project_location": {"lat": lat, "lon": lon},
                "buffer_distance_miles": buffer_distance_miles,
                "ceqr_chapter": 23,
                "ceqr_chapter_title": "Effects on Disadvantaged Communities",
                "legislative_basis": "Environmental Justice Siting Law (EJSL)",
                "data_source": "NYS CJWG DAC designations (March 2023)",
            },
        }

    # ------------------------------------------------------------------
    # Step 3: Identify Affected Tracts
    # ------------------------------------------------------------------

    def _identify_affected_tracts(
        self,
        project_lat: float,
        project_lon: float,
        dac_features: list,
        buffer_miles: float,
        indicators: dict,
    ) -> list:
        """
        Find all DAC tracts within the buffer distance of the project.
        Returns list of DACTractResult ordered by distance.
        """
        affected = []

        for feature in dac_features:
            props = feature.get("properties", {})
            geoid = props.get("GEOID", props.get("geoid", props.get("GEOID20", "")))

            if not geoid:
                continue

            # Calculate distance from project to tract centroid
            tract_lat, tract_lon = feature_centroid(feature)
            distance = haversine_distance(project_lat, project_lon, tract_lat, tract_lon)

            # Check if within buffer (use generous 1.5x buffer to catch edge cases —
            # precise intersection requires real geometry library)
            if distance > buffer_miles * 1.5:
                continue

            # Check if project point is actually inside this tract
            is_within = point_in_feature(project_lat, project_lon, feature)

            # Build result
            tract_indicators = indicators.get(geoid, {})
            top_burden, top_vulnerability = self._rank_indicators(tract_indicators)

            result = DACTractResult(
                geoid=geoid,
                tract_name=props.get("NAME", props.get("name", "")),
                county_name=props.get("COUNTY", props.get("county", "")),
                distance_miles=round(distance, 3),
                is_within_project=is_within,
                is_within_buffer=distance <= buffer_miles or is_within,
                indicator_count=len(tract_indicators),
                top_burden_indicators=top_burden[:5],
                top_vulnerability_indicators=top_vulnerability[:5],
                combined_score_percentile=tract_indicators.get("combined_score"),
                burden_component_percentile=tract_indicators.get("burden_component"),
                vulnerability_component_percentile=tract_indicators.get(
                    "vulnerability_component"
                ),
                geometry=feature.get("geometry"),
            )
            affected.append(result)

        # Sort by distance
        affected.sort(key=lambda t: t.distance_miles)
        return affected

    @staticmethod
    def _rank_indicators(tract_indicators: dict) -> tuple:
        """
        Rank indicators by percentile value, split into burden vs vulnerability.
        Returns (top_burden, top_vulnerability) as lists of (name, percentile) tuples.
        """
        burden_factors = {
            "potential_pollution_exposure",
            "potential_climate_change_risk",
            "land_use_historic_discrimination",
        }
        vulnerability_factors = {
            "health_impacts_burdens",
            "housing_mobility_communications",
            "income",
            "race_ethnicity",
        }

        burden_scores = []
        vulnerability_scores = []

        for indicator, value in tract_indicators.items():
            if not isinstance(value, (int, float)):
                continue
            factor = DACDataLoader.get_indicator_factor(indicator)
            if factor in burden_factors:
                burden_scores.append((indicator, value))
            elif factor in vulnerability_factors:
                vulnerability_scores.append((indicator, value))

        burden_scores.sort(key=lambda x: x[1], reverse=True)
        vulnerability_scores.sort(key=lambda x: x[1], reverse=True)

        return burden_scores, vulnerability_scores

    # ------------------------------------------------------------------
    # Step 4: Classify Proximity
    # ------------------------------------------------------------------

    def _classify_proximity(
        self,
        project_lat: float,
        project_lon: float,
        affected_tracts: list,
        all_dac_features: list,
    ) -> ProximityClassification:
        """
        Determine the project's spatial relationship to DAC tracts.
        """
        # Check if project is physically inside any DAC tract
        for tract in affected_tracts:
            if tract.is_within_project:
                return ProximityClassification.WITHIN

        # Check if any DAC tracts are within the buffer
        tracts_in_buffer = [t for t in affected_tracts if t.is_within_buffer]
        if tracts_in_buffer:
            return ProximityClassification.PROXIMATE

        # Check extended proximity (up to 1 mile for large projects)
        tracts_nearby = [t for t in affected_tracts if t.distance_miles <= 1.0]
        if tracts_nearby:
            return ProximityClassification.EXTENDED_PROXIMITY

        return ProximityClassification.OUTSIDE

    # ------------------------------------------------------------------
    # Step 5: Screen Pollution Relevance
    # ------------------------------------------------------------------

    def _screen_pollution_relevance(self, ceqr_areas: list) -> dict:
        """
        For each CEQR technical area with potential impacts, classify
        its relevance to pollution burden in DACs.
        """
        screening = {}
        for area in ceqr_areas:
            normalized = area.lower().replace(" ", "_").replace("-", "_")
            relevance = CEQR_POLLUTION_RELEVANCE.get(
                normalized, PollutionRelevance.LOW
            )
            screening[area] = {
                "relevance": relevance.value,
                "could_contribute_to_pollution_burden": relevance in (
                    PollutionRelevance.HIGH,
                    PollutionRelevance.MODERATE,
                ),
            }

        # Summary
        high_relevance = [
            a for a, s in screening.items() if s["relevance"] == "high"
        ]
        moderate_relevance = [
            a for a, s in screening.items() if s["relevance"] == "moderate"
        ]

        screening["_summary"] = {
            "high_relevance_areas": high_relevance,
            "moderate_relevance_areas": moderate_relevance,
            "any_pollution_relevant": len(high_relevance) + len(moderate_relevance) > 0,
            "pollution_concern_level": (
                "high" if high_relevance
                else "moderate" if moderate_relevance
                else "low"
            ),
        }

        return screening

    # ------------------------------------------------------------------
    # Step 6: Generate Determination
    # ------------------------------------------------------------------

    def _generate_determination(
        self,
        lat: float,
        lon: float,
        proximity: ProximityClassification,
        affected_tracts: list,
        pollution_screening: dict,
        buffer_miles: float,
    ) -> ScreeningDetermination:
        """Generate the screening-level determination."""

        within = proximity == ProximityClassification.WITHIN
        proximate = proximity in (
            ProximityClassification.WITHIN,
            ProximityClassification.PROXIMATE,
        )
        tracts_in_buffer = [t for t in affected_tracts if t.is_within_buffer]
        nearest = affected_tracts[0] if affected_tracts else None

        # Assessment level
        if proximity == ProximityClassification.OUTSIDE:
            assessment_level = AssessmentLevel.NO_ASSESSMENT
        elif proximity == ProximityClassification.EXTENDED_PROXIMITY:
            assessment_level = AssessmentLevel.SCREENING_ONLY
        else:
            assessment_level = AssessmentLevel.FULL_ASSESSMENT

        # Pollution-relevant areas
        summary = pollution_screening.get("_summary", {})
        pollution_areas = (
            summary.get("high_relevance_areas", [])
            + summary.get("moderate_relevance_areas", [])
        )

        # Rationale
        rationale = self._build_rationale(
            proximity, tracts_in_buffer, nearest, pollution_areas, buffer_miles
        )

        return ScreeningDetermination(
            project_within_dac=within,
            project_within_half_mile_of_dac=proximate,
            proximity_classification=proximity.value,
            assessment_level_required=assessment_level.value,
            dac_tracts_in_study_area=len(tracts_in_buffer),
            nearest_dac_distance_miles=(
                round(nearest.distance_miles, 3) if nearest else None
            ),
            nearest_dac_geoid=nearest.geoid if nearest else None,
            pollution_relevant_technical_areas=pollution_areas,
            eaf_question_within_half_mile="Yes" if proximate else "No",
            eaf_question_could_affect=(
                "Yes"
                if proximity == ProximityClassification.EXTENDED_PROXIMITY
                else "No"
            ),
            rationale=rationale,
        )

    def _build_rationale(
        self,
        proximity: ProximityClassification,
        tracts_in_buffer: list,
        nearest: Optional[DACTractResult],
        pollution_areas: list,
        buffer_miles: float,
    ) -> str:
        """Build human-readable rationale for the determination."""

        if proximity == ProximityClassification.OUTSIDE:
            dist_note = ""
            if nearest:
                dist_note = (
                    f" The nearest DAC census tract ({nearest.geoid}) is "
                    f"approximately {nearest.distance_miles:.2f} miles from the "
                    f"project site."
                )
            return (
                f"The project is not located within or within {buffer_miles} miles of "
                f"a disadvantaged community as designated under the NYS Climate "
                f"Leadership and Community Protection Act.{dist_note} "
                f"No further DAC assessment is required under CEQR Chapter 23."
            )

        tract_count = len(tracts_in_buffer)
        geoids = ", ".join(t.geoid for t in tracts_in_buffer[:5])
        if tract_count > 5:
            geoids += f" (and {tract_count - 5} additional)"

        if proximity == ProximityClassification.WITHIN:
            location_phrase = "located within"
        elif proximity == ProximityClassification.PROXIMATE:
            location_phrase = f"located within {buffer_miles} miles of"
        else:
            location_phrase = "in extended proximity to"

        rationale = (
            f"The project is {location_phrase} {tract_count} disadvantaged "
            f"community census tract(s) ({geoids}) as designated under the NYS "
            f"Climate Leadership and Community Protection Act (CJWG, March 2023)."
        )

        if pollution_areas:
            areas_str = ", ".join(pollution_areas)
            rationale += (
                f" The proposed action has potential impacts in the following "
                f"pollution-relevant CEQR technical areas: {areas_str}. "
                f"Per ECL §8-0109 and §8-0113, the lead agency must evaluate "
                f"whether the proposed action may cause or increase a "
                f"disproportionate pollution burden on the affected DAC(s)."
            )
        else:
            rationale += (
                " No pollution-relevant CEQR technical areas have been identified "
                "at this screening stage. If subsequent analysis identifies "
                "potential air quality, noise, hazardous materials, or other "
                "pollution-related impacts, the DAC assessment should be revisited."
            )

        return rationale

    # ------------------------------------------------------------------
    # Step 7: Generate EAF Responses
    # ------------------------------------------------------------------

    def _generate_eaf_responses(
        self,
        determination: ScreeningDetermination,
        affected_tracts: list,
        pollution_screening: dict,
    ) -> dict:
        """
        Pre-populate answers for the DAC-related questions added to the
        Short and Full Environmental Assessment Forms under the proposed
        amendments to 6 NYCRR Part 617.
        """
        proximate = determination.project_within_half_mile_of_dac
        tracts_in_buffer = [t for t in affected_tracts if t.is_within_buffer]
        summary = pollution_screening.get("_summary", {})

        return {
            "short_eaf": {
                "project_within_or_half_mile_of_dac": (
                    "Yes" if proximate else "No"
                ),
                "could_impacts_affect_dac": (
                    "Yes"
                    if determination.eaf_question_could_affect == "Yes"
                    else "No"
                ),
            },
            "full_eaf": {
                "project_within_or_half_mile_of_dac": (
                    "Yes" if proximate else "No"
                ),
                "dac_census_tracts_affected": [
                    t.geoid for t in tracts_in_buffer
                ],
                "number_of_dac_tracts_in_study_area": len(tracts_in_buffer),
                "could_impacts_affect_dac": (
                    "Yes"
                    if determination.eaf_question_could_affect == "Yes"
                    else "No"
                ),
                "potential_pollution_types": (
                    summary.get("high_relevance_areas", [])
                    + summary.get("moderate_relevance_areas", [])
                ),
                "pollution_burden_assessment_required": (
                    determination.assessment_level_required == "full_assessment"
                    and summary.get("any_pollution_relevant", False)
                ),
            },
            "notes": (
                "These responses are auto-generated based on spatial analysis "
                "of the project location against NYS CJWG DAC designations "
                "(March 2023) and the CEQR Technical Manual Chapter 23 methodology. "
                "The lead agency should verify these responses and may adjust "
                "based on project-specific circumstances."
            ),
        }

    # ------------------------------------------------------------------
    # Step 8: Build Output GeoJSON
    # ------------------------------------------------------------------

    def _build_output_geojson(
        self, affected_tracts: list, dac_features: list
    ) -> dict:
        """
        Build a GeoJSON FeatureCollection of affected DAC tracts
        with assessment metadata in properties.
        """
        features = []
        for tract in affected_tracts:
            if not tract.is_within_buffer:
                continue

            # Find the original feature for full geometry
            geometry = tract.geometry
            if not geometry:
                # Try to find in original features
                for f in dac_features:
                    props = f.get("properties", {})
                    geoid = props.get("GEOID", props.get("geoid", props.get("GEOID20", "")))
                    if geoid == tract.geoid:
                        geometry = f.get("geometry")
                        break

            feature = {
                "type": "Feature",
                "properties": {
                    "geoid": tract.geoid,
                    "tract_name": tract.tract_name,
                    "county_name": tract.county_name,
                    "distance_miles": tract.distance_miles,
                    "is_project_within": tract.is_within_project,
                    "top_burden_indicators": [
                        {"indicator": name, "percentile": pct}
                        for name, pct in tract.top_burden_indicators
                    ],
                    "top_vulnerability_indicators": [
                        {"indicator": name, "percentile": pct}
                        for name, pct in tract.top_vulnerability_indicators
                    ],
                },
                "geometry": geometry,
            }
            features.append(feature)

        return {
            "type": "FeatureCollection",
            "features": features,
        }


# ---------------------------------------------------------------------------
# AutoEIA Platform Integration
# ---------------------------------------------------------------------------

def _load_report_generator():
    """Import DACReportGenerator — handles both package and direct-load contexts."""
    try:
        from .report_generator import DACReportGenerator
    except ImportError:
        from report_generator import DACReportGenerator
    return DACReportGenerator


def _create_visualization(result: dict, lat: float, lon: float,
                           buffer_miles: float) -> str:
    """
    Folium map showing project location, study area buffer, and DAC tracts.
    Consistent with other AutoEIA module visualizations (CartoDB positron basemap).
    """
    import folium

    det = result['screening_determination']
    proximate = det['project_within_half_mile_of_dac']
    n_tracts = det['dac_tracts_in_study_area']

    m = folium.Map(location=[lat, lon], zoom_start=14, tiles='CartoDB positron')

    # Study area buffer (dashed blue circle)
    folium.GeoJson(
        result['study_area_geojson'],
        name=f'Study Area ({buffer_miles} mi buffer)',
        style_function=lambda x: {
            'fillColor': '#3b82f6', 'color': '#1d4ed8',
            'weight': 2, 'fillOpacity': 0.06, 'dashArray': '6 4',
        },
        tooltip=f'{buffer_miles} mile study area (CEQR Ch. 23 §320)',
    ).add_to(m)

    # DAC tracts in study area
    dac_geojson = result['dac_tracts_geojson']
    if dac_geojson.get('features'):
        folium.GeoJson(
            dac_geojson,
            name='DAC Census Tracts (study area)',
            style_function=lambda x: {
                'fillColor': '#ef4444' if x['properties'].get('is_project_within')
                             else '#f97316',
                'color': '#b91c1c', 'weight': 2, 'fillOpacity': 0.45,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['geoid', 'distance_miles'],
                aliases=['Census Tract (GEOID):', 'Distance (mi):'],
                sticky=False,
            ),
        ).add_to(m)

    # Project location marker
    status = 'Within/proximate to DAC' if proximate else 'Not proximate to DAC'
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(
            f"<b>Project Site</b><br>{status}<br>"
            f"DAC tracts in study area: {n_tracts}",
            max_width=260,
        ),
        tooltip='Project Site',
        icon=folium.Icon(color='red' if proximate else 'blue',
                         icon='home', prefix='fa'),
    ).add_to(m)

    folium.LayerControl().add_to(m)
    return m._repr_html_()


def execute(inputs: dict) -> dict:
    """
    AutoEIA platform entry point — CEQR Chapter 23 DAC screening.

    Accepts building_geojson for project location (centroid extracted),
    consistent with the shadow and transportation module conventions.
    Fetches DAC tract data from local cache (datasets/nyc_dac_tracts.geojson)
    or from the NYS ArcGIS Feature Service on first run.
    """
    import json as _json
    import geopandas as _gpd
    from shapely.ops import unary_union as _unary_union

    building_geojson = inputs.get('building_geojson')
    if not building_geojson:
        raise ValueError("building_geojson is required")
    if isinstance(building_geojson, str):
        building_geojson = _json.loads(building_geojson)

    # Extract project centroid from footprint geometry
    building_gdf = _gpd.GeoDataFrame.from_features(building_geojson['features'])
    if building_gdf.crs is None:
        building_gdf.set_crs(epsg=4326, inplace=True)
    centroid = _unary_union(building_gdf.geometry).centroid
    lat, lon = centroid.y, centroid.x

    # Parse ceqr_technical_areas (array type arrives as JSON string from UI textarea)
    ceqr_areas_raw = inputs.get('ceqr_technical_areas')
    ceqr_areas = []
    if ceqr_areas_raw:
        if isinstance(ceqr_areas_raw, str):
            ceqr_areas = _json.loads(ceqr_areas_raw)
        elif isinstance(ceqr_areas_raw, list):
            ceqr_areas = ceqr_areas_raw

    buffer_miles = float(inputs.get('buffer_distance_miles') or 0.5)
    project_description = inputs.get('project_description') or ''

    # Run screening assessment
    result = DACAssessment().run(
        project_location=(lat, lon),
        project_description=project_description,
        ceqr_technical_areas=ceqr_areas,
        buffer_distance_miles=buffer_miles,
    )

    # Generate narrative report
    DACReportGenerator = _load_report_generator()
    report = DACReportGenerator().generate_screening_report(result)

    # Generate Folium map
    viz = _create_visualization(result, lat, lon, buffer_miles)

    return {
        'screening_determination': result['screening_determination'],
        'dac_tracts_geojson': result['dac_tracts_geojson'],
        'eaf_responses': result.get('eaf_responses', {}),
        'screening_report': report,
        'visualization': viz,
    }
