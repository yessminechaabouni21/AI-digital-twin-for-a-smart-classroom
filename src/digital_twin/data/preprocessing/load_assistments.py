"""Runs the ASSISTments 2019-2020 preprocessing pipeline end-to-end and loads it into PostgreSQL.

Stage order mirrors docs/datasets/assist-preprocessing-plan.md exactly:

    {districts, classes, problems} -> {student_classes, assignments}
        -> assignment_logs -> problem_logs

Independent of the OULAD and xAPI pipelines — no shared tables, no join
between any of the three datasets. Reuses load_oulad.py's `_bulk_load`
rather than duplicating it.

Run as: python -m digital_twin.data.preprocessing.load_assistments
"""

from __future__ import annotations

import logging

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.models import (
    AssistAssignment,
    AssistAssignmentLog,
    AssistClass,
    AssistDistrict,
    AssistProblem,
    AssistProblemLog,
    AssistStudentClass,
    Base,
)
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.preprocessing.load_oulad import _bulk_load
from digital_twin.data.preprocessing.preprocess_assist_assignment_logs import (
    preprocess_assist_assignment_logs,
)
from digital_twin.data.preprocessing.preprocess_assist_assignments import (
    preprocess_assist_assignments,
)
from digital_twin.data.preprocessing.preprocess_assist_classes import preprocess_assist_classes
from digital_twin.data.preprocessing.preprocess_assist_districts import (
    preprocess_assist_districts,
)
from digital_twin.data.preprocessing.preprocess_assist_problem_logs import (
    preprocess_assist_problem_logs,
)
from digital_twin.data.preprocessing.preprocess_assist_problems import preprocess_assist_problems
from digital_twin.data.preprocessing.preprocess_assist_student_classes import (
    preprocess_assist_student_classes,
)

logger = logging.getLogger(__name__)


def run() -> None:
    """Execute all seven preprocessing stages in order and load the results into Postgres."""
    configure_logging()
    logger.info("Starting ASSISTments load pipeline")

    logger.info("Stage 1/7: assist_districts")
    districts = preprocess_assist_districts()

    logger.info("Stage 2/7: assist_classes")
    classes = preprocess_assist_classes()

    logger.info("Stage 3/7: assist_problems")
    problems = preprocess_assist_problems()

    logger.info("Stage 4/7: assist_student_classes")
    student_classes = preprocess_assist_student_classes(classes)

    logger.info("Stage 5/7: assist_assignments")
    assignments = preprocess_assist_assignments(classes)

    logger.info("Stage 6/7: assist_assignment_logs")
    assignment_logs = preprocess_assist_assignment_logs(assignments, student_classes)

    logger.info("Stage 7/7: assist_problem_logs")
    problem_logs = preprocess_assist_problem_logs(assignment_logs, problems)

    logger.info("All stages preprocessed and validated; creating tables if not present")
    engine = get_engine()
    Base.metadata.create_all(engine)

    with session_scope() as session:
        _bulk_load(session, AssistDistrict, districts, "assist_districts")
        _bulk_load(session, AssistClass, classes, "assist_classes")
        _bulk_load(session, AssistProblem, problems, "assist_problems")
        _bulk_load(session, AssistStudentClass, student_classes, "assist_student_classes")
        _bulk_load(session, AssistAssignment, assignments, "assist_assignments")
        _bulk_load(session, AssistAssignmentLog, assignment_logs, "assist_assignment_logs")
        _bulk_load(session, AssistProblemLog, problem_logs, "assist_problem_logs")

    logger.info("ASSISTments load pipeline complete")


if __name__ == "__main__":
    run()
