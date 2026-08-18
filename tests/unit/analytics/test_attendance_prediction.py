"""Focused tests for the attendance-risk feature construction and model behavior."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from digital_twin.analytics.attendance_prediction import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    IDENTIFIER_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_preprocessing_pipeline,
    predict,
    split_features_and_target,
    train_baseline_model,
)
from digital_twin.analytics.predictive import evaluate_model, train_val_test_split


def _synthetic_snapshot(n: int = 200, seed: int = 0) -> pd.DataFrame:
    """A small snapshot matching fetch_nyc_attendance_snapshot's output shape.

    Makes absence_rate_rolling_mean genuinely predictive of the target so
    evaluate_model exercises real (not degenerate) metrics, and leaves a
    handful of NaNs in absence_rate_rolling_std to mirror rows with a
    near-constant recent history.
    """
    rng = np.random.default_rng(seed)

    absence_rate_rolling_mean = rng.uniform(0.0, 0.3, size=n)
    is_high_absence_day = (rng.uniform(0, 1, size=n) < absence_rate_rolling_mean * 2).astype(int)

    absence_rate_rolling_std = rng.uniform(0.0, 0.1, size=n)
    absence_rate_rolling_std[rng.choice(n, size=max(1, n // 20), replace=False)] = np.nan

    dates = pd.date_range("2013-01-01", periods=n, freq="D")

    return pd.DataFrame(
        {
            "school_id": rng.choice(["01M015", "02M017"], size=n),
            "attendance_date": dates,
            "school_year": rng.choice(["20122013", "20132014"], size=n),
            "day_of_week": rng.integers(0, 7, size=n),
            "month": rng.integers(1, 13, size=n),
            "absence_rate_lag1": rng.uniform(0.0, 0.3, size=n),
            "absence_rate_rolling_mean": absence_rate_rolling_mean,
            "absence_rate_rolling_std": absence_rate_rolling_std,
            TARGET_COLUMN: is_high_absence_day,
        }
    )


def test_feature_columns_never_include_identifiers_or_target() -> None:
    assert not set(FEATURE_COLUMNS) & set(IDENTIFIER_COLUMNS)
    assert TARGET_COLUMN not in FEATURE_COLUMNS
    assert set(FEATURE_COLUMNS) == set(CATEGORICAL_FEATURES) | set(NUMERIC_FEATURES)


def test_feature_columns_never_include_same_day_attendance_counts() -> None:
    """Static leakage guard: the raw enrolled/present/absent/released counts for the
    target day itself must never enter the feature set — only strictly-prior history."""
    for column in ("enrolled", "present", "absent", "released"):
        assert column not in FEATURE_COLUMNS


def test_split_features_and_target_excludes_identifiers_and_target() -> None:
    df = _synthetic_snapshot()
    x, y = split_features_and_target(df)

    assert list(x.columns) == FEATURE_COLUMNS
    assert not set(x.columns) & set(IDENTIFIER_COLUMNS)
    assert TARGET_COLUMN not in x.columns
    assert y.equals(df[TARGET_COLUMN])
    assert len(x) == len(df)


def test_split_features_and_target_raises_on_missing_columns() -> None:
    df = _synthetic_snapshot().drop(columns=["absence_rate_lag1"])
    with pytest.raises(ValueError, match="missing expected column"):
        split_features_and_target(df)


def test_preprocessing_pipeline_handles_missing_values() -> None:
    df = _synthetic_snapshot()
    x, _ = split_features_and_target(df)
    assert x.isnull().values.any()  # sanity: the synthetic data does have NaNs

    pipeline = build_preprocessing_pipeline()
    transformed = pipeline.fit_transform(x)
    dense = transformed.toarray() if hasattr(transformed, "toarray") else transformed

    assert not np.isnan(dense).any()
    assert transformed.shape[0] == len(x)


def test_train_baseline_model_predicts_probabilities_in_range() -> None:
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, _ = train_val_test_split(x, y, random_state=0)

    model = train_baseline_model(x_train, y_train)
    probabilities = model.predict_proba(x_test)[:, 1]

    assert probabilities.shape[0] == len(x_test)
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()


def test_evaluate_model_returns_expected_metrics_and_shapes() -> None:
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, y_test = train_val_test_split(x, y, random_state=0)

    model = train_baseline_model(x_train, y_train)
    metrics = evaluate_model(model, x_test, y_test)

    for value in (metrics.accuracy, metrics.precision, metrics.recall, metrics.f1, metrics.roc_auc):
        assert 0.0 <= value <= 1.0
    assert len(metrics.confusion_matrix) == 2
    assert all(len(row) == 2 for row in metrics.confusion_matrix)
    assert sum(sum(row) for row in metrics.confusion_matrix) == len(x_test)


def test_predict_returns_one_prediction_per_row_with_valid_probability() -> None:
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, _ = train_val_test_split(x, y, random_state=0)

    model = train_baseline_model(x_train, y_train)
    predictions = predict(model, x_test)

    assert len(predictions) == len(x_test)
    for p in predictions:
        assert 0.0 <= p.high_absence_probability <= 1.0
        assert p.predicted_class in (0, 1)
