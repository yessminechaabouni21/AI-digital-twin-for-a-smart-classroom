"""Fetches one xAPI-Edu-Data student's behavioral engagement counts.

The only place this pipeline touches SQLAlchemy/Postgres (CLAUDE.md: only
data/db/ and data/repositories/ talk to the database). `StudentTwin`'s
engagement summary never imports SQLAlchemy.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from digital_twin.twin_engine.student_twin import XapiEngagementCounts

_QUERY = text("""
    SELECT raised_hands, visited_resources, announcements_view, discussion
    FROM xapi_student_records
    WHERE record_id = :record_id
""")


def fetch_xapi_engagement_counts(engine: Engine, record_id: int) -> XapiEngagementCounts | None:
    """Return one xAPI-Edu-Data student's behavioral counts, or None if `record_id` doesn't exist.

    `record_id` is `XapiStudentRecord`'s DB-generated surrogate key (see its
    own docstring: no natural key exists at this grain) — it only selects
    which row to read. xAPI-Edu-Data has no student-identifying column at
    all and no shared identifier with OULAD/ASSISTments, so there is
    nothing here that could be reused as, or joined onto, a Student Twin's
    identity; the caller decides which twin (if any) these counts get
    attached to via `StudentTwin.attach_xapi_engagement_counts`.
    """
    with engine.connect() as conn:
        row = conn.execute(_QUERY, {"record_id": record_id}).fetchone()
    if row is None:
        return None

    raised_hands, visited_resources, announcements_view, discussion = row
    return XapiEngagementCounts(
        raised_hands=raised_hands,
        visited_resources=visited_resources,
        announcements_view=announcements_view,
        discussion=discussion,
    )


__all__ = ["fetch_xapi_engagement_counts"]
