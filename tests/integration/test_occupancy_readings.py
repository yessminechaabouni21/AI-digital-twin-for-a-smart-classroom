"""Integration test: fetch the real UCI Occupancy Detection dataset and run the baseline model.

Requires a live PostgreSQL instance with `occupancy_readings` loaded —
skipped automatically if the database is unreachable, per CLAUDE.md's rule
that integration tests must be skippable without DB access.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from digital_twin.analytics.occupancy_detection import (
    chronological_train_test_split,
    split_features_and_target,
    train_baseline_model,
)
from digital_twin.analytics.predictive import evaluate_model
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.occupancy_readings import fetch_occupancy_readings


@pytest.fixture
def engine() -> Engine:
    db_engine = get_engine()
    try:
        with db_engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable, skipping integration test: {exc}")
    return db_engine


def test_fetch_occupancy_readings_returns_all_rows_in_chronological_order(engine: Engine) -> None:
    readings = fetch_occupancy_readings(engine)

    assert len(readings) == 20560
    assert readings["recorded_at"].is_monotonic_increasing
    assert set(readings["occupancy"].unique()) <= {0, 1}


def test_occupancy_baseline_model_trains_and_evaluates_on_real_data(engine: Engine) -> None:
    readings = fetch_occupancy_readings(engine)

    train_df, test_df = chronological_train_test_split(readings)
    assert train_df["recorded_at"].max() < test_df["recorded_at"].min()

    x_train, y_train = split_features_and_target(train_df)
    x_test, y_test = split_features_and_target(test_df)

    model = train_baseline_model(x_train, y_train)
    metrics = evaluate_model(model, x_test, y_test)

    for value in (metrics.accuracy, metrics.precision, metrics.recall, metrics.f1, metrics.roc_auc):
        assert 0.0 <= value <= 1.0
    assert sum(sum(row) for row in metrics.confusion_matrix) == len(x_test)
    # Sanity: environmental readings should beat a random-guess baseline by a wide margin
    # on this well-known benchmark dataset.
    assert metrics.roc_auc > 0.8
