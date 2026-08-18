"""Fetches a student-level OULAD snapshot for dropout-risk modeling.

The only place this feature-engineering pipeline touches SQLAlchemy/Postgres
directly (CLAUDE.md: only data/db/ and data/repositories/ talk to the
database) — `analytics/predictive.py` consumes the plain pandas DataFrame
this returns and never imports SQLAlchemy itself.

One row per OULAD enrollment `(code_module, code_presentation, id_student)`,
restricted to enrollments still active past `cutoff_day` and built only from
events dated on or before `cutoff_day` — see
docs/datasets/dropout-prediction-feature-design.md for why this specific
cutoff and population were chosen.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text

DEFAULT_CUTOFF_DAY = 30

_QUERY = text("""
    WITH eligible_enrollments AS (
        SELECT *
        FROM enrollments
        WHERE date_unregistration IS NULL OR date_unregistration > :cutoff_day
    ),
    due_assessments AS (
        SELECT
            code_module,
            code_presentation,
            COUNT(*) AS assessments_due_count
        FROM assessments
        WHERE date <= :cutoff_day
        GROUP BY code_module, code_presentation
    ),
    assessment_features AS (
        SELECT
            sub.id_student,
            asm.code_module,
            asm.code_presentation,
            COUNT(*) AS assessments_submitted_count,
            AVG(sub.score) AS assessments_mean_score
        FROM assessment_submissions sub
        JOIN assessments asm ON sub.id_assessment = asm.id_assessment
        WHERE sub.date_submitted <= :cutoff_day
          AND sub.is_banked = false
        GROUP BY sub.id_student, asm.code_module, asm.code_presentation
    ),
    vle_features AS (
        SELECT
            id_student,
            code_module,
            code_presentation,
            SUM(sum_click) AS vle_total_clicks,
            COUNT(DISTINCT date) AS vle_active_days,
            COUNT(DISTINCT id_site) AS vle_distinct_sites,
            MAX(date) AS vle_last_active_day
        FROM vle_interactions
        WHERE date <= :cutoff_day
        GROUP BY id_student, code_module, code_presentation
    )
    SELECT
        e.code_module,
        e.code_presentation,
        e.id_student,
        e.gender,
        e.highest_education,
        e.imd_band,
        e.age_band,
        e.num_of_prev_attempts,
        e.studied_credits,
        e.disability,
        e.date_registration,
        COALESCE(af.assessments_submitted_count, 0) AS assessments_submitted_count,
        af.assessments_mean_score,
        COALESCE(da.assessments_due_count, 0) AS assessments_due_count,
        COALESCE(af.assessments_submitted_count, 0)::float
            / NULLIF(da.assessments_due_count, 0) AS assessments_submission_rate,
        COALESCE(vf.vle_total_clicks, 0) AS vle_total_clicks,
        COALESCE(vf.vle_active_days, 0) AS vle_active_days,
        COALESCE(vf.vle_distinct_sites, 0) AS vle_distinct_sites,
        (:cutoff_day - vf.vle_last_active_day) AS vle_days_since_last_click,
        CASE WHEN e.final_result = 'Withdrawn' THEN 1 ELSE 0 END AS is_dropout
    FROM eligible_enrollments e
    LEFT JOIN due_assessments da
        ON da.code_module = e.code_module
       AND da.code_presentation = e.code_presentation
    LEFT JOIN assessment_features af
        ON af.id_student = e.id_student
       AND af.code_module = e.code_module
       AND af.code_presentation = e.code_presentation
    LEFT JOIN vle_features vf
        ON vf.id_student = e.id_student
       AND vf.code_module = e.code_module
       AND vf.code_presentation = e.code_presentation
    """)


def fetch_oulad_dropout_snapshot(
    engine: Engine, cutoff_day: int = DEFAULT_CUTOFF_DAY
) -> pd.DataFrame:
    """Return one row per eligible OULAD enrollment, features + `is_dropout` target.

    "Eligible" excludes enrollments that already withdrew on or before
    `cutoff_day` — predicting an outcome that's already visible at the
    cutoff isn't a prediction task. All engineered features (assessment/VLE
    aggregates) are computed only from events dated on or before
    `cutoff_day`, so nothing after the snapshot point leaks in.
    """
    return pd.read_sql(_QUERY, engine, params={"cutoff_day": cutoff_day})
