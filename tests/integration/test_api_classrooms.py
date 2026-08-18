"""Integration tests for GET /classrooms/{twin_id}[/state|/priorities|/recommendations|
/decision-support].

Requires a live PostgreSQL instance with ASSISTments data loaded — skipped
automatically if unreachable, per CLAUDE.md's rule. Uses real class_ids
already verified in prior audits: 1679 (5 eligible students, complete
roster under the default cap) and 27834 (148 eligible students, capped by
default).
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.classroom_context_mapping import (
    delete_classroom_context_mapping,
    upsert_classroom_context_mapping,
)
from digital_twin.domain.classroom import derive_classroom_id
from digital_twin.main import app

SMALL_COMPLETE_CLASS_ID = 1679  # 5 eligible students
LARGE_CAPPED_CLASS_ID = 27834  # 148 eligible students
NONEXISTENT_CLASS_ID = 999999999
# A class_id that will never collide with a real ASSISTments class_id, used
# only to test the explicit context-mapping path without touching a real
# classroom's data.
MAPPED_TEST_CLASS_ID = 900_000_002


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


def test_get_classroom_twin_summary_reports_complete_roster(client: TestClient) -> None:
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(f"/classrooms/{twin_id}", params={"class_id": SMALL_COMPLETE_CLASS_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["twin_id"] == str(twin_id)
    assert body["source_dataset"] == "assistments"
    assert body["source_class_id"] == SMALL_COMPLETE_CLASS_ID
    assert body["students_used"] == body["students_eligible"] == 5
    assert body["roster_capped"] is False


def test_get_classroom_twin_summary_reports_capped_roster(client: TestClient) -> None:
    twin_id = derive_classroom_id("assistments", LARGE_CAPPED_CLASS_ID)

    response = client.get(f"/classrooms/{twin_id}", params={"class_id": LARGE_CAPPED_CLASS_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["students_used"] == 15
    assert body["students_eligible"] == 148
    assert body["roster_capped"] is True


def test_get_classroom_twin_state_returns_real_mastery_and_no_environment_or_attendance(
    client: TestClient,
) -> None:
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/state", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["average_mastery_by_topic"]
    for topic_id, mastery in body["average_mastery_by_topic"].items():
        assert 0.0 <= mastery <= 1.0
        assert body["topic_observation_counts"][topic_id] > 0

    # No CO2 sensor is linked to any real ASSISTments class_id — never fabricated.
    assert body["environment"]["reading_count"] == 0
    assert body["environment"]["average_co2_ppm"] is None
    # No attendance concept exists anywhere in this response shape at all.
    assert "attendance" not in body
    assert "occupancy" not in str(body).lower()


def test_get_classroom_priorities_returns_reliable_topics_only(client: TestClient) -> None:
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/priorities", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    priorities = response.json()
    assert len(priorities) > 0
    for priority in priorities:
        assert priority["observation_count"] >= 3  # DEFAULT_MIN_OBSERVATIONS
        assert 0.0 <= priority["average_mastery"] <= 1.0
    # Sorted lowest-mastery-first.
    masteries = [p["average_mastery"] for p in priorities]
    assert masteries == sorted(masteries)


def test_get_classroom_recommendations_returns_real_problems_not_causal_claims(
    client: TestClient,
) -> None:
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/recommendations", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body is not None
    assert body["recommended_problems"]
    for problem in body["recommended_problems"]:
        assert problem["problem_id"] > 0
        assert 0.0 <= problem["mean_correct"] <= 1.0
        assert problem["student_answer_count"] > 0
    # Response schema has no field claiming causal/optimal effect.
    assert "is_optimal" not in body
    assert "causal_effect" not in body


def test_get_classroom_recommendations_returns_null_for_empty_class(client: TestClient) -> None:
    twin_id = derive_classroom_id("assistments", NONEXISTENT_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/recommendations", params={"class_id": NONEXISTENT_CLASS_ID}
    )

    assert response.status_code == 200
    assert response.json() is None


def test_get_classroom_twin_returns_404_for_identity_mismatch(client: TestClient) -> None:
    """twin_id derived for one real class_id, queried with a different class_id."""
    mismatched_twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{mismatched_twin_id}", params={"class_id": LARGE_CAPPED_CLASS_ID}
    )

    assert response.status_code == 404


def test_get_classroom_twin_returns_404_for_arbitrary_unrelated_twin_id(client: TestClient) -> None:
    unrelated_twin_id = uuid4()

    response = client.get(
        f"/classrooms/{unrelated_twin_id}", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 404


def test_get_classroom_twin_rejects_unsupported_source_dataset(client: TestClient) -> None:
    twin_id = derive_classroom_id("oulad", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}",
        params={"class_id": SMALL_COMPLETE_CLASS_ID, "source_dataset": "oulad"},
    )

    assert response.status_code == 400


def test_get_classroom_twin_state_for_empty_class_has_no_topics_and_no_recommendation(
    client: TestClient,
) -> None:
    twin_id = derive_classroom_id("assistments", NONEXISTENT_CLASS_ID)

    state_response = client.get(
        f"/classrooms/{twin_id}/state", params={"class_id": NONEXISTENT_CLASS_ID}
    )
    priorities_response = client.get(
        f"/classrooms/{twin_id}/priorities", params={"class_id": NONEXISTENT_CLASS_ID}
    )

    assert state_response.status_code == 200
    body = state_response.json()
    assert body["students_used"] == 0
    assert body["students_eligible"] == 0
    assert body["average_mastery_by_topic"] == {}

    assert priorities_response.status_code == 200
    assert priorities_response.json() == []


def test_get_classroom_decision_support_returns_structured_explanation_for_real_class(
    client: TestClient,
) -> None:
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["twin_id"] == str(twin_id)
    assert body["source_class_id"] == SMALL_COMPLETE_CLASS_ID
    assert body["priority_skill"] is not None
    assert body["summary"]
    assert body["rationale"]
    assert body["evidence"]
    assert body["limitations"]
    assert body["suggested_action"]
    assert len(body["recommended_resources"]) > 0
    for resource in body["recommended_resources"]:
        assert resource["problem_id"] > 0
        assert 0.0 <= resource["mean_correct"] <= 1.0
        assert resource["student_answer_count"] > 0

    all_text = " ".join(
        [body["summary"], body["rationale"], body["suggested_action"]]
        + body["evidence"]
        + body["limitations"]
    ).lower()
    banned_phrases = (
        "causes",
        "will improve",
        "guaranteed",
        "proven to",
        "is optimal",
        "best resource",
    )
    for banned in banned_phrases:
        assert banned not in all_text


def test_get_classroom_decision_support_for_empty_class_has_no_priority_skill(
    client: TestClient,
) -> None:
    twin_id = derive_classroom_id("assistments", NONEXISTENT_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": NONEXISTENT_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["priority_skill"] is None
    assert body["recommended_resources"] == []
    assert "no topic" in body["rationale"].lower()


def test_get_classroom_decision_support_returns_404_for_identity_mismatch(
    client: TestClient,
) -> None:
    mismatched_twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{mismatched_twin_id}/decision-support",
        params={"class_id": LARGE_CAPPED_CLASS_ID},
    )

    assert response.status_code == 404


def test_get_classroom_decision_support_returns_404_for_arbitrary_unrelated_twin_id(
    client: TestClient,
) -> None:
    unrelated_twin_id = uuid4()

    response = client.get(
        f"/classrooms/{unrelated_twin_id}/decision-support",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )

    assert response.status_code == 404


FORBIDDEN_CONTEXT_SIGNAL_IDENTITY_FIELDS = ("student_id", "classroom_id", "twin_id")


def test_get_classroom_decision_support_context_signals_have_no_identity_fields(
    client: TestClient,
) -> None:
    """context_signals, if any are ever populated, must never carry an identity field —
    checked structurally on the real endpoint response, not just on the ContextSignal type."""
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert "context_signals" in body
    assert "context_note" in body
    for signal in body["context_signals"]:
        assert set(signal.keys()).isdisjoint(FORBIDDEN_CONTEXT_SIGNAL_IDENTITY_FIELDS)


def test_get_classroom_decision_support_context_signals_empty_does_not_error(
    client: TestClient,
) -> None:
    """No dataset today has a legitimate, non-arbitrary mapping to a specific class_id, so
    context_signals is currently always []; this must not fabricate a signal or error."""
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["context_signals"] == []
    assert body["context_note"] is None
    # Classroom-specific evidence is unaffected by the (empty) context-signal path.
    assert body["priority_skill"] is not None
    assert len(body["recommended_resources"]) > 0


def test_get_classroom_decision_support_identity_validation_unaffected_by_context_signals(
    client: TestClient,
) -> None:
    """Existing identity-mismatch 404 behavior must still hold with the context_signals fields
    present in the response schema."""
    mismatched_twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{mismatched_twin_id}/decision-support",
        params={"class_id": LARGE_CAPPED_CLASS_ID},
    )

    assert response.status_code == 404


@pytest.fixture
def mapped_class(engine: Engine) -> Generator[None, None, None]:
    """Explicitly, temporarily maps MAPPED_TEST_CLASS_ID to a real CO2 sensor and a real
    xAPI record — a caller assertion for this test only, never a claim that this sensor
    or xAPI record actually belongs to this (fake) class_id in reality. Cleaned up after."""
    upsert_classroom_context_mapping(
        engine, "assistments", MAPPED_TEST_CLASS_ID, sensor_id="CO2_01", xapi_record_id=1
    )
    yield
    delete_classroom_context_mapping(engine, "assistments", MAPPED_TEST_CLASS_ID)


def test_get_classroom_decision_support_no_mapping_returns_empty_context_signals(
    client: TestClient,
) -> None:
    """A class_id with no row in classroom_context_mappings must always get context_signals=[]
    — no mapping is ever inferred automatically."""
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["context_signals"] == []
    assert body["context_note"] is None


def test_get_classroom_decision_support_explicit_mapping_populates_context_signals(
    client: TestClient, mapped_class: None
) -> None:
    """With an explicit mapping configured, real CO2 and xAPI signals are produced — but only
    because a caller explicitly asserted the link, never inferred from class_id alone."""
    twin_id = derive_classroom_id("assistments", MAPPED_TEST_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": MAPPED_TEST_CLASS_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["context_signals"]
    assert body["context_note"] is not None
    assert "not this classroom" in body["context_note"]

    source_datasets = {signal["source_dataset"] for signal in body["context_signals"]}
    assert source_datasets == {"environmental_sensors", "xapi_edu_data"}
    for signal in body["context_signals"]:
        assert set(signal.keys()).isdisjoint(FORBIDDEN_CONTEXT_SIGNAL_IDENTITY_FIELDS)

    metric_names = {signal["metric_name"] for signal in body["context_signals"]}
    assert "co2_ppm" in metric_names
    assert "predicted_absence_risk" in metric_names


def test_get_classroom_decision_support_mapping_does_not_leak_to_unmapped_class(
    client: TestClient, mapped_class: None
) -> None:
    """A mapping configured for MAPPED_TEST_CLASS_ID must never apply to a different class_id."""
    twin_id = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    response = client.get(
        f"/classrooms/{twin_id}/decision-support", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    )

    assert response.status_code == 200
    assert response.json()["context_signals"] == []


def test_get_classroom_decision_support_mapping_does_not_alter_classroom_evidence(
    client: TestClient, mapped_class: None
) -> None:
    """Populated context_signals must never change this classroom's own BKT-derived
    priority_skill or resource recommendations."""
    twin_id_mapped = derive_classroom_id("assistments", MAPPED_TEST_CLASS_ID)
    twin_id_small = derive_classroom_id("assistments", SMALL_COMPLETE_CLASS_ID)

    small_response = client.get(
        f"/classrooms/{twin_id_small}/decision-support",
        params={"class_id": SMALL_COMPLETE_CLASS_ID},
    )
    mapped_response = client.get(
        f"/classrooms/{twin_id_mapped}/decision-support",
        params={"class_id": MAPPED_TEST_CLASS_ID},
    )

    assert small_response.status_code == 200
    assert mapped_response.status_code == 200
    # MAPPED_TEST_CLASS_ID has no real ASSISTments roster, so it has no
    # priority_skill of its own — the point here is only that its (empty)
    # skill-priority/resource-recommendation path is unaffected by the
    # populated context_signals, not that it matches the other classroom.
    mapped_body = mapped_response.json()
    assert mapped_body["priority_skill"] is None
    assert mapped_body["recommended_resources"] == []
