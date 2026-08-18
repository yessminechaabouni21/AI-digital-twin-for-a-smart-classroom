"""Stage 7: plogs.csv -> assist_problem_logs.

Largest stage — 20,752,836 raw rows. Read in chunks like OULAD's
studentVle.csv stage, but no aggregation happens here: this is an event
log where every row is a distinct, meaningful attempt, not a fan-out count
to be summed.

`student_id`/`assignment_id` are dropped — verified to always match the
parent alogs row (0 mismatches on the full file; see
docs/datasets/assist-preprocessing-plan.md Stage 7) and reachable via
log_id, the same normalization OULAD applies to AssessmentSubmission.

`problem_id` is checked against `problems` with a warning, not an
assertion: 392 distinct problem_ids referenced here (172,865 rows) have no
matching row in assist_problems, because those problems' pdets row itself
had no problem_id and was dropped in Stage 3. A hard FK would reject real,
verified attempt events over a metadata gap in a different table.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from digital_twin.data.preprocessing.paths import ASSIST_RAW_DIR
from digital_twin.data.preprocessing.validation import (
    assert_foreign_key,
    assert_row_count_preserved,
    warn_foreign_key,
    warn_out_of_range,
)

logger = logging.getLogger(__name__)

LOG_KEY = ["log_id"]
PROBLEM_KEY = ["problem_id"]
USECOLS = [
    "log_id",
    "problem_id",
    "start_time",
    "time_on_task",
    "answer_before_tutoring",
    "fraction_of_hints_used",
    "attempt_count",
    "answer_given",
    "problem_completed",
    "correct",
]
DTYPES = {
    "log_id": "int64",
    "problem_id": "int64",
    "time_on_task": "Float64",
    "answer_before_tutoring": "boolean",
    "fraction_of_hints_used": "Float64",
    "attempt_count": "int64",
    "answer_given": "boolean",
    "problem_completed": "boolean",
    "correct": "boolean",
}
DEFAULT_CHUNK_SIZE = 2_000_000


def preprocess_assist_problem_logs(
    assignment_logs: pd.DataFrame,
    problems: pd.DataFrame,
    raw_dir: Path = ASSIST_RAW_DIR,
    chunksize: int = DEFAULT_CHUNK_SIZE,
) -> pd.DataFrame:
    """Load, clean, and validate plogs.csv into a DB-ready DataFrame.

    `assignment_logs` and `problems` must already be the cleaned Stage 6
    and Stage 3 outputs, needed for foreign key validation.
    """
    logger.info("Preprocessing plogs.csv (chunked, chunksize=%d)", chunksize)
    chunks: list[pd.DataFrame] = []
    total_raw_rows = 0

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            raw_dir / "plogs.csv", usecols=USECOLS, dtype=DTYPES, chunksize=chunksize
        ),
        start=1,
    ):
        chunk["start_time"] = pd.to_datetime(chunk["start_time"], format="ISO8601", utc=True)
        chunks.append(chunk[USECOLS])
        total_raw_rows += len(chunk)
        logger.info("plogs: chunk %d processed (%d raw rows so far)", chunk_number, total_raw_rows)

    df = pd.concat(chunks, ignore_index=True)
    assert_row_count_preserved(total_raw_rows, len(df), table_name="assist_problem_logs")

    warn_out_of_range(df, "attempt_count", 0, float("inf"), "assist_problem_logs")
    warn_out_of_range(df, "time_on_task", 0, float("inf"), "assist_problem_logs")

    assert_foreign_key(
        df,
        assignment_logs,
        LOG_KEY,
        table_name="assist_problem_logs",
        parent_name="assist_assignment_logs",
    )
    warn_foreign_key(
        df, problems, PROBLEM_KEY, table_name="assist_problem_logs", parent_name="assist_problems"
    )

    logger.info("assist_problem_logs: %d rows ready", len(df))
    return df
