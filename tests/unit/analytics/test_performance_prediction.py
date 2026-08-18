"""Focused tests for the performance-prediction feature construction and model behavior."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from digital_twin.analytics.performance_prediction import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    IDENTIFIER_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_preprocessing_pipeline,
    predict,
    split_features_and_target,
    train_baseline_model,
    train_random_forest_model,
)
from digital_twin.analytics.predictive import evaluate_model, train_val_test_split


def _synthetic_snapshot(n: int = 200, seed: int = 0) -> pd.DataFrame:
    """A small snapshot matching fetch_oulad_performance_snapshot's output shape.

    Deliberately includes NaNs in imd_band, date_registration, and
    assessments_mean_score, mirroring the real snapshot's missingness
    pattern, and makes assessments_mean_score/vle_total_clicks genuinely
    predictive of the target so evaluate_model exercises real (not
    degenerate) metrics.
    """
    rng = np.random.default_rng(seed)

    vle_total_clicks = rng.integers(0, 500, size=n).astype(float)
    assessments_mean_score = rng.uniform(20, 100, size=n)
    pass_likelihood = (vle_total_clicks / 500 + assessments_mean_score / 100) / 2
    is_pass = (rng.uniform(0, 1, size=n) < pass_likelihood).astype(int)

    imd_band = rng.choice(["0-10%", "10-20", "90-100%", None], size=n)
    date_registration = rng.uniform(-50, 20, size=n)
    date_registration[rng.choice(n, size=max(1, n // 20), replace=False)] = np.nan
    assessments_mean_score_with_nulls = assessments_mean_score.copy()
    assessments_mean_score_with_nulls[is_pass == 0] = np.where(
        rng.uniform(0, 1, size=(is_pass == 0).sum()) < 0.5,
        np.nan,
        assessments_mean_score_with_nulls[is_pass == 0],
    )

    assessments_due_count = rng.integers(1, 6, size=n)
    assessments_submitted_count = rng.integers(0, 4, size=n)
    assessments_submission_rate = assessments_submitted_count / assessments_due_count
    assessments_submission_rate[rng.choice(n, size=max(1, n // 20), replace=False)] = np.nan

    vle_days_since_last_click = rng.uniform(0, 30, size=n)
    vle_days_since_last_click[rng.choice(n, size=max(1, n // 20), replace=False)] = np.nan

    return pd.DataFrame(
        {
            "code_module": rng.choice(["AAA", "BBB"], size=n),
            "code_presentation": rng.choice(["2013J", "2014B"], size=n),
            "id_student": np.arange(100000, 100000 + n),
            "gender": rng.choice(["M", "F"], size=n),
            "highest_education": rng.choice(["HE Qualification", "A Level or Equivalent"], size=n),
            "imd_band": imd_band,
            "age_band": rng.choice(["0-35", "35-55"], size=n),
            "disability": rng.choice(["Y", "N"], size=n),
            "num_of_prev_attempts": rng.integers(0, 3, size=n),
            "studied_credits": rng.integers(30, 120, size=n),
            "date_registration": date_registration,
            "assessments_submitted_count": assessments_submitted_count,
            "assessments_mean_score": assessments_mean_score_with_nulls,
            "assessments_due_count": assessments_due_count,
            "assessments_submission_rate": assessments_submission_rate,
            "vle_total_clicks": vle_total_clicks,
            "vle_active_days": rng.integers(0, 30, size=n),
            "vle_distinct_sites": rng.integers(0, 10, size=n),
            "vle_days_since_last_click": vle_days_since_last_click,
            TARGET_COLUMN: is_pass,
        }
    )


def test_feature_columns_never_include_identifiers_or_target() -> None:
    """Static leakage guard: protects against a future accidental addition."""
    assert not set(FEATURE_COLUMNS) & set(IDENTIFIER_COLUMNS)
    assert TARGET_COLUMN not in FEATURE_COLUMNS
    assert set(FEATURE_COLUMNS) == set(CATEGORICAL_FEATURES) | set(NUMERIC_FEATURES)


def test_feature_columns_never_include_final_result_or_exam_signal() -> None:
    """Static leakage guard: final_result determines the target, and the Exam
    submission is what final_result is largely computed from — neither may
    ever enter the feature set."""
    assert "final_result" not in FEATURE_COLUMNS
    assert "id_student" not in FEATURE_COLUMNS
    for column in FEATURE_COLUMNS:
        assert "exam" not in column.lower()


def test_split_features_and_target_excludes_identifiers_and_target() -> None:
    df = _synthetic_snapshot()
    x, y = split_features_and_target(df)

    assert list(x.columns) == FEATURE_COLUMNS
    assert not set(x.columns) & set(IDENTIFIER_COLUMNS)
    assert TARGET_COLUMN not in x.columns
    assert y.equals(df[TARGET_COLUMN])
    assert len(x) == len(df)


def test_split_features_and_target_raises_on_missing_columns() -> None:
    df = _synthetic_snapshot().drop(columns=["vle_total_clicks"])
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


def test_train_random_forest_model_predicts_probabilities_in_range() -> None:
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, _ = train_val_test_split(x, y, random_state=0)

    model = train_random_forest_model(x_train, y_train, n_estimators=50)
    probabilities = model.predict_proba(x_test)[:, 1]

    assert probabilities.shape[0] == len(x_test)
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()


def test_train_random_forest_model_evaluates_on_same_split_as_baseline() -> None:
    """Both models must accept the identical X/y splits, for a fair comparison."""
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, y_test = train_val_test_split(x, y, random_state=0)

    logistic_model = train_baseline_model(x_train, y_train)
    forest_model = train_random_forest_model(x_train, y_train, n_estimators=50)

    logistic_metrics = evaluate_model(logistic_model, x_test, y_test)
    forest_metrics = evaluate_model(forest_model, x_test, y_test)

    for metrics in (logistic_metrics, forest_metrics):
        values = (metrics.accuracy, metrics.precision, metrics.recall, metrics.f1, metrics.roc_auc)
        for value in values:
            assert 0.0 <= value <= 1.0
        assert sum(sum(row) for row in metrics.confusion_matrix) == len(x_test)
    assert logistic_metrics.class_distribution == forest_metrics.class_distribution


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
    assert set(metrics.class_distribution.keys()) <= {0, 1}
    assert sum(metrics.class_distribution.values()) == len(y_test)


def test_predict_returns_one_prediction_per_row_with_valid_probability() -> None:
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, _ = train_val_test_split(x, y, random_state=0)

    model = train_baseline_model(x_train, y_train)
    predictions = predict(model, x_test)

    assert len(predictions) == len(x_test)
    for p in predictions:
        assert 0.0 <= p.pass_probability <= 1.0
        assert p.predicted_class in (0, 1)
