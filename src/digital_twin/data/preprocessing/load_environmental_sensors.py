"""Runs the Spanish Classroom CO2 preprocessing pipeline and loads it into PostgreSQL.

Single stage, mirroring docs/datasets/spanish-co2-preprocessing-plan.md:

    environmental_sensors.csv -> co2_sensor_readings

Standalone — no shared table, no join with OULAD, xAPI, ASSISTments, or the
UCI Occupancy Detection dataset. Reuses `load_oulad.py`'s `_bulk_load` helper
rather than duplicating it.

Run as: python -m digital_twin.data.preprocessing.load_environmental_sensors
"""

from __future__ import annotations

import logging

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.models import Base, Co2SensorReading
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.preprocessing.load_oulad import _bulk_load
from digital_twin.data.preprocessing.preprocess_environmental_sensors import (
    preprocess_environmental_sensors,
)

logger = logging.getLogger(__name__)


def run() -> None:
    """Execute the single preprocessing stage and load the result into Postgres."""
    configure_logging()
    logger.info("Starting environmental sensors (Spanish CO2) load pipeline")

    logger.info("Stage 1/1: co2_sensor_readings")
    readings = preprocess_environmental_sensors()

    logger.info("Stage preprocessed and validated; creating tables if not present")
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        _bulk_load(session, Co2SensorReading, readings, "co2_sensor_readings")

    logger.info("Environmental sensors (Spanish CO2) load pipeline complete")


if __name__ == "__main__":
    run()
