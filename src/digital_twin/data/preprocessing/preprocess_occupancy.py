"""Stage 1 (only stage): {datatraining,datatest,datatest2}.txt -> occupancy_readings.

UCI Occupancy Detection dataset. Not the Spanish Classroom CO2 dataset — no
shared identifier, never joined. See
docs/datasets/occupancy-preprocessing-plan.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import (
    OCCUPANCY_TEST2_RAW_FILE,
    OCCUPANCY_TEST_RAW_FILE,
    OCCUPANCY_TRAINING_RAW_FILE,
)
from digital_twin.data.preprocessing.validation import (
    assert_allowed_values,
    assert_row_count_preserved,
    assert_unique,
    warn_out_of_range,
)

logger = logging.getLogger(__name__)

SOURCE_FILES: dict[str, Path] = {
    "training": OCCUPANCY_TRAINING_RAW_FILE,
    "test": OCCUPANCY_TEST_RAW_FILE,
    "test2": OCCUPANCY_TEST2_RAW_FILE,
}

RENAME = {
    "date": "recorded_at",
    "Temperature": "temperature_c",
    "Humidity": "humidity_pct",
    "Light": "light_lux",
    "CO2": "co2_ppm",
    "HumidityRatio": "humidity_ratio",
    "Occupancy": "occupancy",
}

ALLOWED_OCCUPANCY_VALUES = {0, 1}


def _load_one_file(source_file: str, raw_file: Path) -> pd.DataFrame:
    raw = pd.read_csv(raw_file, index_col=0)
    if raw.isnull().values.any():
        raise ValueError(f"occupancy_readings: unexpected null value(s) in {raw_file.name}")

    duplicate_rows = int(raw.duplicated().sum())
    if duplicate_rows:
        raise ValueError(
            f"occupancy_readings: {duplicate_rows} unexpected fully-duplicate "
            f"row(s) in {raw_file.name}"
        )

    df = raw.rename(columns=RENAME).copy()
    df["source_file"] = source_file
    df["source_row_id"] = raw.index.astype("int64")
    return df


def preprocess_occupancy(source_files: dict[str, Path] = SOURCE_FILES) -> pd.DataFrame:
    """Load, combine, clean, and validate the three raw files into a DB-ready DataFrame."""
    logger.info("Preprocessing UCI Occupancy Detection files (occupancy_readings)")

    parts = [
        _load_one_file(source_file, raw_file) for source_file, raw_file in source_files.items()
    ]
    expected_total = sum(len(part) for part in parts)

    combined = pd.concat(parts, ignore_index=True)

    df = combined[
        [
            "source_file",
            "recorded_at",
            "source_row_id",
            "temperature_c",
            "humidity_pct",
            "light_lux",
            "co2_ppm",
            "humidity_ratio",
            "occupancy",
        ]
    ].copy()

    df["source_file"] = df["source_file"].astype("string")
    df["recorded_at"] = pd.to_datetime(df["recorded_at"])
    df["source_row_id"] = df["source_row_id"].astype("int64")
    for column in ["temperature_c", "humidity_pct", "light_lux", "co2_ppm", "humidity_ratio"]:
        df[column] = df[column].astype("float64")
    df["occupancy"] = df["occupancy"].astype("int64")

    assert_row_count_preserved(expected_total, len(df), table_name="occupancy_readings")
    assert_unique(df, ["source_file", "recorded_at"], "occupancy_readings")
    assert_allowed_values(df, "occupancy", ALLOWED_OCCUPANCY_VALUES, "occupancy_readings")
    assert_allowed_values(df, "source_file", set(source_files.keys()), "occupancy_readings")

    warn_out_of_range(df, "temperature_c", 0, 50, "occupancy_readings")
    warn_out_of_range(df, "humidity_pct", 0, 100, "occupancy_readings")
    warn_out_of_range(df, "light_lux", 0, 2000, "occupancy_readings")
    warn_out_of_range(df, "co2_ppm", 300, 5000, "occupancy_readings")
    warn_out_of_range(df, "humidity_ratio", 0, 0.03, "occupancy_readings")

    logger.info("occupancy_readings: %d rows ready", len(df))
    return df
