"""Student performance prediction: will a student Pass or Fail the course.

Consumes the plain pandas DataFrame produced by
`data/repositories/oulad_performance_features.fetch_oulad_performance_snapshot`
— no SQLAlchemy/Postgres import anywhere in this module, and no dependency
on domain/twin_engine either, per CLAUDE.md's module boundaries.
`StudentTwin.attach_performance_prediction` wires a `StudentPerformancePrediction`
produced here into `StudentTwinState.performance_prediction` — the twin
never fits or calls this module's models itself, only attaches an
already-computed result (see `scripts/student_twin_predictions_oulad_demo.py`).

Reuses `analytics/predictive.py`'s `train_val_test_split`, `evaluate_model`,
and `ClassificationMetrics` — those are generic classification-evaluation
utilities, not dropout-specific — rather than duplicating them.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET_COLUMN = "is_pass"

# id_student is the only excluded identifier: dataset-scoped, not a
# person-level identifier, and never a predictive signal.
# code_module/code_presentation are known at enrollment (before any
# cutoff) and are real features (course identity/difficulty signal), same
# treatment as in analytics/predictive.py's dropout feature set.
IDENTIFIER_COLUMNS = ["id_student"]

CATEGORICAL_FEATURES = [
    "gender",
    "highest_education",
    "imd_band",
    "age_band",
    "disability",
    "code_module",
    "code_presentation",
]
NUMERIC_FEATURES = [
    "num_of_prev_attempts",
    "studied_credits",
    "date_registration",
    "assessments_submitted_count",
    "assessments_mean_score",
    "assessments_due_count",
    "assessments_submission_rate",
    "vle_total_clicks",
    "vle_active_days",
    "vle_distinct_sites",
    "vle_days_since_last_click",
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
    """Impute + encode/scale features. Fit only on the training split, never on all data.

    Categorical missingness (e.g. `imd_band`) is filled with an explicit
    "Unknown" category rather than the most-frequent value, so a missing
    socioeconomic proxy is never silently treated as if it were the
    majority category. Numeric missingness (e.g. `assessments_mean_score`
    for students with zero TMA/CMA submissions by the cutoff) is
    median-imputed.
    """
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
    """Fit the performance-prediction baseline: preprocessing + class-weighted logistic regression.

    Logistic regression, not a complex ensemble or deep model — the
    smallest reasonable baseline, matching `analytics/predictive.py`'s
    dropout baseline and `analytics/attendance_prediction.py`'s baseline.
    `class_weight="balanced"` compensates for the pass/fail imbalance
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


def train_random_forest_model(
    x_train: pd.DataFrame,
    y_train: pd.Series,
    *,
    n_estimators: int = 300,
    max_depth: int = 8,
    min_samples_leaf: int = 10,
    random_state: int = 42,
) -> Pipeline:
    """Fit a stronger comparison model: preprocessing + class-weighted random forest.

    Same feature matrix, same leakage-safe day-30 cutoff, same
    `class_weight="balanced"` imbalance handling as `train_baseline_model` —
    only the classifier differs, so the two are directly comparable on
    identical train/validation/test splits.
    `n_estimators`/`max_depth`/`min_samples_leaf` reuse
    `analytics/predictive.py`'s dropout-model config exactly (constrained,
    not sklearn's unbounded defaults, to avoid memorizing the training
    split — see that module's docstring for the validation-set grid check
    behind these values), rather than re-deriving a separate config for a
    second OULAD classification task with the same feature shape.
    """
    model = Pipeline(
        steps=[
            ("preprocessing", build_preprocessing_pipeline()),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    min_samples_leaf=min_samples_leaf,
                    class_weight="balanced",
                    random_state=random_state,
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    return model


class StudentPerformancePrediction(BaseModel):
    """A single student's pass-risk output — deliberately just these two fields.

    The output shape `StudentTwin.attach_performance_prediction` consumes
    (see module docstring) to populate `StudentTwinState.performance_prediction`.
    """

    pass_probability: float
    predicted_class: int


def predict(model: Pipeline, x: pd.DataFrame) -> list[StudentPerformancePrediction]:
    """Run `model` over `x`, returning one StudentPerformancePrediction per row, in order."""
    probabilities = model.predict_proba(x)[:, 1]
    predicted_classes = model.predict(x)
    return [
        StudentPerformancePrediction(pass_probability=float(p), predicted_class=int(c))
        for p, c in zip(probabilities, predicted_classes, strict=True)
    ]


__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURE_COLUMNS",
    "IDENTIFIER_COLUMNS",
    "NUMERIC_FEATURES",
    "TARGET_COLUMN",
    "StudentPerformancePrediction",
    "build_preprocessing_pipeline",
    "predict",
    "split_features_and_target",
    "train_baseline_model",
    "train_random_forest_model",
]
