"""Endpoints for reading persisted Student Twin state.

Thin: every handler here calls `PostgresStudentTwinRepository` and reshapes
its result into a schemas/students.py response — no BKT/update-strategy
logic and no SQLAlchemy import in this file, per CLAUDE.md's module
boundaries (only data/db/ and data/repositories/ talk to the database).

`twin_id` is always a path parameter typed `UUID` — FastAPI/pydantic reject
any non-UUID value (e.g. a raw ASSISTments/OULAD integer id) with a 422
before a handler ever runs, so a source-dataset id can never be silently
accepted as if it were already a twin identity.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sklearn.pipeline import Pipeline
from sqlalchemy import Engine

from digital_twin.analytics import performance_prediction as oulad_performance
from digital_twin.analytics import predictive as oulad_dropout
from digital_twin.analytics.predictive import train_val_test_split
from digital_twin.api.deps import get_db_engine
from digital_twin.data.repositories.oulad_assessment_results import (
    fetch_oulad_assessment_results,
)
from digital_twin.data.repositories.oulad_dropout_features import fetch_oulad_dropout_snapshot
from digital_twin.data.repositories.oulad_performance_features import (
    fetch_oulad_performance_snapshot,
)
from digital_twin.data.repositories.student_twin_repository import (
    PostgresStudentTwinRepository,
)
from digital_twin.domain.student import Student
from digital_twin.schemas.students import (
    AssessmentPerformanceSummaryOut,
    DropoutPredictionOut,
    EngagementSummaryOut,
    KnowledgeStateOut,
    OuladStudentDemoOut,
    StudentPerformancePredictionOut,
    StudentTwinStateOut,
    StudentTwinSummary,
    XapiEngagementCountsOut,
)
from digital_twin.twin_engine.student_twin import StudentTwin, StudentTwinState

router = APIRouter(prefix="/students", tags=["students"])

DbEngine = Annotated[Engine, Depends(get_db_engine)]

# A real OULAD (id_student, code_module, code_presentation) known to fall in
# both models' held-out test splits below — not a guess, verified against
# the cached splits (see get_oulad_student_demo's docstring for why only
# test-split membership is ever served).
DEFAULT_OULAD_ID_STUDENT = 690967
DEFAULT_OULAD_CODE_MODULE = "BBB"
DEFAULT_OULAD_CODE_PRESENTATION = "2014J"

# Process-wide caches: each OULAD model is trained exactly once, on its own
# fixed train split, and reused for every request — this endpoint never
# retrains on demand. Separate from api/routers/demo.py's own caches (that
# module's docstring explains why its caches stay independent); these two
# are likewise independent of each other (dropout vs. performance are
# different snapshots/targets).
_oulad_dropout_state: tuple[Pipeline, pd.DataFrame, frozenset[int]] | None = None
_oulad_performance_state: tuple[Pipeline, pd.DataFrame, frozenset[int]] | None = None


def _get_oulad_dropout_state(engine: Engine) -> tuple[Pipeline, pd.DataFrame, frozenset[int]]:
    global _oulad_dropout_state
    if _oulad_dropout_state is None:
        snapshot = fetch_oulad_dropout_snapshot(engine)
        x, y = oulad_dropout.split_features_and_target(snapshot)
        x_train, _x_val, x_test, y_train, _y_val, _y_test = train_val_test_split(x, y)
        model = oulad_dropout.train_random_forest_model(x_train, y_train)
        _oulad_dropout_state = (model, snapshot, frozenset(x_test.index))
    return _oulad_dropout_state


def _get_oulad_performance_state(engine: Engine) -> tuple[Pipeline, pd.DataFrame, frozenset[int]]:
    global _oulad_performance_state
    if _oulad_performance_state is None:
        snapshot = fetch_oulad_performance_snapshot(engine)
        x, y = oulad_performance.split_features_and_target(snapshot)
        x_train, _x_val, x_test, y_train, _y_val, _y_test = train_val_test_split(x, y)
        model = oulad_performance.train_random_forest_model(x_train, y_train)
        _oulad_performance_state = (model, snapshot, frozenset(x_test.index))
    return _oulad_performance_state


def _find_student_row(
    snapshot: pd.DataFrame, id_student: int, code_module: str, code_presentation: str
) -> pd.DataFrame | None:
    match = snapshot[
        (snapshot["id_student"] == id_student)
        & (snapshot["code_module"] == code_module)
        & (snapshot["code_presentation"] == code_presentation)
    ]
    return match if not match.empty else None


def _get_state_or_404(twin_id: UUID) -> StudentTwinState:
    """Look up persisted state for `twin_id`, or raise 404.

    No knowledge_states were ever saved for `twin_id` (never derived/used)
    and "saved but empty" are indistinguishable here on purpose:
    `PostgresStudentTwinRepository.save()` is a no-op for a state with no
    knowledge_states, so an empty StudentTwinState and a never-seen twin_id
    both correctly resolve to "not found" rather than a fabricated empty
    200 response.
    """
    state = PostgresStudentTwinRepository().get(twin_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"No persisted twin state found for student twin_id={twin_id}",
        )
    return state


@router.get("/oulad-demo", response_model=OuladStudentDemoOut)
def get_oulad_student_demo(
    engine: DbEngine,
    id_student: int = Query(DEFAULT_OULAD_ID_STUDENT),
    code_module: str = Query(DEFAULT_OULAD_CODE_MODULE),
    code_presentation: str = Query(DEFAULT_OULAD_CODE_PRESENTATION),
) -> OuladStudentDemoOut:
    """A Student Twin perspective built from real OULAD data — independent of, and never
    identity-linked to, any ASSISTments student or classroom (see domain/student.py).

    Registered before `/{twin_id}` below so the literal path `/oulad-demo`
    is matched first — FastAPI resolves routes in registration order, and
    `/{twin_id}` would otherwise swallow it and fail UUID parsing.

    Assessment performance is always genuine (`StudentTwin.apply_assessment_result`
    over this student's own real submissions, same wiring as
    `scripts/student_twin_predictions_oulad_demo.py`). Dropout/performance
    predictions are only ever returned when this exact
    (id_student, code_module, code_presentation) row falls in that model's
    own held-out test split (`_get_oulad_dropout_state`/
    `_get_oulad_performance_state`, each trained once per process on a
    fixed `train_val_test_split` and cached — never retrained here): a
    model that was fit on this same row would make its "prediction" for
    that row in-sample, not a genuine one, and this endpoint declines to
    show that rather than silently serving it.
    """
    student = Student(display_name=f"oulad-demo-{id_student}")
    twin = StudentTwin(student)
    results = fetch_oulad_assessment_results(
        engine, id_student, code_module, code_presentation, twin_student_id=student.student_id
    )
    for result in results:
        twin.apply_assessment_result(result)
    state = twin.current_state()

    dropout_model, dropout_snapshot, dropout_test_index = _get_oulad_dropout_state(engine)
    dropout_row = _find_student_row(dropout_snapshot, id_student, code_module, code_presentation)
    dropout_risk: DropoutPredictionOut | None = None
    if dropout_row is None:
        dropout_note = "No dropout-risk snapshot row for this student/course."
    elif dropout_row.index[0] not in dropout_test_index:
        dropout_note = (
            "This student's row was used to fit the cached dropout model, so its own "
            "prediction would be in-sample — withheld rather than shown as if held-out."
        )
    else:
        prediction = oulad_dropout.predict(
            dropout_model, dropout_row[oulad_dropout.FEATURE_COLUMNS]
        )[0]
        dropout_risk = DropoutPredictionOut(**prediction.model_dump())
        dropout_note = "Genuine held-out prediction: this row was not used to fit the model."

    performance_model, performance_snapshot, performance_test_index = _get_oulad_performance_state(
        engine
    )
    performance_row = _find_student_row(
        performance_snapshot, id_student, code_module, code_presentation
    )
    performance_prediction: StudentPerformancePredictionOut | None = None
    if performance_row is None:
        performance_note = (
            "No performance-prediction snapshot row for this student/course "
            "(e.g. the student withdrew)."
        )
    elif performance_row.index[0] not in performance_test_index:
        performance_note = (
            "This student's row was used to fit the cached performance model, so its own "
            "prediction would be in-sample — withheld rather than shown as if held-out."
        )
    else:
        performance_result = oulad_performance.predict(
            performance_model, performance_row[oulad_performance.FEATURE_COLUMNS]
        )[0]
        performance_prediction = StudentPerformancePredictionOut(**performance_result.model_dump())
        performance_note = "Genuine held-out prediction: this row was not used to fit the model."

    return OuladStudentDemoOut(
        id_student=id_student,
        code_module=code_module,
        code_presentation=code_presentation,
        note=(
            "Real OULAD data (Open University Learning Analytics Dataset), shown to "
            "demonstrate that this Digital Twin architecture supports a student-level "
            "perspective alongside the classroom-level one above. OULAD has no shared "
            "identifier with ASSISTments — this student is not, and cannot be, linked "
            "to any ASSISTments classroom or student on this dashboard."
        ),
        assessment_performance=AssessmentPerformanceSummaryOut(
            total_results=state.assessment_performance.total_results,
            average_score=state.assessment_performance.average_score,
            recent_average_score=state.assessment_performance.recent_average_score,
            trend=state.assessment_performance.trend,
            last_assessment_at=state.assessment_performance.last_assessment_at,
        ),
        dropout_risk=dropout_risk,
        dropout_risk_note=dropout_note,
        performance_prediction=performance_prediction,
        performance_prediction_note=performance_note,
    )


@router.get("/{twin_id}", response_model=StudentTwinSummary)
def get_student_twin(twin_id: UUID) -> StudentTwinSummary:
    """Existence check + lightweight summary for one student twin."""
    state = _get_state_or_404(twin_id)
    return StudentTwinSummary(
        twin_id=state.student_id,
        topics_tracked=len(state.knowledge_states),
        total_observations=state.total_observations,
        as_of=state.as_of,
    )


@router.get("/{twin_id}/state", response_model=StudentTwinStateOut)
def get_student_twin_state(twin_id: UUID) -> StudentTwinStateOut:
    """Full persisted StudentTwinState for one student twin."""
    state = _get_state_or_404(twin_id)

    xapi_counts = state.engagement.xapi_behavioral_counts
    return StudentTwinStateOut(
        twin_id=state.student_id,
        knowledge_states={
            topic_id: KnowledgeStateOut(
                topic_id=knowledge_state.topic_id,
                mastery_probability=knowledge_state.mastery_probability,
                observation_count=knowledge_state.observation_count,
                updated_at=knowledge_state.updated_at,
            )
            for topic_id, knowledge_state in state.knowledge_states.items()
        },
        engagement=EngagementSummaryOut(
            total_interactions=state.engagement.total_interactions,
            resource_interaction_days=state.engagement.resource_interaction_days,
            problem_attempts=state.engagement.problem_attempts,
            correct_attempts=state.engagement.correct_attempts,
            incorrect_attempts=state.engagement.incorrect_attempts,
            active_days=state.engagement.active_days,
            trend=state.engagement.trend,
            last_interaction_at=state.engagement.last_interaction_at,
            xapi_behavioral_counts=(
                XapiEngagementCountsOut(**xapi_counts.model_dump())
                if xapi_counts is not None
                else None
            ),
        ),
        assessment_performance=AssessmentPerformanceSummaryOut(
            total_results=state.assessment_performance.total_results,
            average_score=state.assessment_performance.average_score,
            recent_average_score=state.assessment_performance.recent_average_score,
            trend=state.assessment_performance.trend,
            last_assessment_at=state.assessment_performance.last_assessment_at,
        ),
        dropout_risk=(
            DropoutPredictionOut(**state.dropout_risk.model_dump())
            if state.dropout_risk is not None
            else None
        ),
        performance_prediction=(
            StudentPerformancePredictionOut(**state.performance_prediction.model_dump())
            if state.performance_prediction is not None
            else None
        ),
        total_observations=state.total_observations,
        as_of=state.as_of,
    )


__all__ = ["router"]
