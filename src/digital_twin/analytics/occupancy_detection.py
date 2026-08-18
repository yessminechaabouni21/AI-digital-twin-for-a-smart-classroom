"""Room-occupancy classification from environmental readings: UCI Occupancy Detection.

Consumes the plain pandas DataFrame produced by
`data/repositories/occupancy_readings.fetch_occupancy_readings` — no
SQLAlchemy/Postgres import anywhere in this module, and no dependency on
domain/twin_engine either, per CLAUDE.md's module boundaries. Mirrors
`analytics/predictive.py`'s feature/split/train/evaluate shape for a
different real dataset; reuses its generic `evaluate_model`/
`ClassificationMetrics` rather than duplicating metric computation.

This model predicts **binary room occupancy** (is a person present in the
one monitored room this dataset covers, right now) from that room's own
temperature/humidity/CO2/light readings. It is not, and must never be
described as, a prediction of any individual student's attendance —
`occupancy_readings` carries no student or class identity at all (see
docs/datasets/occupancy-preprocessing-plan.md), so there is nothing here to
attribute to a person. It also has no ASSISTments classroom identity to
attach to: `occupancy_readings` shares no identifier with `assist_classes`
(verified, not assumed — see domain/classroom.py's module docstring), so
this module's output is never wired into a `ClassroomTwin`.
"""

from __future__ import annotations

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TARGET_COLUMN = "occupancy"

# temperature_c/humidity_pct/co2_ppm/light_lux only, per the requirement to
# use environmental measurements available at the reading itself.
# humidity_ratio is deliberately excluded: it is a deterministic function of
# temperature_c and humidity_pct already present in the source (see
# docs/datasets/occupancy-preprocessing-plan.md), so including it would add
# a redundant, perfectly-collinear feature rather than new information.
NUMERIC_FEATURES = ["temperature_c", "humidity_pct", "co2_ppm", "light_lux"]
FEATURE_COLUMNS = list(NUMERIC_FEATURES)


def split_features_and_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Select the model's input columns and target from a fetch_occupancy_readings DataFrame."""
    missing = set(FEATURE_COLUMNS + [TARGET_COLUMN]) - set(df.columns)
    if missing:
        raise ValueError(f"occupancy readings are missing expected column(s): {sorted(missing)}")

    x = df[FEATURE_COLUMNS].copy()
    y = df[TARGET_COLUMN].copy()
    return x, y


def chronological_train_test_split(
    df: pd.DataFrame, *, test_size: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a fetch_occupancy_readings DataFrame into an earlier-train / later-test holdout.

    `df` must already be ordered by `recorded_at` (as `fetch_occupancy_readings`
    returns it) — this function does not re-sort, so a caller passing
    unordered rows gets an unordered, meaningless split. The earliest
    `1 - test_size` fraction of rows becomes train, the latest `test_size`
    fraction becomes test: a genuine forecast-style holdout where the model
    never sees a reading from after any training reading. A random/stratified
    split (as `predictive.py` uses for OULAD) is deliberately not used here:
    this dataset's ~1-minute-interval readings are strongly autocorrelated
    with their immediate neighbors, so randomly scattering adjacent-in-time
    rows across train and test would leak near-duplicate conditions across
    the split and inflate every metric below. The dataset's own
    `source_file` split (training/test/test2) is also deliberately not
    reused as-is: its date ranges are not monotonic in file order (`test`
    2015-02-02..02-04, `training` 02-04..02-10, `test2` 02-11..02-18,
    verified against the live table) — reusing it as train/test would put
    `test` (chronologically earliest) after `training` in the eval
    narrative, which is not a forward-looking holdout.
    """
    split_index = int(len(df) * (1 - test_size))
    return df.iloc[:split_index].copy(), df.iloc[split_index:].copy()


def transition_event_mask(y: pd.Series) -> pd.Series:
    """Return a boolean mask selecting only rows where `y` differs from the immediately
    preceding row (`y` must already be in the same chronological order the row-level
    `y` was, i.e. as `chronological_train_test_split` produces it).

    Row-level accuracy on this dataset is inflated by strong autocorrelation
    (~1-minute-apart readings rarely change occupancy state between
    consecutive rows) — a persistence baseline (predict "same as last
    reading") scores almost identically to the trained model on raw
    row-level accuracy (see `scripts/occupancy_detection_demo.py`'s
    reported comparison). Restricting evaluation to only the rows where the
    true label actually changed isolates the harder, more informative
    question: does the model detect real occupancy transitions, where a
    persistence baseline is guaranteed wrong by construction. The first row
    is never a transition (no preceding row to compare against) and is
    excluded.
    """
    shifted = y.shift(1)
    mask = y != shifted
    mask.iloc[0] = False
    return mask


def build_preprocessing_pipeline() -> StandardScaler:
    """Scale the four numeric environmental features.

    No imputer: `occupancy_readings` is asserted to have zero missing values
    at load time (docs/datasets/occupancy-preprocessing-plan.md), unlike
    OULAD's genuinely incomplete columns, so there is nothing to impute.
    """
    return StandardScaler()


def train_baseline_model(x_train: pd.DataFrame, y_train: pd.Series) -> Pipeline:
    """Fit the interpretable baseline: scaling + class-weighted logistic regression.

    Logistic regression, not a complex ensemble — the first, explainable
    baseline, same choice `predictive.py` makes for the OULAD dropout model.
    `class_weight="balanced"` compensates for occupancy's ~21-36% positive
    rate (observed per source file; see
    docs/datasets/occupancy-preprocessing-plan.md) without resampling.
    """
    model = Pipeline(
        steps=[
            ("preprocessing", build_preprocessing_pipeline()),
            ("classifier", LogisticRegression(class_weight="balanced", max_iter=1000)),
        ]
    )
    model.fit(x_train, y_train)
    return model


__all__ = [
    "FEATURE_COLUMNS",
    "NUMERIC_FEATURES",
    "TARGET_COLUMN",
    "build_preprocessing_pipeline",
    "chronological_train_test_split",
    "split_features_and_target",
    "train_baseline_model",
    "transition_event_mask",
]
