"""Focused tests for the dropout-risk feature construction and preprocessing pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from digital_twin.analytics.predictive import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    IDENTIFIER_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_preprocessing_pipeline,
    evaluate_model,
    predict,
    split_features_and_target,
    train_baseline_model,
    train_random_forest_model,
    train_val_test_split,
)


def _synthetic_snapshot(n: int = 80, seed: int = 0) -> pd.DataFrame:
    """A small snapshot matching fetch_oulad_dropout_snapshot's output shape.

    Deliberately includes NaNs in imd_band, date_registration, and
    assessments_mean_score, mirroring the real snapshot's missingness
    pattern, and makes vle_total_clicks/assessments_mean_score genuinely
    predictive of the target so evaluate_model exercises real (not
    degenerate) metrics.
    """
    rng = np.random.default_rng(seed)

    vle_total_clicks = rng.integers(0, 500, size=n).astype(float)
    assessments_mean_score = rng.uniform(20, 100, size=n)
    # Lower engagement/score -> higher dropout probability, plus noise.
    risk = 1 - (vle_total_clicks / 500 + assessments_mean_score / 100) / 2
    is_dropout = (rng.uniform(0, 1, size=n) < risk).astype(int)

    imd_band = rng.choice(["0-10%", "10-20", "90-100%", None], size=n)
    date_registration = rng.uniform(-50, 20, size=n)
    date_registration[rng.choice(n, size=max(1, n // 20), replace=False)] = np.nan
    assessments_mean_score_with_nulls = assessments_mean_score.copy()
    assessments_mean_score_with_nulls[is_dropout == 1] = np.where(
        rng.uniform(0, 1, size=(is_dropout == 1).sum()) < 0.5,
        np.nan,
        assessments_mean_score_with_nulls[is_dropout == 1],
    )

    assessments_due_count = rng.integers(1, 6, size=n)
    assessments_submitted_count = rng.integers(0, 4, size=n)
    assessments_submission_rate = assessments_submitted_count / assessments_due_count
    # Null when nothing was due yet by the cutoff (0/0), mirroring the SQL's
    # NULLIF(assessments_due_count, 0)-driven NULL for that case.
    assessments_submission_rate[rng.choice(n, size=max(1, n // 20), replace=False)] = np.nan

    vle_days_since_last_click = rng.uniform(0, 45, size=n)
    # Null when the student had zero VLE clicks by the cutoff.
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
            TARGET_COLUMN: is_dropout,
        }
    )


def test_feature_columns_never_include_identifiers_or_target() -> None:
    """Static leakage guard: protects against a future accidental addition."""
    assert not set(FEATURE_COLUMNS) & set(IDENTIFIER_COLUMNS)
    assert TARGET_COLUMN not in FEATURE_COLUMNS
    assert set(FEATURE_COLUMNS) == set(CATEGORICAL_FEATURES) | set(NUMERIC_FEATURES)


def test_feature_columns_never_include_post_cutoff_or_outcome_fields() -> None:
    """Static leakage guard: the fields that would trivially reveal the target
    (final_result, date_unregistration) must never be added as features."""
    assert "final_result" not in FEATURE_COLUMNS
    assert "date_unregistration" not in FEATURE_COLUMNS
    assert "id_student" not in FEATURE_COLUMNS


def test_feature_columns_include_course_identity_and_richer_behavior_features() -> None:
    """code_module/code_presentation are known at enrollment (no leakage) and are now
    features, not identifiers; the richer VLE/assessment aggregates are day-45-safe
    (computed only from events on or before the cutoff, same as the original features)."""
    assert "code_module" in CATEGORICAL_FEATURES
    assert "code_presentation" in CATEGORICAL_FEATURES
    assert "id_student" in IDENTIFIER_COLUMNS

    for feature in (
        "assessments_due_count",
        "assessments_submission_rate",
        "vle_days_since_last_click",
    ):
        assert feature in NUMERIC_FEATURES


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


def test_train_val_test_split_preserves_stratification() -> None:
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, x_val, x_test, y_train, y_val, y_test = train_val_test_split(x, y)

    assert len(x_train) + len(x_val) + len(x_test) == len(x)
    overall_rate = y.mean()
    for split_y in (y_train, y_val, y_test):
        assert split_y.mean() == pytest.approx(overall_rate, abs=0.1)


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


def test_evaluate_model_lower_threshold_never_decreases_recall() -> None:
    """A lower decision threshold classifies more cases positive, so recall
    can only rise (or stay flat), never fall, relative to threshold=0.5."""
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, y_test = train_val_test_split(x, y, random_state=0)

    model = train_random_forest_model(x_train, y_train, n_estimators=50)
    default_metrics = evaluate_model(model, x_test, y_test, threshold=0.5)
    lowered_metrics = evaluate_model(model, x_test, y_test, threshold=0.3)

    assert lowered_metrics.recall >= default_metrics.recall


def test_predict_returns_one_prediction_per_row_with_valid_probability() -> None:
    df = _synthetic_snapshot(n=200)
    x, y = split_features_and_target(df)
    x_train, _, x_test, y_train, _, _ = train_val_test_split(x, y, random_state=0)

    model = train_baseline_model(x_train, y_train)
    predictions = predict(model, x_test)

    assert len(predictions) == len(x_test)
    for p in predictions:
        assert 0.0 <= p.dropout_probability <= 1.0
        assert p.predicted_class in (0, 1)
