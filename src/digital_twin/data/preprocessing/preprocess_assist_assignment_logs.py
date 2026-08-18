"""Stage 6: alogs.csv -> assist_assignment_logs.

`student_id` is validated here in software against assist_student_classes'
distinct student_id values — there is no database-level foreign key for it
(assist_student_classes' primary key is the composite (student_id,
class_id); student_id alone is not unique there, so Postgres cannot express
a single-column FK to it). Same situation as OULAD's AssessmentSubmission.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ASSIST_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_foreign_key, assert_unique

logger = logging.getLogger(__name__)

KEY = ["log_id"]
ASSIGNMENT_KEY = ["assignment_id"]
STUDENT_KEY = ["student_id"]
COLUMNS = [
    *KEY,
    *STUDENT_KEY,
    *ASSIGNMENT_KEY,
    "start_time",
    "mean_correct",
    "time_on_task",
    "assignment_completed",
]


def preprocess_assist_assignment_logs(
    assignments: pd.DataFrame,
    student_classes: pd.DataFrame,
    raw_dir: Path = ASSIST_RAW_DIR,
) -> pd.DataFrame:
    """Load, clean, and validate alogs.csv into a DB-ready DataFrame.

    `assignments` and `student_classes` must already be the cleaned Stage 5
    and Stage 4 outputs — both are needed for foreign key validation.
    """
    logger.info("Preprocessing alogs.csv")
    df = pd.read_csv(raw_dir / "alogs.csv")[COLUMNS].copy()

    df["log_id"] = df["log_id"].astype("int64")
    df["student_id"] = df["student_id"].astype("int64")
    df["assignment_id"] = df["assignment_id"].astype("int64")
    df["start_time"] = pd.to_datetime(df["start_time"], format="ISO8601", utc=True)
    df["mean_correct"] = df["mean_correct"].astype("Float64")
    df["time_on_task"] = df["time_on_task"].astype("Float64")
    df["assignment_completed"] = df["assignment_completed"].astype("bool")

    assert_unique(df, KEY, "assist_assignment_logs")
    assert_foreign_key(
        df,
        assignments,
        ASSIGNMENT_KEY,
        table_name="assist_assignment_logs",
        parent_name="assist_assignments",
    )
    assert_foreign_key(
        df,
        student_classes,
        STUDENT_KEY,
        table_name="assist_assignment_logs",
        parent_name="assist_student_classes",
    )

    logger.info("assist_assignment_logs: %d rows ready", len(df))
    return df
