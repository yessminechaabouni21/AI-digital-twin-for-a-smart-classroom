"""Stage 3: assessments.csv -> assessments.

Keeps all 6 source columns. `date` is left null for the 11 Exam rows where
OULAD withholds/varies the final exam date — documented dataset behavior,
not missing data (see docs/datasets/oulad-preprocessing-plan.md Stage 3).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import OULAD_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_foreign_key, assert_unique

logger = logging.getLogger(__name__)

KEY = ["id_assessment"]
COURSE_KEY = ["code_module", "code_presentation"]
COLUMNS = [*KEY, *COURSE_KEY, "assessment_type", "date", "weight"]


def preprocess_assessments(courses: pd.DataFrame, raw_dir: Path = OULAD_RAW_DIR) -> pd.DataFrame:
    """Load, clean, and validate assessments.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing assessments.csv")
    df = pd.read_csv(raw_dir / "assessments.csv")[COLUMNS].copy()

    df["id_assessment"] = df["id_assessment"].astype("int64")
    df["code_module"] = df["code_module"].astype("string")
    df["code_presentation"] = df["code_presentation"].astype("string")
    df["assessment_type"] = df["assessment_type"].astype("string")
    df["date"] = df["date"].astype("Int64")
    df["weight"] = df["weight"].astype("float64")

    assert_unique(df, KEY, "assessments")
    assert_foreign_key(df, courses, COURSE_KEY, table_name="assessments", parent_name="courses")

    logger.info("assessments: %d rows ready", len(df))
    return df
