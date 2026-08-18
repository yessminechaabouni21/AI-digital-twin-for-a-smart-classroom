"""Deterministic, template-based decision-support layer for teacher-facing classroom insights.

Turns already-computed ClassroomTwin analytics (`skill_priority.py`'s
ranked topics, `resource_recommendation.py`'s problem suggestions) into a
structured, teacher-facing explanation — summary, why a skill was
prioritized, evidence, caveats, and a suggested next action. This module
never computes mastery, selects students, or invents a resource: every
number in its output is copied from the `SkillPriorityRecommendation`/
`ClassroomResourceRecommendation` objects it is given, formatted into
sentences, nothing more.

    deterministic analytics (skill_priority.py, resource_recommendation.py)
        -> ClassroomDecisionContext (structured, already-computed inputs)
        -> DecisionSupportProvider.generate()
        -> ClassroomDecisionSupport (structured, teacher-facing explanation)

Provider-independent by design: `DecisionSupportProvider` is the stable
contract; `RuleBasedDecisionSupportProvider` is the first, deterministic
implementation — works with no external service and no Anthropic SDK
import, which is what keeps this module inside `analytics/`'s CLAUDE.md
boundary ("classical ML/stats only. No Anthropic SDK calls here"). A future
LLM-backed provider satisfying the same `DecisionSupportProvider` Protocol
— turning a `ClassroomDecisionContext` into a more natural-language
`ClassroomDecisionSupport` — belongs in `agents/decision_support_agent.py`,
not here, per CLAUDE.md's "agents/ — the only place Anthropic SDK calls
live" rule; that module already exists as a TODO stub for exactly this.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from digital_twin.analytics.context_signals import ContextSignal
from digital_twin.analytics.resource_recommendation import (
    DEFAULT_MIN_STUDENT_ANSWER_COUNT,
    DEFAULT_TARGET_SUCCESS_PROBABILITY,
    ClassroomResourceRecommendation,
)
from digital_twin.analytics.skill_priority import (
    DEFAULT_MIN_OBSERVATIONS,
    SkillPriorityRecommendation,
)

NON_CAUSAL_DISCLAIMER = (
    "This summary describes patterns in already-recorded ASSISTments attempt history. "
    "It does not establish that any listed problem improves learning outcomes — no "
    "controlled or randomized comparison exists in this data."
)

CONTEXT_SIGNAL_DISCLAIMER = (
    "The signals below come from datasets with no identity mapping to this "
    "classroom's roster or students (see each signal's own scope_description). "
    "They describe broader patterns in an unrelated cohort, room, or sensor — "
    "not this classroom — and must not be read as evidence about it."
)


class ClassroomIdentity(BaseModel):
    """Provenance for the classroom this decision-support response is about."""

    twin_id: UUID
    source_dataset: str
    source_class_id: int


class ClassroomDecisionContext(BaseModel):
    """Structured, already-computed analytics this module explains — never recomputes.

    Every field here is copied from an existing, verified source:
    `identity`/`students_used`/`students_eligible`/`roster_capped`/
    `topics_observed` mirror what `api/routers/classrooms.py`'s other
    endpoints already return; `skill_priorities` is
    `skill_priority.recommend_skill_priorities`'s own output, unmodified;
    `resource_recommendation` is
    `resource_recommendation.recommend_classroom_resource`'s own output,
    unmodified, or `None` if the caller has none to offer (an empty class,
    or a topic with no reliable catalog candidates). `context_signals`, if
    any, are `analytics/context_signals.py::ContextSignal`s from datasets
    with no legitimate mapping to this classroom — carried through
    unmodified and never used to influence `skill_priorities` or
    `resource_recommendation`.
    """

    identity: ClassroomIdentity
    students_used: int = Field(ge=0)
    students_eligible: int = Field(ge=0)
    roster_capped: bool
    topics_observed: int = Field(ge=0)
    skill_priorities: list[SkillPriorityRecommendation]
    resource_recommendation: ClassroomResourceRecommendation | None
    as_of: datetime | None
    context_signals: list[ContextSignal] = Field(
        default_factory=list,
        description=(
            "Cohort-level signals from datasets with no legitimate mapping to this "
            "classroom (UCI Occupancy, xAPI-Edu-Data, independent environmental "
            "sensors). Never influences skill_priorities/resource_recommendation "
            "above; carried through to ClassroomDecisionSupport unmodified and kept "
            "structurally separate from this classroom's own evidence."
        ),
    )


class RecommendedResource(BaseModel):
    """One already-ranked problem, carried through unmodified from resource_recommendation.py."""

    problem_id: int
    mean_correct: float
    student_answer_count: int
    distance_from_target: float


class ClassroomDecisionSupport(BaseModel):
    """Structured, teacher-facing explanation of an already-computed classroom analysis."""

    summary: str
    priority_skill: str | None
    rationale: str
    recommended_resources: list[RecommendedResource]
    evidence: list[str]
    limitations: list[str]
    suggested_action: str
    context_signals: list[ContextSignal] = Field(default_factory=list)
    context_note: str | None = Field(
        default=None,
        description=(
            "Set (to CONTEXT_SIGNAL_DISCLAIMER) only when context_signals is "
            "non-empty; explains why those signals are not evidence about this "
            "classroom."
        ),
    )


class DecisionSupportProvider(Protocol):
    """Turns a ClassroomDecisionContext into a ClassroomDecisionSupport.

    The stable contract every provider satisfies —
    `RuleBasedDecisionSupportProvider` today, a future LLM-backed provider
    (`agents/decision_support_agent.py`) later — so callers (the API layer)
    never need to change when the provider does.
    """

    def generate(self, context: ClassroomDecisionContext) -> ClassroomDecisionSupport:
        """Return a structured, teacher-facing explanation of `context`."""
        ...


class RuleBasedDecisionSupportProvider:
    """Deterministic, template-based DecisionSupportProvider — no external service required.

    Every sentence is assembled from `context`'s own fields via plain
    string formatting; nothing here estimates mastery, ranks resources, or
    picks students — that all already happened in twin_engine/analytics
    before this module ever runs.
    """

    def generate(self, context: ClassroomDecisionContext) -> ClassroomDecisionSupport:
        summary = self._summary(context)
        context_note = CONTEXT_SIGNAL_DISCLAIMER if context.context_signals else None

        if not context.skill_priorities:
            return ClassroomDecisionSupport(
                summary=summary,
                priority_skill=None,
                rationale=(
                    "No topic in this classroom has at least "
                    f"{DEFAULT_MIN_OBSERVATIONS} pooled observations, the minimum "
                    "this system requires before treating a topic's average mastery "
                    "as reliable enough to rank."
                ),
                recommended_resources=[],
                evidence=[
                    "No topic met the minimum observation-count reliability threshold "
                    "used by skill_priority.recommend_skill_priorities."
                ],
                limitations=self._limitations(context, include_resource_note=False),
                suggested_action=(
                    "Consider assigning additional graded practice across topics, "
                    "then re-run this analysis once more attempts are recorded."
                ),
                context_signals=context.context_signals,
                context_note=context_note,
            )

        top = context.skill_priorities[0]
        rationale = (
            f"'{top.topic_id}' is ranked as the top-priority topic because it has the "
            f"lowest average mastery ({top.average_mastery:.2f}) among topics with at "
            f"least {DEFAULT_MIN_OBSERVATIONS} pooled observations (this topic has "
            f"{top.observation_count}), based on the {context.students_used} students "
            "included in this analysis."
        )

        evidence = [
            f"'{top.topic_id}': average_mastery={top.average_mastery:.2f}, "
            f"priority_score={top.priority_score:.2f}, "
            f"observation_count={top.observation_count}."
        ]

        recommended_resources: list[RecommendedResource] = []
        recommendation = context.resource_recommendation
        if recommendation is None:
            evidence.append(
                f"No resource recommendation is currently available for '{top.topic_id}'."
            )
        elif not recommendation.recommended_problems:
            evidence.append(
                f"No catalog problem tagged '{top.topic_id}' had at least "
                f"{DEFAULT_MIN_STUDENT_ANSWER_COUNT} recorded answers, the minimum "
                "this system requires before trusting a problem's historical success "
                "rate."
            )
        else:
            for problem in recommendation.recommended_problems:
                recommended_resources.append(
                    RecommendedResource(
                        problem_id=problem.problem_id,
                        mean_correct=problem.mean_correct,
                        student_answer_count=problem.student_answer_count,
                        distance_from_target=problem.distance_from_target,
                    )
                )
                evidence.append(
                    f"Problem {problem.problem_id}: historical mean_correct="
                    f"{problem.mean_correct:.2f} over {problem.student_answer_count} "
                    f"recorded answers (target success rate "
                    f"~{DEFAULT_TARGET_SUCCESS_PROBABILITY:.2f})."
                )

        return ClassroomDecisionSupport(
            summary=summary,
            priority_skill=top.topic_id,
            rationale=rationale,
            recommended_resources=recommended_resources,
            evidence=evidence,
            limitations=self._limitations(context, include_resource_note=True),
            suggested_action=self._suggested_action(top.topic_id, recommended_resources),
            context_signals=context.context_signals,
            context_note=context_note,
        )

    def _summary(self, context: ClassroomDecisionContext) -> str:
        roster_note = (
            f"{context.students_used} of {context.students_eligible} eligible students"
            if context.roster_capped
            else f"all {context.students_used} eligible students"
        )
        return (
            f"Classroom {context.identity.source_class_id} "
            f"({context.identity.source_dataset}): {roster_note} included, "
            f"{context.topics_observed} topics observed."
        )

    def _limitations(
        self, context: ClassroomDecisionContext, *, include_resource_note: bool
    ) -> list[str]:
        limitations = [NON_CAUSAL_DISCLAIMER]
        if context.roster_capped:
            limitations.append(
                f"Only {context.students_used} of {context.students_eligible} eligible "
                "students were included in this analysis; the remaining roster was not "
                "sampled and may differ."
            )
        if include_resource_note:
            limitations.append(
                "Recommended problems are ranked by how close their own historical "
                "success rate is to a target range, not by any measured learning "
                "outcome."
            )
        return limitations

    def _suggested_action(
        self, topic_id: str, recommended_resources: list[RecommendedResource]
    ) -> str:
        if recommended_resources:
            return (
                f"Consider reviewing the listed problems for '{topic_id}' with the "
                "class, then check mastery again after new attempts are recorded."
            )
        return (
            f"Consider reviewing the ASSISTments catalog for '{topic_id}' directly, "
            "since no ranked resource is currently available."
        )


__all__ = [
    "CONTEXT_SIGNAL_DISCLAIMER",
    "ClassroomDecisionContext",
    "ClassroomDecisionSupport",
    "ClassroomIdentity",
    "DecisionSupportProvider",
    "RecommendedResource",
    "RuleBasedDecisionSupportProvider",
]
