"""Focused tests for agents/decision_support_agent.py: provenance-aware context building,
structured-output parsing, and failure handling — no live Anthropic API calls."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pandas as pd
import pytest

from digital_twin.agents.decision_support_agent import (
    AnthropicExplanationProvider,
    ClassroomIdentitySummary,
    ExplanationGenerationError,
    LLMDecisionContext,
    SyntheticScenarioSummary,
    build_llm_decision_context,
)
from digital_twin.analytics.context_signals import ContextSignal
from digital_twin.analytics.decision_support import (
    ClassroomDecisionContext,
    ClassroomIdentity,
    RuleBasedDecisionSupportProvider,
)
from digital_twin.analytics.resource_recommendation import (
    ClassroomResourceRecommendation,
    ProblemRecommendation,
)
from digital_twin.analytics.skill_priority import SkillPriorityRecommendation
from digital_twin.analytics.synthetic_context import (
    synthetic_absence_risk_indicator,
    synthetic_classroom_environment,
    synthetic_engagement,
)
from digital_twin.analytics.xapi_absence_risk import FEATURE_COLUMNS, train_baseline_model

FORBIDDEN_IDENTITY_FIELDS = {"student_id", "classroom_id", "class_id", "twin_id", "sensor_id"}


def _identity(class_id: int = 1679) -> ClassroomIdentitySummary:
    return ClassroomIdentitySummary(
        twin_id=uuid4(), source_dataset="assistments", source_class_id=class_id
    )


def _skill_priority() -> SkillPriorityRecommendation:
    return SkillPriorityRecommendation(
        topic_id="7.EE.B.4a-1", priority_score=0.87, average_mastery=0.13, observation_count=6
    )


def _context_signal(source_dataset: str = "environmental_sensors") -> ContextSignal:
    return ContextSignal(
        source_dataset=source_dataset,
        scope_description="Independent environmental sensor reading (sensor_id='CO2_01').",
        metric_name="co2_ppm",
        value=650.0,
        as_of=None,
    )


def _decision_support(*, context_signals: list[ContextSignal] | None = None) -> Any:
    priority = _skill_priority()
    context = ClassroomDecisionContext(
        identity=ClassroomIdentity(
            twin_id=uuid4(), source_dataset="assistments", source_class_id=1679
        ),
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
            recommended_problems=[
                ProblemRecommendation(
                    problem_id=87609,
                    mean_correct=0.65,
                    student_answer_count=60,
                    distance_from_target=0.0,
                )
            ],
        ),
        as_of=None,
        context_signals=context_signals or [],
    )
    return RuleBasedDecisionSupportProvider().generate(context)


# ---------------------------------------------------------------------------
# build_llm_decision_context: provenance
# ---------------------------------------------------------------------------


def test_real_classroom_with_no_mapping_has_no_fabricated_context() -> None:
    """The class_id=1679 case: context_signals=[] on the decision-support object must
    never turn into fabricated CO2/occupancy/xAPI/sensor data in the LLM context."""
    decision_support = _decision_support(context_signals=[])

    llm_context = build_llm_decision_context(_identity(1679), decision_support, mode="real")

    assert llm_context.verified_context_signals == []
    assert len(llm_context.unavailable_context) == 3
    joined = " ".join(llm_context.unavailable_context).lower()
    assert "co2" in joined
    assert "xapi" in joined
    assert "occupancy" in joined


def test_learning_state_carries_real_twin_linked_evidence_unmodified() -> None:
    decision_support = _decision_support()

    llm_context = build_llm_decision_context(_identity(), decision_support)

    assert llm_context.learning_state.priority_skill == "7.EE.B.4a-1"
    assert llm_context.learning_state.rationale == decision_support.rationale
    assert llm_context.learning_state.evidence == decision_support.evidence
    assert llm_context.recommended_resources[0].problem_id == 87609


def test_verified_context_signals_are_tagged_as_benchmark_research() -> None:
    decision_support = _decision_support(context_signals=[_context_signal()])

    llm_context = build_llm_decision_context(_identity(), decision_support)

    assert len(llm_context.verified_context_signals) == 1
    signal = llm_context.verified_context_signals[0]
    assert signal.provenance == "benchmark_research"
    assert signal.source_dataset == "environmental_sensors"


def test_context_signal_summary_has_no_identity_fields() -> None:
    decision_support = _decision_support(context_signals=[_context_signal()])
    llm_context = build_llm_decision_context(_identity(), decision_support)

    signal_fields = set(llm_context.verified_context_signals[0].model_dump().keys())
    assert signal_fields.isdisjoint(FORBIDDEN_IDENTITY_FIELDS)


def test_present_category_is_not_listed_as_unavailable() -> None:
    decision_support = _decision_support(
        context_signals=[_context_signal(source_dataset="environmental_sensors")]
    )
    llm_context = build_llm_decision_context(_identity(), decision_support)

    joined = " ".join(llm_context.unavailable_context).lower()
    assert "co2" not in joined  # environmental_sensors IS present -> not "unavailable"
    assert "xapi" in joined  # xapi_edu_data still absent -> still "unavailable"


def test_demo_mode_does_not_invent_additional_signals() -> None:
    """mode='demo' must only change labeling — never grant permission to add signals
    beyond what the underlying (unmodified) ClassroomDecisionSupport actually has."""
    decision_support_real = _decision_support(context_signals=[])
    decision_support_demo = _decision_support(context_signals=[])

    real_context = build_llm_decision_context(_identity(), decision_support_real, mode="real")
    demo_context = build_llm_decision_context(_identity(), decision_support_demo, mode="demo")

    assert real_context.verified_context_signals == demo_context.verified_context_signals == []
    assert real_context.unavailable_context == demo_context.unavailable_context
    assert demo_context.mode == "demo"
    assert real_context.mode == "real"


def test_context_note_becomes_a_provenance_note_only_when_signals_present() -> None:
    without_signals = build_llm_decision_context(_identity(), _decision_support())
    with_signals = build_llm_decision_context(
        _identity(), _decision_support(context_signals=[_context_signal()])
    )

    assert len(without_signals.provenance_notes) == 1  # only NON_CAUSAL_DISCLAIMER
    assert len(with_signals.provenance_notes) == 2  # + CONTEXT_SIGNAL_DISCLAIMER


# ---------------------------------------------------------------------------
# build_llm_decision_context: synthetic_scenario (demo mode only)
# ---------------------------------------------------------------------------


def _fit_test_xapi_model() -> Any:
    """A real train_baseline_model fit on a tiny in-memory frame — enough to run
    synthetic_absence_risk_indicator's real predict() call without a live DB."""
    frame = pd.DataFrame(
        {
            "stage_id": ["lowerlevel", "MiddleSchool"] * 5,
            "grade_id": ["G-02", "G-07"] * 5,
            "section_id": ["A", "B"] * 5,
            "topic": ["Math", "Science"] * 5,
            "semester": ["F", "S"] * 5,
            "parent_answering_survey": ["Yes", "No"] * 5,
            "parent_school_satisfaction": ["Good", "Bad"] * 5,
            "raised_hands": [5] * 5 + [80] * 5,
            "visited_resources": [5] * 5 + [80] * 5,
            "announcements_view": [2] * 5 + [35] * 5,
            "discussion": [3] * 5 + [55] * 5,
        }
    )
    target = pd.Series([1] * 5 + [0] * 5, name="is_high_absence_risk")
    return train_baseline_model(frame[FEATURE_COLUMNS], target)


def _synthetic_scenario(class_id: int = 1679) -> SyntheticScenarioSummary:
    engagement = synthetic_engagement("assistments", class_id)
    return SyntheticScenarioSummary(
        environment=synthetic_classroom_environment("assistments", class_id),
        engagement=engagement,
        absence_risk=synthetic_absence_risk_indicator(engagement, model=_fit_test_xapi_model()),
    )


def test_real_mode_rejects_a_synthetic_scenario() -> None:
    """Real mode must never carry fabricated data — enforced here, not just by
    convention, so no future caller can accidentally leak synthetic data into it."""
    decision_support = _decision_support()

    try:
        build_llm_decision_context(
            _identity(), decision_support, mode="real", synthetic_scenario=_synthetic_scenario()
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "synthetic_scenario" in str(exc)


def test_real_mode_without_synthetic_scenario_leaves_field_none() -> None:
    decision_support = _decision_support()

    llm_context = build_llm_decision_context(_identity(), decision_support, mode="real")

    assert llm_context.synthetic_scenario is None


def test_demo_mode_carries_synthetic_scenario_through_unmodified() -> None:
    decision_support = _decision_support()
    scenario = _synthetic_scenario()

    llm_context = build_llm_decision_context(
        _identity(), decision_support, mode="demo", synthetic_scenario=scenario
    )

    assert llm_context.synthetic_scenario == scenario
    assert llm_context.synthetic_scenario.environment.provenance == "synthetic_demo"
    assert llm_context.synthetic_scenario.engagement.provenance == "synthetic_demo"
    assert llm_context.synthetic_scenario.absence_risk.provenance == "synthetic_demo"


def test_demo_mode_without_synthetic_scenario_still_works() -> None:
    """synthetic_scenario is optional even in demo mode — callers that don't have one
    yet (or don't want one) must not be forced to supply it."""
    decision_support = _decision_support()

    llm_context = build_llm_decision_context(_identity(), decision_support, mode="demo")

    assert llm_context.synthetic_scenario is None
    assert llm_context.mode == "demo"


def test_synthetic_scenario_never_shares_fields_with_verified_context_signals() -> None:
    """Structural guarantee: the synthetic scenario type and the real
    benchmark-signal type must never be interchangeable."""
    decision_support = _decision_support(context_signals=[_context_signal()])
    llm_context = build_llm_decision_context(
        _identity(), decision_support, mode="demo", synthetic_scenario=_synthetic_scenario()
    )

    assert llm_context.synthetic_scenario is not None
    assert llm_context.verified_context_signals
    synthetic_dump = llm_context.synthetic_scenario.model_dump()
    for real_signal in llm_context.verified_context_signals:
        assert real_signal.model_dump() not in (
            synthetic_dump["environment"],
            synthetic_dump["engagement"],
            synthetic_dump["absence_risk"],
        )


# ---------------------------------------------------------------------------
# AnthropicExplanationProvider: structured-output parsing and failure handling
# ---------------------------------------------------------------------------


def _fake_tool_use_response(input_payload: dict[str, Any]) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", input=input_payload)
    return SimpleNamespace(content=[block])


def _fake_text_only_response() -> SimpleNamespace:
    block = SimpleNamespace(type="text", text="not a tool call")
    return SimpleNamespace(content=[block])


def _llm_context() -> LLMDecisionContext:
    return build_llm_decision_context(_identity(), _decision_support())


def test_provider_returns_validated_explanation_on_success() -> None:
    valid_payload = {
        "summary": "s",
        "reasoning": "r",
        "recommended_actions": ["a"],
        "evidence_used": ["e"],
        "limitations": ["l"],
    }
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_: _fake_tool_use_response(valid_payload))
    )
    provider = AnthropicExplanationProvider(client=fake_client)  # type: ignore[arg-type]

    explanation = provider.generate_explanation(_llm_context())

    assert explanation.summary == "s"
    assert explanation.mode == "real"


def test_provider_raises_when_no_tool_use_block_present() -> None:
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_: _fake_text_only_response())
    )
    provider = AnthropicExplanationProvider(client=fake_client)  # type: ignore[arg-type]

    with pytest.raises(ExplanationGenerationError, match="tool_use"):
        provider.generate_explanation(_llm_context())


def test_provider_raises_on_schema_invalid_tool_input() -> None:
    invalid_payload = {"summary": "s"}  # missing required fields
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **_: _fake_tool_use_response(invalid_payload))
    )
    provider = AnthropicExplanationProvider(client=fake_client)  # type: ignore[arg-type]

    with pytest.raises(ExplanationGenerationError, match="schema validation"):
        provider.generate_explanation(_llm_context())


def test_provider_raises_when_api_key_not_configured() -> None:
    provider = AnthropicExplanationProvider(client=None)
    provider._get_client = lambda: (_ for _ in ()).throw(  # type: ignore[method-assign]
        ExplanationGenerationError("ANTHROPIC_API_KEY is not configured")
    )

    with pytest.raises(ExplanationGenerationError, match="ANTHROPIC_API_KEY"):
        provider.generate_explanation(_llm_context())


def test_provider_wraps_underlying_api_errors() -> None:
    def _raise_api_error(**_: Any) -> Any:
        from anthropic import APIConnectionError

        raise APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=_raise_api_error))
    provider = AnthropicExplanationProvider(client=fake_client)  # type: ignore[arg-type]

    with pytest.raises(ExplanationGenerationError, match="Anthropic API call failed"):
        provider.generate_explanation(_llm_context())
