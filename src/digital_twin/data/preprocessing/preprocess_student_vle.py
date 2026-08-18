"""Stage 6: studentVle.csv -> vle_interactions.

The critical operation: group by the full 5-column key and SUM `sum_click`
in one pass, without pre-deduplicating exact-duplicate rows first.

Why: the raw file is not pre-aggregated despite `sum_click`'s name — 20.6%
of raw rows share this table's key with a *differing* `sum_click` value,
and a further 7.4% are fully-duplicate rows. Both are treated as genuine
partial contributions to a day's total and summed together, because there
is no documented way in the public OULAD release to tell a redundant
duplicate log entry apart from two real contributions that happen to
match — see docs/datasets/oulad-preprocessing-plan.md Stage 6 for the full
reasoning behind this call.

Read in chunks (10.6M raw rows / ~433MB) with incremental groupby-sum
accumulation rather than loading the whole file into memory at once.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import OULAD_RAW_DIR
from digital_twin.data.preprocessing.validation import (
    OuladValidationError,
    assert_foreign_key,
    assert_unique,
)

logger = logging.getLogger(__name__)

KEY = ["code_module", "code_presentation", "id_student", "id_site", "date"]
ENROLLMENT_KEY = ["code_module", "code_presentation", "id_student"]
SITE_KEY = ["id_site"]
DEFAULT_CHUNK_SIZE = 1_000_000


def preprocess_vle_interactions(
    vle_sites: pd.DataFrame,
    enrollments: pd.DataFrame,
    raw_dir: Path = OULAD_RAW_DIR,
    chunksize: int = DEFAULT_CHUNK_SIZE,
) -> pd.DataFrame:
    """Load, aggregate, and validate studentVle.csv into a DB-ready DataFrame.

    `vle_sites` and `enrollments` must already be the cleaned Stage 2 and
    Stage 4 outputs, needed for foreign key validation.
    """
    logger.info("Preprocessing studentVle.csv (chunked, chunksize=%d)", chunksize)
    accumulated: pd.DataFrame | None = None
    total_raw_rows = 0

    for chunk_number, chunk in enumerate(
        pd.read_csv(raw_dir / "studentVle.csv", chunksize=chunksize), start=1
    ):
        total_raw_rows += len(chunk)
        partial = chunk.groupby(KEY, as_index=False)["sum_click"].sum()
        accumulated = (
            partial
            if accumulated is None
            else pd.concat([accumulated, partial], ignore_index=True)
            .groupby(KEY, as_index=False)["sum_click"]
            .sum()
        )
        logger.info(
            "studentVle: chunk %d processed (%d raw rows so far, %d aggregated keys so far)",
            chunk_number,
            total_raw_rows,
            len(accumulated),
        )

    if accumulated is None:
        raise OuladValidationError("studentVle.csv produced no rows")

    df = accumulated
    df["code_module"] = df["code_module"].astype("string")
    df["code_presentation"] = df["code_presentation"].astype("string")
    df["id_student"] = df["id_student"].astype("int64")
    df["id_site"] = df["id_site"].astype("int64")
    df["date"] = df["date"].astype("int64")
    df["sum_click"] = df["sum_click"].astype("int64")

    assert_unique(df, KEY, "vle_interactions")
    assert_foreign_key(
        df, vle_sites, SITE_KEY, table_name="vle_interactions", parent_name="vle_sites"
    )
    assert_foreign_key(
        df,
        enrollments,
        ENROLLMENT_KEY,
        table_name="vle_interactions",
        parent_name="enrollments",
    )

    logger.info(
        "vle_interactions: %d aggregated rows ready (from %d raw rows)", len(df), total_raw_rows
    )
    return df
