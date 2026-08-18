"""Runs the UCI Occupancy Detection preprocessing pipeline and loads it into PostgreSQL.

Single stage, mirroring docs/datasets/occupancy-preprocessing-plan.md:

    {datatraining,datatest,datatest2}.txt -> occupancy_readings

Standalone — no shared table, no join with OULAD, xAPI, ASSISTments, or
co2_sensor_readings (the Spanish Classroom CO2 dataset). Reuses
`load_oulad.py`'s `_bulk_load` helper rather than duplicating it.

Run as: python -m digital_twin.data.preprocessing.load_occupancy
"""

from __future__ import annotations

import logging

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.models import Base, OccupancyReading
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.preprocessing.load_oulad import _bulk_load
from digital_twin.data.preprocessing.preprocess_occupancy import preprocess_occupancy

logger = logging.getLogger(__name__)


def run() -> None:
    """Execute the single preprocessing stage and load the result into Postgres."""
    configure_logging()
    logger.info("Starting UCI Occupancy Detection load pipeline")

    logger.info("Stage 1/1: occupancy_readings")
    readings = preprocess_occupancy()

    logger.info("Stage preprocessed and validated; creating tables if not present")
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        _bulk_load(session, OccupancyReading, readings, "occupancy_readings")

    logger.info("UCI Occupancy Detection load pipeline complete")


if __name__ == "__main__":
    run()
