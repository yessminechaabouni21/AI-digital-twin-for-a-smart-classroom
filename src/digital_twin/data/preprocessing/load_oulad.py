"""Runs the OULAD preprocessing pipeline end-to-end and loads it into PostgreSQL.

Stage order mirrors docs/datasets/oulad-preprocessing-plan.md exactly, since
preprocessing order, foreign-key validation order, and Postgres load order
are the same sequence by construction:

    courses -> {vle_sites, assessments} -> enrollments
             -> assessment_submissions -> vle_interactions

Each preprocess_* function already validates its own uniqueness/foreign-key
invariants (see data/preprocessing/validation.py) and raises
OuladValidationError before returning, so by the time a stage's DataFrame
reaches `_bulk_load` here it is known-good — this script's own job is
sequencing, table creation, batched insertion, and stage-by-stage logging.

Run as: python -m digital_twin.data.preprocessing.load_oulad
"""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import insert
from sqlalchemy.orm import Session

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.models import (
    Assessment,
    AssessmentSubmission,
    Base,
    Course,
    Enrollment,
    VleInteraction,
    VleSite,
)
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.preprocessing.preprocess_assessments import preprocess_assessments
from digital_twin.data.preprocessing.preprocess_courses import preprocess_courses
from digital_twin.data.preprocessing.preprocess_enrollments import preprocess_enrollments
from digital_twin.data.preprocessing.preprocess_student_assessment import (
    preprocess_assessment_submissions,
)
from digital_twin.data.preprocessing.preprocess_student_vle import preprocess_vle_interactions
from digital_twin.data.preprocessing.preprocess_vle import preprocess_vle_sites

logger = logging.getLogger(__name__)

DEFAULT_INSERT_BATCH_SIZE = 50_000


def _to_records(df: pd.DataFrame) -> list[dict[str, object]]:
    """Convert a cleaned DataFrame to DB-ready records, NaN/NA/NaT -> None."""
    clean = df.astype(object).where(pd.notnull(df), None)
    records: list[dict[str, object]] = clean.to_dict("records")
    return records


def _bulk_load(
    session: Session,
    model: type[Base],
    df: pd.DataFrame,
    table_name: str,
    batch_size: int = DEFAULT_INSERT_BATCH_SIZE,
) -> None:
    """Insert `df` into `model`'s table in batches, via SQLAlchemy Core executemany."""
    records = _to_records(df)
    total = len(records)
    logger.info("Loading %s: %d row(s)", table_name, total)

    for start in range(0, total, batch_size):
        batch = records[start : start + batch_size]
        session.execute(insert(model), batch)
        logger.info("%s: inserted %d/%d row(s)", table_name, min(start + batch_size, total), total)

    logger.info("Loaded %s", table_name)


def run() -> None:
    """Execute all six preprocessing stages in order and load the results into Postgres."""
    configure_logging()
    logger.info("Starting OULAD load pipeline")

    logger.info("Stage 1/6: courses")
    courses = preprocess_courses()

    logger.info("Stage 2/6: vle_sites")
    vle_sites = preprocess_vle_sites(courses)

    logger.info("Stage 3/6: assessments")
    assessments = preprocess_assessments(courses)

    logger.info("Stage 4/6: enrollments")
    enrollments = preprocess_enrollments(courses)

    logger.info("Stage 5/6: assessment_submissions")
    assessment_submissions = preprocess_assessment_submissions(assessments, enrollments)

    logger.info("Stage 6/6: vle_interactions")
    vle_interactions = preprocess_vle_interactions(vle_sites, enrollments)

    logger.info("All stages preprocessed and validated; creating tables if not present")
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        _bulk_load(session, Course, courses, "courses")
        _bulk_load(session, VleSite, vle_sites, "vle_sites")
        _bulk_load(session, Assessment, assessments, "assessments")
        _bulk_load(session, Enrollment, enrollments, "enrollments")
        _bulk_load(session, AssessmentSubmission, assessment_submissions, "assessment_submissions")
        _bulk_load(session, VleInteraction, vle_interactions, "vle_interactions")

    logger.info("OULAD load pipeline complete")


if __name__ == "__main__":
    run()
