"""Filesystem locations for raw dataset files, resolved relative to the repo root."""

from __future__ import annotations

from pathlib import Path

# src/digital_twin/data/preprocessing/paths.py -> repo root is 4 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[4]

OULAD_RAW_DIR = _REPO_ROOT / "data" / "raw" / "oulad"
XAPI_RAW_FILE = _REPO_ROOT / "data" / "raw" / "xAPI-Edu-Data" / "xAPI-Edu-Data.csv"
ASSIST_RAW_DIR = _REPO_ROOT / "data" / "raw" / "2019-2020_school_year"
ENVIRONMENTAL_SENSORS_RAW_FILE = _REPO_ROOT / "data" / "raw" / "environmental_sensors.csv"

OCCUPANCY_RAW_DIR = _REPO_ROOT / "data" / "raw" / "occupancy+detection"
OCCUPANCY_TRAINING_RAW_FILE = OCCUPANCY_RAW_DIR / "datatraining.txt"
OCCUPANCY_TEST_RAW_FILE = OCCUPANCY_RAW_DIR / "datatest.txt"
OCCUPANCY_TEST2_RAW_FILE = OCCUPANCY_RAW_DIR / "datatest2.txt"

NYC_ATTENDANCE_RAW_FILE = _REPO_ROOT / "data" / "raw" / "NYC_attendance.csv"

DROPOUT_PREDICTION_RAW_FILE = _REPO_ROOT / "data" / "raw" / "dropout_prediction" / "data.csv"
