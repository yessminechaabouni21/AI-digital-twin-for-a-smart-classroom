"""Stage 1 (only stage): environmental_sensors.csv -> co2_sensor_readings.

Spanish Classroom CO2 sensor dataset. Not the UCI Occupancy Detection
dataset — no shared identifier, never joined, no code here should assume
otherwise. See docs/datasets/spanish-co2-preprocessing-plan.md.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ENVIRONMENTAL_SENSORS_RAW_FILE
from digital_twin.data.preprocessing.validation import (
    assert_unique,
    warn_out_of_range,
)

logger = logging.getLogger(__name__)

KNOWN_SENSOR_IDS = {"CO2_01", "CO2_02", "CO2_03", "CO2_04", "CO2_05", "CO2_06"}

RENAME = {
    "published_at": "recorded_at",
    "temp": "temperature_c",
    "hum": "humidity_pct",
    "co2": "co2_ppm",
    "bat": "battery_pct",
}
SOURCE_COLUMNS = ["sensor_id", "published_at", "temp", "hum", "co2", "bat"]


def _unwrap_double_quoted_lines(raw_file: Path) -> str:
    """Undo the source file's non-standard "whole line double-quoted" framing.

    Every line, including the header, is wrapped in an outer pair of double
    quotes with embedded quotes doubled (`"published_at,""date_time"",..."`),
    which `pandas.read_csv` cannot parse directly. This strips the outer
    quote pair and un-escapes `""` -> `"` per line, a framing fix only — no
    field values are altered.
    """
    fixed_lines: list[str] = []
    with raw_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith('"') and line.endswith('"'):
                line = line[1:-1]
            fixed_lines.append(line.replace('""', '"'))
    return "\n".join(fixed_lines)


def preprocess_environmental_sensors(
    raw_file: Path = ENVIRONMENTAL_SENSORS_RAW_FILE,
) -> pd.DataFrame:
    """Load, clean, and validate environmental_sensors.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing environmental_sensors.csv (co2_sensor_readings)")
    raw = pd.read_csv(io.StringIO(_unwrap_double_quoted_lines(raw_file)))
    if raw.isnull().values.any():
        raise ValueError("co2_sensor_readings: unexpected null value(s) in source file")

    raw["sensor_id"] = raw["sensor_id"].str.strip()

    before = len(raw)
    deduped = raw.drop_duplicates()
    dropped = before - len(deduped)
    if dropped:
        logger.info(
            "co2_sensor_readings: dropped %d fully-duplicate source row(s) "
            "(sensor retransmissions), %d row(s) remain",
            dropped,
            len(deduped),
        )

    df = deduped[SOURCE_COLUMNS].rename(columns=RENAME).copy()
    df["sensor_id"] = df["sensor_id"].astype("string")
    df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
    for column in ["temperature_c", "humidity_pct", "battery_pct"]:
        df[column] = df[column].astype("float64")
    df["co2_ppm"] = df["co2_ppm"].astype("int64")

    assert_unique(df, ["sensor_id", "recorded_at"], "co2_sensor_readings")

    warn_out_of_range(df, "temperature_c", 0, 50, "co2_sensor_readings")
    warn_out_of_range(df, "humidity_pct", 0, 100, "co2_sensor_readings")
    warn_out_of_range(df, "co2_ppm", 300, 5000, "co2_sensor_readings")
    warn_out_of_range(df, "battery_pct", 0, 100, "co2_sensor_readings")

    unknown_sensors = set(df["sensor_id"].unique()) - KNOWN_SENSOR_IDS
    if unknown_sensors:
        logger.warning(
            "co2_sensor_readings: %d sensor_id value(s) not previously observed: %s",
            len(unknown_sensors),
            sorted(unknown_sensors),
        )

    logger.info("co2_sensor_readings: %d rows ready", len(df))
    return df
