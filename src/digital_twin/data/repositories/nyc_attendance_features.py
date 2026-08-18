"""Fetches a school-day-level NYC DOE attendance snapshot for absence-risk modeling.

The only place this feature-engineering pipeline touches SQLAlchemy/Postgres
directly (CLAUDE.md: only data/db/ and data/repositories/ talk to the
database) — `analytics/attendance_prediction.py` consumes the plain pandas
DataFrame this returns and never imports SQLAlchemy itself.

`nyc_daily_attendance` is a school-level daily count table (enrolled/present/
absent/released per school per day), not a per-student attendance log — OULAD/
xAPI/ASSISTments have no shared identifier with it either, so there is no
student-level attendance record anywhere in this project's data. The
prediction target here is therefore whether a *school* will have an elevated
absence rate on a given day, built from that school's own attendance history
strictly before that day — not an individual student's future absence.

One row per `(school_id, attendance_date)` with at least 10 prior recorded
school days for that school (the trailing window size below) — rows without
that much history are dropped rather than feature-padded, so no row's
features are computed from fewer than 10 real prior observations.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text

DEFAULT_ROLLING_WINDOW = 10
DEFAULT_HIGH_ABSENCE_THRESHOLD = 0.10

_QUERY = text("""
    WITH ordered AS (
        SELECT
            school_id,
            attendance_date,
            school_year,
            absent::float / enrolled AS absence_rate,
            ROW_NUMBER() OVER (PARTITION BY school_id ORDER BY attendance_date) AS day_rank
        FROM nyc_daily_attendance
        WHERE enrolled > 0
    ),
    features AS (
        SELECT
            school_id,
            attendance_date,
            school_year,
            day_rank,
            EXTRACT(DOW FROM attendance_date)::int AS day_of_week,
            EXTRACT(MONTH FROM attendance_date)::int AS month,
            LAG(absence_rate, 1) OVER w AS absence_rate_lag1,
            AVG(absence_rate) OVER (
                PARTITION BY school_id ORDER BY attendance_date
                ROWS BETWEEN :window_size PRECEDING AND 1 PRECEDING
            ) AS absence_rate_rolling_mean,
            STDDEV_SAMP(absence_rate) OVER (
                PARTITION BY school_id ORDER BY attendance_date
                ROWS BETWEEN :window_size PRECEDING AND 1 PRECEDING
            ) AS absence_rate_rolling_std,
            CASE WHEN absence_rate > :high_absence_threshold
                 THEN 1 ELSE 0 END AS is_high_absence_day
        FROM ordered
        WINDOW w AS (PARTITION BY school_id ORDER BY attendance_date)
    )
    SELECT
        school_id,
        attendance_date,
        school_year,
        day_of_week,
        month,
        absence_rate_lag1,
        absence_rate_rolling_mean,
        absence_rate_rolling_std,
        is_high_absence_day
    FROM features
    WHERE day_rank > :window_size
    """)


def fetch_nyc_attendance_snapshot(
    engine: Engine,
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    high_absence_threshold: float = DEFAULT_HIGH_ABSENCE_THRESHOLD,
) -> pd.DataFrame:
    """Return one row per eligible `(school_id, attendance_date)`, features + `is_high_absence_day`.

    `absence_rate_lag1` and `absence_rate_rolling_mean`/`_std` are computed
    only from that school's rows strictly before `attendance_date` (SQL
    `PRECEDING` window frames), so nothing from the target day or later ever
    reaches a feature. `day_of_week`/`month`/`school_year` are calendar facts
    known in advance of the day, not leakage. `is_high_absence_day` is
    derived from that day's own absence rate — that is the label being
    predicted, not a feature.
    """
    return pd.read_sql(
        _QUERY,
        engine,
        params={"window_size": rolling_window, "high_absence_threshold": high_absence_threshold},
    )
