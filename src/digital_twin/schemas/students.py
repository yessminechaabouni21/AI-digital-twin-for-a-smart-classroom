"""Typed HTTP response schemas for student twin endpoints.

Deliberately separate from domain/twin_engine's pydantic models even where
fields look identical today (CLAUDE.md: domain/ and schemas/ diverge over
time — API versioning, field renaming — and coupling them makes that
painful later). Response shapes only; every endpoint in
api/routers/students.py is a GET with no request body.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class StudentTwinSummary(BaseModel):
    """Lightweight existence + provenance summary for one student twin.

    `twin_id` is this system's own synthetic identity — never a raw
    ASSISTments/OULAD student id (see domain/student.py::Student's own
    docstring). `student_knowledge_states` records no reverse mapping back
    to a real source-dataset id, so none is returned here: a caller who
    minted `twin_id` via `derive_student_id` already knows which real
    student it corresponds to; this endpoint does not re-derive or expose
    that link.
    """

    twin_id: UUID
    topics_tracked: int = Field(description="Number of distinct topics with persisted mastery.")
    total_observations: int
    as_of: datetime | None


class KnowledgeStateOut(BaseModel):
    topic_id: str = Field(
        description="Reuses ASSISTments' own skill identifiers (see domain/knowledge_state.py)."
    )
    mastery_probability: float
    observation_count: int
    updated_at: datetime


class XapiEngagementCountsOut(BaseModel):
    raised_hands: int
    visited_resources: int
    announcements_view: int
    discussion: int


class EngagementSummaryOut(BaseModel):
    total_interactions: int
    resource_interaction_days: int
    problem_attempts: int
    correct_attempts: int
    incorrect_attempts: int
    active_days: int
    trend: str | None
    last_interaction_at: datetime | None
    xapi_behavioral_counts: XapiEngagementCountsOut | None = Field(
        default=None,
        description=(
            "Only set if separately attached via StudentTwin.attach_xapi_engagement_counts — "
            "xAPI-Edu-Data has no student identifier, so this is never inferred to belong to "
            "this twin. Always None for state reconstructed from persisted knowledge state, "
            "since PostgresStudentTwinRepository does not persist it."
        ),
    )


class AssessmentPerformanceSummaryOut(BaseModel):
    total_results: int
    average_score: float | None
    recent_average_score: float | None
    trend: str | None
    last_assessment_at: datetime | None


class DropoutPredictionOut(BaseModel):
    dropout_probability: float
    predicted_class: int


class StudentPerformancePredictionOut(BaseModel):
    pass_probability: float
    predicted_class: int


class OuladStudentDemoOut(BaseModel):
    """One OULAD student's real assessment/dropout/performance summary — a StudentTwin
    perspective built from OULAD data, entirely independent of ASSISTments identity.

    `dropout_risk`/`performance_prediction` are only ever populated from a
    model's own genuine held-out test split (see
    `api/routers/students.py::get_oulad_student_demo`) — never from a model
    that was fit on this same student's row, and never retrained per
    request (both models are trained once per process and cached, the same
    posture `api/routers/demo.py` already uses for its own cached models).
    `*_note` explains which case applied. `id_student` is OULAD's own
    dataset-scoped identifier (see domain/student.py::Student's docstring)
    — it is never joined or compared to any ASSISTments student_id.
    """

    id_student: int
    code_module: str
    code_presentation: str
    note: str
    assessment_performance: AssessmentPerformanceSummaryOut
    dropout_risk: DropoutPredictionOut | None
    dropout_risk_note: str
    performance_prediction: StudentPerformancePredictionOut | None
    performance_prediction_note: str


class StudentTwinStateOut(BaseModel):
    """Full derived StudentTwinState for one student twin.

    `knowledge_states`/`total_observations`/`as_of` are real persisted
    values from `student_knowledge_states`. `engagement`/
    `assessment_performance` come back as their empty defaults and
    `dropout_risk`/`performance_prediction` as `None`: this repository only
    persists BKT-derived knowledge state (see
    data/repositories/student_twin_repository.py's module docstring) — the
    rest is never recomputed or fabricated here.
    """

    twin_id: UUID
    knowledge_states: dict[str, KnowledgeStateOut]
    engagement: EngagementSummaryOut
    assessment_performance: AssessmentPerformanceSummaryOut
    dropout_risk: DropoutPredictionOut | None
    performance_prediction: StudentPerformancePredictionOut | None
    total_observations: int
    as_of: datetime | None


__all__ = [
    "AssessmentPerformanceSummaryOut",
    "DropoutPredictionOut",
    "EngagementSummaryOut",
    "KnowledgeStateOut",
    "OuladStudentDemoOut",
    "StudentPerformancePredictionOut",
    "StudentTwinStateOut",
    "StudentTwinSummary",
    "XapiEngagementCountsOut",
]
