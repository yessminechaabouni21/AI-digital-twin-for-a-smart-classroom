"""Runs the xAPI-Edu-Data preprocessing pipeline end-to-end and loads it into PostgreSQL.

Stage order mirrors docs/datasets/xapi-preprocessing-plan.md exactly:

    xapi_class_sections -> xapi_student_records

Independent of the OULAD pipeline (load_oulad.py) — no shared tables, no
join between the two datasets. Reuses its `_to_records`/`_bulk_load` helpers
rather than duplicating them.

Run as: python -m digital_twin.data.preprocessing.load_xapi
"""

from __future__ import annotations

import logging

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.models import Base, XapiClassSection, XapiStudentRecord
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.preprocessing.load_oulad import _bulk_load
from digital_twin.data.preprocessing.preprocess_xapi_class_sections import (
    preprocess_xapi_class_sections,
)
from digital_twin.data.preprocessing.preprocess_xapi_student_records import (
    preprocess_xapi_student_records,
)

logger = logging.getLogger(__name__)


def run() -> None:
    """Execute both preprocessing stages in order and load the results into Postgres."""
    configure_logging()
    logger.info("Starting xAPI load pipeline")

    logger.info("Stage 1/2: xapi_class_sections")
    class_sections = preprocess_xapi_class_sections()

    logger.info("Stage 2/2: xapi_student_records")
    student_records = preprocess_xapi_student_records(class_sections)

    logger.info("All stages preprocessed and validated; creating tables if not present")
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        _bulk_load(session, XapiClassSection, class_sections, "xapi_class_sections")
        _bulk_load(session, XapiStudentRecord, student_records, "xapi_student_records")

    logger.info("xAPI load pipeline complete")


if __name__ == "__main__":
    run()
