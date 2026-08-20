"""Integration tests for GET /demo/context-signals and GET /demo/classroom-scenario.

Requires a live PostgreSQL instance with xAPI-Edu-Data and UCI Occupancy
Detection loaded — skipped automatically if unreachable, per CLAUDE.md's
rule.

/demo/context-signals takes no `class_id`/`twin_id` at all: every test for
it verifies it never fabricates a classroom relationship and always labels
its content as real benchmark data.

/demo/classroom-scenario is deliberately scoped to one `class_id`. Its
`environment`/`engagement` are entirely fabricated (`provenance="synthetic_demo"`),
verified deterministic per classroom and never confusable with real xAPI/UCI
output. Its `absence_risk` is different — a REAL prediction from the real,
already-trained xAPI absence-risk model, run on that fabricated engagement
input — and several tests below cross-check it against an independently,
freshly-trained copy of that same real model to prove the endpoint is
actually calling it, not fabricating the percentage.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from digital_twin.analytics.xapi_absence_risk import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    drop_duplicate_rows,
    split_features_and_target,
    train_baseline_model,
)
from digital_twin.analytics.xapi_absence_risk import (
    predict as predict_xapi_absence_risk,
)
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.xapi_snapshot import fetch_xapi_snapshot
from digital_twin.main import app

EXISTING_XAPI_RECORD_ID = 1
NONEXISTENT_XAPI_RECORD_ID = 999_999_999


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


def test_default_request_returns_demo_mode_and_disclaimer(client: TestClient) -> None:
    response = client.get("/demo/context-signals")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert body["disclaimer"] == "DEMONSTRATION MODE — BENCHMARK / NOT CLASSROOM OBSERVED"


def test_response_never_carries_a_classroom_or_twin_identity(client: TestClient) -> None:
    """Structural guarantee: no field anywhere in the response can be mistaken for
    evidence about a specific classroom, since none of those keys exist at all."""
    response = client.get("/demo/context-signals")
    body = response.json()

    def assert_no_classroom_keys(node: object) -> None:
        if isinstance(node, dict):
            for forbidden in ("twin_id", "class_id", "source_class_id", "classroom_id"):
                assert forbidden not in node
            for value in node.values():
                assert_no_classroom_keys(value)
        elif isinstance(node, list):
            for item in node:
                assert_no_classroom_keys(item)

    assert_no_classroom_keys(body)


def test_xapi_signals_for_a_real_record_are_tagged_benchmark_and_unlinked(
    client: TestClient,
) -> None:
    response = client.get(
        "/demo/context-signals", params={"xapi_record_id": EXISTING_XAPI_RECORD_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["xapi_record_id"] == EXISTING_XAPI_RECORD_ID
    # raised_hands, visited_resources, announcements_view, discussion
    assert len(body["xapi_context_signals"]) == 4

    for signal in body["xapi_context_signals"]:
        assert signal["provenance"] == "benchmark_research"
        assert signal["source_dataset"] == "xapi_edu_data"
        assert "not associated with any classroom" in signal["scope_description"]

    absence_signal = body["xapi_absence_risk_signal"]
    assert absence_signal is not None
    assert absence_signal["provenance"] == "benchmark_research"
    assert absence_signal["metric_name"] == "predicted_absence_risk"
    assert 0.0 <= absence_signal["value"] <= 1.0


def test_nonexistent_xapi_record_returns_empty_signals_not_fabricated_data(
    client: TestClient,
) -> None:
    response = client.get(
        "/demo/context-signals", params={"xapi_record_id": NONEXISTENT_XAPI_RECORD_ID}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["xapi_context_signals"] == []
    assert body["xapi_absence_risk_signal"] is None
    assert str(NONEXISTENT_XAPI_RECORD_ID) in body["xapi_note"]


def test_occupancy_benchmark_reports_model_quality_metrics_not_a_context_signal(
    client: TestClient,
) -> None:
    response = client.get("/demo/context-signals")

    assert response.status_code == 200
    occupancy = response.json()["occupancy_benchmark"]
    assert occupancy["source_dataset"] == "uci_occupancy"
    assert occupancy["provenance"] == "benchmark_research"
    assert "classroom" in occupancy["description"].lower()

    headline = occupancy["headline_metrics"]
    for key in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        assert 0.0 <= headline[key] <= 1.0
    assert occupancy["train_row_count"] > 0
    assert occupancy["test_row_count"] > 0

    # Real UCI Occupancy Detection has known transitions in its chronological test
    # split (verified via scripts/occupancy_detection_demo.py) — assert the
    # transition-event evaluation is actually populated, not silently skipped.
    assert occupancy["transition_event_count"] > 0
    transition_metrics = occupancy["transition_event_metrics"]
    assert transition_metrics is not None
    for key in ("accuracy", "precision", "recall", "f1", "roc_auc"):
        assert 0.0 <= transition_metrics[key] <= 1.0

    assert len(occupancy["limitations"]) >= 3


def test_occupancy_benchmark_is_identical_across_requests(client: TestClient) -> None:
    """The cached, once-trained model must not silently retrain/change between calls."""
    first = client.get("/demo/context-signals").json()["occupancy_benchmark"]
    second = client.get("/demo/context-signals").json()["occupancy_benchmark"]

    assert first == second


def test_endpoint_requires_no_class_id_or_twin_id_query_param(client: TestClient) -> None:
    """The whole point of this endpoint: it must be callable with zero classroom context."""
    response = client.get("/demo/context-signals")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /demo/classroom-scenario
# ---------------------------------------------------------------------------

SMALL_COMPLETE_CLASS_ID = 1679
LARGE_CAPPED_CLASS_ID = 27834


def test_classroom_scenario_is_labeled_synthetic_and_scoped_to_the_classroom(
    client: TestClient,
) -> None:
    response = client.get("/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert body["disclaimer"] == "DEMONSTRATION MODE — BENCHMARK / NOT CLASSROOM OBSERVED"
    assert body["source_class_id"] == SMALL_COMPLETE_CLASS_ID
    assert body["source_dataset"] == "assistments"
    assert "synthetic" in body["scenario_note"].lower()

    for section in ("environment", "engagement", "absence_risk"):
        assert body[section]["provenance"] == "synthetic_demo"


def test_classroom_scenario_absence_risk_has_distinct_input_and_model_provenance(
    client: TestClient,
) -> None:
    response = client.get("/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID})
    body = response.json()

    absence_risk = body["absence_risk"]
    assert absence_risk["provenance"] == "synthetic_demo"
    assert absence_risk["input_provenance"] == "synthetic_demo"
    assert absence_risk["model_provenance"] == "real_xapi_trained_model"
    assert 0.0 <= absence_risk["absence_risk_indicator"] <= 1.0
    assert "real analytics/xapi_absence_risk.py model" in absence_risk["scope_description"].lower()
    assert "trained only on real xapi-edu-data" in absence_risk["scope_description"].lower()
    assert "not a real attendance observation" in absence_risk["scope_description"]
    # Deliberately not the real model's own field/metric name — never confusable
    # with ContextSignalOut's predicted_absence_risk for a real, mapped record.
    assert "absence_risk_probability" not in absence_risk
    assert "metric_name" not in absence_risk


def _train_reference_xapi_model(engine: Engine) -> object:
    """Independently, freshly train the exact same real model the endpoint's own
    cache trains — same procedure as api/routers/demo.py's
    `_get_xapi_absence_risk_model_and_snapshot` — so tests can prove the endpoint's
    absence_risk value is this real model's actual output, not a second number."""
    snapshot = fetch_xapi_snapshot(engine)
    training_snapshot = drop_duplicate_rows(snapshot)
    x_train, y_train = split_features_and_target(training_snapshot)
    return train_baseline_model(x_train, y_train)


def test_classroom_scenario_absence_risk_matches_an_independently_trained_real_model(
    client: TestClient, engine: Engine
) -> None:
    """Proves the endpoint is actually routing synthetic input through the real,
    already-trained xAPI absence-risk model — not generating a look-alike number."""
    reference_model = _train_reference_xapi_model(engine)

    body = client.get(
        "/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    ).json()
    engagement = body["engagement"]

    feature_row = {feature: None for feature in CATEGORICAL_FEATURES}
    feature_row["raised_hands"] = engagement["raised_hands"]
    feature_row["visited_resources"] = engagement["visited_resources"]
    feature_row["announcements_view"] = engagement["announcements_view"]
    feature_row["discussion"] = engagement["discussion"]
    x = pd.DataFrame([feature_row], columns=FEATURE_COLUMNS)

    expected_prediction = predict_xapi_absence_risk(reference_model, x)[0]
    assert (
        body["absence_risk"]["absence_risk_indicator"]
        == expected_prediction.absence_risk_probability
    )


def test_classroom_scenario_absence_risk_changes_when_engagement_differs(
    client: TestClient,
) -> None:
    """Two classrooms with different synthetic engagement counts must (in general)
    get different absence-risk predictions — proof the model is actually being
    evaluated on each scenario's own input, not returning a fixed value."""
    small = client.get(
        "/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    ).json()
    large = client.get(
        "/demo/classroom-scenario", params={"class_id": LARGE_CAPPED_CLASS_ID}
    ).json()

    numeric_fields = ("raised_hands", "visited_resources", "announcements_view", "discussion")
    small_engagement = {field: small["engagement"][field] for field in numeric_fields}
    large_engagement = {field: large["engagement"][field] for field in numeric_fields}
    if small_engagement == large_engagement:
        pytest.skip("synthetic engagement happened to collide for these two class_ids")
    assert (
        small["absence_risk"]["absence_risk_indicator"]
        != large["absence_risk"]["absence_risk_indicator"]
    )


def test_classroom_scenario_is_deterministic_for_the_same_classroom(client: TestClient) -> None:
    first = client.get(
        "/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    ).json()
    second = client.get(
        "/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    ).json()

    assert first == second


def test_classroom_scenario_differs_between_classrooms(client: TestClient) -> None:
    small = client.get(
        "/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID}
    ).json()
    large = client.get(
        "/demo/classroom-scenario", params={"class_id": LARGE_CAPPED_CLASS_ID}
    ).json()

    assert small["environment"] != large["environment"]


def test_classroom_scenario_introduces_no_classroom_to_xapi_identity_mapping(
    client: TestClient,
) -> None:
    """The absence-risk prediction must come purely from synthetic engagement counts —
    never by looking up, or associating this class_id with, any real xapi_record_id."""
    response = client.get("/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID})
    body = response.json()

    def assert_no_xapi_record_id(node: object) -> None:
        if isinstance(node, dict):
            assert "xapi_record_id" not in node
            for value in node.values():
                assert_no_xapi_record_id(value)
        elif isinstance(node, list):
            for item in node:
                assert_no_xapi_record_id(item)

    assert_no_xapi_record_id(body)


def test_classroom_scenario_never_carries_a_twin_id(client: TestClient) -> None:
    response = client.get("/demo/classroom-scenario", params={"class_id": SMALL_COMPLETE_CLASS_ID})
    body = response.json()

    def assert_no_twin_id(node: object) -> None:
        if isinstance(node, dict):
            assert "twin_id" not in node
            for value in node.values():
                assert_no_twin_id(value)
        elif isinstance(node, list):
            for item in node:
                assert_no_twin_id(item)

    assert_no_twin_id(body)
