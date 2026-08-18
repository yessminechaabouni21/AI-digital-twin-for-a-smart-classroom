"""Focused tests for RuleBasedDecisionSupportProvider: template output over synthetic
already-computed analytics — no BKT/ranking recomputation, no DB, no LLM."""

from __future__ import annotations

from uuid import uuid4

from digital_twin.analytics.context_signals import ContextSignal
from digital_twin.analytics.decision_support import (
    CONTEXT_SIGNAL_DISCLAIMER,
    ClassroomDecisionContext,
    ClassroomDecisionSupport,
    ClassroomIdentity,
    RuleBasedDecisionSupportProvider,
)
from digital_twin.analytics.resource_recommendation import (
    ClassroomResourceRecommendation,
    ProblemRecommendation,
)
from digital_twin.analytics.skill_priority import SkillPriorityRecommendation

# Wording a decision-support response must never contain: it would assert a causal
# effect or an "optimal"/"best" claim this data cannot support.
BANNED_CAUSAL_OPTIMAL_PHRASES = [
    "causes",
    "will improve",
    "guaranteed",
    "proven to",
    "is optimal",
    "the best resource",
    "the best problem",
]


def _identity(class_id: int = 1679) -> ClassroomIdentity:
    return ClassroomIdentity(
        twin_id=uuid4(), source_dataset="assistments", source_class_id=class_id
    )


def _skill_priority(
    topic_id: str = "7.EE.B.4a-1",
    average_mastery: float = 0.13,
    observation_count: int = 6,
) -> SkillPriorityRecommendation:
    return SkillPriorityRecommendation(
        topic_id=topic_id,
        priority_score=1.0 - average_mastery,
        average_mastery=average_mastery,
        observation_count=observation_count,
    )


def _problem(problem_id: int = 87609) -> ProblemRecommendation:
    return ProblemRecommendation(
        problem_id=problem_id,
        mean_correct=0.65,
        student_answer_count=60,
        distance_from_target=0.0,
    )


def _all_text_fields(result: ClassroomDecisionSupport) -> list[str]:
    """Every string this provider produced, for the causal/optimal-wording scan."""
    fields = [result.summary, result.rationale, result.suggested_action]
    if result.priority_skill is not None:
        fields.append(result.priority_skill)
    fields.extend(result.evidence)
    fields.extend(result.limitations)
    return fields


def test_empty_skill_priorities_produces_no_priority_skill_and_empty_resources() -> None:
    context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=0,
        students_eligible=0,
        roster_capped=False,
        topics_observed=0,
        skill_priorities=[],
        resource_recommendation=None,
        as_of=None,
    )

    result = RuleBasedDecisionSupportProvider().generate(context)

    assert result.priority_skill is None
    assert result.recommended_resources == []
    assert "no topic" in result.rationale.lower()
    assert result.evidence
    assert result.limitations
    assert result.suggested_action


def test_skill_priorities_present_but_no_resource_recommendation() -> None:
    """Missing resource recommendation (None) must not be fabricated into a resource."""
    context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=5,
        students_eligible=5,
        roster_capped=False,
        topics_observed=2,
        skill_priorities=[_skill_priority()],
        resource_recommendation=None,
        as_of=None,
    )

    result = RuleBasedDecisionSupportProvider().generate(context)

    assert result.priority_skill == "7.EE.B.4a-1"
    assert result.recommended_resources == []
    assert any("no resource recommendation" in e.lower() for e in result.evidence)
    assert "no ranked resource" in result.suggested_action.lower()


def test_resource_recommendation_with_no_reliable_problems() -> None:
    """A ClassroomResourceRecommendation with an empty recommended_problems list
    (no catalog candidate cleared the reliability bar) must not be fabricated either."""
    context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=5,
        students_eligible=5,
        roster_capped=False,
        topics_observed=2,
        skill_priorities=[_skill_priority()],
        resource_recommendation=ClassroomResourceRecommendation(
            topic_id="7.EE.B.4a-1",
            priority_score=0.87,
            average_mastery=0.13,
            observation_count=6,
            recommended_problems=[],
        ),
        as_of=None,
    )

    result = RuleBasedDecisionSupportProvider().generate(context)

    assert result.recommended_resources == []
    assert any("no catalog problem" in e.lower() for e in result.evidence)


def test_full_context_carries_real_numbers_through_unmodified() -> None:
    priority = _skill_priority()
    problem = _problem()
    context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=5,
        students_eligible=5,
        roster_capped=False,
        topics_observed=2,
        skill_priorities=[priority],
        resource_recommendation=ClassroomResourceRecommendation(
            topic_id=priority.topic_id,
            priority_score=priority.priority_score,
            average_mastery=priority.average_mastery,
            observation_count=priority.observation_count,
            recommended_problems=[problem],
        ),
        as_of=None,
    )

    result = RuleBasedDecisionSupportProvider().generate(context)

    assert result.priority_skill == priority.topic_id
    assert len(result.recommended_resources) == 1
    resource = result.recommended_resources[0]
    assert resource.problem_id == problem.problem_id
    assert resource.mean_correct == problem.mean_correct
    assert resource.student_answer_count == problem.student_answer_count
    assert resource.distance_from_target == problem.distance_from_target
    assert str(priority.observation_count) in result.rationale
    assert f"{priority.average_mastery:.2f}" in result.rationale


def test_roster_capped_adds_a_limitation_not_present_when_complete() -> None:
    capped_context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=15,
        students_eligible=148,
        roster_capped=True,
        topics_observed=17,
        skill_priorities=[_skill_priority()],
        resource_recommendation=None,
        as_of=None,
    )
    complete_context = capped_context.model_copy(
        update={"students_used": 5, "students_eligible": 5, "roster_capped": False}
    )

    capped_result = RuleBasedDecisionSupportProvider().generate(capped_context)
    complete_result = RuleBasedDecisionSupportProvider().generate(complete_context)

    assert any("15 of 148" in limitation for limitation in capped_result.limitations)
    assert not any("eligible" in limitation.lower() for limitation in complete_result.limitations)
    assert "15 of 148" in capped_result.summary
    assert "all 5" in complete_result.summary


def test_no_causal_or_optimal_wording_anywhere_in_output() -> None:
    """Scans every string field across every case above for banned causal/optimal phrasing."""
    contexts = [
        ClassroomDecisionContext(
            identity=_identity(),
            students_used=0,
            students_eligible=0,
            roster_capped=False,
            topics_observed=0,
            skill_priorities=[],
            resource_recommendation=None,
            as_of=None,
        ),
        ClassroomDecisionContext(
            identity=_identity(),
            students_used=5,
            students_eligible=5,
            roster_capped=False,
            topics_observed=2,
            skill_priorities=[_skill_priority()],
            resource_recommendation=None,
            as_of=None,
        ),
        ClassroomDecisionContext(
            identity=_identity(),
            students_used=15,
            students_eligible=148,
            roster_capped=True,
            topics_observed=2,
            skill_priorities=[_skill_priority()],
            resource_recommendation=ClassroomResourceRecommendation(
                topic_id="7.EE.B.4a-1",
                priority_score=0.87,
                average_mastery=0.13,
                observation_count=6,
                recommended_problems=[_problem(), _problem(problem_id=1507411)],
            ),
            as_of=None,
        ),
    ]

    provider = RuleBasedDecisionSupportProvider()
    for context in contexts:
        result = provider.generate(context)
        for text in _all_text_fields(result):
            lowered = text.lower()
            for banned in BANNED_CAUSAL_OPTIMAL_PHRASES:
                assert banned not in lowered, f"found banned phrase {banned!r} in: {text!r}"


def _context_signal() -> ContextSignal:
    return ContextSignal(
        source_dataset="environmental_sensors",
        scope_description="Independent environmental sensor reading (sensor_id='CO2_01').",
        metric_name="co2_ppm",
        value=650.0,
        as_of=None,
    )


def test_default_context_signals_is_empty_and_preserves_existing_behavior() -> None:
    context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=5,
        students_eligible=5,
        roster_capped=False,
        topics_observed=2,
        skill_priorities=[_skill_priority()],
        resource_recommendation=None,
        as_of=None,
    )

    result = RuleBasedDecisionSupportProvider().generate(context)

    assert context.context_signals == []
    assert result.context_signals == []
    assert result.context_note is None


def test_context_signals_are_rendered_separately_with_a_disclaimer() -> None:
    priority = _skill_priority()
    signal = _context_signal()
    context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=5,
        students_eligible=5,
        roster_capped=False,
        topics_observed=2,
        skill_priorities=[priority],
        resource_recommendation=None,
        as_of=None,
        context_signals=[signal],
    )

    result = RuleBasedDecisionSupportProvider().generate(context)

    assert result.context_signals == [signal]
    assert result.context_note == CONTEXT_SIGNAL_DISCLAIMER
    # The disclaimer text must never leak into evidence/rationale (those stay
    # purely about the classroom itself).
    assert CONTEXT_SIGNAL_DISCLAIMER not in result.rationale
    assert not any(CONTEXT_SIGNAL_DISCLAIMER in e for e in result.evidence)


def test_context_signals_cannot_alter_priority_skill_or_resources() -> None:
    priority = _skill_priority()
    problem = _problem()
    signal = _context_signal()

    context_without_signal = ClassroomDecisionContext(
        identity=_identity(),
        students_used=5,
        students_eligible=5,
        roster_capped=False,
        topics_observed=2,
        skill_priorities=[priority],
        resource_recommendation=ClassroomResourceRecommendation(
            topic_id=priority.topic_id,
            priority_score=priority.priority_score,
            average_mastery=priority.average_mastery,
            observation_count=priority.observation_count,
            recommended_problems=[problem],
        ),
        as_of=None,
    )
    context_with_signal = context_without_signal.model_copy(update={"context_signals": [signal]})

    provider = RuleBasedDecisionSupportProvider()
    result_without_signal = provider.generate(context_without_signal)
    result_with_signal = provider.generate(context_with_signal)

    assert result_with_signal.priority_skill == result_without_signal.priority_skill
    assert result_with_signal.recommended_resources == result_without_signal.recommended_resources
    assert result_with_signal.rationale == result_without_signal.rationale
    assert result_with_signal.evidence == result_without_signal.evidence
    assert result_with_signal.limitations == result_without_signal.limitations
    assert result_with_signal.suggested_action == result_without_signal.suggested_action


def test_limitations_remain_present_when_context_signals_are_included() -> None:
    context = ClassroomDecisionContext(
        identity=_identity(),
        students_used=5,
        students_eligible=5,
        roster_capped=False,
        topics_observed=2,
        skill_priorities=[_skill_priority()],
        resource_recommendation=None,
        as_of=None,
        context_signals=[_context_signal()],
    )

    result = RuleBasedDecisionSupportProvider().generate(context)

    assert result.limitations
