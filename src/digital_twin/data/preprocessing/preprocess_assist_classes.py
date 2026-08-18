"""Stage 2: cdets.csv -> assist_classes.

Root table for everything class-scoped — assist_student_classes and
assist_assignments both FK into this table. No cleaning needed: no nulls,
no duplicates present.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ASSIST_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_unique

logger = logging.getLogger(__name__)

KEY = ["class_id"]
COLUMNS = [
    *KEY,
    "teacher_id",
    "class_creation_date",
    "student_count",
    "problem_sets_assigned",
    "skill_builders_assigned",
]


def preprocess_assist_classes(raw_dir: Path = ASSIST_RAW_DIR) -> pd.DataFrame:
    """Load and validate cdets.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing cdets.csv")
    df = pd.read_csv(raw_dir / "cdets.csv")[COLUMNS].copy()

    df["class_id"] = df["class_id"].astype("int64")
    # No teacher table exists in this release — plain attribute, not an FK.
    df["teacher_id"] = df["teacher_id"].astype("int64")
    df["class_creation_date"] = pd.to_datetime(
        df["class_creation_date"], format="ISO8601", utc=True
    )
    df["student_count"] = df["student_count"].astype("int64")
    df["problem_sets_assigned"] = df["problem_sets_assigned"].astype("int64")
    df["skill_builders_assigned"] = df["skill_builders_assigned"].astype("int64")

    assert_unique(df, KEY, "assist_classes")

    logger.info("assist_classes: %d rows ready", len(df))
    return df
