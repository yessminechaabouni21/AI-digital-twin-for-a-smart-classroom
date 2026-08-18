"""Fetches a student-level OULAD snapshot for pass/fail performance prediction.

The only place this feature-engineering pipeline touches SQLAlchemy/Postgres
directly (CLAUDE.md: only data/db/ and data/repositories/ talk to the
database) — `analytics/performance_prediction.py` consumes the plain pandas
DataFrame this returns and never imports SQLAlchemy itself.

One row per OULAD enrollment `(code_module, code_presentation, id_student)`
that reached a Pass/Fail/Distinction outcome (Withdrawn excluded — that
outcome is the dropout model's target, not this one), built only from
TMA/CMA assessment submissions and VLE interactions dated on or before
`cutoff_day` — same fixed early-course cutoff approach as
`oulad_dropout_features.fetch_oulad_dropout_snapshot`. The `Exam`
assessment type is deliberately excluded from the feature aggregates at
every cutoff, not just before it: its score is what `final_result` is
largely determined by, so including it (even filtered by date) would leak
the target into the features.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text

DEFAULT_CUTOFF_DAY = 30

_QUERY = text("""
    WITH eligible_enrollments AS (
        SELECT *
        FROM enrollments
        WHERE final_result IN ('Pass', 'Fail', 'Distinction')
    ),
    due_assessments AS (
        SELECT
            code_module,
            code_presentation,
            COUNT(*) AS assessments_due_count
        FROM assessments
        WHERE assessment_type IN ('TMA', 'CMA')
          AND date <= :cutoff_day
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
        WHERE asm.assessment_type IN ('TMA', 'CMA')
          AND sub.date_submitted <= :cutoff_day
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
        CASE WHEN e.final_result IN ('Pass', 'Distinction') THEN 1 ELSE 0 END AS is_pass
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


def fetch_oulad_performance_snapshot(
    engine: Engine, cutoff_day: int = DEFAULT_CUTOFF_DAY
) -> pd.DataFrame:
    """Return one row per eligible OULAD enrollment, features + `is_pass` target.

    "Eligible" excludes Withdrawn enrollments — no Pass/Fail outcome exists
    for them, and that population is already the dropout model's target.
    All engineered features (TMA/CMA assessment and VLE aggregates) are
    computed only from events dated on or before `cutoff_day`, and only from
    non-Exam assessments, so neither post-cutoff data nor the Exam score
    that `final_result` is largely determined by ever leaks into a feature.
    """
    return pd.read_sql(_QUERY, engine, params={"cutoff_day": cutoff_day})
