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
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def fetch_dac_data(data_dir: str = None):
    """Fetch all DAC data and save to local cache."""
    from .dac_assessment import DACDataLoader

    loader = DACDataLoader(data_dir=data_dir, offline=False)

    logger.info("=" * 60)
    logger.info("AutoEIA — DAC Data Fetcher")
    logger.info("=" * 60)

    # 1. DAC tracts (all NYC census tracts with DAC designation field)
    logger.info("\n[1/2] Fetching NYC census tracts + DAC designations from data.ny.gov...")
    try:
        dac_tracts = loader.load_dac_tracts(force_reload=True)
        total = len(dac_tracts.get("features", []))
        dac_count = sum(
            1 for f in dac_tracts.get("features", [])
            if f.get("properties", {}).get("dac_designation") == "Designated as DAC"
        )
        logger.info(f"  ✓ Downloaded {total} NYC tracts ({dac_count} designated as DAC)")
    except Exception as e:
        logger.error(f"  ✗ Failed: {e}")
        return

    # 2. Extract and save indicator CSV
    logger.info("\n[2/2] Extracting indicator data to CSV...")
    try:
        indicators = loader.load_indicators(force_reload=True)
        count = len(indicators)
        logger.info(f"  ✓ Extracted indicators for {count} tracts")
        _save_indicators_csv(indicators, loader.data_dir / "dac_indicators.csv")
    except Exception as e:
        logger.error(f"  ✗ Failed to extract indicators: {e}")

    logger.info("\n" + "=" * 60)
    logger.info(f"Data saved to: {loader.data_dir}")
    logger.info("=" * 60)


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


# Alias for `autoeia fetch modules/dac`
fetch = fetch_dac_data


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
