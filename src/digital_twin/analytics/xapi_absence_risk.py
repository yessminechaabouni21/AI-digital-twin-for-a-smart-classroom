"""Absence-risk prediction: xAPI-Edu-Data's own coarse `student_absence_days` bucket.

Deliberately NOT named/described as "attendance prediction" anywhere in this
module: the underlying target is a coarse, self-reported/administrative
2-bucket field, not a verified per-day attendance record, and this project
does not overstate it as one — see the terminology note below.

Target: `student_absence_days` ("Above-7" vs "Under-7" recorded absence
days, verified on the live table: 191/289 of 480 rows) -> binary
`is_high_absence_risk` (1 = "Above-7"). This is xAPI-Edu-Data's own
absence-adjacent field — the only column in this dataset with any semantic
relationship to absence — not something invented for this project. It is
coarse (a two-bucket administrative/self-reported count, not a verified
per-day attendance record); this module's evaluation and any consumer of
its output must describe it as a predicted *absence-days-category risk*,
never as verified daily attendance.

`class_label` ("H"/"M"/"L" performance level) is deliberately excluded
from the feature set: it is a *separate* outcome variable in the same
dataset, plausibly correlated with `student_absence_days` by construction
(both summarize "how this student did"), so using it as a predictor would
leak one target into another rather than genuinely predicting absence risk
from independent behavioral signal.

`gender`/`nationality`/`place_of_birth`/`relation` are deliberately
excluded too: using demographic/identity attributes as predictors of an
absence-risk score is a fairness-sensitive design choice this module does
not make silently. The feature set here is limited to behavioral
engagement counts, parent-involvement fields, and class-section context.

No student identity exists anywhere in xAPI-Edu-Data (see
`data/repositories/xapi_engagement.py`'s docstring) — this module cannot
group rows by student for a leakage-safe split, and documents that as a
limitation rather than fabricating a grouping key. `drop_duplicate_rows`
removes the 4-of-480 fully-duplicate rows (verified on the live table, 2
groups of 2) before any split, so a duplicate row's exact feature+target
combination can never appear in both train and test.

Reuses `analytics/predictive.py`'s `train_val_test_split`, `evaluate_model`,
and `ClassificationMetrics` — generic classification-evaluation utilities,
not OULAD-specific — rather than duplicating them.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET_COLUMN = "is_high_absence_risk"
_SOURCE_TARGET_COLUMN = "student_absence_days"
_HIGH_ABSENCE_VALUE = "Above-7"

# record_id identifies the row but is never a predictive feature.
IDENTIFIER_COLUMNS = ["record_id"]

CATEGORICAL_FEATURES = [
    "stage_id",
    "grade_id",
    "section_id",
    "topic",
    "semester",
    "parent_answering_survey",
    "parent_school_satisfaction",
]
NUMERIC_FEATURES = [
    "raised_hands",
    "visited_resources",
    "announcements_view",
    "discussion",
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES


def drop_duplicate_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop fully content-duplicate rows (identifier excluded) before any split.

    Prevents a near-verbatim copy of a training row's exact feature+target
    combination from being scored as "held out" test performance.
    """
    content_columns = [column for column in df.columns if column not in IDENTIFIER_COLUMNS]
    return df.drop_duplicates(subset=content_columns, keep="first").reset_index(drop=True)


def split_features_and_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Select the model's input columns and binary target from a fetch_xapi_snapshot DataFrame."""
    missing = set(FEATURE_COLUMNS + [_SOURCE_TARGET_COLUMN]) - set(df.columns)
    if missing:
        raise ValueError(f"xAPI snapshot is missing expected column(s): {sorted(missing)}")

    x = df[FEATURE_COLUMNS].copy()
    y = (df[_SOURCE_TARGET_COLUMN] == _HIGH_ABSENCE_VALUE).astype(int)
    y.name = TARGET_COLUMN
    return x, y


def build_preprocessing_pipeline() -> ColumnTransformer:
    """Impute + encode/scale features. No missing values are expected in this dataset
    (verified: 480/480 rows fully populated on every selected column), but imputers are
    kept for the same defensive reason predictive.py/attendance_prediction.py keep theirs."""
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
    """Fit the absence-risk baseline: preprocessing + class-weighted logistic regression.

    Logistic regression, not an ensemble — the smallest reasonable baseline,
    consistent with `attendance_prediction.py`/`occupancy_detection.py`.
    `class_weight="balanced"` compensates for the ~40%/60% class split
    without resampling.
    """
    model = Pipeline(
        steps=[
            ("preprocessing", build_preprocessing_pipeline()),
            ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ]
    )
    model.fit(x_train, y_train)
    return model


class XapiAbsenceRiskPrediction(BaseModel):
    """One xAPI record's predicted absence-days-category risk — deliberately just two fields.

    Not "attendance": this is a probability that the source
    `student_absence_days` bucket is "Above-7", a coarse self-reported/
    administrative 2-bucket field — never a verified daily attendance
    prediction. See this module's docstring.
    """

    absence_risk_probability: float
    predicted_class: int


def predict(model: Pipeline, x: pd.DataFrame) -> list[XapiAbsenceRiskPrediction]:
    """Run `model` over `x`, returning one XapiAbsenceRiskPrediction per row, in order."""
    probabilities = model.predict_proba(x)[:, 1]
    predicted_classes = model.predict(x)
    return [
        XapiAbsenceRiskPrediction(absence_risk_probability=float(p), predicted_class=int(c))
        for p, c in zip(probabilities, predicted_classes, strict=True)
    ]


__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURE_COLUMNS",
    "IDENTIFIER_COLUMNS",
    "NUMERIC_FEATURES",
    "TARGET_COLUMN",
    "XapiAbsenceRiskPrediction",
    "build_preprocessing_pipeline",
    "drop_duplicate_rows",
    "predict",
    "split_features_and_target",
    "train_baseline_model",
]
