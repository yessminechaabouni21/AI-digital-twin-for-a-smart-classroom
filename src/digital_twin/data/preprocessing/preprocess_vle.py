"""Stage 2: vle.csv -> vle_sites.

Drops week_from/week_to — 82% null on both, decided in
docs/datasets/oulad-preprocessing-plan.md Stage 2 as too sparse to keep as
a general feature.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import OULAD_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_foreign_key, assert_unique

logger = logging.getLogger(__name__)

KEY = ["id_site"]
COURSE_KEY = ["code_module", "code_presentation"]
COLUMNS = [*KEY, *COURSE_KEY, "activity_type"]


def preprocess_vle_sites(courses: pd.DataFrame, raw_dir: Path = OULAD_RAW_DIR) -> pd.DataFrame:
    """Load, clean, and validate vle.csv into a DB-ready DataFrame.

    `courses` must already be the cleaned Stage 1 output — its
    (code_module, code_presentation) keys are what this stage's foreign key
    is validated against.
    """
    logger.info("Preprocessing vle.csv")
    df = pd.read_csv(raw_dir / "vle.csv")[COLUMNS].copy()

    df["id_site"] = df["id_site"].astype("int64")
    df["code_module"] = df["code_module"].astype("string")
    df["code_presentation"] = df["code_presentation"].astype("string")
    df["activity_type"] = df["activity_type"].astype("string")

    assert_unique(df, KEY, "vle_sites")
    assert_foreign_key(df, courses, COURSE_KEY, table_name="vle_sites", parent_name="courses")

    logger.info("vle_sites: %d rows ready", len(df))
    return df
