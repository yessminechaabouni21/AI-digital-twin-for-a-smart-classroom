"""Focused tests for xAPI absence-risk feature construction, dedup, split, and baseline model."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from digital_twin.analytics.predictive import evaluate_model
from digital_twin.analytics.xapi_absence_risk import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    build_preprocessing_pipeline,
    drop_duplicate_rows,
    split_features_and_target,
    train_baseline_model,
)


def _synthetic_snapshot(n: int = 200, seed: int = 0) -> pd.DataFrame:
    """A small DataFrame matching fetch_xapi_snapshot's output shape.

    `discussion`/`raised_hands` are made genuinely predictive of high absence
    (low engagement -> more likely "Above-7"), mirroring the real dataset's
    documented negative correlation between engagement and absence, so
    evaluate_model exercises real, non-degenerate metrics.
    """
    rng = np.random.default_rng(seed)
    raised_hands = rng.integers(0, 100, size=n)
    discussion = rng.integers(0, 100, size=n)
    risk = 1 - (raised_hands + discussion) / 200
    is_above_7 = rng.uniform(0, 1, size=n) < risk

    return pd.DataFrame(
        {
            "record_id": range(1, n + 1),
            "stage_id": rng.choice(["lowerlevel", "MiddleSchool", "HighSchool"], size=n),
            "grade_id": rng.choice(["G-02", "G-07", "G-08"], size=n),
            "section_id": rng.choice(["A", "B", "C"], size=n),
            "topic": rng.choice(["IT", "Math", "Science"], size=n),
            "semester": rng.choice(["F", "S"], size=n),
            "raised_hands": raised_hands,
            "visited_resources": rng.integers(0, 100, size=n),
            "announcements_view": rng.integers(0, 100, size=n),
            "discussion": discussion,
            "parent_answering_survey": rng.choice(["Yes", "No"], size=n),
            "parent_school_satisfaction": rng.choice(["Good", "Bad"], size=n),
            "student_absence_days": np.where(is_above_7, "Above-7", "Under-7"),
        }
    )


def test_feature_columns_exclude_target_and_demographics() -> None:
    assert set(FEATURE_COLUMNS) == set(CATEGORICAL_FEATURES) | set(NUMERIC_FEATURES)
    for excluded in ("gender", "nationality", "place_of_birth", "relation", "class_label"):
        assert excluded not in FEATURE_COLUMNS
    assert "student_absence_days" not in FEATURE_COLUMNS


def test_split_features_and_target_encodes_binary_target() -> None:
    df = _synthetic_snapshot()
    x, y = split_features_and_target(df)

    assert list(x.columns) == FEATURE_COLUMNS
    assert y.name == TARGET_COLUMN
    assert set(y.unique()) <= {0, 1}
    assert (y == 1).sum() == (df["student_absence_days"] == "Above-7").sum()


def test_split_features_and_target_raises_on_missing_columns() -> None:
    df = _synthetic_snapshot().drop(columns=["discussion"])
    with pytest.raises(ValueError, match="missing expected column"):
        split_features_and_target(df)


def test_drop_duplicate_rows_removes_content_duplicates_ignoring_record_id() -> None:
    df = _synthetic_snapshot(n=10)
    duplicate_row = df.iloc[0].copy()
    duplicate_row["record_id"] = 999  # different identifier, identical content otherwise
    df_with_dup = pd.concat([df, duplicate_row.to_frame().T], ignore_index=True)

    deduped = drop_duplicate_rows(df_with_dup)

    assert len(deduped) == len(df)
    assert 999 not in deduped["record_id"].to_numpy()


def test_drop_duplicate_rows_keeps_distinct_rows_intact() -> None:
    df = _synthetic_snapshot(n=50)
    deduped = drop_duplicate_rows(df)
    assert len(deduped) == 50


def test_preprocessing_pipeline_scales_without_altering_row_count() -> None:
    df = _synthetic_snapshot()
    x, _ = split_features_and_target(df)

    pipeline = build_preprocessing_pipeline()
    transformed = pipeline.fit_transform(x)

    assert transformed.shape[0] == x.shape[0]


def test_train_baseline_model_predicts_probabilities_in_range() -> None:
    df = _synthetic_snapshot(n=300)
    x, y = split_features_and_target(df)

    model = train_baseline_model(x, y)
    probabilities = model.predict_proba(x)[:, 1]

    assert probabilities.shape[0] == len(x)
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()


def test_train_baseline_model_evaluates_with_shared_evaluate_model() -> None:
    """Reuses predictive.py's generic evaluate_model rather than duplicating metric logic."""
    df = _synthetic_snapshot(n=300)
    x, y = split_features_and_target(df)

    model = train_baseline_model(x, y)
    metrics = evaluate_model(model, x, y)

    for value in (metrics.accuracy, metrics.precision, metrics.recall, metrics.f1, metrics.roc_auc):
        assert 0.0 <= value <= 1.0
    assert set(metrics.class_distribution.keys()) <= {0, 1}
