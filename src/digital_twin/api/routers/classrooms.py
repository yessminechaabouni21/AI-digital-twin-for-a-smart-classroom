"""Endpoints for reading classroom-twin state, built live from real ASSISTments data.

Thin orchestration only: every handler calls existing data/repositories/
functions and twin_engine/analytics classes, the same composition
`scripts/classroom_skill_priority_demo.py` already demonstrates — no BKT,
aggregation, or ranking logic is reimplemented here.

`ClassroomTwin` has no persistence of its own (see the persistence audit
this implements: aggregating already-persisted StudentTwinStates
reproduces the same aggregate a live-data run would, so a dedicated
classroom-state table would only duplicate storage). Each request rebuilds
the roster's StudentTwins from real ASSISTments problem-attempt history via
BKT and aggregates them, exactly like the demo script.

`twin_id` is never trusted on its own: every handler re-derives the
expected id from the caller-supplied `class_id`/`source_dataset` via
`domain/classroom.py::derive_classroom_id` and compares, before touching
any data — a `twin_id` that doesn't match its claimed source resolves to
404, the same as a `twin_id` that was never derived from a real class at
all. This is what keeps a caller from ever getting a classroom twin's data
back for the wrong classroom just by guessing/mismatching a `class_id`.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sklearn.pipeline import Pipeline
from sqlalchemy import Engine

from digital_twin.agents.decision_support_agent import (
    ClassroomIdentitySummary,
    ExplanationGenerationError,
    ExplanationProvider,
    build_llm_decision_context,
)
from digital_twin.analytics.context_signals import (
    ContextSignal,
    environmental_sensor_context_signals,
    xapi_absence_risk_context_signal,
    xapi_cohort_engagement_context_signals,
)
from digital_twin.analytics.decision_support import (
    ClassroomDecisionContext,
    ClassroomDecisionSupport,
    ClassroomIdentity,
    RuleBasedDecisionSupportProvider,
)
from digital_twin.analytics.resource_recommendation import (
    ClassroomResourceRecommendation,
    recommend_classroom_resource,
)
from digital_twin.analytics.skill_priority import (
    DEFAULT_MIN_OBSERVATIONS,
    SkillPriorityRecommendation,
    recommend_skill_priorities,
)
from digital_twin.analytics.xapi_absence_risk import (
    FEATURE_COLUMNS as XAPI_FEATURE_COLUMNS,
)
from digital_twin.analytics.xapi_absence_risk import (
    drop_duplicate_rows as drop_duplicate_xapi_rows,
)
from digital_twin.analytics.xapi_absence_risk import (
    predict as predict_xapi_absence_risk,
)
from digital_twin.analytics.xapi_absence_risk import (
    split_features_and_target as split_xapi_features_and_target,
)
from digital_twin.analytics.xapi_absence_risk import (
    train_baseline_model as train_xapi_absence_risk_model,
)
from digital_twin.api.deps import get_db_engine, get_explanation_provider
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_problem_attempts,
    fetch_assistments_problems_for_skill,
    fetch_assistments_student_ids_for_class,
)
from digital_twin.data.repositories.classroom_context_mapping import (
    get_classroom_context_mapping,
)
from digital_twin.data.repositories.co2_sensor_readings import fetch_co2_sensor_readings
from digital_twin.data.repositories.xapi_engagement import fetch_xapi_engagement_counts
from digital_twin.data.repositories.xapi_snapshot import fetch_xapi_snapshot
from digital_twin.domain.classroom import Classroom, derive_classroom_id
from digital_twin.domain.student import Student
from digital_twin.schemas.agent import LLMDecisionExplanationOut
from digital_twin.schemas.classrooms import (
    ClassroomAssessmentSummaryOut,
    ClassroomDecisionSupportOut,
    ClassroomEngagementSummaryOut,
    ClassroomEnvironmentSummaryOut,
    ClassroomResourceRecommendationOut,
    ClassroomTwinStateOut,
    ClassroomTwinSummary,
    ContextSignalOut,
    ProblemRecommendationOut,
    RecommendedResourceOut,
    SkillPriorityOut,
)
from digital_twin.twin_engine.classroom_twin import ClassroomTwin, ClassroomTwinState
from digital_twin.twin_engine.student_twin import StudentTwin
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

router = APIRouter(prefix="/classrooms", tags=["classrooms"])

# Process-wide cache: (fitted xAPI absence-risk model, its full raw training
# snapshot). Trained once, lazily, on first use — never retrained per request.
# The same lazy-singleton pattern data/db/session.py uses for its engine/session
# factory. `_xapi_absence_risk_state` deliberately keeps the *raw* (non-deduplicated)
# snapshot alongside the model: a specific explicitly-mapped record_id must be
# looked up by its own real row, which drop_duplicate_rows (used only for
# training) might have removed as someone else's kept duplicate.
_xapi_absence_risk_state: tuple[Pipeline, pd.DataFrame] | None = None


def _get_xapi_absence_risk_model_and_snapshot(engine: Engine) -> tuple[Pipeline, pd.DataFrame]:
    global _xapi_absence_risk_state
    if _xapi_absence_risk_state is None:
        snapshot = fetch_xapi_snapshot(engine)
        training_snapshot = drop_duplicate_xapi_rows(snapshot)
        x_train, y_train = split_xapi_features_and_target(training_snapshot)
        model = train_xapi_absence_risk_model(x_train, y_train)
        _xapi_absence_risk_state = (model, snapshot)
    return _xapi_absence_risk_state


DbEngine = Annotated[Engine, Depends(get_db_engine)]
ExplanationProviderDep = Annotated[ExplanationProvider, Depends(get_explanation_provider)]

# Same default scripts/classroom_skill_priority_demo.py uses (MAX_STUDENTS).
DEFAULT_MAX_STUDENTS = 15
# The only dataset with a real classroom-scoped roster repository today.
SUPPORTED_SOURCE_DATASETS = {"assistments"}


def _verify_identity(twin_id: UUID, source_dataset: str, class_id: int) -> None:
    if source_dataset not in SUPPORTED_SOURCE_DATASETS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported source_dataset={source_dataset!r}; expected one of "
                f"{sorted(SUPPORTED_SOURCE_DATASETS)}"
            ),
        )
    expected_twin_id = derive_classroom_id(source_dataset, class_id)
    if expected_twin_id != twin_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No classroom twin found for twin_id={twin_id}: it does not match "
                f"derive_classroom_id({source_dataset!r}, {class_id})."
            ),
        )


def _roster(engine: Engine, class_id: int, max_students: int) -> tuple[list[int], list[int]]:
    eligible_ids = fetch_assistments_student_ids_for_class(engine, class_id)
    used_ids = eligible_ids[:max_students]
    return eligible_ids, used_ids


def _build_classroom_twin(engine: Engine, class_id: int, used_ids: list[int]) -> ClassroomTwin:
    classroom_twin = ClassroomTwin(Classroom(source_class_id=class_id))
    for assistments_student_id in used_ids:
        student = Student(display_name=f"class-{class_id}-student-{assistments_student_id}")
        student_twin = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())
        attempts = fetch_assistments_problem_attempts(
            engine, assistments_student_id, twin_student_id=student.student_id
        )
        for interaction in attempts:
            student_twin.apply_interaction(interaction)
        classroom_twin.attach_student_state(student_twin.current_state())
    return classroom_twin


def _skill_priorities_and_resource_recommendation(
    engine: Engine, classroom_twin: ClassroomTwin
) -> tuple[list[SkillPriorityRecommendation], ClassroomResourceRecommendation | None]:
    """Shared by /recommendations and /decision-support: rank topics, then look up
    real catalog problems for the single top-priority one — no duplicated ranking
    or lookup logic between the two endpoints."""
    skill_priorities = recommend_skill_priorities(classroom_twin.current_state())
    if not skill_priorities:
        return skill_priorities, None

    top_topic_id = skill_priorities[0].topic_id
    problem_candidates = fetch_assistments_problems_for_skill(engine, top_topic_id)
    resource_recommendation = recommend_classroom_resource(
        skill_priorities, {top_topic_id: problem_candidates}
    )
    return skill_priorities, resource_recommendation


def _context_signals(engine: Engine, source_dataset: str, class_id: int) -> list[ContextSignal]:
    """Look up class_id's explicitly configured mapping and convert whatever is configured
    into ContextSignals. Returns [] if no mapping row exists — this function never picks
    a sensor_id/xapi_record_id on its own; see
    data/repositories/classroom_context_mapping.py for the one place that mapping is set.
    """
    mapping = get_classroom_context_mapping(engine, source_dataset, class_id)
    if mapping is None:
        return []

    signals: list[ContextSignal] = []

    if mapping.sensor_id is not None:
        readings = fetch_co2_sensor_readings(engine, mapping.sensor_id)
        if readings:
            signals.extend(environmental_sensor_context_signals(readings[-1]))

    if mapping.xapi_record_id is not None:
        counts = fetch_xapi_engagement_counts(engine, mapping.xapi_record_id)
        record_scope = (
            f"xapi_record_id={mapping.xapi_record_id} "
            f"(explicitly configured for {source_dataset} class_id={class_id})"
        )
        if counts is not None:
            signals.extend(
                xapi_cohort_engagement_context_signals(counts, class_section_scope=record_scope)
            )

            model, snapshot = _get_xapi_absence_risk_model_and_snapshot(engine)
            record_rows = snapshot.loc[snapshot["record_id"] == mapping.xapi_record_id]
            if not record_rows.empty:
                x_row = record_rows[XAPI_FEATURE_COLUMNS]
                prediction = predict_xapi_absence_risk(model, x_row)[0]
                signals.append(
                    xapi_absence_risk_context_signal(prediction, class_section_scope=record_scope)
                )

    return signals


def _state_response(
    twin_id: UUID,
    source_dataset: str,
    class_id: int,
    eligible_ids: list[int],
    used_ids: list[int],
    state: ClassroomTwinState,
) -> ClassroomTwinStateOut:
    return ClassroomTwinStateOut(
        twin_id=twin_id,
        source_dataset=source_dataset,
        source_class_id=class_id,
        students_used=len(used_ids),
        students_eligible=len(eligible_ids),
        roster_capped=len(used_ids) < len(eligible_ids),
        average_mastery_by_topic=state.average_mastery_by_topic,
        topic_observation_counts=state.topic_observation_counts,
        engagement=ClassroomEngagementSummaryOut(**state.engagement.model_dump()),
        assessment_performance=ClassroomAssessmentSummaryOut(
            **state.assessment_performance.model_dump()
        ),
        environment=ClassroomEnvironmentSummaryOut(**state.environment.model_dump()),
        as_of=state.as_of,
    )


@router.get("/{twin_id}", response_model=ClassroomTwinSummary)
def get_classroom_twin(
    twin_id: UUID,
    engine: DbEngine,
    class_id: int = Query(..., description="Real ASSISTments assist_classes.class_id"),
    source_dataset: str = Query("assistments"),
    max_students: int = Query(DEFAULT_MAX_STUDENTS, ge=1),
) -> ClassroomTwinSummary:
    """Existence check + roster provenance for one real ASSISTments classroom's twin."""
    _verify_identity(twin_id, source_dataset, class_id)
    eligible_ids, used_ids = _roster(engine, class_id, max_students)
    return ClassroomTwinSummary(
        twin_id=twin_id,
        source_dataset=source_dataset,
        source_class_id=class_id,
        students_used=len(used_ids),
        students_eligible=len(eligible_ids),
        roster_capped=len(used_ids) < len(eligible_ids),
    )


@router.get("/{twin_id}/state", response_model=ClassroomTwinStateOut)
def get_classroom_twin_state(
    twin_id: UUID,
    engine: DbEngine,
    class_id: int = Query(...),
    source_dataset: str = Query("assistments"),
    max_students: int = Query(DEFAULT_MAX_STUDENTS, ge=1),
) -> ClassroomTwinStateOut:
    """Full ClassroomTwinState, built live from real ASSISTments problem-attempt history."""
    _verify_identity(twin_id, source_dataset, class_id)
    eligible_ids, used_ids = _roster(engine, class_id, max_students)
    classroom_twin = _build_classroom_twin(engine, class_id, used_ids)
    return _state_response(
        twin_id, source_dataset, class_id, eligible_ids, used_ids, classroom_twin.current_state()
    )


@router.get("/{twin_id}/priorities", response_model=list[SkillPriorityOut])
def get_classroom_priorities(
    twin_id: UUID,
    engine: DbEngine,
    class_id: int = Query(...),
    source_dataset: str = Query("assistments"),
    max_students: int = Query(DEFAULT_MAX_STUDENTS, ge=1),
    min_observations: int = Query(DEFAULT_MIN_OBSERVATIONS, ge=0),
) -> list[SkillPriorityOut]:
    """Rule-based skill priority ranking (analytics/skill_priority.py) for this classroom."""
    _verify_identity(twin_id, source_dataset, class_id)
    _, used_ids = _roster(engine, class_id, max_students)
    classroom_twin = _build_classroom_twin(engine, class_id, used_ids)
    priorities = recommend_skill_priorities(
        classroom_twin.current_state(), min_observations=min_observations
    )
    return [SkillPriorityOut(**priority.model_dump()) for priority in priorities]


@router.get(
    "/{twin_id}/recommendations",
    response_model=ClassroomResourceRecommendationOut | None,
)
def get_classroom_recommendations(
    twin_id: UUID,
    engine: DbEngine,
    class_id: int = Query(...),
    source_dataset: str = Query("assistments"),
    max_students: int = Query(DEFAULT_MAX_STUDENTS, ge=1),
) -> ClassroomResourceRecommendationOut | None:
    """Non-causal, desirable-difficulty problem suggestion for this classroom's top-priority skill.

    Returns `null` (never a fabricated/empty recommendation) if no topic
    met the reliability threshold — same posture
    `analytics/resource_recommendation.recommend_classroom_resource` itself
    already takes.
    """
    _verify_identity(twin_id, source_dataset, class_id)
    _, used_ids = _roster(engine, class_id, max_students)
    classroom_twin = _build_classroom_twin(engine, class_id, used_ids)
    skill_priorities = recommend_skill_priorities(classroom_twin.current_state())
    if not skill_priorities:
        return None

    top_topic_id = skill_priorities[0].topic_id
    problem_candidates = fetch_assistments_problems_for_skill(engine, top_topic_id)
    recommendation = recommend_classroom_resource(
        skill_priorities, {top_topic_id: problem_candidates}
    )
    if recommendation is None:
        return None

    return ClassroomResourceRecommendationOut(
        topic_id=recommendation.topic_id,
        priority_score=recommendation.priority_score,
        average_mastery=recommendation.average_mastery,
        observation_count=recommendation.observation_count,
        recommended_problems=[
            ProblemRecommendationOut(**problem.model_dump())
            for problem in recommendation.recommended_problems
        ],
    )


def _build_decision_support(
    engine: Engine, twin_id: UUID, source_dataset: str, class_id: int, max_students: int
) -> ClassroomDecisionSupport:
    """Shared by GET .../decision-support and POST .../decision-support/explanation:
    builds the same live ClassroomTwin every other endpoint in this router builds,
    reuses `_skill_priorities_and_resource_recommendation` and `_context_signals`
    to get already-computed analytics, then hands them to
    `analytics/decision_support.py`'s `RuleBasedDecisionSupportProvider` to format —
    no BKT, ranking, or recommendation logic here, and no duplicated orchestration
    between the two endpoints.

    `context_signals` comes from `_context_signals`, which looks up class_id's row
    (if any) in `classroom_context_mappings` — the one explicit, human-authorized
    link from a classroom to a CO2 sensor and/or xAPI-Edu-Data record (see
    `data/db/models.py::ClassroomContextMapping`). No row exists for a class_id
    unless someone explicitly created one via
    `data/repositories/classroom_context_mapping.py::upsert_classroom_context_mapping`
    — this function never guesses which sensor or xAPI record "belongs" to a
    class_id, which is exactly the fabricated mapping this system must not produce.
    UCI Occupancy still has no wrapper here at all: see
    `analytics/context_signals.py::occupancy_context_signal`'s docstring.
    """
    eligible_ids, used_ids = _roster(engine, class_id, max_students)
    classroom_twin = _build_classroom_twin(engine, class_id, used_ids)
    state = classroom_twin.current_state()
    skill_priorities, resource_recommendation = _skill_priorities_and_resource_recommendation(
        engine, classroom_twin
    )

    context = ClassroomDecisionContext(
        identity=ClassroomIdentity(
            twin_id=twin_id, source_dataset=source_dataset, source_class_id=class_id
        ),
        students_used=len(used_ids),
        students_eligible=len(eligible_ids),
        roster_capped=len(used_ids) < len(eligible_ids),
        topics_observed=len(state.average_mastery_by_topic),
        skill_priorities=skill_priorities,
        resource_recommendation=resource_recommendation,
        as_of=state.as_of,
        context_signals=_context_signals(engine, source_dataset, class_id),
    )
    return RuleBasedDecisionSupportProvider().generate(context)


@router.get("/{twin_id}/decision-support", response_model=ClassroomDecisionSupportOut)
def get_classroom_decision_support(
    twin_id: UUID,
    engine: DbEngine,
    class_id: int = Query(...),
    source_dataset: str = Query("assistments"),
    max_students: int = Query(DEFAULT_MAX_STUDENTS, ge=1),
) -> ClassroomDecisionSupportOut:
    """Structured, teacher-facing explanation of this classroom's skill priority + recommendation.

    Deterministic only — never calls the Anthropic SDK or depends on it in
    any way, so this endpoint keeps working even if the LLM explanation
    layer (`POST .../decision-support/explanation`) is unavailable. See
    `_build_decision_support` for the shared orchestration.
    """
    _verify_identity(twin_id, source_dataset, class_id)
    decision_support = _build_decision_support(
        engine, twin_id, source_dataset, class_id, max_students
    )

    return ClassroomDecisionSupportOut(
        twin_id=twin_id,
        source_dataset=source_dataset,
        source_class_id=class_id,
        summary=decision_support.summary,
        priority_skill=decision_support.priority_skill,
        rationale=decision_support.rationale,
        recommended_resources=[
            RecommendedResourceOut(**resource.model_dump())
            for resource in decision_support.recommended_resources
        ],
        evidence=decision_support.evidence,
        limitations=decision_support.limitations,
        suggested_action=decision_support.suggested_action,
        context_signals=[
            ContextSignalOut(**signal.model_dump()) for signal in decision_support.context_signals
        ],
        context_note=decision_support.context_note,
    )


@router.post(
    "/{twin_id}/decision-support/explanation",
    response_model=LLMDecisionExplanationOut,
)
def post_classroom_decision_support_explanation(
    twin_id: UUID,
    engine: DbEngine,
    explanation_provider: ExplanationProviderDep,
    class_id: int = Query(...),
    source_dataset: str = Query("assistments"),
    max_students: int = Query(DEFAULT_MAX_STUDENTS, ge=1),
    mode: Literal["real", "demo"] = Query(
        "real",
        description=(
            'One of "real" (a genuine classroom) or "demo" (illustrates the pipeline; '
            'forces the response to open with "DEMONSTRATION MODE"). Never grants '
            "permission to invent data beyond what this classroom's own, unmodified "
            "decision-support context actually contains — see "
            "agents/decision_support_agent.py::build_llm_decision_context."
        ),
    ),
) -> LLMDecisionExplanationOut:
    """LLM-generated, teacher-facing explanation layered on top of the deterministic
    decision support above — a separate, optional endpoint (POST, since it triggers a
    paid external LLM call) that never replaces or feeds back into it.

        deterministic decision support (GET, above)
                    |
              (unmodified ClassroomDecisionSupport)
                    v
        build_llm_decision_context()   -- no LLM call, no I/O, this module only
                    v
        ExplanationProvider.generate_explanation()  -- the only Anthropic SDK call
                    v
        LLMDecisionExplanationOut

    Builds the identical `ClassroomDecisionSupport` the GET endpoint would for the
    same parameters (same identity check, same live ClassroomTwin, same
    context_signals) via `_build_decision_support`, so the LLM's explanation is
    always grounded in the same numbers a caller could independently verify from the
    deterministic endpoint. On any LLM failure (`ExplanationGenerationError` — API
    error, timeout, invalid/unparseable output), returns 503 rather than fabricating
    text; the deterministic endpoint is entirely unaffected either way.
    """
    _verify_identity(twin_id, source_dataset, class_id)
    decision_support = _build_decision_support(
        engine, twin_id, source_dataset, class_id, max_students
    )
    llm_context = build_llm_decision_context(
        ClassroomIdentitySummary(
            twin_id=twin_id, source_dataset=source_dataset, source_class_id=class_id
        ),
        decision_support,
        mode=mode,
    )

    try:
        explanation = explanation_provider.generate_explanation(llm_context)
    except ExplanationGenerationError as exc:
        raise HTTPException(
            status_code=503, detail=f"LLM explanation is unavailable: {exc}"
        ) from exc

    return LLMDecisionExplanationOut(
        twin_id=twin_id,
        source_dataset=source_dataset,
        source_class_id=class_id,
        mode=explanation.mode,
        summary=explanation.summary,
        reasoning=explanation.reasoning,
        recommended_actions=explanation.recommended_actions,
        evidence_used=explanation.evidence_used,
        limitations=explanation.limitations,
    )


__all__ = ["router"]
