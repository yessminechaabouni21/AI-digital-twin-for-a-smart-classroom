"""Integration test: all four Student Twin real-data pipelines combined on one twin.

Requires a live PostgreSQL instance with the OULAD/ASSISTments/xAPI-Edu-Data
tables loaded — skipped automatically if the database is unreachable, per
CLAUDE.md's rule that integration tests must be skippable without DB access.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import Engine

from digital_twin.analytics import performance_prediction as perf
from digital_twin.analytics import predictive as dropout
from digital_twin.analytics.predictive import train_val_test_split
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_problem_attempts,
)
from digital_twin.data.repositories.oulad_assessment_results import (
    fetch_oulad_assessment_results,
)
from digital_twin.data.repositories.oulad_dropout_features import fetch_oulad_dropout_snapshot
from digital_twin.data.repositories.oulad_performance_features import (
    fetch_oulad_performance_snapshot,
)
from digital_twin.data.repositories.oulad_vle_interactions import fetch_oulad_vle_interactions
from digital_twin.data.repositories.xapi_engagement import fetch_xapi_engagement_counts
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

ASSISTMENTS_STUDENT_ID = 52964
OULAD_ID_STUDENT = 134188
OULAD_CODE_MODULE = "DDD"
OULAD_CODE_PRESENTATION = "2013B"
XAPI_RECORD_ID = 1

# A different real OULAD enrollment than OULAD_ID_STUDENT above, chosen only
# because it has a matching row in both the dropout and performance
# snapshots (verified against the live table) — needed to exercise both
# predictions in one test.
PREDICTIONS_ID_STUDENT = 441201
PREDICTIONS_CODE_MODULE = "DDD"
PREDICTIONS_CODE_PRESENTATION = "2013B"


@pytest.fixture
def engine() -> Engine:
    db_engine = get_engine()
    try:
        with db_engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable, skipping integration test: {exc}")
    return db_engine


def test_full_student_twin_pipeline_combines_all_four_real_sources(engine: Engine) -> None:
    """ASSISTments->BKT, OULAD assessments, OULAD VLE, and xAPI counts all land
    on one StudentTwinState without any repository/twin_engine code changes."""
    student = Student()
    twin = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())

    problem_attempts = fetch_assistments_problem_attempts(
        engine, ASSISTMENTS_STUDENT_ID, twin_student_id=student.student_id
    )
    assert problem_attempts, "expected ASSISTments fixture student to have scorable attempts"
    for interaction in problem_attempts:
        twin.apply_interaction(interaction)

    assessment_results = fetch_oulad_assessment_results(
        engine,
        OULAD_ID_STUDENT,
        OULAD_CODE_MODULE,
        OULAD_CODE_PRESENTATION,
        twin_student_id=student.student_id,
    )
    assert assessment_results, "expected OULAD fixture student to have assessment results"
    for result in assessment_results:
        twin.apply_assessment_result(result)

    vle_interactions = fetch_oulad_vle_interactions(
        engine,
        OULAD_ID_STUDENT,
        OULAD_CODE_MODULE,
        OULAD_CODE_PRESENTATION,
        twin_student_id=student.student_id,
    )
    assert vle_interactions, "expected OULAD fixture student to have VLE clicks"
    for interaction in vle_interactions:
        twin.apply_interaction(interaction)

    xapi_counts = fetch_xapi_engagement_counts(engine, XAPI_RECORD_ID)
    assert xapi_counts is not None, "expected xAPI fixture record_id to exist"
    twin.attach_xapi_engagement_counts(xapi_counts)

    state = twin.current_state()

    # 1. Knowledge states / mastery by topic (from ASSISTments -> BKT).
    assert state.student_id == student.student_id
    assert len(state.knowledge_states) > 0
    assert all(0.0 <= ks.mastery_probability <= 1.0 for ks in state.knowledge_states.values())
    assert state.total_observations == len(problem_attempts)

    # 2. Assessment performance (from OULAD assessment submissions).
    assert state.assessment_performance.total_results == len(assessment_results)
    assert state.assessment_performance.average_score is not None

    # 3. Engagement (from OULAD VLE clicks + xAPI behavioral counts).
    assert state.engagement.total_interactions == len(problem_attempts) + len(vle_interactions)
    assert state.engagement.resource_interaction_days == len(vle_interactions)
    assert state.engagement.problem_attempts == len(problem_attempts)
    assert state.engagement.active_days > 0
    assert state.engagement.xapi_behavioral_counts == xapi_counts

    # 4. Overall snapshot bookkeeping.
    assert state.as_of is not None
    assert state.as_of >= state.assessment_performance.last_assessment_at
    assert state.as_of >= state.engagement.last_interaction_at


def _exclude_student_row(
    snapshot: pd.DataFrame, id_student: int, code_module: str, code_presentation: str
) -> pd.DataFrame:
    """Same discipline as scripts/student_twin_predictions_oulad_demo.py's helper of the
    same name: the target student's own row must never reach model training, or a
    prediction "for" them would really be an in-sample result."""
    is_this_student = (
        (snapshot["id_student"] == id_student)
        & (snapshot["code_module"] == code_module)
        & (snapshot["code_presentation"] == code_presentation)
    )
    return snapshot[~is_this_student]


def test_real_oulad_dropout_and_performance_predictions_attach_to_student_twin(
    engine: Engine,
) -> None:
    """Real OULAD-sourced DropoutPrediction/StudentPerformancePrediction, trained
    out-of-sample (the target student's own row excluded before any split), surface
    correctly on StudentTwinState after StudentTwin.attach_dropout_risk/
    attach_performance_prediction — same wiring scripts/student_twin_predictions_oulad_demo.py
    demonstrates, exercised here as a regression check."""
    student = Student()
    twin = StudentTwin(student)

    dropout_snapshot = fetch_oulad_dropout_snapshot(engine)
    dropout_row = dropout_snapshot[
        (dropout_snapshot["id_student"] == PREDICTIONS_ID_STUDENT)
        & (dropout_snapshot["code_module"] == PREDICTIONS_CODE_MODULE)
        & (dropout_snapshot["code_presentation"] == PREDICTIONS_CODE_PRESENTATION)
    ]
    assert not dropout_row.empty, "expected fixture student to have a dropout-snapshot row"
    dropout_training_pool = _exclude_student_row(
        dropout_snapshot,
        PREDICTIONS_ID_STUDENT,
        PREDICTIONS_CODE_MODULE,
        PREDICTIONS_CODE_PRESENTATION,
    )
    assert len(dropout_training_pool) == len(dropout_snapshot) - len(dropout_row)
    dropout_x, dropout_y = dropout.split_features_and_target(dropout_training_pool)
    dropout_x_train, _, _, dropout_y_train, _, _ = train_val_test_split(
        dropout_x, dropout_y, random_state=0
    )
    dropout_model = dropout.train_baseline_model(dropout_x_train, dropout_y_train)
    dropout_prediction = dropout.predict(dropout_model, dropout_row[dropout.FEATURE_COLUMNS])[0]
    twin.attach_dropout_risk(dropout_prediction)

    performance_snapshot = fetch_oulad_performance_snapshot(engine)
    performance_row = performance_snapshot[
        (performance_snapshot["id_student"] == PREDICTIONS_ID_STUDENT)
        & (performance_snapshot["code_module"] == PREDICTIONS_CODE_MODULE)
        & (performance_snapshot["code_presentation"] == PREDICTIONS_CODE_PRESENTATION)
    ]
    assert not performance_row.empty, "expected fixture student to have a performance-snapshot row"
    performance_training_pool = _exclude_student_row(
        performance_snapshot,
        PREDICTIONS_ID_STUDENT,
        PREDICTIONS_CODE_MODULE,
        PREDICTIONS_CODE_PRESENTATION,
    )
    assert len(performance_training_pool) == len(performance_snapshot) - len(performance_row)
    performance_x, performance_y = perf.split_features_and_target(performance_training_pool)
    performance_x_train, _, _, performance_y_train, _, _ = train_val_test_split(
        performance_x, performance_y, random_state=0
    )
    performance_model = perf.train_baseline_model(performance_x_train, performance_y_train)
    performance_prediction = perf.predict(performance_model, performance_row[perf.FEATURE_COLUMNS])[
        0
    ]
    twin.attach_performance_prediction(performance_prediction)

    state = twin.current_state()

    assert state.dropout_risk == dropout_prediction
    assert 0.0 <= state.dropout_risk.dropout_probability <= 1.0
    assert state.dropout_risk.predicted_class in (0, 1)

    assert state.performance_prediction == performance_prediction
    assert 0.0 <= state.performance_prediction.pass_probability <= 1.0
    assert state.performance_prediction.predicted_class in (0, 1)

    # Independent of the twin's own event history (empty here) and of each other.
    assert state.total_observations == 0
    assert state.knowledge_states == {}
