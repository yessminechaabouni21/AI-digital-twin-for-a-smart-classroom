"""Stage 5: adets.csv -> assist_assignments."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ASSIST_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_foreign_key, assert_unique

logger = logging.getLogger(__name__)

KEY = ["assignment_id"]
CLASS_KEY = ["class_id"]
COLUMNS = [
    *KEY,
    *CLASS_KEY,
    "release_date",
    "due_date",
    "assignment_type",
    "started_student_count",
    "completed_or_mastered_student_count",
    "problem_count",
    "mean_correct",
    "mean_time_on_task",
]


def preprocess_assist_assignments(
    classes: pd.DataFrame, raw_dir: Path = ASSIST_RAW_DIR
) -> pd.DataFrame:
    """Load, clean, and validate adets.csv into a DB-ready DataFrame.

    `classes` must already be the cleaned Stage 2 output — its class_id
    values are what this stage's foreign key is validated against.
    """
    logger.info("Preprocessing adets.csv")
    df = pd.read_csv(raw_dir / "adets.csv")[COLUMNS].copy()

    df["assignment_id"] = df["assignment_id"].astype("int64")
    df["class_id"] = df["class_id"].astype("int64")
    df["release_date"] = pd.to_datetime(df["release_date"], format="ISO8601", utc=True)
    df["due_date"] = pd.to_datetime(df["due_date"], format="ISO8601", utc=True)
    df["assignment_type"] = df["assignment_type"].astype("string")
    df["started_student_count"] = df["started_student_count"].astype("int64")
    df["completed_or_mastered_student_count"] = df[
        "completed_or_mastered_student_count"
    ].astype("int64")
    df["problem_count"] = df["problem_count"].astype("int64")
    df["mean_correct"] = df["mean_correct"].astype("Float64")
    df["mean_time_on_task"] = df["mean_time_on_task"].astype("Float64")

    assert_unique(df, KEY, "assist_assignments")
    assert_foreign_key(
        df, classes, CLASS_KEY, table_name="assist_assignments", parent_name="assist_classes"
    )

    logger.info("assist_assignments: %d rows ready", len(df))
    return df
