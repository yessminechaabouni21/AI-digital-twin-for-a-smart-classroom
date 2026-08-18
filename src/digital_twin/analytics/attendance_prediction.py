"""Attendance-risk prediction: will a school have an elevated absence rate on a given day.

`nyc_daily_attendance` is school-level, not per-student, so the target this
module predicts is school-day absenteeism, not an individual student's
absence — see
`data/repositories/nyc_attendance_features.fetch_nyc_attendance_snapshot`'s
docstring for why. No SQLAlchemy import anywhere in this module, and no
dependency on domain/twin_engine either, per CLAUDE.md's module boundaries;
this model is standalone and not wired into StudentTwin.

Reuses `analytics/predictive.py`'s `train_val_test_split`, `evaluate_model`,
and `ClassificationMetrics` — those are generic classification-evaluation
utilities, not OULAD-specific — rather than duplicating them.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET_COLUMN = "is_high_absence_day"

# school_id/attendance_date identify the row (which school, which day) but
# are never predictive features: school_id is a dataset-scoped code, not a
# behavioral signal, and attendance_date is subsumed by the day_of_week/month
# features below.
IDENTIFIER_COLUMNS = ["school_id", "attendance_date"]

CATEGORICAL_FEATURES = ["school_year", "day_of_week", "month"]
NUMERIC_FEATURES = [
    "absence_rate_lag1",
    "absence_rate_rolling_mean",
    "absence_rate_rolling_std",
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES


def split_features_and_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Select the model's input columns and target, dropping identifiers explicitly.

    The one place that draws the line between "predictive feature" and
    "identifier/target" — every other function in this module takes
    already-split X/y, so this function is the single point that would need
    to change if the feature set ever changes.
    """
    missing = set(FEATURE_COLUMNS + [TARGET_COLUMN]) - set(df.columns)
    if missing:
        raise ValueError(f"snapshot is missing expected column(s): {sorted(missing)}")

    x = df[FEATURE_COLUMNS].copy()
    y = df[TARGET_COLUMN].copy()
    return x, y


def build_preprocessing_pipeline() -> ColumnTransformer:
    """Impute + encode/scale features. Fit only on the training split, never on all data."""
    categorical_pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="constant", fill_value="Unknown")),
            ("encode", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    numeric_pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("categorical", categorical_pipeline, CATEGORICAL_FEATURES),
            ("numeric", numeric_pipeline, NUMERIC_FEATURES),
        ]
    )


def train_baseline_model(x_train: pd.DataFrame, y_train: pd.Series) -> Pipeline:
    """Fit the attendance-risk baseline: preprocessing + class-weighted logistic regression.

    Logistic regression, not an ensemble — the smallest reasonable baseline
    for a first, explainable model. `class_weight="balanced"` compensates
    for the ~32%/68% class imbalance without resampling.
    """
    model = Pipeline(
        steps=[
            ("preprocessing", build_preprocessing_pipeline()),
            ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ]
    )
    model.fit(x_train, y_train)
    return model


class AttendancePrediction(BaseModel):
    """A single school-day's high-absence-risk output — deliberately just these two fields.

    Not wired into StudentTwin yet (see module docstring); this is the
    output shape a future consumer would use.
    """

    high_absence_probability: float
    predicted_class: int


def predict(model: Pipeline, x: pd.DataFrame) -> list[AttendancePrediction]:
    """Run `model` over `x`, returning one AttendancePrediction per row, in order."""
    probabilities = model.predict_proba(x)[:, 1]
    predicted_classes = model.predict(x)
    return [
        AttendancePrediction(high_absence_probability=float(p), predicted_class=int(c))
        for p, c in zip(probabilities, predicted_classes, strict=True)
    ]


__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURE_COLUMNS",
    "IDENTIFIER_COLUMNS",
    "NUMERIC_FEATURES",
    "TARGET_COLUMN",
    "AttendancePrediction",
    "build_preprocessing_pipeline",
    "predict",
    "split_features_and_target",
    "train_baseline_model",
]
