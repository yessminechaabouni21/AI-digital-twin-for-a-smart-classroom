"""Typed HTTP response schemas for classroom twin endpoints.

Deliberately separate from domain/twin_engine's pydantic models, same
reasoning as schemas/students.py. Response shapes only.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ClassroomResolveOut(BaseModel):
    """`(source_dataset, class_id) -> twin_id`, via `domain/classroom.py::derive_classroom_id`.

    Pure identity derivation — no DB access, no analytics, no relation to
    decision-support logic. Exists so a client (e.g. a dashboard) never
    needs to reimplement `derive_classroom_id`'s uuid5 derivation itself
    just to know which `twin_id` to call the other endpoints with.
    """

    twin_id: UUID
    source_dataset: str
    class_id: int


class ClassroomTwinSummary(BaseModel):
    """Existence + roster provenance for one real ASSISTments classroom's twin.

    `twin_id` only resolves against the `source_class_id`/`source_dataset`
    supplied alongside it (recomputed via
    domain/classroom.py::derive_classroom_id and compared, never trusted
    on its own) — a `twin_id` that doesn't match its claimed source is
    treated as not found, never silently served.
    """

    twin_id: UUID
    source_dataset: str
    source_class_id: int
    students_used: int = Field(description="Roster size actually built into this twin (capped).")
    students_eligible: int = Field(
        description="Real ASSISTments students in this class with >=1 scoreable attempt."
    )
    roster_capped: bool


class ClassroomEngagementSummaryOut(BaseModel):
    students_with_interactions: int
    total_interactions: int
    total_correct_attempts: int
    total_incorrect_attempts: int
    average_active_days: float | None


class ClassroomAssessmentSummaryOut(BaseModel):
    students_with_results: int
    average_score: float | None


class ClassroomEnvironmentSummaryOut(BaseModel):
    """Always empty via this endpoint: no CO2 sensor is linked to any ASSISTments
    class_id in the source data (see domain/classroom.py's module docstring), so
    this endpoint never attaches one. This is not, and is never populated from,
    UCI Occupancy Detection or any attendance data."""

    reading_count: int
    average_temperature_c: float | None
    average_humidity_pct: float | None
    average_co2_ppm: float | None
    latest_battery_pct: float | None
    last_recorded_at: datetime | None


class ClassroomTwinStateOut(BaseModel):
    """Full ClassroomTwinState for one real classroom's twin, built live and roster-capped."""

    twin_id: UUID
    source_dataset: str
    source_class_id: int
    students_used: int
    students_eligible: int
    roster_capped: bool
    average_mastery_by_topic: dict[str, float]
    topic_observation_counts: dict[str, int]
    engagement: ClassroomEngagementSummaryOut
    assessment_performance: ClassroomAssessmentSummaryOut
    environment: ClassroomEnvironmentSummaryOut
    as_of: datetime | None


class SkillPriorityOut(BaseModel):
    topic_id: str
    priority_score: float
    average_mastery: float
    observation_count: int


class ProblemRecommendationOut(BaseModel):
    problem_id: int
    mean_correct: float
    student_answer_count: int
    distance_from_target: float = Field(
        description="Closeness to a desirable-difficulty target — not a causal-effect ranking."
    )


class ClassroomResourceRecommendationOut(BaseModel):
    """A rule-based, non-causal suggestion — see analytics/resource_recommendation.py.

    Ranks real ASSISTments problems already tagged with the classroom's
    top-priority skill by how close their own historically recorded
    `mean_correct` is to a target success-probability band. Not a claim
    that any listed problem is optimal or causes better learning outcomes
    than another: ASSISTments has no randomized/counterfactual assignment
    data to support that — only each problem's own recorded historical
    difficulty, which is what is ranked on here.
    """

    topic_id: str
    priority_score: float
    average_mastery: float
    observation_count: int
    recommended_problems: list[ProblemRecommendationOut]


class RecommendedResourceOut(BaseModel):
    """One already-ranked problem — see analytics/decision_support.py's RecommendedResource."""

    problem_id: int
    mean_correct: float
    student_answer_count: int
    distance_from_target: float


class ContextSignalOut(BaseModel):
    """One cohort-level signal from a dataset with no legitimate mapping to this classroom.

    See `analytics/context_signals.py::ContextSignal` — deliberately has no
    `student_id`/`classroom_id`/`twin_id` field. `scope_description` is the
    only place identity/provenance is stated, in plain text, so a client
    can never mistake this for evidence about the requested classroom.
    """

    source_dataset: str
    scope_description: str
    metric_name: str
    value: float
    as_of: datetime | None


class ClassroomDecisionSupportOut(BaseModel):
    """Structured, teacher-facing explanation of an already-computed classroom analysis.

    Every field is produced by `analytics/decision_support.py`'s
    `RuleBasedDecisionSupportProvider` from already-computed
    skill-priority/resource-recommendation output — this schema adds no
    new computation, only response shaping. `evidence`/`limitations` are
    plain descriptive sentences, never a causal or "optimal resource"
    claim — see `analytics/decision_support.py`'s `NON_CAUSAL_DISCLAIMER`.
    `context_signals`/`context_note` are structurally separate from
    everything else in this response: they describe an unrelated cohort,
    room, or sensor, never this classroom — see
    `analytics/decision_support.py`'s `CONTEXT_SIGNAL_DISCLAIMER`.
    """

    twin_id: UUID
    source_dataset: str
    source_class_id: int
    summary: str
    priority_skill: str | None
    rationale: str
    recommended_resources: list[RecommendedResourceOut]
    evidence: list[str]
    limitations: list[str]
    suggested_action: str
    context_signals: list[ContextSignalOut] = Field(default_factory=list)
    context_note: str | None = None


__all__ = [
    "ClassroomAssessmentSummaryOut",
    "ClassroomDecisionSupportOut",
    "ClassroomEngagementSummaryOut",
    "ClassroomEnvironmentSummaryOut",
    "ClassroomResolveOut",
    "ClassroomResourceRecommendationOut",
    "ClassroomTwinStateOut",
    "ClassroomTwinSummary",
    "ContextSignalOut",
    "ProblemRecommendationOut",
    "RecommendedResourceOut",
    "SkillPriorityOut",
]
