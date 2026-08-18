"""Stage 1 (only stage): dropout_prediction/data.csv -> dropout_records.

UCI/Zenodo "Predict students' dropout and academic success" dataset.
Standalone — no shared identifier with OULAD, xAPI, ASSISTments,
co2_sensor_readings, occupancy_readings, or nyc_daily_attendance.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import DROPOUT_PREDICTION_RAW_FILE
from digital_twin.data.preprocessing.validation import (
    assert_allowed_values,
    assert_row_count_preserved,
    warn_out_of_range,
)

logger = logging.getLogger(__name__)

RENAME = {
    "Marital status": "marital_status",
    "Application mode": "application_mode",
    "Application order": "application_order",
    "Course": "course",
    "Daytime/evening attendance\t": "daytime_evening_attendance",
    "Previous qualification": "previous_qualification",
    "Previous qualification (grade)": "previous_qualification_grade",
    "Nacionality": "nationality",
    "Mother's qualification": "mothers_qualification",
    "Father's qualification": "fathers_qualification",
    "Mother's occupation": "mothers_occupation",
    "Father's occupation": "fathers_occupation",
    "Admission grade": "admission_grade",
    "Displaced": "displaced",
    "Educational special needs": "educational_special_needs",
    "Debtor": "debtor",
    "Tuition fees up to date": "tuition_fees_up_to_date",
    "Gender": "gender",
    "Scholarship holder": "scholarship_holder",
    "Age at enrollment": "age_at_enrollment",
    "International": "international",
    "Curricular units 1st sem (credited)": "curricular_units_1st_sem_credited",
    "Curricular units 1st sem (enrolled)": "curricular_units_1st_sem_enrolled",
    "Curricular units 1st sem (evaluations)": "curricular_units_1st_sem_evaluations",
    "Curricular units 1st sem (approved)": "curricular_units_1st_sem_approved",
    "Curricular units 1st sem (grade)": "curricular_units_1st_sem_grade",
    "Curricular units 1st sem (without evaluations)": (
        "curricular_units_1st_sem_without_evaluations"
    ),
    "Curricular units 2nd sem (credited)": "curricular_units_2nd_sem_credited",
    "Curricular units 2nd sem (enrolled)": "curricular_units_2nd_sem_enrolled",
    "Curricular units 2nd sem (evaluations)": "curricular_units_2nd_sem_evaluations",
    "Curricular units 2nd sem (approved)": "curricular_units_2nd_sem_approved",
    "Curricular units 2nd sem (grade)": "curricular_units_2nd_sem_grade",
    "Curricular units 2nd sem (without evaluations)": (
        "curricular_units_2nd_sem_without_evaluations"
    ),
    "Unemployment rate": "unemployment_rate",
    "Inflation rate": "inflation_rate",
    "GDP": "gdp",
    "Target": "target",
}

INTEGER_COLUMNS = [
    "marital_status",
    "application_mode",
    "application_order",
    "course",
    "daytime_evening_attendance",
    "previous_qualification",
    "nationality",
    "mothers_qualification",
    "fathers_qualification",
    "mothers_occupation",
    "fathers_occupation",
    "displaced",
    "educational_special_needs",
    "debtor",
    "tuition_fees_up_to_date",
    "gender",
    "scholarship_holder",
    "age_at_enrollment",
    "international",
    "curricular_units_1st_sem_credited",
    "curricular_units_1st_sem_enrolled",
    "curricular_units_1st_sem_evaluations",
    "curricular_units_1st_sem_approved",
    "curricular_units_1st_sem_without_evaluations",
    "curricular_units_2nd_sem_credited",
    "curricular_units_2nd_sem_enrolled",
    "curricular_units_2nd_sem_evaluations",
    "curricular_units_2nd_sem_approved",
    "curricular_units_2nd_sem_without_evaluations",
]

FLOAT_COLUMNS = [
    "previous_qualification_grade",
    "admission_grade",
    "curricular_units_1st_sem_grade",
    "curricular_units_2nd_sem_grade",
    "unemployment_rate",
    "inflation_rate",
    "gdp",
]

ALLOWED_TARGET_VALUES = {"Graduate", "Dropout", "Enrolled"}
ALLOWED_BINARY_VALUES = {0, 1}
BINARY_COLUMNS = [
    "daytime_evening_attendance",
    "displaced",
    "educational_special_needs",
    "debtor",
    "tuition_fees_up_to_date",
    "gender",
    "scholarship_holder",
    "international",
]


def preprocess_dropout(raw_file: Path = DROPOUT_PREDICTION_RAW_FILE) -> pd.DataFrame:
    """Load, clean, and validate dropout_prediction/data.csv into a DB-ready DataFrame."""
    logger.info("Preprocessing dropout_prediction/data.csv (dropout_records)")
    raw = pd.read_csv(raw_file, sep=";")
    if raw.isnull().values.any():
        raise ValueError("dropout_records: unexpected null value(s) in source file")

    before = len(raw)
    df = raw.rename(columns=RENAME).copy()
    if set(df.columns) != set(RENAME.values()):
        raise ValueError(
            "dropout_records: source columns don't match the expected schema "
            f"(missing {set(RENAME.values()) - set(df.columns)}, "
            f"unexpected {set(df.columns) - set(RENAME.values())})"
        )

    for column in INTEGER_COLUMNS:
        df[column] = df[column].astype("int64")
    for column in FLOAT_COLUMNS:
        df[column] = df[column].astype("float64")
    df["target"] = df["target"].astype("string")

    assert_row_count_preserved(before, len(df), table_name="dropout_records")
    assert_allowed_values(df, "target", ALLOWED_TARGET_VALUES, "dropout_records")
    for column in BINARY_COLUMNS:
        assert_allowed_values(df, column, ALLOWED_BINARY_VALUES, "dropout_records")

    warn_out_of_range(df, "age_at_enrollment", 15, 80, "dropout_records")
    warn_out_of_range(df, "admission_grade", 0, 200, "dropout_records")
    warn_out_of_range(df, "previous_qualification_grade", 0, 200, "dropout_records")
    warn_out_of_range(df, "curricular_units_1st_sem_grade", 0, 20, "dropout_records")
    warn_out_of_range(df, "curricular_units_2nd_sem_grade", 0, 20, "dropout_records")

    logger.info("dropout_records: %d rows ready", len(df))
    return df
