"""Stage 3: pdets.csv -> assist_problems.

Drops the 392 rows with a null problem_id — every one of them also has
content_source == "['Undetermined']" and null skills/problem_type/
tutoring_types, a coherent "unidentified problem" bucket, not random
corruption. No identifier may be invented for them (see
docs/datasets/assist-preprocessing-plan.md Stage 3).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ASSIST_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_unique, warn_out_of_range

logger = logging.getLogger(__name__)

KEY = ["problem_id"]
COLUMNS = [
    *KEY,
    "content_source",
    "skills",
    "problem_type",
    "tutoring_types",
    "student_answer_count",
    "mean_correct",
    "mean_time_on_task",
]


def preprocess_assist_problems(raw_dir: Path = ASSIST_RAW_DIR) -> pd.DataFrame:
    """Load, clean, and validate pdets.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing pdets.csv")
    raw = pd.read_csv(raw_dir / "pdets.csv")[COLUMNS]

    df = raw[raw["problem_id"].notna()].copy()
    dropped = len(raw) - len(df)
    logger.info("assist_problems: dropped %d row(s) with null problem_id", dropped)

    df["problem_id"] = df["problem_id"].astype("int64")
    df["content_source"] = df["content_source"].astype("string")
    df["skills"] = df["skills"].astype("string")
    df["problem_type"] = df["problem_type"].astype("string")
    df["tutoring_types"] = df["tutoring_types"].astype("string")
    df["student_answer_count"] = df["student_answer_count"].astype("int64")
    df["mean_correct"] = df["mean_correct"].astype("Float64")
    df["mean_time_on_task"] = df["mean_time_on_task"].astype("Float64")

    assert_unique(df, KEY, "assist_problems")
    warn_out_of_range(df, "mean_correct", 0, 1, "assist_problems")

    logger.info("assist_problems: %d rows ready", len(df))
    return df
