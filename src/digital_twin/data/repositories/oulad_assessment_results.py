"""Fetches one OULAD student's assessment submissions as domain AssessmentResults.

The only place this pipeline touches SQLAlchemy/Postgres (CLAUDE.md: only
data/db/ and data/repositories/ talk to the database) — mirrors
`assistments_problem_attempts.py`'s pattern for a different real dataset.
`StudentTwin`'s assessment-performance summary never imports SQLAlchemy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from sqlalchemy import Engine, text

from digital_twin.domain.assessment import AssessmentResult

# OULAD's date_submitted is a course-relative day offset, not a calendar
# date (see courses.module_presentation_length) — anchored to a fixed,
# arbitrary epoch so AssessmentResult.submitted_at is a valid datetime.
# Only relative ordering/deltas matter downstream (last_assessment_at,
# recent-vs-earlier trend), never the absolute date.
_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

_QUERY = text("""
    SELECT sub.id_assessment, sub.date_submitted, sub.score
    FROM assessment_submissions sub
    JOIN assessments asm ON asm.id_assessment = sub.id_assessment
    WHERE sub.id_student = :id_student
      AND asm.code_module = :code_module
      AND asm.code_presentation = :code_presentation
      AND sub.is_banked = false
      AND sub.score IS NOT NULL
    ORDER BY sub.date_submitted
""")


def fetch_oulad_assessment_results(
    engine: Engine,
    id_student: int,
    code_module: str,
    code_presentation: str,
    *,
    twin_student_id: UUID | None = None,
) -> list[AssessmentResult]:
    """Return one student's AssessmentResults for one course presentation, oldest first.

    Reads `assessment_submissions` joined to `assessments` for one OULAD
    `(id_student, code_module, code_presentation)` triple. Banked scores (a
    previous presentation's carried-over effort — see
    `AssessmentSubmission`'s own docstring) and null scores (ungraded) are
    excluded: neither reflects this presentation's actual performance.

    `id_student` selects and orders rows only; it is never copied into the
    returned AssessmentResults. Each call mints a fresh `twin_student_id`
    (a `uuid4()`) unless the caller supplies one, so an OULAD `id_student`
    is never reused as, or joined onto, a Student Twin's own identity — the
    same separation `fetch_assistments_problem_attempts` applies for
    ASSISTments.

    `assessment_id` is a deterministic `uuid5` of the OULAD `id_assessment`
    (not a person identifier, so deterministic reuse across calls is safe
    and useful — repeated fetches referencing the same OULAD assessment get
    the same `assessment_id`).
    """
    student_id = twin_student_id if twin_student_id is not None else uuid4()

    with engine.connect() as conn:
        rows = conn.execute(
            _QUERY,
            {
                "id_student": id_student,
                "code_module": code_module,
                "code_presentation": code_presentation,
            },
        ).fetchall()

    return [
        AssessmentResult(
            student_id=student_id,
            assessment_id=uuid5(NAMESPACE_DNS, f"oulad-assessment-{id_assessment}"),
            score=score,
            submitted_at=_EPOCH + timedelta(days=date_submitted),
        )
        for id_assessment, date_submitted, score in rows
    ]


__all__ = ["fetch_oulad_assessment_results"]
