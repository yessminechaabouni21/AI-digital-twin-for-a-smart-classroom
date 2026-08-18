"""Fetches one ASSISTments student's chronological problem attempts as Interactions.

The only place this BKT-facing pipeline touches SQLAlchemy/Postgres (CLAUDE.md:
only data/db/ and data/repositories/ talk to the database) — the
`BayesianKnowledgeTracingStrategy` and `StudentTwin` this feeds never import
SQLAlchemy, per the requirement that the update strategy stay independent of
persistence.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import Engine, bindparam, text

from digital_twin.analytics.resource_recommendation import AssistmentsProblemCandidate
from digital_twin.domain.interaction import Interaction, InteractionType

_STUDENT_IDS_QUERY = text("""
    SELECT DISTINCT al.student_id
    FROM assist_problem_logs pl
    JOIN assist_assignment_logs al ON al.log_id = pl.log_id
    JOIN assist_problems p ON p.problem_id = pl.problem_id
    WHERE pl.correct IS NOT NULL AND p.skills IS NOT NULL
    ORDER BY al.student_id
""")

_CLASS_STUDENT_IDS_QUERY = text("""
    SELECT DISTINCT al.student_id
    FROM assist_problem_logs pl
    JOIN assist_assignment_logs al ON al.log_id = pl.log_id
    JOIN assist_problems p ON p.problem_id = pl.problem_id
    JOIN assist_student_classes sc ON sc.student_id = al.student_id
    WHERE pl.correct IS NOT NULL AND p.skills IS NOT NULL AND sc.class_id = :class_id
    ORDER BY al.student_id
""")

_BULK_QUERY = text("""
    SELECT al.student_id, pl.start_time, pl.correct, p.skills
    FROM assist_problem_logs pl
    JOIN assist_assignment_logs al ON al.log_id = pl.log_id
    JOIN assist_problems p ON p.problem_id = pl.problem_id
    WHERE pl.correct IS NOT NULL
      AND p.skills IS NOT NULL
      AND al.student_id IN :student_ids
    ORDER BY al.student_id, pl.start_time
""").bindparams(bindparam("student_ids", expanding=True))

_QUERY = text("""
    SELECT pl.start_time, pl.correct, p.skills
    FROM assist_problem_logs pl
    JOIN assist_assignment_logs al ON al.log_id = pl.log_id
    JOIN assist_problems p ON p.problem_id = pl.problem_id
    WHERE al.student_id = :student_id
      AND pl.correct IS NOT NULL
      AND p.skills IS NOT NULL
    ORDER BY pl.start_time
""")

_PROBLEMS_WITH_SKILLS_QUERY = text("""
    SELECT problem_id, skills, mean_correct, mean_time_on_task, student_answer_count
    FROM assist_problems
    WHERE skills IS NOT NULL AND mean_correct IS NOT NULL
""")


def _first_skill(skills_repr: str) -> str | None:
    """Parse `assist_problems.skills`'s raw Python-list-repr string, e.g. "['8.F.B.5']".

    A problem tagged with multiple skills (a real, if uncommon, case in the
    source data) contributes only its first skill as `topic_id` — the same
    "decomposition is an analytics-layer concern" simplification
    `AssistProblem.skills`'s own docstring already calls out, applied here
    rather than left unaddressed.
    """
    try:
        skills = ast.literal_eval(skills_repr)
    except (ValueError, SyntaxError):
        return None
    if not skills:
        return None
    return str(skills[0])


def _skill_tagged(skills_repr: str, topic_id: str) -> bool:
    """Whether `topic_id` appears anywhere in `assist_problems.skills`'s parsed list.

    Unlike `_first_skill` (which only takes a problem's first skill, for
    the one-`topic_id`-per-Interaction shape BKT needs), problem-catalog
    lookups care about every skill a problem is tagged with — a problem
    tagged `['4.NF.A.1', '6.RP.A.3b']` is a legitimate candidate for either
    skill. Parses with the same `ast.literal_eval` rather than a SQL `LIKE`
    substring match, which would false-positive (e.g. "7.G.B.6" matching
    inside "7.G.B.6-2").
    """
    try:
        skills = ast.literal_eval(skills_repr)
    except (ValueError, SyntaxError):
        return False
    return topic_id in skills


def fetch_assistments_problem_attempts(
    engine: Engine,
    assistments_student_id: int,
    *,
    twin_student_id: UUID | None = None,
) -> list[Interaction]:
    """Return one student's PROBLEM_ATTEMPT Interactions, oldest first.

    Reads `assist_problem_logs` for one ASSISTments `student_id`, joined to
    `assist_assignment_logs` (shared `student_id`, for selecting this
    student's rows) and `assist_problems` (`skills` -> `topic_id`). Rows
    with a null `correct` (no answer given) or null `skills` (untagged, so
    unscoreable) are excluded — there is no topic to trace mastery against.

    `assistments_student_id` selects and orders rows only; it is never
    copied into the returned Interactions. Each call mints a fresh
    `twin_student_id` (a `uuid4()`) unless the caller supplies one, so an
    ASSISTments `student_id` is never reused as, or joined onto, a Student
    Twin's own identity — the same separation `Student.student_id`'s own
    docstring documents (ASSISTments' `student_id` is dataset-scoped and
    reused across a student's own classes, not a real person identifier).
    """
    student_id = twin_student_id if twin_student_id is not None else uuid4()

    with engine.connect() as conn:
        rows = conn.execute(_QUERY, {"student_id": assistments_student_id}).fetchall()

    interactions = []
    for start_time, correct, skills_repr in rows:
        topic_id = _first_skill(skills_repr)
        if topic_id is None:
            continue
        interactions.append(
            Interaction(
                student_id=student_id,
                occurred_at=start_time,
                interaction_type=InteractionType.PROBLEM_ATTEMPT,
                topic_id=topic_id,
                outcome=bool(correct),
            )
        )
    return interactions


def fetch_assistments_student_ids(engine: Engine) -> list[int]:
    """Distinct ASSISTments student_ids with >=1 scoreable, skill-tagged attempt.

    Ordered by student_id (not insertion/DB-internal order), so any
    downstream sample drawn from this list with a fixed random seed is
    reproducible run-to-run. Feeds BKT parameter calibration
    (`analytics/bkt_calibration.py`), never a StudentTwin directly.
    """
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(_STUDENT_IDS_QUERY).fetchall()]


def fetch_assistments_student_ids_for_class(engine: Engine, class_id: int) -> list[int]:
    """Distinct student_ids in one real `assist_classes.class_id` with >=1 scoreable attempt.

    Reuses `fetch_assistments_student_ids`'s eligibility filter (non-null
    `correct`, non-null `skills`), narrowed to one real ASSISTments class via
    `assist_student_classes` — for building a genuine classroom-scoped
    roster (e.g. `scripts/classroom_skill_priority_demo.py`), rather than an
    arbitrary cross-class sample of students.
    """
    with engine.connect() as conn:
        return [
            row[0]
            for row in conn.execute(_CLASS_STUDENT_IDS_QUERY, {"class_id": class_id}).fetchall()
        ]


def fetch_assistments_problems_for_skill(
    engine: Engine, topic_id: str
) -> list[AssistmentsProblemCandidate]:
    """Return every real ASSISTments problem tagged with `topic_id`, with its recorded stats.

    Feeds `analytics/resource_recommendation.py`'s difficulty-band ranking —
    this function only fetches and type-shapes the catalog rows, it does no
    ranking/filtering beyond the `skills`/`mean_correct` non-null conditions
    already applied in `_PROBLEMS_WITH_SKILLS_QUERY`. Rows are matched via
    `_skill_tagged` (full parsed skills-list membership), not a first-skill
    or substring match.
    """
    with engine.connect() as conn:
        rows = conn.execute(_PROBLEMS_WITH_SKILLS_QUERY).fetchall()

    return [
        AssistmentsProblemCandidate(
            problem_id=problem_id,
            mean_correct=mean_correct,
            mean_time_on_task=mean_time_on_task,
            student_answer_count=student_answer_count,
        )
        for problem_id, skills_repr, mean_correct, mean_time_on_task, student_answer_count in rows
        if _skill_tagged(skills_repr, topic_id)
    ]


def fetch_assistments_attempt_sequences(
    engine: Engine, student_ids: Sequence[int]
) -> dict[int, dict[str, list[bool]]]:
    """Return {student_id: {topic_id: [outcome, ...]}}, each outcome list chronological.

    Bulk counterpart to `fetch_assistments_problem_attempts`, for BKT
    parameter calibration/evaluation (`analytics/bkt_calibration.py`) only —
    it deliberately keys results by the raw ASSISTments `student_id`
    instead of minting a Student Twin identity, because this data never
    reaches a StudentTwin; it only estimates the shared BKT parameters a
    StudentTwin's strategy later uses. Rows are ordered by
    `(student_id, start_time)` in SQL, and Python dicts preserve insertion
    order, so each per-topic outcome list stays chronological without a
    separate sort step.
    """
    if not student_ids:
        return {}

    with engine.connect() as conn:
        rows = conn.execute(_BULK_QUERY, {"student_ids": list(student_ids)}).fetchall()

    sequences: dict[int, dict[str, list[bool]]] = {}
    for student_id, _start_time, correct, skills_repr in rows:
        topic_id = _first_skill(skills_repr)
        if topic_id is None:
            continue
        sequences.setdefault(student_id, {}).setdefault(topic_id, []).append(bool(correct))
    return sequences


__all__ = [
    "fetch_assistments_attempt_sequences",
    "fetch_assistments_problem_attempts",
    "fetch_assistments_problems_for_skill",
    "fetch_assistments_student_ids",
    "fetch_assistments_student_ids_for_class",
]
