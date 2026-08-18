"""Stage 1: courses.csv -> courses.

No cleaning needed (22 rows, 3 columns, already clean per
docs/datasets/oulad.md) — this module mainly establishes the column
contract and uniqueness guard every other stage validates its own foreign
keys against.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import OULAD_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_unique

logger = logging.getLogger(__name__)

KEY = ["code_module", "code_presentation"]
COLUMNS = [*KEY, "module_presentation_length"]


def preprocess_courses(raw_dir: Path = OULAD_RAW_DIR) -> pd.DataFrame:
    """Load and validate courses.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing courses.csv")
    df = pd.read_csv(raw_dir / "courses.csv")[COLUMNS].copy()

    df["code_module"] = df["code_module"].astype("string")
    df["code_presentation"] = df["code_presentation"].astype("string")
    df["module_presentation_length"] = df["module_presentation_length"].astype("int64")

    assert_unique(df, KEY, "courses")

    logger.info("courses: %d rows ready", len(df))
    return df
