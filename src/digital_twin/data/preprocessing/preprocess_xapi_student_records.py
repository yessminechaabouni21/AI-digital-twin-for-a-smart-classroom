"""Stage 2: xAPI-Edu-Data.csv -> xapi_student_records.

No natural key exists at this grain (4 source rows are fully duplicate
across all 17 columns) — `record_id` is assigned by Postgres on insert, not
by this stage. The 4 duplicate rows are kept, not dropped: see "Guiding
rules" in docs/datasets/xapi-preprocessing-plan.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import XAPI_RAW_FILE
from digital_twin.data.preprocessing.validation import (
    assert_foreign_key,
    assert_row_count_preserved,
    warn_on_duplicate_rows,
    warn_out_of_range,
)

logger = logging.getLogger(__name__)

CLASS_KEY = ["stage_id", "grade_id", "section_id", "topic", "semester"]
RENAME = {
    "StageID": "stage_id",
    "GradeID": "grade_id",
    "SectionID": "section_id",
    "Topic": "topic",
    "Semester": "semester",
    "gender": "gender",
    "NationalITy": "nationality",
    "PlaceofBirth": "place_of_birth",
    "Relation": "relation",
    "raisedhands": "raised_hands",
    "VisITedResources": "visited_resources",
    "AnnouncementsView": "announcements_view",
    "Discussion": "discussion",
    "ParentAnsweringSurvey": "parent_answering_survey",
    "ParentschoolSatisfaction": "parent_school_satisfaction",
    "StudentAbsenceDays": "student_absence_days",
    "Class": "class_label",
}
ENGAGEMENT_COLUMNS = ["raised_hands", "visited_resources", "announcements_view", "discussion"]
STRING_COLUMNS = [
    "gender",
    "nationality",
    "place_of_birth",
    "relation",
    "parent_answering_survey",
    "parent_school_satisfaction",
    "student_absence_days",
    "class_label",
]


def preprocess_xapi_student_records(
    class_sections: pd.DataFrame, raw_file: Path = XAPI_RAW_FILE
) -> pd.DataFrame:
    """Load, clean, and validate xAPI-Edu-Data.csv into a DB-ready DataFrame.

    `class_sections` must already be the cleaned Stage 1 output — its
    (stage_id, grade_id, section_id, topic, semester) keys are what this
    stage's foreign key is validated against.
    """
    logger.info("Preprocessing xAPI-Edu-Data.csv (student records)")
    raw = pd.read_csv(raw_file)
    before = len(raw)
    if raw.isnull().values.any():
        raise ValueError("xapi_student_records: unexpected null value(s) in source file")

    df = raw.rename(columns=RENAME)[[*CLASS_KEY, *STRING_COLUMNS, *ENGAGEMENT_COLUMNS]].copy()
    assert_row_count_preserved(before, len(df), table_name="xapi_student_records")

    for column in [*CLASS_KEY, *STRING_COLUMNS]:
        df[column] = df[column].astype("string")
    for column in ENGAGEMENT_COLUMNS:
        df[column] = df[column].astype("int64")

    warn_on_duplicate_rows(df, "xapi_student_records")
    for column in ENGAGEMENT_COLUMNS:
        warn_out_of_range(df, column, 0, 100, "xapi_student_records")

    assert_foreign_key(
        df,
        class_sections,
        CLASS_KEY,
        table_name="xapi_student_records",
        parent_name="xapi_class_sections",
    )

    logger.info("xapi_student_records: %d rows ready", len(df))
    return df
