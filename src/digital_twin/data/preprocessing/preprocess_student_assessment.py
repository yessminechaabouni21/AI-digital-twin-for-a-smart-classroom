"""Stage 5: studentAssessment.csv -> assessment_submissions.

`code_module`/`code_presentation` are recovered via a join through
`assessments` purely to validate the enrollments foreign key — they are NOT
persisted on `assessment_submissions` itself (see the finalized schema in
docs/datasets/oulad.md: the table's grain is (id_assessment, id_student),
course context is reached via assessments, not duplicated here).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import OULAD_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_foreign_key, assert_unique

logger = logging.getLogger(__name__)

KEY = ["id_assessment", "id_student"]
COLUMNS = [*KEY, "date_submitted", "score", "is_banked"]
ENROLLMENT_KEY = ["code_module", "code_presentation", "id_student"]


def preprocess_assessment_submissions(
    assessments: pd.DataFrame,
    enrollments: pd.DataFrame,
    raw_dir: Path = OULAD_RAW_DIR,
) -> pd.DataFrame:
    """Load, clean, and validate studentAssessment.csv into a DB-ready DataFrame.

    `assessments` and `enrollments` must already be the cleaned Stage 3 and
    Stage 4 outputs — both are needed for foreign key validation, and
    `assessments` additionally supplies the join used to reach `enrollments`
    two hops away (see module docstring).
    """
    logger.info("Preprocessing studentAssessment.csv")
    df = pd.read_csv(raw_dir / "studentAssessment.csv")[COLUMNS].copy()

    df["id_assessment"] = df["id_assessment"].astype("int64")
    df["id_student"] = df["id_student"].astype("int64")
    df["date_submitted"] = df["date_submitted"].astype("int64")
    # ~0.1% null — genuinely ungraded/missing, not zero (zero would read as
    # "failed"). The submission's existence + date is still valid signal.
    df["score"] = df["score"].astype("Float64")
    df["is_banked"] = df["is_banked"].astype("bool")

    assert_unique(df, KEY, "assessment_submissions")
    assert_foreign_key(
        df,
        assessments,
        ["id_assessment"],
        table_name="assessment_submissions",
        parent_name="assessments",
    )

    # Two-hop check: derive (code_module, code_presentation) via assessments,
    # then confirm the resulting enrollment key exists. Validation only —
    # these derived columns are not part of the returned/persisted frame.
    with_course = df.merge(
        assessments[["id_assessment", "code_module", "code_presentation"]],
        on="id_assessment",
        how="left",
    )
    assert_foreign_key(
        with_course,
        enrollments,
        ENROLLMENT_KEY,
        table_name="assessment_submissions (via assessments)",
        parent_name="enrollments",
    )

    logger.info("assessment_submissions: %d rows ready", len(df))
    return df
