"""Stage 4: sdets.csv -> assist_student_classes.

student_id alone is not unique — 8,560 students appear under more than one
class_id (verified) — so the composite (student_id, class_id) is this
table's real identity, the same student_id reuse pattern OULAD's
enrollments has. See docs/datasets/assist-preprocessing-plan.md Stage 4.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ASSIST_RAW_DIR
from digital_twin.data.preprocessing.validation import (
    assert_foreign_key,
    assert_row_count_preserved,
    assert_unique,
)

logger = logging.getLogger(__name__)

KEY = ["student_id", "class_id"]
CLASS_KEY = ["class_id"]
COLUMNS = [
    *KEY,
    "account_creation_date",
    "started_problem_sets_count",
    "completed_problem_sets_count",
    "started_skill_builders_count",
    "mastered_skill_builders_count",
    "answered_problems_count",
    "mean_problem_correctness",
    "mean_problem_time_on_task",
]


def preprocess_assist_student_classes(
    classes: pd.DataFrame, raw_dir: Path = ASSIST_RAW_DIR
) -> pd.DataFrame:
    """Load, clean, and validate sdets.csv into a DB-ready DataFrame.

    `classes` must already be the cleaned Stage 2 output — its class_id
    values are what this stage's foreign key is validated against.
    """
    logger.info("Preprocessing sdets.csv")
    raw = pd.read_csv(raw_dir / "sdets.csv")
    df = raw[COLUMNS].copy()
    assert_row_count_preserved(len(raw), len(df), table_name="assist_student_classes")

    df["student_id"] = df["student_id"].astype("int64")
    df["class_id"] = df["class_id"].astype("int64")
    df["account_creation_date"] = pd.to_datetime(
        df["account_creation_date"], format="ISO8601", utc=True
    )
    for column in [
        "started_problem_sets_count",
        "completed_problem_sets_count",
        "started_skill_builders_count",
        "mastered_skill_builders_count",
        "answered_problems_count",
    ]:
        df[column] = df[column].astype("int64")
    df["mean_problem_correctness"] = df["mean_problem_correctness"].astype("Float64")
    df["mean_problem_time_on_task"] = df["mean_problem_time_on_task"].astype("Float64")

    assert_unique(df, KEY, "assist_student_classes")
    assert_foreign_key(
        df, classes, CLASS_KEY, table_name="assist_student_classes", parent_name="assist_classes"
    )

    logger.info("assist_student_classes: %d rows ready", len(df))
    return df
