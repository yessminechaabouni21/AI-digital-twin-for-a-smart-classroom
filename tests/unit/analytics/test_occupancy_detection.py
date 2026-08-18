"""Focused tests for UCI Occupancy Detection's feature construction, split, and baseline model."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from digital_twin.analytics.occupancy_detection import (
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_preprocessing_pipeline,
    chronological_train_test_split,
    split_features_and_target,
    train_baseline_model,
    transition_event_mask,
)
from digital_twin.analytics.predictive import evaluate_model


def _synthetic_readings(n: int = 200, seed: int = 0) -> pd.DataFrame:
    """A small DataFrame matching fetch_occupancy_readings' output shape, in time order.

    `co2_ppm` and `light_lux` are made genuinely predictive of `occupancy`
    (higher CO2/light -> occupied), mirroring the dataset's own documented
    correlation (light_lux == 0 for unoccupied rooms), so evaluate_model
    exercises real, non-degenerate metrics rather than chance-level output.
    """
    rng = np.random.default_rng(seed)
    recorded_at = pd.date_range("2015-02-04", periods=n, freq="min")

    co2_ppm = rng.uniform(400, 2000, size=n)
    light_lux = rng.uniform(0, 1600, size=n)
    risk = (co2_ppm - 400) / 1600 * 0.5 + (light_lux / 1600) * 0.5
    occupancy = (rng.uniform(0, 1, size=n) < risk).astype(int)

    return pd.DataFrame(
        {
            "source_file": "training",
            "recorded_at": recorded_at,
            "temperature_c": rng.uniform(19, 24, size=n),
            "humidity_pct": rng.uniform(17, 40, size=n),
            "light_lux": light_lux,
            "co2_ppm": co2_ppm,
            TARGET_COLUMN: occupancy,
        }
    )


def test_feature_columns_exclude_humidity_ratio_and_target() -> None:
    assert set(FEATURE_COLUMNS) == set(NUMERIC_FEATURES)
    assert "humidity_ratio" not in FEATURE_COLUMNS
    assert TARGET_COLUMN not in FEATURE_COLUMNS
    assert set(FEATURE_COLUMNS) == {"temperature_c", "humidity_pct", "co2_ppm", "light_lux"}


def test_split_features_and_target_excludes_target_and_identifiers() -> None:
    df = _synthetic_readings()
    x, y = split_features_and_target(df)

    assert list(x.columns) == FEATURE_COLUMNS
    assert "source_file" not in x.columns
    assert "recorded_at" not in x.columns
    assert TARGET_COLUMN not in x.columns
    assert y.equals(df[TARGET_COLUMN])
    assert len(x) == len(df)


def test_split_features_and_target_raises_on_missing_columns() -> None:
    df = _synthetic_readings().drop(columns=["co2_ppm"])
    with pytest.raises(ValueError, match="missing expected column"):
        split_features_and_target(df)


def test_chronological_train_test_split_keeps_train_strictly_before_test() -> None:
    df = _synthetic_readings(n=100)
    train_df, test_df = chronological_train_test_split(df, test_size=0.2)

    assert len(train_df) == 80
    assert len(test_df) == 20
    assert train_df["recorded_at"].max() < test_df["recorded_at"].min()
    assert len(train_df) + len(test_df) == len(df)


def test_chronological_train_test_split_does_not_shuffle_rows() -> None:
    df = _synthetic_readings(n=50)
    train_df, test_df = chronological_train_test_split(df, test_size=0.2)

    assert train_df["recorded_at"].is_monotonic_increasing
    assert test_df["recorded_at"].is_monotonic_increasing
    assert list(train_df.index) == list(range(40))
    assert list(test_df.index) == list(range(40, 50))


def test_preprocessing_pipeline_scales_without_altering_row_count() -> None:
    df = _synthetic_readings()
    x, _ = split_features_and_target(df)

    pipeline = build_preprocessing_pipeline()
    transformed = pipeline.fit_transform(x)

    assert transformed.shape == x.shape
    assert not np.isnan(transformed).any()


def test_train_baseline_model_predicts_probabilities_in_range() -> None:
    df = _synthetic_readings(n=300)
    train_df, test_df = chronological_train_test_split(df)
    x_train, y_train = split_features_and_target(train_df)
    x_test, _ = split_features_and_target(test_df)

    model = train_baseline_model(x_train, y_train)
    probabilities = model.predict_proba(x_test)[:, 1]

    assert probabilities.shape[0] == len(x_test)
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()


def test_train_baseline_model_evaluates_with_shared_evaluate_model() -> None:
    """Reuses predictive.py's generic evaluate_model rather than duplicating metric logic."""
    df = _synthetic_readings(n=300)
    train_df, test_df = chronological_train_test_split(df)
    x_train, y_train = split_features_and_target(train_df)
    x_test, y_test = split_features_and_target(test_df)

    model = train_baseline_model(x_train, y_train)
    metrics = evaluate_model(model, x_test, y_test)

    for value in (metrics.accuracy, metrics.precision, metrics.recall, metrics.f1, metrics.roc_auc):
        assert 0.0 <= value <= 1.0
    assert len(metrics.confusion_matrix) == 2
    assert all(len(row) == 2 for row in metrics.confusion_matrix)
    assert sum(sum(row) for row in metrics.confusion_matrix) == len(x_test)
    assert set(metrics.class_distribution.keys()) <= {0, 1}
    assert sum(metrics.class_distribution.values()) == len(y_test)


def test_transition_event_mask_selects_only_changed_rows() -> None:
    y = pd.Series([0, 0, 0, 1, 1, 0, 0, 1])
    mask = transition_event_mask(y)

    assert list(mask) == [False, False, False, True, False, True, False, True]
    assert mask.sum() == 3


def test_transition_event_mask_first_row_is_never_a_transition() -> None:
    y = pd.Series([1, 1, 1])
    mask = transition_event_mask(y)
    assert not bool(mask.iloc[0])


def test_transition_event_mask_all_same_value_has_no_transitions() -> None:
    y = pd.Series([1, 1, 1, 1])
    mask = transition_event_mask(y)
    assert mask.sum() == 0
