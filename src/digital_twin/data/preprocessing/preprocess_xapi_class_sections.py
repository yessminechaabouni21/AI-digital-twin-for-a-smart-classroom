"""Stage 1: xAPI-Edu-Data.csv -> xapi_class_sections.

Root reference table for the xAPI dataset — every `xapi_student_records` row
FKs into this table. Independent of OULAD's `courses`; never joined to it.
See docs/datasets/xapi-preprocessing-plan.md Stage 1.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import XAPI_RAW_FILE
from digital_twin.data.preprocessing.validation import assert_unique

logger = logging.getLogger(__name__)

KEY = ["stage_id", "grade_id", "section_id", "topic", "semester"]
RENAME = {
    "StageID": "stage_id",
    "GradeID": "grade_id",
    "SectionID": "section_id",
    "Topic": "topic",
    "Semester": "semester",
}


def preprocess_xapi_class_sections(raw_file: Path = XAPI_RAW_FILE) -> pd.DataFrame:
    """Load and validate the class-context columns of xAPI-Edu-Data.csv."""
    logger.info("Preprocessing xAPI-Edu-Data.csv (class sections)")
    df = pd.read_csv(raw_file)[list(RENAME)].rename(columns=RENAME)
    df = df.drop_duplicates(subset=KEY).reset_index(drop=True)

    for column in KEY:
        df[column] = df[column].astype("string")

    assert_unique(df, KEY, "xapi_class_sections")

    logger.info("xapi_class_sections: %d rows ready", len(df))
    return df
