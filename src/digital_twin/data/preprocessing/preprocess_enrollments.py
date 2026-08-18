"""Stage 4: studentInfo.csv + studentRegistration.csv -> enrollments (merge).

The one merge in the schema — both source files share the exact same grain
and key set (verified in docs/datasets/oulad.md), so this is a lossless 1:1
join, not a denormalization risk. See
docs/datasets/oulad-preprocessing-plan.md Stage 4 for the rationale behind
each cleaning/null-handling decision below.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import OULAD_RAW_DIR
from digital_twin.data.preprocessing.validation import (
    assert_foreign_key,
    assert_row_count_preserved,
    assert_unique,
)

logger = logging.getLogger(__name__)

KEY = ["code_module", "code_presentation", "id_student"]
COURSE_KEY = ["code_module", "code_presentation"]
COLUMNS = [
    *KEY,
    "gender",
    "highest_education",
    "imd_band",
    "age_band",
    "num_of_prev_attempts",
    "studied_credits",
    "disability",
    "date_registration",
    "date_unregistration",
    "final_result",
]


def _normalize_imd_band(imd_band: pd.Series) -> pd.Series:
    """Fix the one source formatting inconsistency: `"10-20"` missing its `%`.

    Every other imd_band bucket is formatted `"XX-XX%"`. Must run before
    `imd_band` is treated as a fixed category set anywhere downstream, so
    the missing `%` isn't mistaken for a distinct valid category.
    """
    needs_percent = imd_band.notna() & ~imd_band.str.endswith("%")
    return imd_band.where(~needs_percent, imd_band + "%")


def preprocess_enrollments(courses: pd.DataFrame, raw_dir: Path = OULAD_RAW_DIR) -> pd.DataFrame:
    """Load, merge, clean, and validate studentInfo + studentRegistration."""
    logger.info("Preprocessing studentInfo.csv + studentRegistration.csv")
    info = pd.read_csv(raw_dir / "studentInfo.csv")
    registration = pd.read_csv(raw_dir / "studentRegistration.csv")

    # UK-specific geography, no analog in a generic classroom twin (oulad.md #3).
    info = info.drop(columns=["region"])
    info["imd_band"] = _normalize_imd_band(info["imd_band"])

    merged = info.merge(registration, on=KEY, how="inner", validate="one_to_one")
    assert_row_count_preserved(len(info), len(merged), table_name="enrollments (vs. studentInfo)")
    assert_row_count_preserved(
        len(registration), len(merged), table_name="enrollments (vs. studentRegistration)"
    )

    df = merged[COLUMNS].copy()
    df["id_student"] = df["id_student"].astype("int64")
    df["code_module"] = df["code_module"].astype("string")
    df["code_presentation"] = df["code_presentation"].astype("string")
    df["gender"] = df["gender"].astype("string")
    df["highest_education"] = df["highest_education"].astype("string")
    df["imd_band"] = df["imd_band"].astype("string")
    df["age_band"] = df["age_band"].astype("string")
    df["num_of_prev_attempts"] = df["num_of_prev_attempts"].astype("int64")
    df["studied_credits"] = df["studied_credits"].astype("int64")
    df["disability"] = df["disability"].astype("string")
    # NULL = unknown registration date (~0.14%), not day zero.
    df["date_registration"] = df["date_registration"].astype("Int64")
    # NULL = did not withdraw (~69%) — never impute, never treat as 0.
    df["date_unregistration"] = df["date_unregistration"].astype("Int64")
    df["final_result"] = df["final_result"].astype("string")

    assert_unique(df, KEY, "enrollments")
    assert_foreign_key(df, courses, COURSE_KEY, table_name="enrollments", parent_name="courses")

    logger.info("enrollments: %d rows ready", len(df))
    return df
