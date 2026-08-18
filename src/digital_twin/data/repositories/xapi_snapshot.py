"""Fetches the full xAPI-Edu-Data student-record table for absence-risk modeling.

The only place this pipeline touches SQLAlchemy/Postgres (CLAUDE.md: only
data/db/ and data/repositories/ talk to the database) —
`analytics/xapi_absence_risk.py` consumes the plain pandas DataFrame this
returns and never imports SQLAlchemy itself.

Deliberately excludes `gender`/`nationality`/`place_of_birth`/`relation`
and `class_label` from the selected columns — see
`analytics/xapi_absence_risk.py`'s module docstring for why (demographic
attributes are not used as absence-risk predictors here; `class_label` is a
separate, plausibly-correlated outcome variable, not an independent
feature).
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text

_QUERY = text("""
    SELECT record_id, stage_id, grade_id, section_id, topic, semester,
           raised_hands, visited_resources, announcements_view, discussion,
           parent_answering_survey, parent_school_satisfaction, student_absence_days
    FROM xapi_student_records
    ORDER BY record_id
""")


def fetch_xapi_snapshot(engine: Engine) -> pd.DataFrame:
    """Return every real xAPI-Edu-Data student record's engagement/context columns.

    One row per `record_id` — xAPI-Edu-Data's own surrogate key (see
    `data/db/models.py::XapiStudentRecord`'s docstring: no natural key
    exists at this grain). Carries no student identity of any kind.
    """
    return pd.read_sql(_QUERY, engine)


__all__ = ["fetch_xapi_snapshot"]
