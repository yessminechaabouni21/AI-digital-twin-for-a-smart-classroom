"""Runs the Dropout Prediction preprocessing pipeline and loads it into PostgreSQL.

Single stage:

    dropout_prediction/data.csv -> dropout_records

Standalone — no shared table, no join with OULAD, xAPI, ASSISTments,
co2_sensor_readings, occupancy_readings, or nyc_daily_attendance. Reuses
`load_oulad.py`'s `_bulk_load` helper rather than duplicating it.

Run as: python -m digital_twin.data.preprocessing.load_dropout
"""

from __future__ import annotations

import logging

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.models import Base, DropoutRecord
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.preprocessing.load_oulad import _bulk_load
from digital_twin.data.preprocessing.preprocess_dropout import preprocess_dropout

logger = logging.getLogger(__name__)


def run() -> None:
    """Execute the single preprocessing stage and load the result into Postgres."""
    configure_logging()
    logger.info("Starting Dropout Prediction load pipeline")

    logger.info("Stage 1/1: dropout_records")
    records = preprocess_dropout()

    logger.info("Stage preprocessed and validated; creating tables if not present")
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        _bulk_load(session, DropoutRecord, records, "dropout_records")

    logger.info("Dropout Prediction load pipeline complete")


if __name__ == "__main__":
    run()
