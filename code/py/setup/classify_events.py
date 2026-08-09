"""
Apply Algorithm §3.12 5-priority classification cascade к existing event catalog.

Used post-hoc к re-classify events после empirical threshold calibration
(e.g., updating COMPACTNESS_THRESHOLD_PLACEHOLDER в rca/classify_events.py
based на ≥100 events distribution analysis).

For new catalog builds, classification happens inline в
`build_ch4_event_catalog.py::process_year` via `apply_classification()`.

Запуск (apply re-classification к existing catalog)::

    cd src/py
    python -m setup.classify_events --year 2024
    python -m setup.classify_events --year 2024 --launch
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import ee

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "src" / "py") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src" / "py"))

from rca.classify_events import apply_classification  # noqa: E402

PROJECT_ID = "nodal-thunder-481307-u1"
ASSETS_ROOT = f"projects/{PROJECT_ID}/assets"
CATALOG_ASSET_TEMPLATE = f"{ASSETS_ROOT}/RuPlumeScan/catalog/CH4/events_{{year}}"
RECLASSIFIED_ASSET_TEMPLATE = f"{ASSETS_ROOT}/RuPlumeScan/catalog/CH4/events_{{year}}_reclassified"


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("classify_events")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(h)
    return logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-classify existing CH4 event catalog (post-hoc)"
    )
    parser.add_argument("--year", type=int, required=True, help="Catalog year к reclassify")
    parser.add_argument(
        "--launch", action="store_true", help="Submit Export task (default plan only)"
    )
    parser.add_argument("--ee-project", type=str, default=PROJECT_ID)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logger = setup_logger()

    try:
        ee.Initialize(project=args.ee_project)
    except Exception as exc:
        logger.error("ee.Initialize() failed: %s", exc)
        return 1

    src_asset = CATALOG_ASSET_TEMPLATE.format(year=args.year)
    dst_asset = RECLASSIFIED_ASSET_TEMPLATE.format(year=args.year)

    logger.info("Source: %s", src_asset)
    logger.info("Destination: %s", dst_asset)

    try:
        fc = ee.FeatureCollection(src_asset)
        n = fc.size().getInfo()
        logger.info("Loaded %d events", n)
    except Exception as exc:
        logger.error("Failed к load source catalog: %s", exc)
        return 1

    reclassified = apply_classification(fc)
    logger.info("Cascade applied (lazy — Export materializes)")

    if not args.launch:
        logger.info("Plan only. Use --launch к submit Export task.")
        return 0

    task = ee.batch.Export.table.toAsset(
        collection=reclassified,
        description=f"reclassify_ch4_events_{args.year}",
        assetId=dst_asset,
    )
    task.start()
    logger.info("Submitted: task_id=%s", task.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
