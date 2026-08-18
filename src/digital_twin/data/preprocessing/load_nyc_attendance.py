"""Runs the NYC DOE Attendance preprocessing pipeline and loads it into PostgreSQL.

Single stage:

    NYC_attendance.csv -> nyc_daily_attendance

Standalone — no shared table, no join with OULAD, xAPI, ASSISTments,
co2_sensor_readings, or occupancy_readings. Reuses `load_oulad.py`'s
`_bulk_load` helper rather than duplicating it.

Run as: python -m digital_twin.data.preprocessing.load_nyc_attendance
"""

from __future__ import annotations

import logging

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.models import Base, NycDailyAttendance
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.preprocessing.load_oulad import _bulk_load
from digital_twin.data.preprocessing.preprocess_nyc_attendance import (
    preprocess_nyc_attendance,
)

logger = logging.getLogger(__name__)


def run() -> None:
    """Execute the single preprocessing stage and load the result into Postgres."""
    configure_logging()
    logger.info("Starting NYC DOE Attendance load pipeline")

    logger.info("Stage 1/1: nyc_daily_attendance")
    attendance = preprocess_nyc_attendance()

    logger.info("Stage preprocessed and validated; creating tables if not present")
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        _bulk_load(session, NycDailyAttendance, attendance, "nyc_daily_attendance")

    logger.info("NYC DOE Attendance load pipeline complete")


if __name__ == "__main__":
    run()
