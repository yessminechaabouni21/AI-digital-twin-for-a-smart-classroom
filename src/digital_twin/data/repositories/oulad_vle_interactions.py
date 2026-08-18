"""Fetches one OULAD student's VLE clickstream as domain Interactions.

The only place this pipeline touches SQLAlchemy/Postgres (CLAUDE.md: only
data/db/ and data/repositories/ talk to the database) — mirrors
`oulad_assessment_results.py`'s pattern for the engagement side of OULAD.
`StudentTwin`'s engagement summary never imports SQLAlchemy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from digital_twin.domain.interaction import Interaction, InteractionType

# OULAD's vle_interactions.date is a course-relative day offset, not a
# calendar date (same convention as oulad_assessment_results.py) — anchored
# to a fixed, arbitrary epoch so Interaction.occurred_at is a valid
# datetime. Only relative ordering/deltas (active days, last_interaction_at,
# recent-vs-earlier trend) matter downstream, never the absolute date.
_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

_QUERY = text("""
    SELECT date, id_site, sum_click
    FROM vle_interactions
    WHERE id_student = :id_student
      AND code_module = :code_module
      AND code_presentation = :code_presentation
    ORDER BY date
""")


def fetch_oulad_vle_interactions(
    engine: Engine,
    id_student: int,
    code_module: str,
    code_presentation: str,
    *,
    twin_student_id: UUID | None = None,
) -> list[Interaction]:
    """Return one student's VLE-click Interactions for one course presentation, oldest first.

    Reads `vle_interactions` for one OULAD `(id_student, code_module,
    code_presentation)` triple. Each row (one student's aggregated click
    count on one VLE site on one day — see `VleInteraction`'s own
    docstring) becomes one RESOURCE_VIEW `Interaction`, matching
    `Interaction.InteractionType`'s own documented convention that
    RESOURCE_VIEW carries no `topic_id`/`outcome` (OULAD has no skill/topic
    concept). The row's `id_site`/`sum_click` are kept in `metadata` rather
    than dropped or invented into a false per-interaction count.

    `id_student` selects and orders rows only; it is never copied into the
    returned Interactions. Each call mints a fresh `twin_student_id` (a
    `uuid4()`) unless the caller supplies one, so an OULAD `id_student` is
    never reused as, or joined onto, a Student Twin's own identity — the
    same separation `fetch_oulad_assessment_results` and
    `fetch_assistments_problem_attempts` apply.
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
        Interaction(
            student_id=student_id,
            occurred_at=_EPOCH + timedelta(days=date),
            interaction_type=InteractionType.RESOURCE_VIEW,
            metadata={"id_site": id_site, "sum_click": sum_click},
        )
        for date, id_site, sum_click in rows
    ]


__all__ = ["fetch_oulad_vle_interactions"]
