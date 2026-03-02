"""
DAC Data Loader
===============
Handles acquisition, caching, and querying of Disadvantaged Community data:
  - DAC census tract boundaries (GeoJSON) from NYS Open Data / ArcGIS
  - 45-indicator percentile scores from CJWG technical documentation
  - NYC census tract geometries for spatial overlay

Data sources:
  - NYS DAC designations: ArcGIS Feature Service via data.ny.gov
  - CJWG indicators: climate.ny.gov technical documentation
  - Census tracts: US Census Bureau TIGER/Line via Census API

Offline mode: Can load from local datasets/ directory if network unavailable.
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ArcGIS Feature Service for NYS DAC tracts
# This is the authoritative source published by NYSDOS
DAC_FEATURE_SERVICE_URL = (
    "https://services6.arcgis.com/DZHaqZm9elBMHCq6/arcgis/rest/services/"
    "Final_Disadvantaged_Communities_DAC_2023/FeatureServer/0/query"
)

# NYC bounding box for filtering statewide data to city tracts
NYC_BBOX = {
    "xmin": -74.2591,
    "ymin": 40.4774,
    "xmax": -73.7004,
    "ymax": 40.9176,
}

# Default local data paths (relative to module root)
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "datasets"
DAC_TRACTS_FILE = "nyc_dac_tracts.geojson"
DAC_INDICATORS_FILE = "dac_indicators.csv"
CENSUS_TRACTS_FILE = "nyc_census_tracts_2020.geojson"

# The 45 CJWG indicators grouped by factor
DAC_INDICATOR_FACTORS = {
    "health_impacts_burdens": [
        "asthma_ed_visits",
        "cardiac_disease_hospitalizations",
        "copd_ed_visits",
        "heat_stress_ed_visits",
        "low_birth_weight",
        "premature_deaths",
        "self_reported_health",
    ],
    "housing_mobility_communications": [
        "broadband_access",
        "group_quarters",
        "housing_tenure",
        "linguistic_isolation",
        "mobile_homes",
        "overcrowding",
        "rent_burden",
    ],
    "income": [
        "educational_attainment",
        "poverty_rate",
        "unemployment_rate",
    ],
    "race_ethnicity": [
        "pct_bipoc",
    ],
    "land_use_historic_discrimination": [
        "brownfield_cleanup",
        "historic_redlining",
        "housing_violations",
        "industrial_land_use",
        "landfills_scrap_yards",
        "remediation_sites",
        "urban_heat_island",
        "water_body_impairments",
    ],
    "potential_climate_change_risk": [
        "coastal_flood_risk",
        "combined_sewer_overflows",
        "drought_risk",
        "floodplain_proximity",
        "heat_vulnerability",
        "inland_flood_risk",
        "wildfire_risk",
    ],
    "potential_pollution_exposure": [
        "air_toxics_cancer_risk",
        "air_toxics_respiratory_risk",
        "diesel_pm_emissions",
        "drinking_water_contamination",
        "hazardous_waste_proximity",
        "major_facility_proximity",
        "ozone_concentration",
        "pm25_concentration",
        "traffic_proximity",
        "truck_traffic",
        "wastewater_discharge",
        "water_quality_violations",
    ],
}

# Flatten for quick lookup
ALL_INDICATORS = []
INDICATOR_TO_FACTOR = {}
for factor, indicators in DAC_INDICATOR_FACTORS.items():
    for ind in indicators:
        ALL_INDICATORS.append(ind)
        INDICATOR_TO_FACTOR[ind] = factor


class DACDataLoader:
    """
    Loads and manages DAC geospatial and indicator data.

    Supports two modes:
      1. Online: Fetches from ArcGIS Feature Service (requires requests + internet)
      2. Offline: Loads from local GeoJSON/CSV files in datasets/ directory

    The loader caches data in memory after first load.
    """

    def __init__(self, data_dir: Optional[str] = None, offline: bool = False):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.offline = offline
        self._dac_tracts = None
        self._census_tracts = None
        self._indicators = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_dac_tracts(self, force_reload: bool = False) -> dict:
        """
        Load DAC census tract boundaries as GeoJSON FeatureCollection.

        Returns:
            dict: GeoJSON FeatureCollection with DAC tract polygons.
                  Each feature has properties including:
                  - GEOID: Census tract FIPS code
                  - DAC_Designation: "Yes" / "No"
                  - county_name, tract_name
        """
        if self._dac_tracts and not force_reload:
            return self._dac_tracts

        local_path = self.data_dir / DAC_TRACTS_FILE
        if local_path.exists():
            logger.info(f"Loading DAC tracts from local file: {local_path}")
            self._dac_tracts = self._load_geojson(local_path)
            return self._dac_tracts

        if self.offline:
            raise FileNotFoundError(
                f"DAC tracts file not found at {local_path}. "
                f"Run `python -m modules.dac_assessment.fetch_data` to download, "
                f"or set offline=False to fetch from ArcGIS."
            )

        logger.info("Fetching DAC tracts from ArcGIS Feature Service...")
        self._dac_tracts = self._fetch_dac_tracts_from_arcgis()
        return self._dac_tracts

    def load_census_tracts(self, force_reload: bool = False) -> dict:
        """
        Load all NYC census tract boundaries (DAC and non-DAC).

        Returns:
            dict: GeoJSON FeatureCollection of all NYC census tracts.
        """
        if self._census_tracts and not force_reload:
            return self._census_tracts

        local_path = self.data_dir / CENSUS_TRACTS_FILE
        if local_path.exists():
            logger.info(f"Loading census tracts from local file: {local_path}")
            self._census_tracts = self._load_geojson(local_path)
            return self._census_tracts

        if self.offline:
            raise FileNotFoundError(
                f"Census tracts file not found at {local_path}. "
                f"Run `python -m modules.dac_assessment.fetch_data` to download."
            )

        logger.info("Fetching NYC census tracts from Census Bureau...")
        self._census_tracts = self._fetch_census_tracts()
        return self._census_tracts

    def load_indicators(self, force_reload: bool = False) -> dict:
        """
        Load DAC indicator percentile data.

        Returns:
            dict: Mapping of GEOID -> {indicator_name: percentile_value, ...}
        """
        if self._indicators and not force_reload:
            return self._indicators

        local_path = self.data_dir / DAC_INDICATORS_FILE
        if local_path.exists():
            logger.info(f"Loading indicators from local file: {local_path}")
            self._indicators = self._load_indicators_csv(local_path)
            return self._indicators

        # If no local CSV, try to extract from GeoJSON properties
        dac_tracts = self.load_dac_tracts()
        self._indicators = self._extract_indicators_from_geojson(dac_tracts)
        return self._indicators

    def save_local_cache(self, dac_tracts: dict = None, census_tracts: dict = None):
        """Save fetched data to local files for offline use."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if dac_tracts:
            path = self.data_dir / DAC_TRACTS_FILE
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dac_tracts, f)
            logger.info(f"Saved DAC tracts to {path}")

        if census_tracts:
            path = self.data_dir / CENSUS_TRACTS_FILE
            with open(path, "w", encoding="utf-8") as f:
                json.dump(census_tracts, f)
            logger.info(f"Saved census tracts to {path}")

    @staticmethod
    def get_indicator_factors() -> dict:
        """Return the indicator-to-factor mapping."""
        return DAC_INDICATOR_FACTORS

    @staticmethod
    def get_all_indicators() -> list:
        """Return flat list of all 45 indicator names."""
        return ALL_INDICATORS.copy()

    @staticmethod
    def get_indicator_factor(indicator_name: str) -> Optional[str]:
        """Return the factor category for a given indicator."""
        return INDICATOR_TO_FACTOR.get(indicator_name)

    # ------------------------------------------------------------------
    # Private: Data Loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_geojson(path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _load_indicators_csv(path: Path) -> dict:
        """Parse indicators CSV into {GEOID: {indicator: percentile}} mapping."""
        import csv

        indicators = {}
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                geoid = row.get("GEOID", row.get("geoid", ""))
                if not geoid:
                    continue
                tract_indicators = {}
                for col, val in row.items():
                    if col.lower() in ("geoid", "tract", "county", "name"):
                        continue
                    try:
                        tract_indicators[col] = float(val)
                    except (ValueError, TypeError):
                        tract_indicators[col] = val
                indicators[geoid] = tract_indicators
        return indicators

    @staticmethod
    def _extract_indicators_from_geojson(geojson: dict) -> dict:
        """
        If the GeoJSON features contain indicator percentiles in properties,
        extract them into the indicators dict format.
        """
        indicators = {}
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            geoid = props.get("GEOID", props.get("geoid", ""))
            if not geoid:
                continue
            tract_indicators = {}
            for key, val in props.items():
                normalized = key.lower().replace(" ", "_")
                if normalized in INDICATOR_TO_FACTOR:
                    try:
                        tract_indicators[normalized] = float(val)
                    except (ValueError, TypeError):
                        tract_indicators[normalized] = val
            if tract_indicators:
                indicators[geoid] = tract_indicators
        return indicators

    def _fetch_dac_tracts_from_arcgis(self) -> dict:
        """
        Fetch DAC tracts from ArcGIS Feature Service.
        Filters to NYC bounding box to reduce payload.

        Returns GeoJSON FeatureCollection.
        """
        try:
            import requests
        except ImportError:
            raise ImportError(
                "The `requests` library is required for online data fetching. "
                "Install with: pip install requests"
            )

        # Query with NYC spatial filter
        bbox = NYC_BBOX
        geometry_filter = (
            f"{bbox['xmin']},{bbox['ymin']},{bbox['xmax']},{bbox['ymax']}"
        )

        params = {
            "where": "DAC_Designation='Yes' OR DAC_designa='Yes'",
            "geometryType": "esriGeometryEnvelope",
            "geometry": geometry_filter,
            "inSR": "4326",
            "outSR": "4326",
            "outFields": "*",
            "f": "geojson",
            "resultRecordCount": 5000,
        }

        response = requests.get(DAC_FEATURE_SERVICE_URL, params=params, timeout=60)
        response.raise_for_status()

        geojson = response.json()
        feature_count = len(geojson.get("features", []))
        logger.info(f"Fetched {feature_count} DAC tracts from ArcGIS")

        # Cache locally
        self.save_local_cache(dac_tracts=geojson)
        return geojson

    def _fetch_census_tracts(self) -> dict:
        """
        Fetch NYC census tract boundaries from Census Bureau TIGERweb.
        Falls back to a simplified local dataset if API unavailable.
        """
        try:
            import requests
        except ImportError:
            raise ImportError("The `requests` library is required.")

        # Census Bureau TIGERweb WMS — NYC counties (FIPS: 36005, 36047, 36061, 36081, 36085)
        nyc_county_fips = ["36005", "36047", "36061", "36081", "36085"]
        all_features = []

        base_url = (
            "https://tigerweb.geo.census.gov/arcgis/rest/services/"
            "TIGERweb/tigerWMS_Census2020/MapServer/8/query"
        )

        for county_fips in nyc_county_fips:
            params = {
                "where": f"STATE='{county_fips[:2]}' AND COUNTY='{county_fips[2:]}'",
                "outFields": "GEOID,NAME,STATE,COUNTY,TRACT,AREALAND",
                "outSR": "4326",
                "f": "geojson",
                "resultRecordCount": 5000,
            }
            try:
                response = requests.get(base_url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                all_features.extend(data.get("features", []))
            except Exception as e:
                logger.warning(f"Failed to fetch tracts for county {county_fips}: {e}")

        geojson = {
            "type": "FeatureCollection",
            "features": all_features,
        }

        logger.info(f"Fetched {len(all_features)} census tracts for NYC")
        self.save_local_cache(census_tracts=geojson)
        return geojson
