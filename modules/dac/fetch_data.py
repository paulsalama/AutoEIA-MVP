"""
Fetch DAC Data
==============
Standalone script to download and cache DAC data for offline use.

Usage:
    python -m modules.dac_assessment.fetch_data [--data-dir ./datasets]

Downloads:
    1. NYS DAC census tract boundaries (GeoJSON) — filtered to NYC
    2. NYC census tract boundaries (GeoJSON) — all five boroughs
    3. DAC indicator data (CSV) — 45 indicators per tract

Sources:
    - NYS DAC designations: ArcGIS Feature Service (NYSDOS)
    - Census tracts: US Census Bureau TIGERweb
    - Indicators: NYS Climate Act / CJWG technical data
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def fetch_dac_data(data_dir: str = None):
    """Fetch all DAC data and save to local cache."""
    from .dac_data_loader import DACDataLoader

    loader = DACDataLoader(data_dir=data_dir, offline=False)

    logger.info("=" * 60)
    logger.info("AutoEIA — DAC Data Fetcher")
    logger.info("=" * 60)

    # 1. DAC tracts
    logger.info("\n[1/3] Fetching NYS DAC census tracts (NYC only)...")
    try:
        dac_tracts = loader.load_dac_tracts(force_reload=True)
        count = len(dac_tracts.get("features", []))
        logger.info(f"  ✓ Downloaded {count} DAC tracts")
    except Exception as e:
        logger.error(f"  ✗ Failed to fetch DAC tracts: {e}")
        logger.info("  Trying alternate approach...")
        dac_tracts = _fetch_dac_tracts_fallback(loader.data_dir)

    # 2. Census tracts
    logger.info("\n[2/3] Fetching NYC census tract boundaries...")
    try:
        census_tracts = loader.load_census_tracts(force_reload=True)
        count = len(census_tracts.get("features", []))
        logger.info(f"  ✓ Downloaded {count} census tracts")
    except Exception as e:
        logger.error(f"  ✗ Failed to fetch census tracts: {e}")

    # 3. Indicator data
    logger.info("\n[3/3] Extracting indicator data...")
    try:
        indicators = loader.load_indicators(force_reload=True)
        count = len(indicators)
        logger.info(f"  ✓ Extracted indicators for {count} tracts")

        # Save as CSV
        _save_indicators_csv(indicators, loader.data_dir / "dac_indicators.csv")
    except Exception as e:
        logger.error(f"  ✗ Failed to extract indicators: {e}")

    logger.info("\n" + "=" * 60)
    logger.info(f"Data saved to: {loader.data_dir}")
    logger.info("=" * 60)


def _fetch_dac_tracts_fallback(data_dir: Path) -> dict:
    """
    Fallback: If ArcGIS Feature Service is unavailable, try Open Data NY.
    """
    try:
        import requests
    except ImportError:
        logger.error("requests library not available")
        return {"type": "FeatureCollection", "features": []}

    # Try data.ny.gov SODA API
    url = "https://data.ny.gov/resource/74eg-japs.geojson"
    params = {
        "$limit": 5000,
        "$where": "starts_with(geoid, '36005') OR starts_with(geoid, '36047') "
                  "OR starts_with(geoid, '36061') OR starts_with(geoid, '36081') "
                  "OR starts_with(geoid, '36085')",
    }

    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        geojson = response.json()
        count = len(geojson.get("features", []))
        logger.info(f"  ✓ Fallback: Downloaded {count} tracts from data.ny.gov")

        # Save
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / "nyc_dac_tracts.geojson", "w") as f:
            json.dump(geojson, f)

        return geojson
    except Exception as e:
        logger.error(f"  ✗ Fallback also failed: {e}")
        return {"type": "FeatureCollection", "features": []}


def _save_indicators_csv(indicators: dict, filepath: Path):
    """Save indicator data as CSV."""
    import csv

    if not indicators:
        logger.warning("No indicator data to save")
        return

    # Collect all indicator columns
    all_columns = set()
    for tract_data in indicators.values():
        all_columns.update(tract_data.keys())
    columns = sorted(all_columns)

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["GEOID"] + columns)
        for geoid, data in sorted(indicators.items()):
            row = [geoid] + [data.get(col, "") for col in columns]
            writer.writerow(row)

    logger.info(f"  ✓ Saved indicators to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Download and cache DAC data for AutoEIA"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Directory to save data files (default: datasets/)",
    )
    args = parser.parse_args()
    fetch_dac_data(data_dir=args.data_dir)


if __name__ == "__main__":
    main()
