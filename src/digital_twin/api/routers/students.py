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

from uuid import UUID

from fastapi import APIRouter, HTTPException

from digital_twin.data.repositories.student_twin_repository import (
    PostgresStudentTwinRepository,
)
from digital_twin.schemas.students import (
    AssessmentPerformanceSummaryOut,
    DropoutPredictionOut,
    EngagementSummaryOut,
    KnowledgeStateOut,
    StudentPerformancePredictionOut,
    StudentTwinStateOut,
    StudentTwinSummary,
    XapiEngagementCountsOut,
)
from digital_twin.twin_engine.student_twin import StudentTwinState

router = APIRouter(prefix="/students", tags=["students"])


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
