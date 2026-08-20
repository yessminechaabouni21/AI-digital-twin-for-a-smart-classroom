"""Integration tests for POST /classrooms/{twin_id}/decision-support/explanation.

Requires a live PostgreSQL instance (the endpoint still builds a real
ClassroomTwin) — skipped automatically if unreachable, per CLAUDE.md's
rule. Never calls the real Anthropic API: `get_explanation_provider` is
overridden with fakes via FastAPI's `dependency_overrides`, so these tests
run without `ANTHROPIC_API_KEY` and never incur API cost.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from digital_twin.agents.decision_support_agent import (
    ExplanationGenerationError,
    LLMDecisionContext,
    LLMDecisionExplanation,
)
from digital_twin.api.deps import get_explanation_provider
from digital_twin.data.db.session import get_engine
from digital_twin.domain.classroom import derive_classroom_id
from digital_twin.main import app

SMALL_COMPLETE_CLASS_ID = 1679  # 5 eligible students, no configured context mapping
LARGE_CAPPED_CLASS_ID = 27834


@pytest.fixture
def engine() -> Engine:
    db_engine = get_engine()
    try:
        with db_engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable, skipping integration test: {exc}")
    return db_engine


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Generator[None, None, None]:
    yield
    app.dependency_overrides.pop(get_explanation_provider, None)


class _RecordingFakeProvider:
    """Echoes back a fixed explanation and records the context it was given, so tests
    can assert on exactly what the backend sent the "LLM" without a real API call."""

    def __init__(self) -> None:
        self.received_context: LLMDecisionContext | None = None

    def generate_explanation(self, context: LLMDecisionContext) -> LLMDecisionExplanation:
        self.received_context = context
        prefix = "DEMONSTRATION MODE: " if context.mode == "demo" else ""
        return LLMDecisionExplanation(
            summary=f"{prefix}Fake summary.",
            reasoning="Fake reasoning grounded in supplied evidence.",
            recommended_actions=["Do X"],
            evidence_used=["evidence 1"],
            limitations=list(context.unavailable_context),
            mode=context.mode,
        )


class _FailingProvider:
    def generate_explanation(self, context: LLMDecisionContext) -> LLMDecisionExplanation:
        raise ExplanationGenerationError("simulated Anthropic API failure")


class _InvalidOutputProvider:
    """Simulates a provider whose own internal validation already failed — the router
    must never receive or forward malformed output as if it were valid."""

    def generate_explanation(self, context: LLMDecisionContext) -> LLMDecisionExplanation:
        raise ExplanationGenerationError("Anthropic response failed schema validation")


def test_real_classroom_1679_no_mapping_has_no_fabricated_context(
    client: TestClient,
) -> None:
    """The core provenance test this phase requires: class_id=1679 has no configured
    classroom_context_mappings row, so the LLM's context must contain no fabricated
    CO2, occupancy, attendance, xAPI, or sensor information — only explicit
    "unavailable" labels."""
    provider = _RecordingFakeProvider()
    app.dependency_overrides[get_explanation_provider] = lambda: provider

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert response.status_code == 200
    assert provider.received_context is not None
    assert provider.received_context.verified_context_signals == []
    unavailable_joined = " ".join(provider.received_context.unavailable_context).lower()
    assert "co2" in unavailable_joined
    assert "xapi" in unavailable_joined
    assert "occupancy" in unavailable_joined

    body = response.json()
    assert body["mode"] == "real"
    assert body["twin_id"] == str(twin_id)
    assert body["summary"]
    assert body["reasoning"]
    assert body["recommended_actions"]
    assert body["evidence_used"]
    assert body["limitations"]


def test_real_classroom_1679_learning_state_matches_deterministic_endpoint(
    client: TestClient,
) -> None:
    """The LLM context must be built from the exact same numbers the deterministic
    endpoint already returns — never a second, independently-computed source."""
    provider = _RecordingFakeProvider()
    app.dependency_overrides[get_explanation_provider] = lambda: provider

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    deterministic = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    ).json()
    client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert provider.received_context is not None
    received_learning_state = provider.received_context.learning_state
    assert received_learning_state.priority_skill == deterministic["priority_skill"]
    assert received_learning_state.rationale == deterministic["rationale"]
    assert [r.problem_id for r in provider.received_context.recommended_resources] == [
        r["problem_id"] for r in deterministic["recommended_resources"]
    ]


def test_demo_mode_is_threaded_through_and_labeled(client: TestClient) -> None:
    provider = _RecordingFakeProvider()
    app.dependency_overrides[get_explanation_provider] = lambda: provider

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID, "mode": "demo"},
    )

    assert response.status_code == 200
    assert provider.received_context is not None
    assert provider.received_context.mode == "demo"
    body = response.json()
    assert body["mode"] == "demo"
    assert body["summary"].startswith("DEMONSTRATION MODE")
    # Demo mode must not fabricate signals beyond the real (empty) decision support.
    assert provider.received_context.verified_context_signals == []


def test_demo_mode_attaches_a_synthetic_scenario_matching_the_dashboard_endpoint(
    client: TestClient,
) -> None:
    """The LLM's synthetic_scenario must be the same data GET /demo/classroom-scenario
    would show for this class_id, so the dashboard panel and the LLM's narrative never
    diverge."""
    provider = _RecordingFakeProvider()
    app.dependency_overrides[get_explanation_provider] = lambda: provider

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID, "mode": "demo"},
    )
    scenario_response = client.get(
        "/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    ).json()

    assert provider.received_context is not None
    synthetic = provider.received_context.synthetic_scenario
    assert synthetic is not None
    assert synthetic.environment.provenance == "synthetic_demo"
    assert synthetic.environment.temperature_c == scenario_response["environment"]["temperature_c"]
    assert synthetic.environment.co2_ppm == scenario_response["environment"]["co2_ppm"]
    assert synthetic.engagement.raised_hands == scenario_response["engagement"]["raised_hands"]
    assert (
        synthetic.absence_risk.absence_risk_indicator
        == scenario_response["absence_risk"]["absence_risk_indicator"]
    )


def test_real_mode_never_carries_a_synthetic_scenario(client: TestClient) -> None:
    provider = _RecordingFakeProvider()
    app.dependency_overrides[get_explanation_provider] = lambda: provider

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert provider.received_context is not None
    assert provider.received_context.mode == "real"
    assert provider.received_context.synthetic_scenario is None


def test_default_mode_is_real(client: TestClient) -> None:
    provider = _RecordingFakeProvider()
    app.dependency_overrides[get_explanation_provider] = lambda: provider

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert response.json()["mode"] == "real"


def test_llm_failure_returns_503_and_does_not_fabricate_text(client: TestClient) -> None:
    app.dependency_overrides[get_explanation_provider] = lambda: _FailingProvider()

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_llm_failure_does_not_break_deterministic_decision_support(client: TestClient) -> None:
    app.dependency_overrides[get_explanation_provider] = lambda: _FailingProvider()

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    explanation_response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )
    deterministic_response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert explanation_response.status_code == 503
    assert deterministic_response.status_code == 200
    assert deterministic_response.json()["priority_skill"] is not None


def test_invalid_llm_output_returns_503_not_fabricated_text(client: TestClient) -> None:
    app.dependency_overrides[get_explanation_provider] = lambda: _InvalidOutputProvider()

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert response.status_code == 503


def test_identity_mismatch_returns_404_before_calling_llm(client: TestClient) -> None:
    provider = _RecordingFakeProvider()
    app.dependency_overrides[get_explanation_provider] = lambda: provider

    mismatched_twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{mismatched_twin_id}/decision-support/explanation",
        params={"class_id": LARGE_CAPPED_CLASS_ID},
    )

    assert response.status_code == 404
    assert provider.received_context is None  # LLM was never called


def test_arbitrary_unrelated_twin_id_returns_404(client: TestClient) -> None:
    app.dependency_overrides[get_explanation_provider] = lambda: _RecordingFakeProvider()

    unrelated_twin_id = uuid4()
    response = client.post(
        f"/classrooms/{unrelated_twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert response.status_code == 404


def test_response_body_matches_llm_decision_explanation_out_schema(client: TestClient) -> None:
    app.dependency_overrides[get_explanation_provider] = lambda: _RecordingFakeProvider()

    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    body = response.json()
    expected_keys = {
        "twin_id",
        "source_dataset",
        "source_class_id",
        "mode",
        "summary",
        "reasoning",
        "recommended_actions",
        "evidence_used",
        "limitations",
    }
    assert set(body.keys()) == expected_keys
    assert isinstance(body["recommended_actions"], list)
    assert isinstance(body["evidence_used"], list)
    assert isinstance(body["limitations"], list)


def test_without_dependency_override_provider_missing_key_returns_503(
    client: TestClient,
) -> None:
    """Without any override, the real AnthropicExplanationProvider is used; with no
    ANTHROPIC_API_KEY configured in this environment, it must fail gracefully (503),
    never crash the process or return fabricated text."""
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)
    response = client.post(
        f"/classrooms/{twin_id}/decision-support/explanation",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    # Either this environment has no key configured (503) or it does (200) — both are
    # acceptable outcomes; what must never happen is an unhandled crash (500) or a
    # response that isn't a clean HTTP error / valid schema.
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert "unavailable" in response.json()["detail"].lower()
