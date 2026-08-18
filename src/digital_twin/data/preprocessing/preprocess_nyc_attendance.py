"""Stage 1 (only stage): NYC_attendance.csv -> nyc_daily_attendance.

NYC DOE daily school attendance, 2012-2013 through 2014-2015 school years.
Standalone — no shared identifier with OULAD, xAPI, ASSISTments,
co2_sensor_readings, or occupancy_readings.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import NYC_ATTENDANCE_RAW_FILE
from digital_twin.data.preprocessing.validation import (
    assert_row_count_preserved,
    warn_out_of_range,
)

logger = logging.getLogger(__name__)

RENAME = {
    "School": "school_id",
    "Date": "attendance_date",
    "SchoolYear": "school_year",
    "Enrolled": "enrolled",
    "Present": "present",
    "Absent": "absent",
    "Released": "released",
}

COUNT_COLUMNS = ["enrolled", "present", "absent", "released"]


def preprocess_nyc_attendance(raw_file: Path = NYC_ATTENDANCE_RAW_FILE) -> pd.DataFrame:
    """Load, clean, and validate NYC_attendance.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing NYC_attendance.csv (nyc_daily_attendance)")
    raw = pd.read_csv(raw_file, dtype=str)
    if raw.isnull().values.any():
        raise ValueError("nyc_daily_attendance: unexpected null value(s) in source file")

    before = len(raw)
    df = raw.rename(columns=RENAME).copy()

    df["school_id"] = df["school_id"].astype("string")
    df["attendance_date"] = pd.to_datetime(df["attendance_date"], format="%Y%m%d").dt.date
    df["school_year"] = df["school_year"].astype("string")
    for column in COUNT_COLUMNS:
        # Source uses "1,670"-style thousands separators on some rows.
        df[column] = df[column].str.replace(",", "", regex=False).astype("int64")

    assert_row_count_preserved(before, len(df), table_name="nyc_daily_attendance")

    for column in COUNT_COLUMNS:
        warn_out_of_range(df, column, 0, 10_000, "nyc_daily_attendance")

    mismatched = df[df["enrolled"] != df["present"] + df["absent"] + df["released"]]
    if not mismatched.empty:
        logger.warning(
            "nyc_daily_attendance: %d row(s) where enrolled != present + absent + released",
            len(mismatched),
        )

    duplicate_keys = df.duplicated(subset=["school_id", "attendance_date"], keep=False)
    if duplicate_keys.any():
        logger.warning(
            "nyc_daily_attendance: %d row(s) share (school_id, attendance_date) with "
            "another row (distinct data, not duplicate transmissions — using a surrogate "
            "primary key, not this pair, for that reason)",
            int(duplicate_keys.sum()),
        )

    logger.info("nyc_daily_attendance: %d rows ready", len(df))
    return df
