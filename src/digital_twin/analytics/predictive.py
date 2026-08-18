"""Predictive analytics: at-risk detection, performance forecasting.

First model: OULAD dropout-risk baseline. Consumes the plain pandas
DataFrame produced by
`data/repositories/oulad_dropout_features.fetch_oulad_dropout_snapshot` —
no SQLAlchemy/Postgres import anywhere in this module, and no dependency on
domain/twin_engine either, per CLAUDE.md's module boundaries and the
explicit requirement to keep ML code separate from persistence and from the
Student Digital Twin runtime. See
docs/datasets/dropout-prediction-feature-design.md for the feature/target
design this implements.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET_COLUMN = "is_dropout"

# id_student is the only excluded identifier: dataset-scoped, not a
# person-level identifier (see domain/student.py's Student docstring), and
# never a predictive signal. code_module/code_presentation are now real
# features (below) rather than identifiers — known at enrollment (before
# any cutoff), a real course-difficulty/pacing signal, and no longer
# withheld now that the model has more than course-base-rate signal to
# lean on (assessment submission rate, VLE recency) alongside them.
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

    Categorical missingness (e.g. ~3.4% of `imd_band`) is filled with an
    explicit "Unknown" category rather than the most-frequent value, so a
    missing socioeconomic proxy is never silently treated as if it were the
    majority category. Numeric missingness (e.g. `assessments_mean_score`
    for students with zero submissions by the cutoff) is median-imputed.
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


def train_val_test_split(
    x: pd.DataFrame,
    y: pd.Series,
    *,
    val_size: float = 0.2,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Stratified 60/20/20 (by default) train/validation/test split.

    Stratified on `y` at both splits so the ~18% dropout rate is preserved
    in every split, not just the full dataset.
    """
    x_train_val, x_test, y_train_val, y_test = train_test_split(
        x, y, test_size=test_size, stratify=y, random_state=random_state
    )
    relative_val_size = val_size / (1 - test_size)
    x_train, x_val, y_train, y_val = train_test_split(
        x_train_val,
        y_train_val,
        test_size=relative_val_size,
        stratify=y_train_val,
        random_state=random_state,
    )
    return x_train, x_val, x_test, y_train, y_val, y_test


def train_baseline_model(x_train: pd.DataFrame, y_train: pd.Series) -> Pipeline:
    """Fit the baseline dropout-risk model: preprocessing + class-weighted logistic regression.

    Logistic regression, not a complex ensemble or deep model — chosen for
    interpretability (coefficients are directly inspectable) as the first,
    explainable baseline. `class_weight="balanced"` compensates for the
    ~18%/82% class imbalance without resampling.
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
    """Fit a stronger baseline: preprocessing + class-weighted random forest.

    Same feature matrix, same leakage-safe day-30 cutoff, same
    `class_weight="balanced"` imbalance handling as `train_baseline_model` —
    only the classifier differs, so the two are directly comparable on
    identical train/validation/test splits. Random forest, not
    XGBoost/LightGBM: neither is a project dependency (see
    pyproject.toml), and scikit-learn's own ensemble already gives a
    non-linear, interaction-capturing comparison point without adding one.
    `max_depth`/`min_samples_leaf` are deliberately constrained (not
    sklearn's unbounded defaults) — an untuned forest memorizes the training
    split (train ROC-AUC ~1.0) while generalizing worse than the logistic
    baseline on validation; this depth/leaf-size combination was selected by
    comparing validation-set recall/precision/F1/ROC-AUC across a small grid,
    the same evaluation this module reports for every model.
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


class ClassificationMetrics(BaseModel):
    """Standard binary-classification evaluation report for one dataset split."""

    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    class_distribution: dict[int, int]
    confusion_matrix: list[list[int]]


def evaluate_model(
    model: Pipeline, x: pd.DataFrame, y: pd.Series, *, threshold: float = 0.5
) -> ClassificationMetrics:
    """Compute standard classification metrics for `model` on (`x`, `y`).

    `threshold` classifies on `predict_proba(x)[:, 1] >= threshold` rather
    than `model.predict`, so callers can evaluate the same fitted model at a
    non-default decision threshold without retraining or reimplementing
    metric computation.
    """
    y_proba = model.predict_proba(x)[:, 1]
    y_pred = (y_proba >= threshold).astype(int)

    return ClassificationMetrics(
        accuracy=accuracy_score(y, y_pred),
        precision=precision_score(y, y_pred, zero_division=0),
        recall=recall_score(y, y_pred, zero_division=0),
        f1=f1_score(y, y_pred, zero_division=0),
        roc_auc=roc_auc_score(y, y_proba),
        class_distribution={int(k): int(v) for k, v in y.value_counts().sort_index().items()},
        confusion_matrix=confusion_matrix(y, y_pred).tolist(),
    )


class DropoutPrediction(BaseModel):
    """A single student's dropout-risk output — deliberately just these two fields.

    Not wired into StudentTwin yet (see module docstring); this is the
    output shape a future StudentTwin-facing interface would consume.
    """

    dropout_probability: float
    predicted_class: int


def predict(model: Pipeline, x: pd.DataFrame) -> list[DropoutPrediction]:
    """Run `model` over `x`, returning one DropoutPrediction per row, in order."""
    probabilities = model.predict_proba(x)[:, 1]
    predicted_classes = model.predict(x)
    return [
        DropoutPrediction(dropout_probability=float(p), predicted_class=int(c))
        for p, c in zip(probabilities, predicted_classes, strict=True)
    ]


__all__ = [
    "CATEGORICAL_FEATURES",
    "FEATURE_COLUMNS",
    "IDENTIFIER_COLUMNS",
    "NUMERIC_FEATURES",
    "TARGET_COLUMN",
    "ClassificationMetrics",
    "DropoutPrediction",
    "build_preprocessing_pipeline",
    "evaluate_model",
    "predict",
    "split_features_and_target",
    "train_baseline_model",
    "train_random_forest_model",
    "train_val_test_split",
]
