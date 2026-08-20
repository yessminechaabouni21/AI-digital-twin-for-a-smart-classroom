"""LLM explanation layer over the deterministic ClassroomDecisionSupport output.

Pivot from this module's original TODO sketch: rather than a second
`analytics.decision_support.DecisionSupportProvider` implementation
(context -> `ClassroomDecisionSupport`, replacing the rule-based one), this
module is an *explanation* layer that sits on top of an already-computed
`ClassroomDecisionSupport` —

    RuleBasedDecisionSupportProvider (unchanged, still the source of truth)
        -> ClassroomDecisionSupport
        -> build_llm_decision_context()      (this module, no LLM call, no I/O)
        -> LLMDecisionContext                 (the LLM's *entire* input)
        -> ExplanationProvider.generate_explanation()   (this module, Anthropic SDK)
        -> LLMDecisionExplanation

The deterministic `GET /classrooms/{twin_id}/decision-support` endpoint
never depends on this module or on the Anthropic SDK — see
`api/routers/classrooms.py`'s separate `POST .../decision-support/explanation`
endpoint, which is the only caller. This keeps CLAUDE.md's "agents/ — the
only place Anthropic SDK calls live" boundary and its "agents call into
twin_engine/ and analytics/ ... they don't reach into data/db/ directly"
rule: this module never imports SQLAlchemy, `ClassroomTwin`, or any
repository — every field on `LLMDecisionContext` is copied or trivially
reshaped from a `ClassroomDecisionSupport` the caller already computed.

Three data-provenance categories this module enforces structurally, not by
convention:

    A. Real twin-linked data   -> `LLMDecisionContext.learning_state` /
                                   `.recommended_resources` (BKT/skill-priority/
                                   resource-recommendation output; always real
                                   for a real classroom).
    B. Benchmark/research data -> `LLMDecisionContext.verified_context_signals`,
                                   each item stamped `provenance="benchmark_research"`
                                   (a field `ContextSignal` itself deliberately does
                                   NOT have — see analytics/context_signals.py) so the
                                   LLM cannot describe one as classroom-observed.
    C. Synthetic/demo data     -> `LLMDecisionContext.mode == "demo"`; the prompt
                                   (agents/prompts/decision_support_explanation.md)
                                   requires every "demo" response to open with the
                                   literal phrase "DEMONSTRATION MODE". This module
                                   never generates synthetic data itself — `mode`
                                   only changes labeling of whatever
                                   `ClassroomDecisionSupport` the caller already
                                   built. `LLMDecisionContext.synthetic_scenario`
                                   (a `SyntheticScenarioSummary`, always `None` in
                                   real mode — see `build_llm_decision_context`'s
                                   docstring) carries a fabricated
                                   `provenance="synthetic_demo"` Smart-Classroom
                                   scenario from `analytics/synthetic_context.py`,
                                   never generated here, and structurally distinct
                                   from category B: it is deliberately classroom-
                                   scoped (the demo narrative) and never confusable
                                   with `verified_context_signals`. Its `environment`/
                                   `engagement` are entirely fabricated; its
                                   `absence_risk` is subtler — a REAL prediction from
                                   the real, already-trained xAPI absence-risk model
                                   (`model_provenance="real_xapi_trained_model"`) run
                                   on that fabricated engagement input
                                   (`input_provenance="synthetic_demo"`) — see
                                   `SyntheticAbsenceRiskIndicator`'s own docstring for
                                   why both facts must be surfaced together.

Missing context is represented explicitly (`unavailable_context: list[str]`),
never filled with a guess — see `build_llm_decision_context`'s docstring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from anthropic import Anthropic, AnthropicError
from pydantic import BaseModel, Field, ValidationError

from digital_twin.analytics.decision_support import (
    NON_CAUSAL_DISCLAIMER,
    ClassroomDecisionSupport,
)
from digital_twin.analytics.synthetic_context import (
    SyntheticAbsenceRiskIndicator,
    SyntheticClassroomEnvironment,
    SyntheticEngagement,
)
from digital_twin.config import get_settings

_PROMPT_PATH = Path(__file__).parent / "prompts" / "decision_support_explanation.md"

DataMode = Literal["real", "demo"]

# source_dataset -> human-readable label, used to build `unavailable_context`.
# "uci_occupancy" is deliberately absent from this dict: it is handled by
# _ALWAYS_UNAVAILABLE_CONTEXT below instead, since it is unconditionally
# unavailable (see analytics/context_signals.py::occupancy_context_signal's
# docstring — no inference-on-new-observation function exists for it), not
# something that becomes available once a mapping is configured.
_KNOWN_CONTEXT_CATEGORIES: dict[str, str] = {
    "environmental_sensors": "environmental/CO2 sensor context",
    "xapi_edu_data": "xAPI-Edu-Data engagement/absence-risk context",
}

_ALWAYS_UNAVAILABLE_CONTEXT = (
    "UCI Occupancy Detection room-occupancy benchmark data (no inference-on-new-"
    "observation model exists for it in this system, so it is never available for "
    "any classroom)"
)


class ClassroomIdentitySummary(BaseModel):
    """Which classroom this explanation is about — carried through unmodified."""

    twin_id: UUID
    source_dataset: str
    source_class_id: int


class LearningStateSummary(BaseModel):
    """Twin-linked evidence only — copied unmodified from ClassroomDecisionSupport."""

    priority_skill: str | None
    rationale: str
    evidence: list[str]
    limitations: list[str]


class RecommendedResourceSummary(BaseModel):
    problem_id: int
    mean_correct: float
    student_answer_count: int


class ContextSignalSummary(BaseModel):
    """One ContextSignal, explicitly re-tagged as benchmark/research data.

    Deliberately NOT the same type as `analytics/context_signals.py::ContextSignal`
    (which stays exactly 5 fields, no provenance field, no identity field) —
    this LLM-input-only type adds `provenance` so the prompt/model has an
    explicit, machine-checkable label distinguishing "data about an
    unrelated cohort/room/sensor" from "evidence about this classroom".
    """

    source_dataset: str
    scope_description: str
    metric_name: str
    value: float
    provenance: Literal["benchmark_research"] = "benchmark_research"


class SyntheticScenarioSummary(BaseModel):
    """A fabricated, illustrative Smart-Classroom scenario, carried through unmodified
    from `analytics/synthetic_context.py`.

    Deliberately a separate type from `ContextSignalSummary`/
    `verified_context_signals`: that category is real benchmark/research data
    with no classroom identity; this category is synthetic data deliberately
    scoped to the classroom being demonstrated. `build_llm_decision_context`
    never generates this data itself — see its docstring — and this field is
    only ever non-`None` when `mode == "demo"`.
    """

    environment: SyntheticClassroomEnvironment
    engagement: SyntheticEngagement
    absence_risk: SyntheticAbsenceRiskIndicator


class LLMDecisionContext(BaseModel):
    """Structured, provenance-aware input to the LLM explanation layer.

    This is the *entire* information the LLM is allowed to reason over — the
    LLM has no database access, no tool access, and no ability to fetch
    anything itself (per CLAUDE.md: "the backend remains responsible for
    retrieving and validating data"). Every field here was already computed
    and validated before this object was built.
    """

    mode: DataMode
    identity: ClassroomIdentitySummary
    learning_state: LearningStateSummary
    recommended_resources: list[RecommendedResourceSummary]
    verified_context_signals: list[ContextSignalSummary]
    unavailable_context: list[str]
    provenance_notes: list[str]
    synthetic_scenario: SyntheticScenarioSummary | None = Field(
        default=None,
        description=(
            "A fabricated, provenance='synthetic_demo' Smart-Classroom scenario. "
            "Always None when mode='real' — build_llm_decision_context raises if a "
            "caller ever supplies one alongside mode='real'."
        ),
    )


class LLMDecisionExplanation(BaseModel):
    """Structured, teacher-facing explanation — parsed/validated from the LLM's
    forced tool call, never accepted as free-form text."""

    summary: str
    reasoning: str
    recommended_actions: list[str]
    evidence_used: list[str]
    limitations: list[str]
    mode: DataMode


class ExplanationGenerationError(Exception):
    """Raised when no valid LLMDecisionExplanation could be produced — an Anthropic
    API failure/timeout, a malformed/missing tool call, or output that fails schema
    validation. Callers (the API router) must catch this and return a clear error,
    never fabricated text, and it must never affect the deterministic decision-support
    result — see api/routers/classrooms.py's `/decision-support/explanation` handler.
    """


def build_llm_decision_context(
    identity: ClassroomIdentitySummary,
    decision_support: ClassroomDecisionSupport,
    *,
    mode: DataMode = "real",
    synthetic_scenario: SyntheticScenarioSummary | None = None,
) -> LLMDecisionContext:
    """Build the LLM's entire input from an already-computed ClassroomDecisionSupport.

    Performs no DB access and recomputes nothing — every field here is
    copied or trivially reshaped from `decision_support`, which was already
    produced by `RuleBasedDecisionSupportProvider`. `mode` only changes
    labeling: even when `mode="demo"`, this function includes only whatever
    `decision_support.context_signals` actually contains — it never invents
    additional signals for demonstration purposes. If
    `decision_support.context_signals` is empty (as it is for any real
    classroom with no configured `classroom_context_mappings` row, e.g.
    class_id=1679 today), `verified_context_signals` here is empty too, and
    every known context category ends up in `unavailable_context` instead.

    `synthetic_scenario`, if supplied, is carried through completely
    unmodified onto `LLMDecisionContext.synthetic_scenario` — this function
    never generates it itself (see `analytics/synthetic_context.py` for the
    only place that happens). Passing it together with `mode="real"` raises
    `ValueError`: real mode must never carry fabricated data into the LLM's
    context, so this is enforced here rather than trusted to every caller.
    """
    if mode == "real" and synthetic_scenario is not None:
        raise ValueError("synthetic_scenario must never be supplied when mode='real'.")

    verified_signals = [
        ContextSignalSummary(
            source_dataset=signal.source_dataset,
            scope_description=signal.scope_description,
            metric_name=signal.metric_name,
            value=signal.value,
        )
        for signal in decision_support.context_signals
    ]

    present_categories = {signal.source_dataset for signal in decision_support.context_signals}
    unavailable_context = [
        label
        for source_dataset, label in _KNOWN_CONTEXT_CATEGORIES.items()
        if source_dataset not in present_categories
    ]
    unavailable_context.append(_ALWAYS_UNAVAILABLE_CONTEXT)

    provenance_notes = [NON_CAUSAL_DISCLAIMER]
    if decision_support.context_note:
        provenance_notes.append(decision_support.context_note)

    return LLMDecisionContext(
        mode=mode,
        identity=identity,
        learning_state=LearningStateSummary(
            priority_skill=decision_support.priority_skill,
            rationale=decision_support.rationale,
            evidence=decision_support.evidence,
            limitations=decision_support.limitations,
        ),
        recommended_resources=[
            RecommendedResourceSummary(
                problem_id=resource.problem_id,
                mean_correct=resource.mean_correct,
                student_answer_count=resource.student_answer_count,
            )
            for resource in decision_support.recommended_resources
        ],
        verified_context_signals=verified_signals,
        unavailable_context=unavailable_context,
        provenance_notes=provenance_notes,
        synthetic_scenario=synthetic_scenario,
    )


class ExplanationProvider(Protocol):
    """The stable contract every explanation provider satisfies — so the API router
    (and tests) never need to change when the provider does. Mirrors
    `analytics/decision_support.py::DecisionSupportProvider`'s same pattern."""

    def generate_explanation(self, context: LLMDecisionContext) -> LLMDecisionExplanation:
        """Return a structured explanation of `context`, or raise ExplanationGenerationError."""
        ...


_EXPLANATION_TOOL_NAME = "submit_explanation"

_EXPLANATION_TOOL_SCHEMA = {
    "name": _EXPLANATION_TOOL_NAME,
    "description": (
        "Submit the structured, teacher-facing explanation of the supplied "
        "classroom decision-support context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "reasoning": {"type": "string"},
            "recommended_actions": {"type": "array", "items": {"type": "string"}},
            "evidence_used": {"type": "array", "items": {"type": "string"}},
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "summary",
            "reasoning",
            "recommended_actions",
            "evidence_used",
            "limitations",
        ],
    },
}


class AnthropicExplanationProvider:
    """ExplanationProvider backed by the Anthropic Messages API.

    Forces a structured response via a single required tool call
    (`_EXPLANATION_TOOL_SCHEMA`) instead of parsing free-form text — the
    standard way to get schema-validated output from Claude's Messages API.
    Reads `Settings.anthropic_model`/`anthropic_api_key` (CLAUDE.md: "Don't
    hardcode model strings in agents/ — read from settings"). The client is
    constructed lazily, on first `generate_explanation` call, so a process
    with no `ANTHROPIC_API_KEY` configured can still start up and serve the
    deterministic decision-support endpoint — the error only surfaces when
    the explanation endpoint is actually used, as `ExplanationGenerationError`.
    """

    def __init__(self, client: Anthropic | None = None) -> None:
        self._client = client
        self._system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    def _get_client(self) -> Anthropic:
        if self._client is not None:
            return self._client

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ExplanationGenerationError(
                "ANTHROPIC_API_KEY is not configured; the explanation layer is unavailable."
            )
        self._client = Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def generate_explanation(self, context: LLMDecisionContext) -> LLMDecisionExplanation:
        client = self._get_client()
        settings = get_settings()

        # The tool/tool_choice/messages shapes below are built as plain dicts (not the
        # SDK's precise TypedDicts) so this module has no dependency on internal
        # anthropic.types names beyond Anthropic/AnthropicError; cast(Any, ...) only
        # widens the *static* type for mypy — the runtime dicts are exactly what the
        # Messages API documents.
        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                system=self._system_prompt,
                tools=cast(Any, [_EXPLANATION_TOOL_SCHEMA]),
                tool_choice=cast(Any, {"type": "tool", "name": _EXPLANATION_TOOL_NAME}),
                messages=cast(Any, [{"role": "user", "content": context.model_dump_json()}]),
            )
        except AnthropicError as exc:
            raise ExplanationGenerationError(f"Anthropic API call failed: {exc}") from exc

        tool_use_block = next(
            (block for block in response.content if block.type == "tool_use"), None
        )
        if tool_use_block is None:
            raise ExplanationGenerationError(
                "Anthropic response did not include the expected tool_use block."
            )

        try:
            return LLMDecisionExplanation.model_validate(
                {**tool_use_block.input, "mode": context.mode}
            )
        except ValidationError as exc:
            raise ExplanationGenerationError(
                f"Anthropic response failed schema validation: {exc}"
            ) from exc


__all__ = [
    "AnthropicExplanationProvider",
    "ClassroomIdentitySummary",
    "ContextSignalSummary",
    "DataMode",
    "ExplanationGenerationError",
    "ExplanationProvider",
    "LLMDecisionContext",
    "LLMDecisionExplanation",
    "LearningStateSummary",
    "RecommendedResourceSummary",
    "SyntheticScenarioSummary",
    "build_llm_decision_context",
]
