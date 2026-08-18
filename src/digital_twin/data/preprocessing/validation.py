"""Shared validation helpers for the OULAD preprocessing pipeline.

Every stage re-verifies the uniqueness/FK invariants documented in
docs/datasets/oulad-preprocessing-plan.md rather than trusting the earlier
one-time audit — the audit was a point-in-time profiling pass; these
assertions make the same invariants fail loudly if a future re-download of
OULAD ever violates them.
"""

from __future__ import annotations

import logging
from collections.abc import Set as AbstractSet

import pandas as pd

logger = logging.getLogger(__name__)


class OuladValidationError(ValueError):
    """Raised when a cleaned OULAD table violates a documented invariant."""


def assert_unique(df: pd.DataFrame, key_columns: list[str], table_name: str) -> None:
    """Raise if any row shares its key_columns values with another row."""
    duplicated = df.duplicated(subset=key_columns, keep=False)
    if duplicated.any():
        count = int(duplicated.sum())
        raise OuladValidationError(
            f"{table_name}: {count} row(s) violate uniqueness on {key_columns}"
        )


def assert_row_count_preserved(before: int, after: int, *, table_name: str) -> None:
    """Raise if a step expected to be lossless changed the row count."""
    if before != after:
        raise OuladValidationError(
            f"{table_name}: row count changed from {before} to {after} "
            "during a step expected to be lossless"
        )


def assert_foreign_key(
    child_df: pd.DataFrame,
    parent_df: pd.DataFrame,
    key_columns: list[str],
    *,
    table_name: str,
    parent_name: str,
) -> None:
    """Raise if any distinct key_columns value in child_df is absent from parent_df.

    Both frames must carry the same column names for key_columns — every
    call site in this pipeline joins on identically-named columns, so this
    stays a single `on=` merge rather than juggling left/right column lists.
    """
    child_keys = child_df[key_columns].drop_duplicates()
    parent_keys = parent_df[key_columns].drop_duplicates()
    merged = child_keys.merge(parent_keys, on=key_columns, how="left", indicator=True)
    orphans = merged[merged["_merge"] == "left_only"]
    if not orphans.empty:
        raise OuladValidationError(
            f"{table_name}: {len(orphans)} distinct key(s) on {key_columns} "
            f"not found in {parent_name}"
        )


def warn_foreign_key(
    child_df: pd.DataFrame,
    parent_df: pd.DataFrame,
    key_columns: list[str],
    *,
    table_name: str,
    parent_name: str,
) -> None:
    """Log (not raise) if any distinct key_columns value in child_df is absent from parent_df.

    Same shape as `assert_foreign_key`, for the rare case where an orphan
    is a verified, explained property of the source data (see
    docs/datasets/assist-preprocessing-plan.md's `assist_problem_logs`
    stage) rather than a violation to reject the load over.
    """
    child_keys = child_df[key_columns].drop_duplicates()
    parent_keys = parent_df[key_columns].drop_duplicates()
    merged = child_keys.merge(parent_keys, on=key_columns, how="left", indicator=True)
    orphans = merged[merged["_merge"] == "left_only"]
    if not orphans.empty:
        affected_rows = len(child_df[key_columns].merge(orphans[key_columns], on=key_columns))
        logger.warning(
            "%s: %d distinct key(s) on %s not found in %s (%d row(s) affected)",
            table_name,
            len(orphans),
            key_columns,
            parent_name,
            affected_rows,
        )


def warn_on_duplicate_rows(df: pd.DataFrame, table_name: str) -> None:
    """Log (not raise) the count of fully-duplicate rows.

    Some source tables have documented, expected full-row duplicates (see
    docs/datasets/xapi-preprocessing-plan.md) that are intentionally kept,
    not deduplicated. This surfaces the count for review rather than
    silently loading it or failing the pipeline over it.
    """
    count = int(df.duplicated(keep=False).sum())
    if count:
        logger.warning("%s: %d fully-duplicate row(s) found (kept, not dropped)", table_name, count)


def assert_allowed_values(
    df: pd.DataFrame, column: str, allowed: AbstractSet[object], table_name: str
) -> None:
    """Raise if `column` contains any value outside `allowed`.

    For finite-domain columns (e.g. a binary target variable, an internally
    assigned split tag) where an out-of-domain value means the data itself
    is corrupted, not just unusual — unlike `warn_out_of_range`, this
    rejects the load rather than logging.
    """
    invalid = set(df[column].unique()) - allowed
    if invalid:
        raise OuladValidationError(
            f"{table_name}: {column} contains value(s) outside {allowed}: "
            f"{sorted(invalid, key=str)}"
        )


def warn_out_of_range(
    df: pd.DataFrame, column: str, low: float, high: float, table_name: str
) -> None:
    """Log (not raise) rows where `column` falls outside [low, high].

    The range is an observation from profiling, not a schema-enforced
    source constraint, so a violation is surfaced rather than rejected.
    Nulls are skipped, not flagged — a missing value isn't out of range,
    it's absent (relevant for nullable dtypes, e.g. pandas "Float64").
    """
    mask = ((df[column] < low) | (df[column] > high)).fillna(False).astype(bool)
    out_of_range = df[mask]
    if not out_of_range.empty:
        logger.warning(
            "%s: %d row(s) with %s outside [%s, %s]",
            table_name,
            len(out_of_range),
            column,
            low,
            high,
        )
