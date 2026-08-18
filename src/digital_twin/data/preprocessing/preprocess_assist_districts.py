"""Stage 1: ddets.csv -> assist_districts.

Standalone table — no other ASSISTments file carries a district_id or any
other district-linking column in this release (verified, not assumed; see
docs/datasets/assist-preprocessing-plan.md). Never referenced by, or
referencing, any other assist_ table.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ASSIST_RAW_DIR
from digital_twin.data.preprocessing.validation import assert_unique

logger = logging.getLogger(__name__)

KEY = ["district_id"]
COLUMNS = [*KEY, "location", "opportunity_zone", "locale_description"]


def preprocess_assist_districts(raw_dir: Path = ASSIST_RAW_DIR) -> pd.DataFrame:
    """Load and validate ddets.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing ddets.csv")
    df = pd.read_csv(raw_dir / "ddets.csv")[COLUMNS].copy()

    df["district_id"] = df["district_id"].astype("int64")
    df["location"] = df["location"].astype("string")
    df["opportunity_zone"] = df["opportunity_zone"].astype("string")
    # ~97.5% null — populated only for classified US districts; informative
    # when present, not sparse noise, so left nullable rather than dropped.
    df["locale_description"] = df["locale_description"].astype("string")

    assert_unique(df, KEY, "assist_districts")

    logger.info("assist_districts: %d rows ready", len(df))
    return df
