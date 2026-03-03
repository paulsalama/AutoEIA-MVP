"""
DAC Assessment — CEQR Technical Manual Chapter 23
Effects on Disadvantaged Communities

Implements the Environmental Justice Siting Law (EJSL) screening workflow:
  1. LOCATE  — extract project centroid from building_geojson; build ½-mile buffer
  2. IDENTIFY — find NYS DAC census tracts intersecting the study area
  3. CLASSIFY — within / proximate / outside
  4. SCREEN   — assess which CEQR technical areas create pollution burden relevance
  5. REPORT   — generate EAF responses + narrative screening report

Data: NYS CJWG DAC designations (loaded from datasets/nyc_dac_tracts.geojson,
fetched from ArcGIS Feature Service on first run via fetch_data.py).

Legislative basis:
  - NYS Climate Leadership and Community Protection Act (2019)
  - Environmental Justice Siting Law (Ch. 840/2022, amended Ch. 49/2023)
  - Proposed amendments to 6 NYCRR Part 617 (effective Dec 30, 2024)
"""

import csv
import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data constants
# ---------------------------------------------------------------------------

# data.ny.gov Socrata API — Final Disadvantaged Communities (DAC) 2023
# Dataset: https://data.ny.gov/Energy-Environment/Final-Disadvantaged-Communities-DAC-2023/2e6c-s6fp
DAC_SOCRATA_URL = "https://data.ny.gov/resource/2e6c-s6fp.geojson"

# NYC borough county names as used in this dataset
NYC_COUNTIES = ("Bronx", "Kings", "New York", "Queens", "Richmond")

NYC_BBOX = {
    "xmin": -74.2591, "ymin": 40.4774,
    "xmax": -73.7004, "ymax": 40.9176,
}

DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "datasets"
DAC_TRACTS_FILE = "nyc_dac_tracts.geojson"
DAC_INDICATORS_FILE = "dac_indicators.csv"

# CJWG 45 indicators grouped by factor
DAC_INDICATOR_FACTORS = {
    "health_impacts_burdens": [
        "asthma_ed_visits", "cardiac_disease_hospitalizations", "copd_ed_visits",
        "heat_stress_ed_visits", "low_birth_weight", "premature_deaths",
        "self_reported_health",
    ],
    "housing_mobility_communications": [
        "broadband_access", "group_quarters", "housing_tenure",
        "linguistic_isolation", "mobile_homes", "overcrowding", "rent_burden",
    ],
    "income": [
        "educational_attainment", "poverty_rate", "unemployment_rate",
    ],
    "race_ethnicity": [
        "pct_bipoc",
    ],
    "land_use_historic_discrimination": [
        "brownfield_cleanup", "historic_redlining", "housing_violations",
        "industrial_land_use", "landfills_scrap_yards", "remediation_sites",
        "urban_heat_island", "water_body_impairments",
    ],
    "potential_climate_change_risk": [
        "coastal_flood_risk", "combined_sewer_overflows", "drought_risk",
        "floodplain_proximity", "heat_vulnerability", "inland_flood_risk",
        "wildfire_risk",
    ],
    "potential_pollution_exposure": [
        "air_toxics_cancer_risk", "air_toxics_respiratory_risk",
        "diesel_pm_emissions", "drinking_water_contamination",
        "hazardous_waste_proximity", "major_facility_proximity",
        "ozone_concentration", "pm25_concentration", "traffic_proximity",
        "truck_traffic", "wastewater_discharge", "water_quality_violations",
    ],
}

# Flat lookup: indicator_name → factor_name
_INDICATOR_TO_FACTOR = {
    ind: factor
    for factor, indicators in DAC_INDICATOR_FACTORS.items()
    for ind in indicators
}

# Maps data.ny.gov column names → internal indicator names
_FIELD_MAPPING = {
    "asthma_ed_rate": "asthma_ed_visits",
    "copd_ed_rate": "copd_ed_visits",
    "mi_hospitalization_rate": "cardiac_disease_hospitalizations",
    "low_birth_weight": "low_birth_weight",
    "premature_deaths": "premature_deaths",
    "internet_access": "broadband_access",
    "mobile_homes": "mobile_homes",
    "rent_percent_income": "rent_burden",
    "english_proficiency": "linguistic_isolation",
    "unemployment_rate": "unemployment_rate",
    "lmi_poverty_federal": "poverty_rate",
    "population_no_college": "educational_attainment",
    "redlining_updated": "historic_redlining",
    "industrial_land_use": "industrial_land_use",
    "landfills": "landfills_scrap_yards",
    "remediation_sites": "remediation_sites",
    "wastewater_discharge": "wastewater_discharge",
    "coastal_flooding_storm_risk": "coastal_flood_risk",
    "inland_flooding_risk": "inland_flood_risk",
    "days_above_90_degrees_2050": "heat_vulnerability",
    "particulate_matter_25": "pm25_concentration",
    "traffic_number_vehicles": "traffic_proximity",
    "traffic_truck_highways": "truck_traffic",
    "benzene_concentration": "air_toxics_cancer_risk",
    "rmp_sites": "major_facility_proximity",
    "scrap_metal_processing": "landfills_scrap_yards",
    "low_vegetative_cover": "urban_heat_island",
}

# CEQR technical area → pollution burden relevance
BURDEN_FACTORS = {
    "potential_pollution_exposure",
    "potential_climate_change_risk",
    "land_use_historic_discrimination",
}
VULNERABILITY_FACTORS = {
    "health_impacts_burdens",
    "housing_mobility_communications",
    "income",
    "race_ethnicity",
}


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

class DACDataLoader:
    """
    Loads DAC census tract boundaries and indicator data.
    Checks datasets/ for a local cache first; fetches from ArcGIS on first run.
    Run `python fetch_data.py` to pre-seed the cache.
    """

    def __init__(self, data_dir: Optional[str] = None, offline: bool = False):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.offline = offline
        self._dac_tracts = None
        self._indicators = None

    def load_dac_tracts(self, force_reload: bool = False) -> dict:
        if self._dac_tracts and not force_reload:
            return self._dac_tracts
        local = self.data_dir / DAC_TRACTS_FILE
        if local.exists():
            logger.info(f"Loading DAC tracts from {local}")
            self._dac_tracts = self._load_geojson(local)
            return self._dac_tracts
        if self.offline:
            raise FileNotFoundError(
                f"DAC tracts not found at {local}. Run fetch_data.py to download."
            )
        logger.info("Fetching DAC tracts from ArcGIS Feature Service...")
        self._dac_tracts = self._fetch_dac_tracts()
        return self._dac_tracts

    def load_indicators(self, force_reload: bool = False) -> dict:
        if self._indicators and not force_reload:
            return self._indicators
        local = self.data_dir / DAC_INDICATORS_FILE
        if local.exists():
            self._indicators = self._load_indicators_csv(local)
            return self._indicators
        # Fall back to extracting from GeoJSON properties
        self._indicators = self._extract_indicators_from_geojson(self.load_dac_tracts())
        return self._indicators

    def save_local_cache(self, dac_tracts: dict = None):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if dac_tracts:
            path = self.data_dir / DAC_TRACTS_FILE
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dac_tracts, f)
            logger.info(f"Saved DAC tracts to {path}")

    @staticmethod
    def get_indicator_factors() -> dict:
        return DAC_INDICATOR_FACTORS

    @staticmethod
    def get_all_indicators() -> list:
        return list(_INDICATOR_TO_FACTOR.keys())

    @staticmethod
    def get_indicator_factor(indicator_name: str) -> Optional[str]:
        return _INDICATOR_TO_FACTOR.get(indicator_name)

    @staticmethod
    def _load_geojson(path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _load_indicators_csv(path: Path) -> dict:
        indicators = {}
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                geoid = row.get("GEOID", row.get("geoid", ""))
                if not geoid:
                    continue
                tract = {}
                for col, val in row.items():
                    if col.lower() in ("geoid", "tract", "county", "name"):
                        continue
                    try:
                        tract[col] = float(val)
                    except (ValueError, TypeError):
                        tract[col] = val
                indicators[geoid] = tract
        return indicators

    @staticmethod
    def _extract_indicators_from_geojson(geojson: dict) -> dict:
        indicators = {}
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            geoid = props.get("GEOID", props.get("geoid", ""))
            if not geoid:
                continue
            tract = {}
            for key, val in props.items():
                # Try direct name match first, then field mapping
                norm = key.lower().replace(" ", "_")
                internal = _FIELD_MAPPING.get(norm, norm if norm in _INDICATOR_TO_FACTOR else None)
                if internal:
                    try:
                        tract[internal] = float(val)
                    except (ValueError, TypeError):
                        pass
                # Also pass through score fields verbatim for percentile lookups
                elif norm in ("combined_score", "burden_score_percentile",
                              "vulnerability_score_percentile", "percentile_rank_combined"):
                    try:
                        tract[norm] = float(val)
                    except (ValueError, TypeError):
                        pass
            if tract:
                indicators[geoid] = tract
        return indicators

    def _fetch_dac_tracts(self) -> dict:
        try:
            import requests
        except ImportError:
            raise ImportError(
                "`requests` library required for online fetching. pip install requests"
            )
        county_filter = " OR ".join(f"county='{c}'" for c in NYC_COUNTIES)
        params = {"$limit": 5000, "$where": county_filter}
        resp = requests.get(DAC_SOCRATA_URL, params=params, timeout=60)
        resp.raise_for_status()
        geojson = resp.json()
        logger.info(f"Fetched {len(geojson.get('features', []))} NYC tracts from data.ny.gov")
        self.save_local_cache(dac_tracts=geojson)
        return geojson


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ProximityClassification(str, Enum):
    WITHIN = "within_dac"
    PROXIMATE = "proximate_to_dac"
    EXTENDED_PROXIMITY = "extended_proximity"
    OUTSIDE = "outside_dac"

class AssessmentLevel(str, Enum):
    FULL_ASSESSMENT = "full_assessment"
    SCREENING_ONLY = "screening_only"
    NO_ASSESSMENT = "no_assessment"

class PollutionRelevance(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    NONE = "none"


@dataclass
class DACTractResult:
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
    geometry: Optional[dict] = None


@dataclass
class ScreeningDetermination:
    project_within_dac: bool
    project_within_half_mile_of_dac: bool
    proximity_classification: str
    assessment_level_required: str
    dac_tracts_in_study_area: int
    nearest_dac_distance_miles: Optional[float]
    nearest_dac_geoid: Optional[str]
    pollution_relevant_technical_areas: list
    eaf_question_within_half_mile: str
    eaf_question_could_affect: str
    rationale: str


# ---------------------------------------------------------------------------
# CEQR technical area → pollution relevance
# ---------------------------------------------------------------------------

CEQR_POLLUTION_RELEVANCE = {
    "air_quality": PollutionRelevance.HIGH,
    "noise": PollutionRelevance.HIGH,
    "hazardous_materials": PollutionRelevance.HIGH,
    "stationary_source_air": PollutionRelevance.HIGH,
    "mobile_source_air": PollutionRelevance.HIGH,
    "industrial_source_air": PollutionRelevance.HIGH,
    "transportation_traffic": PollutionRelevance.MODERATE,
    "water_sewer": PollutionRelevance.MODERATE,
    "solid_waste": PollutionRelevance.MODERATE,
    "energy": PollutionRelevance.MODERATE,
    "construction": PollutionRelevance.MODERATE,
    "greenhouse_gas": PollutionRelevance.MODERATE,
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
def _pct100(val) -> Optional[float]:
    """Convert a 0–1 decimal proportion to 0–100 percentage, pass through None."""
    if val is None:
        return None
    try:
        v = float(val)
        # Values already > 1 are assumed to already be 0–100
        return round(v * 100, 1) if v <= 1.0 else round(v, 1)
    except (TypeError, ValueError):
        return None


# Geometry helpers (pure Python — no Shapely dependency for spatial checks)
# ---------------------------------------------------------------------------

def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in miles."""
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def feature_centroid(feature: dict) -> tuple:
    geom = feature.get("geometry", {})
    coords = geom.get("coordinates", [])
    gtype = geom.get("type", "")
    if gtype == "Point":
        return (coords[1], coords[0])
    if gtype == "Polygon":
        ring = coords[0] if coords else []
        if not ring:
            return (0.0, 0.0)
        n = len(ring)
        return (sum(p[1] for p in ring) / n, sum(p[0] for p in ring) / n)
    if gtype == "MultiPolygon":
        pts = [p for poly in coords for p in poly[0]]
        if not pts:
            return (0.0, 0.0)
        n = len(pts)
        return (sum(p[1] for p in pts) / n, sum(p[0] for p in pts) / n)
    return (0.0, 0.0)


def point_in_feature(lat: float, lon: float, feature: dict) -> bool:
    geom = feature.get("geometry", {})
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", [])

    def _pip(ring):
        inside = False
        j = len(ring) - 1
        for i, (xi, yi) in enumerate(ring):
            xj, yj = ring[j]
            if ((yi > lat) != (yj > lat)) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    if gtype == "Polygon":
        return _pip(coords[0]) if coords else False
    if gtype == "MultiPolygon":
        return any(_pip(poly[0]) for poly in coords if poly)
    return False


def create_buffer_circle(lat: float, lon: float, radius_miles: float,
                          num_points: int = 64) -> dict:
    coords = []
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        dlat = (radius_miles / 69.0) * math.cos(angle)
        dlon = (radius_miles / (69.0 * math.cos(math.radians(lat)))) * math.sin(angle)
        coords.append([lon + dlon, lat + dlat])
    coords.append(coords[0])
    return {
        "type": "Feature",
        "properties": {"buffer_radius_miles": radius_miles, "center_lat": lat, "center_lon": lon},
        "geometry": {"type": "Polygon", "coordinates": [coords]},
    }


# ---------------------------------------------------------------------------
# Core assessment
# ---------------------------------------------------------------------------

class DACAssessment:
    """
    Orchestrates the CEQR Chapter 23 DAC screening.

    Usage:
        result = DACAssessment().run(
            project_location=(40.6782, -73.9442),
            ceqr_technical_areas=["air_quality", "noise"],
        )
    """

    def __init__(self, data_loader: Optional[DACDataLoader] = None):
        self.data_loader = data_loader or DACDataLoader()

    def run(self, project_location: tuple, project_polygon: Optional[dict] = None,
            project_description: str = "", ceqr_technical_areas: Optional[list] = None,
            buffer_distance_miles: float = 0.5) -> dict:
        lat, lon = project_location
        ceqr_areas = ceqr_technical_areas or []

        dac_features = self.data_loader.load_dac_tracts().get("features", [])
        indicators = self.data_loader.load_indicators()

        study_area = create_buffer_circle(lat, lon, buffer_distance_miles)
        affected = self._identify_affected_tracts(lat, lon, dac_features,
                                                   buffer_distance_miles, indicators)
        proximity = self._classify_proximity(lat, lon, affected)
        pollution = self._screen_pollution_relevance(ceqr_areas)
        determination = self._generate_determination(
            lat, lon, proximity, affected, pollution, buffer_distance_miles
        )
        eaf = self._generate_eaf_responses(determination, affected, pollution)
        dac_geojson = self._build_output_geojson(affected, dac_features)

        return {
            "screening_determination": asdict(determination),
            "dac_tracts": [asdict(t) for t in affected],
            "study_area_geojson": study_area,
            "dac_tracts_geojson": dac_geojson,
            "eaf_responses": eaf,
            "pollution_screening": pollution,
            "metadata": {
                "project_location": {"lat": lat, "lon": lon},
                "buffer_distance_miles": buffer_distance_miles,
                "ceqr_chapter": 23,
                "data_source": "NYS CJWG DAC designations (March 2023)",
            },
        }

    def _identify_affected_tracts(self, project_lat, project_lon, dac_features,
                                   buffer_miles, indicators) -> list:
        affected = []
        for feature in dac_features:
            props = feature.get("properties", {})
            # Skip non-DAC tracts (dataset contains all NYC tracts)
            if props.get("dac_designation") != "Designated as DAC":
                continue
            geoid = props.get("GEOID", props.get("geoid", props.get("GEOID20", "")))
            if not geoid:
                continue
            tract_lat, tract_lon = feature_centroid(feature)
            dist = haversine_distance(project_lat, project_lon, tract_lat, tract_lon)
            if dist > buffer_miles * 1.5:   # generous pre-filter; exact check below
                continue
            is_within = point_in_feature(project_lat, project_lon, feature)
            tract_indicators = indicators.get(geoid, {})
            burden, vuln = self._rank_indicators(tract_indicators)
            affected.append(DACTractResult(
                geoid=geoid,
                tract_name=props.get("NAME", props.get("name", props.get("city_town", ""))),
                county_name=props.get("COUNTY", props.get("county", "")),
                distance_miles=round(dist, 3),
                is_within_project=is_within,
                is_within_buffer=dist <= buffer_miles or is_within,
                indicator_count=len(tract_indicators),
                top_burden_indicators=burden[:5],
                top_vulnerability_indicators=vuln[:5],
                combined_score_percentile=_pct100(tract_indicators.get("percentile_rank_combined")),
                burden_component_percentile=_pct100(tract_indicators.get("burden_score_percentile")),
                vulnerability_component_percentile=_pct100(tract_indicators.get("vulnerability_score_percentile")),
                geometry=feature.get("geometry"),
            ))
        affected.sort(key=lambda t: t.distance_miles)
        return affected

    @staticmethod
    def _rank_indicators(tract_indicators: dict) -> tuple:
        burden, vuln = [], []
        for name, val in tract_indicators.items():
            if not isinstance(val, (int, float)):
                continue
            factor = _INDICATOR_TO_FACTOR.get(name)
            if factor in BURDEN_FACTORS:
                burden.append((name, val))
            elif factor in VULNERABILITY_FACTORS:
                vuln.append((name, val))
        burden.sort(key=lambda x: x[1], reverse=True)
        vuln.sort(key=lambda x: x[1], reverse=True)
        return burden, vuln

    def _classify_proximity(self, project_lat, project_lon, affected) -> ProximityClassification:
        for t in affected:
            if t.is_within_project:
                return ProximityClassification.WITHIN
        if any(t.is_within_buffer for t in affected):
            return ProximityClassification.PROXIMATE
        if any(t.distance_miles <= 1.0 for t in affected):
            return ProximityClassification.EXTENDED_PROXIMITY
        return ProximityClassification.OUTSIDE

    def _screen_pollution_relevance(self, ceqr_areas: list) -> dict:
        screening = {}
        for area in ceqr_areas:
            norm = area.lower().replace(" ", "_").replace("-", "_")
            rel = CEQR_POLLUTION_RELEVANCE.get(norm, PollutionRelevance.LOW)
            screening[area] = {
                "relevance": rel.value,
                "could_contribute_to_pollution_burden": rel in (
                    PollutionRelevance.HIGH, PollutionRelevance.MODERATE,
                ),
            }
        high = [a for a, s in screening.items() if s["relevance"] == "high"]
        mod = [a for a, s in screening.items() if s["relevance"] == "moderate"]
        screening["_summary"] = {
            "high_relevance_areas": high,
            "moderate_relevance_areas": mod,
            "any_pollution_relevant": len(high) + len(mod) > 0,
            "pollution_concern_level": "high" if high else "moderate" if mod else "low",
        }
        return screening

    def _generate_determination(self, lat, lon, proximity, affected,
                                 pollution, buffer_miles) -> ScreeningDetermination:
        within = proximity == ProximityClassification.WITHIN
        proximate = proximity in (ProximityClassification.WITHIN,
                                   ProximityClassification.PROXIMATE)
        in_buffer = [t for t in affected if t.is_within_buffer]
        nearest = affected[0] if affected else None

        if proximity == ProximityClassification.OUTSIDE:
            level = AssessmentLevel.NO_ASSESSMENT
        elif proximity == ProximityClassification.EXTENDED_PROXIMITY:
            level = AssessmentLevel.SCREENING_ONLY
        else:
            level = AssessmentLevel.FULL_ASSESSMENT

        summary = pollution.get("_summary", {})
        pollution_areas = (summary.get("high_relevance_areas", []) +
                           summary.get("moderate_relevance_areas", []))

        return ScreeningDetermination(
            project_within_dac=within,
            project_within_half_mile_of_dac=proximate,
            proximity_classification=proximity.value,
            assessment_level_required=level.value,
            dac_tracts_in_study_area=len(in_buffer),
            nearest_dac_distance_miles=round(nearest.distance_miles, 3) if nearest else None,
            nearest_dac_geoid=nearest.geoid if nearest else None,
            pollution_relevant_technical_areas=pollution_areas,
            eaf_question_within_half_mile="Yes" if proximate else "No",
            eaf_question_could_affect=(
                "Yes" if proximity == ProximityClassification.EXTENDED_PROXIMITY else "No"
            ),
            rationale=self._build_rationale(proximity, in_buffer, nearest,
                                             pollution_areas, buffer_miles),
        )

    @staticmethod
    def _build_rationale(proximity, tracts_in_buffer, nearest, pollution_areas,
                          buffer_miles) -> str:
        if proximity == ProximityClassification.OUTSIDE:
            note = ""
            if nearest:
                note = (f" The nearest DAC census tract ({nearest.geoid}) is "
                        f"approximately {nearest.distance_miles:.2f} miles away.")
            return (f"The project is not located within or within {buffer_miles} miles of "
                    f"a disadvantaged community under the NYS Climate Act.{note} "
                    f"No further DAC assessment is required under CEQR Chapter 23.")

        count = len(tracts_in_buffer)
        geoids = ", ".join(t.geoid for t in tracts_in_buffer[:5])
        if count > 5:
            geoids += f" (and {count - 5} additional)"

        loc = {"within_dac": "located within",
               "proximate_to_dac": f"located within {buffer_miles} miles of",
               "extended_proximity": "in extended proximity to"}.get(proximity.value, "near")

        rationale = (f"The project is {loc} {count} disadvantaged community census "
                     f"tract(s) ({geoids}) under the NYS Climate Act (CJWG, March 2023).")

        if pollution_areas:
            rationale += (f" Potential impacts in: {', '.join(pollution_areas)}. "
                          f"Per ECL §8-0109 and §8-0113, the lead agency must evaluate "
                          f"whether the action may cause or increase a disproportionate "
                          f"pollution burden on the affected DAC(s).")
        else:
            rationale += (" No pollution-relevant CEQR technical areas identified. "
                          "Revisit if air quality, noise, or hazmat impacts are found.")
        return rationale

    def _generate_eaf_responses(self, determination, affected, pollution) -> dict:
        proximate = determination.project_within_half_mile_of_dac
        in_buffer = [t for t in affected if t.is_within_buffer]
        summary = pollution.get("_summary", {})
        return {
            "short_eaf": {
                "project_within_or_half_mile_of_dac": "Yes" if proximate else "No",
                "could_impacts_affect_dac": determination.eaf_question_could_affect,
            },
            "full_eaf": {
                "project_within_or_half_mile_of_dac": "Yes" if proximate else "No",
                "dac_census_tracts_affected": [t.geoid for t in in_buffer],
                "number_of_dac_tracts_in_study_area": len(in_buffer),
                "could_impacts_affect_dac": determination.eaf_question_could_affect,
                "potential_pollution_types": (
                    summary.get("high_relevance_areas", []) +
                    summary.get("moderate_relevance_areas", [])
                ),
                "pollution_burden_assessment_required": (
                    determination.assessment_level_required == "full_assessment" and
                    summary.get("any_pollution_relevant", False)
                ),
            },
            "notes": (
                "Auto-generated from NYS CJWG DAC designations (March 2023) and "
                "CEQR Technical Manual Chapter 23. Verify before submission."
            ),
        }

    def _build_output_geojson(self, affected, dac_features) -> dict:
        features = []
        for tract in affected:
            if not tract.is_within_buffer:
                continue
            geometry = tract.geometry
            if not geometry:
                for f in dac_features:
                    props = f.get("properties", {})
                    gid = props.get("GEOID", props.get("geoid", props.get("GEOID20", "")))
                    if gid == tract.geoid:
                        geometry = f.get("geometry")
                        break
            # List top burden/vulnerability indicator names (values are relative, not statewide pct)
            burden_parts = [
                n.replace('_', ' ').title()
                for n, _ in tract.top_burden_indicators[:5]
            ]
            vuln_parts = [
                n.replace('_', ' ').title()
                for n, _ in tract.top_vulnerability_indicators[:3]
            ]
            features.append({
                "type": "Feature",
                "properties": {
                    "geoid": tract.geoid,
                    "tract_name": tract.tract_name or tract.geoid,
                    "county_name": tract.county_name,
                    "distance_miles": round(tract.distance_miles, 2),
                    "is_project_within": tract.is_within_project,
                    "combined_score_pct": tract.combined_score_percentile,
                    "burden_score_pct": tract.burden_component_percentile,
                    "vulnerability_score_pct": tract.vulnerability_component_percentile,
                    "top_burdens": " · ".join(burden_parts) if burden_parts else "See CJWG map",
                    "top_vulnerabilities": " · ".join(vuln_parts) if vuln_parts else "",
                },
                "geometry": geometry,
            })
        return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

class DACReportGenerator:
    """Generates CEQR Ch. 23 narrative screening reports."""

    def generate_screening_report(self, assessment_result: dict,
                                   project_name: str = "Proposed Action",
                                   applicant_name: str = "",
                                   ceqr_number: str = "",
                                   include_methodology: bool = True) -> str:
        det = assessment_result["screening_determination"]
        tracts = assessment_result["dac_tracts"]
        pollution = assessment_result["pollution_screening"]
        meta = assessment_result.get("metadata", {})
        eaf = assessment_result.get("eaf_responses", {})

        sections = [
            self._header(project_name, ceqr_number, applicant_name),
            self._introduction(det),
        ]
        if include_methodology:
            sections.append(self._regulatory_context())
        sections += [
            self._study_area(meta, det),
            self._dac_identification(det, tracts),
        ]
        if det["dac_tracts_in_study_area"] > 0:
            sections += [
                self._burden_profile(tracts),
                self._pollution_screening(pollution),
            ]
        sections += [
            self._determination(det),
            self._eaf_responses(eaf),
        ]
        return "\n\n".join(sections)

    def generate_summary(self, assessment_result: dict) -> str:
        det = assessment_result["screening_determination"]
        if det["proximity_classification"] == "outside_dac":
            return ("The proposed action is not located within or within ½ mile of a "
                    "disadvantaged community. No further assessment is warranted.")
        n = det["dac_tracts_in_study_area"]
        cls = det["proximity_classification"].replace("_", " ")
        summary = f"The proposed action is {cls} to {n} disadvantaged community census tract(s)."
        if det["pollution_relevant_technical_areas"]:
            areas = ", ".join(det["pollution_relevant_technical_areas"])
            summary += (f" Potential pollution-relevant impacts in: {areas}. "
                        f"Further assessment per CEQR Chapter 23 and EJSL is recommended.")
        return summary

    @staticmethod
    def _header(project_name, ceqr_number, applicant_name) -> str:
        lines = [
            "# Effects on Disadvantaged Communities — Screening Assessment",
            f"## {project_name}",
        ]
        if ceqr_number:
            lines.append(f"**CEQR Number:** {ceqr_number}")
        if applicant_name:
            lines.append(f"**Applicant:** {applicant_name}")
        lines.append(f"**Assessment Date:** {datetime.now().strftime('%B %d, %Y')}")
        lines.append("**CEQR Technical Manual Chapter:** 23 — Effects on Disadvantaged "
                     "Communities (December 2025 Edition)")
        return "\n\n".join(lines)

    @staticmethod
    def _introduction(det) -> str:
        cls = det["proximity_classification"]
        phrases = {
            "outside_dac": "the proposed action is **not located within or proximate to** a disadvantaged community",
            "within_dac": "the proposed action is **located within** a designated disadvantaged community",
            "proximate_to_dac": "the proposed action is **located within ½ mile of** a designated disadvantaged community",
        }
        finding = phrases.get(cls, "the proposed action is in **extended proximity** to a designated disadvantaged community")
        level = det["assessment_level_required"].replace("_", " ").title()
        return (
            "## 1. Introduction\n\n"
            "This assessment evaluates the potential effects of the proposed action "
            "on disadvantaged communities (DACs) as required by the Environmental "
            "Justice Siting Law (EJSL) and CEQR Technical Manual Chapter 23 "
            "(December 2025 Edition). The EJSL, effective December 30, 2024, requires "
            "lead agencies to consider whether an action may cause or increase a "
            "disproportionate pollution burden on a DAC as part of the SEQRA process.\n\n"
            f"Based on this screening, {finding}. "
            f"**Assessment level required: {level}.**"
        )

    @staticmethod
    def _regulatory_context() -> str:
        return (
            "## 2. Regulatory Context\n\n"
            "Under the NYS Climate Leadership and Community Protection Act (2019), "
            "the Climate Justice Working Group (CJWG) identified approximately 35% of "
            "NYS census tracts as disadvantaged communities using 45 indicators spanning "
            "environmental burdens, climate risks, health vulnerabilities, and "
            "socioeconomic characteristics.\n\n"
            "The Environmental Justice Siting Law (Ch. 840/2022, amended Ch. 49/2023) "
            "amends SEQRA (ECL Article 8) to require lead agencies to evaluate whether a "
            "proposed action may cause or increase a disproportionate pollution burden on "
            "a DAC — in both the determination of significance (ECL §8-0109) and in the "
            "preparation of an EIS (ECL §8-0113). DEC's proposed amendments to "
            "6 NYCRR Part 617 implement these requirements through updated EAF questions."
        )

    @staticmethod
    def _study_area(meta, det) -> str:
        loc = meta.get("project_location", {})
        buf = meta.get("buffer_distance_miles", 0.5)
        return (
            f"## 3. Study Area Definition\n\n"
            f"Per CEQR Ch. 23 §320, the study area is defined as the area within "
            f"**{buf} miles** of the project site.\n\n"
            f"**Project Location:** {loc.get('lat', 'N/A')}°N, {abs(loc.get('lon', 0))}°W\n\n"
            f"**Study Area Radius:** {buf} miles\n\n"
            f"**DAC Tracts in Study Area:** {det['dac_tracts_in_study_area']}"
        )

    @staticmethod
    def _dac_identification(det, tracts) -> str:
        lines = ["## 4. DAC Identification Results\n"]
        if det["dac_tracts_in_study_area"] == 0:
            lines.append("No DAC census tracts were identified within the study area.")
            if det.get("nearest_dac_geoid"):
                lines.append(f"\nNearest DAC tract ({det['nearest_dac_geoid']}) is "
                              f"~{det['nearest_dac_distance_miles']:.2f} miles away.")
            return "\n".join(lines)
        lines.append(f"The following {det['dac_tracts_in_study_area']} DAC tract(s) "
                     f"were identified:\n")
        lines.append("| Census Tract (GEOID) | Distance (mi) | Relationship |")
        lines.append("|---|---|---|")
        for t in tracts:
            if not t.get("is_within_buffer"):
                continue
            rel = "Project within tract" if t.get("is_within_project") else "Within study area"
            lines.append(f"| {t['geoid']} | {t['distance_miles']:.3f} | {rel} |")
        return "\n".join(lines)

    @staticmethod
    def _burden_profile(tracts) -> str:
        lines = ["## 5. Existing Burden and Vulnerability Profile\n"]
        for t in tracts:
            if not t.get("is_within_buffer"):
                continue
            lines.append(f"### Census Tract {t['geoid']}\n")
            burden = t.get("top_burden_indicators", [])
            vuln = t.get("top_vulnerability_indicators", [])
            if burden:
                lines.append("**Elevated Environmental Burden Indicators:**\n")
                for name, pct in burden[:5]:
                    lines.append(f"- {name.replace('_', ' ').title()}: {pct:.0f}th percentile statewide")
                lines.append("")
            if vuln:
                lines.append("**Elevated Population Vulnerability Indicators:**\n")
                for name, pct in vuln[:5]:
                    lines.append(f"- {name.replace('_', ' ').title()}: {pct:.0f}th percentile statewide")
                lines.append("")
            if not burden and not vuln:
                lines.append("*Detailed indicator data not available. See CJWG DAC map.*\n")
        return "\n".join(lines)

    @staticmethod
    def _pollution_screening(pollution) -> str:
        lines = ["## 6. Pollution Burden Relevance Screening\n"]
        summary = pollution.get("_summary", {})
        high = summary.get("high_relevance_areas", [])
        mod = summary.get("moderate_relevance_areas", [])
        if not high and not mod:
            lines.append("No CEQR technical areas with potential pollution relevance "
                         "identified at this stage. Revisit if air quality, noise, or "
                         "hazardous materials impacts are identified.")
            return "\n".join(lines)
        lines.append("The following CEQR technical areas may contribute to pollution "
                     "burden in the affected DAC(s):\n")
        if high:
            lines.append("**High Pollution Relevance:**\n")
            for a in high:
                lines.append(f"- {a.replace('_', ' ').title()}")
            lines.append("")
        if mod:
            lines.append("**Moderate Pollution Relevance:**\n")
            for a in mod:
                lines.append(f"- {a.replace('_', ' ').title()}")
            lines.append("")
        lines.append("Per ECL §8-0109 and §8-0113, the lead agency must evaluate "
                     "whether these impacts may cause or increase a disproportionate "
                     "pollution burden on the affected DAC(s).")
        return "\n".join(lines)

    @staticmethod
    def _determination(det) -> str:
        lines = [
            "## 7. Screening Determination\n",
            f"**EAF — Within ½ mile of DAC:** {det['eaf_question_within_half_mile']}\n",
        ]
        if det["eaf_question_could_affect"] == "Yes":
            lines.append(f"**EAF — Could impacts affect DAC:** {det['eaf_question_could_affect']}\n")
        lines.append(f"**Assessment Level Required:** "
                     f"{det['assessment_level_required'].replace('_', ' ').title()}\n")
        lines.append(f"**Rationale:**\n\n{det['rationale']}")
        return "\n".join(lines)

    @staticmethod
    def _eaf_responses(eaf) -> str:
        lines = [
            "## 8. Environmental Assessment Form Responses\n",
            "Pre-populated responses for updated EAF DAC questions "
            "(per proposed amendments to 6 NYCRR Part 617):\n",
            "### Short EAF\n",
        ]
        for k, v in eaf.get("short_eaf", {}).items():
            lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        lines.append("\n### Full EAF\n")
        for k, v in eaf.get("full_eaf", {}).items():
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v) if v else "None"
            lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        if eaf.get("notes"):
            lines.append(f"\n*{eaf['notes']}*")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AutoEIA Platform Integration
# ---------------------------------------------------------------------------

def _burden_color(score) -> str:
    """Map combined burden score (0–100 percentile) to a red-yellow gradient."""
    if score is None:
        return '#9ca3af'   # gray — no data
    if score >= 85:
        return '#b91c1c'   # dark red
    if score >= 70:
        return '#dc2626'   # red
    if score >= 55:
        return '#ea580c'   # dark orange
    if score >= 40:
        return '#f97316'   # orange
    return '#fbbf24'       # yellow


def _create_visualization(result: dict, lat: float, lon: float,
                           buffer_miles: float) -> str:
    """
    Folium map showing:
    - DAC census tracts colored by cumulative environmental burden score
    - ½-mile study area buffer
    - Project location with assessment result
    """
    import folium

    det = result['screening_determination']
    proximate = det['project_within_half_mile_of_dac']
    n_tracts = det['dac_tracts_in_study_area']
    classification = det.get('proximity_classification', '')

    m = folium.Map(location=[lat, lon], zoom_start=13, tiles='CartoDB positron')

    # --- Study area buffer ---
    folium.GeoJson(
        result['study_area_geojson'],
        name=f'½-Mile Study Area',
        style_function=lambda x: {
            'fillColor': '#3b82f6', 'color': '#1d4ed8',
            'weight': 2.5, 'fillOpacity': 0.04, 'dashArray': '8 4',
        },
        tooltip=f'{buffer_miles}-mile study area (CEQR Ch. 23 §320)',
    ).add_to(m)

    # --- DAC tracts colored by burden score ---
    dac_geojson = result['dac_tracts_geojson']
    if dac_geojson.get('features'):
        folium.GeoJson(
            dac_geojson,
            name='Disadvantaged Community Tracts',
            style_function=lambda x: {
                'fillColor': _burden_color(x['properties'].get('combined_score_pct')),
                'color': '#7f1d1d',
                'weight': 1.5,
                'fillOpacity': 0.65,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[
                    'geoid', 'county_name', 'distance_miles',
                    'combined_score_pct', 'burden_score_pct',
                    'vulnerability_score_pct', 'top_burdens',
                ],
                aliases=[
                    'Census Tract:', 'County:', 'Distance from project (mi):',
                    'Combined Burden Score (statewide pct):',
                    'Environmental Burden (statewide pct):',
                    'Population Vulnerability (statewide pct):',
                    'Highest Burden Indicators:',
                ],
                sticky=True,
                max_width=360,
            ),
        ).add_to(m)

    # --- Project location marker ---
    if proximate:
        status_line = (
            f"⚠️ Within ½ mile of {n_tracts} DAC tract{'s' if n_tracts != 1 else ''}"
            if not det.get('project_within_dac')
            else f"⚠️ Project site is WITHIN a DAC"
        )
        marker_color = 'red'
    else:
        status_line = "✅ Not proximate to a DAC"
        marker_color = 'blue'

    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(
            f"<b>Project Site</b><br>{status_line}<br>"
            f"<span style='color:#6b7280;font-size:11px'>"
            f"Assessment required: {det['assessment_level_required'].replace('_', ' ').title()}"
            f"</span>",
            max_width=280,
        ),
        tooltip='Project Site — click for result',
        icon=folium.Icon(color=marker_color, icon='building', prefix='fa'),
    ).add_to(m)

    # --- Legend ---
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;
                background:white;border:1px solid #d1d5db;border-radius:8px;
                padding:12px 16px;font-family:sans-serif;font-size:12px;
                box-shadow:0 2px 6px rgba(0,0,0,0.15);min-width:190px">
      <b style="font-size:13px">Cumulative Burden Score</b>
      <div style="color:#6b7280;font-size:11px;margin-bottom:8px">(statewide percentile)</div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <div><span style="display:inline-block;width:16px;height:12px;background:#b91c1c;border-radius:2px;margin-right:6px"></span>85th+ percentile — most burdened</div>
        <div><span style="display:inline-block;width:16px;height:12px;background:#ea580c;border-radius:2px;margin-right:6px"></span>55–84th percentile</div>
        <div><span style="display:inline-block;width:16px;height:12px;background:#fbbf24;border-radius:2px;margin-right:6px"></span>Below 55th percentile</div>
        <div><span style="display:inline-block;width:16px;height:12px;background:#9ca3af;border-radius:2px;margin-right:6px"></span>No data</div>
      </div>
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid #e5e7eb;color:#6b7280;font-size:10px">
        Source: NYS CJWG DAC 2023 · CEQR Ch. 23
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    folium.LayerControl().add_to(m)
    return m._repr_html_()


def execute(inputs: dict) -> dict:
    """
    AutoEIA platform entry point — CEQR Chapter 23 DAC screening.
    Uses building_geojson centroid as project location (consistent with other modules).
    """
    import geopandas as _gpd
    from shapely.ops import unary_union as _unary_union

    building_geojson = inputs.get('building_geojson')
    if not building_geojson:
        raise ValueError("building_geojson is required")
    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    building_gdf = _gpd.GeoDataFrame.from_features(building_geojson['features'])
    if building_gdf.crs is None:
        building_gdf.set_crs(epsg=4326, inplace=True)
    centroid = _unary_union(building_gdf.geometry).centroid
    lat, lon = centroid.y, centroid.x

    # ceqr_technical_areas arrives as a list from the multiselect UI widget
    ceqr_areas_raw = inputs.get('ceqr_technical_areas')
    ceqr_areas = []
    if ceqr_areas_raw:
        if isinstance(ceqr_areas_raw, str):
            ceqr_areas = json.loads(ceqr_areas_raw)
        elif isinstance(ceqr_areas_raw, list):
            ceqr_areas = ceqr_areas_raw

    buffer_miles = float(inputs.get('buffer_distance_miles') or 0.5)
    project_description = inputs.get('project_description') or ''

    result = DACAssessment().run(
        project_location=(lat, lon),
        project_description=project_description,
        ceqr_technical_areas=ceqr_areas,
        buffer_distance_miles=buffer_miles,
    )

    report = DACReportGenerator().generate_screening_report(result)
    viz = _create_visualization(result, lat, lon, buffer_miles)

    return {
        'screening_determination': result['screening_determination'],
        'dac_tracts_geojson': result['dac_tracts_geojson'],
        'eaf_responses': result.get('eaf_responses', {}),
        'screening_report': report,
        'visualization': viz,
    }
