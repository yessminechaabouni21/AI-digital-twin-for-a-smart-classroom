"""Repository for persisting/retrieving Student Twin state.

`StudentTwinRepository` is the stable contract (a `Protocol`) that
twin_engine and future analytics/agent code depend on.
`PostgresStudentTwinRepository` is its one concrete implementation — the
only place in this file that touches SQLAlchemy/Postgres, per CLAUDE.md's
rule that only data/db/ and data/repositories/ may talk to the database.

Persists `KnowledgeState` (BKT mastery) only, into `student_knowledge_states`
(`data/db/models.py::StudentKnowledgeState`) — not `EngagementSummary`,
`AssessmentPerformanceSummary`, `DropoutPrediction`, or
`StudentPerformancePrediction`. Those are either cheap to recompute from
already-persisted raw logs (engagement/assessment) or externally-attached,
point-in-time model outputs never meant to be replayed as if they were
observations (dropout risk/performance prediction) — persisting them here
would duplicate `analytics/` logic inside the persistence layer, which this
repository deliberately does not do. `get()` returns a `StudentTwinState`
with only `knowledge_states`/`total_observations`/`as_of` populated from
real persisted rows; `engagement`/`assessment_performance` come back as
their empty defaults and `dropout_risk`/`performance_prediction` as `None`
— never fabricated, and callers that need the full picture must still
assemble it from the relevant repository/analytics call, same as
`StudentTwin.current_state()` already requires.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from digital_twin.data.db.models import StudentKnowledgeState
from digital_twin.data.db.session import session_scope
from digital_twin.domain.knowledge_state import KnowledgeState
from digital_twin.twin_engine.student_twin import (
    AssessmentPerformanceSummary,
    EngagementSummary,
    StudentTwinState,
)


class StudentTwinRepository(Protocol):
    """Persists and retrieves a StudentTwin's current-state snapshot.

    Deliberately scoped to the derived StudentTwinState snapshot, not the
    full raw Interaction/AssessmentResult history — that history's
    persistence is a separate, dataset-shaped concern (OULAD/ASSISTments
    tables today; a future twin-native event store if one is ever needed),
    not this repository's job.
    """

    def get(self, student_id: UUID) -> StudentTwinState | None:
        """Return the most recently saved state for `student_id`, or None if none exists."""
        ...

    def save(self, state: StudentTwinState) -> None:
        """Persist `state`, replacing any previously saved state for its student_id."""
        ...


class PostgresStudentTwinRepository:
    """Postgres-backed `StudentTwinRepository`: persists only `knowledge_states`.

    Uses the process-global `session_scope()`/`get_engine()` from
    `data/db/session.py`, the same pattern every `data/preprocessing/load_*.py`
    loader already uses — no per-instance engine wiring invented here.
    """

    def get(self, student_id: UUID) -> StudentTwinState | None:
        """Return `student_id`'s persisted knowledge_states, or None if nothing was ever saved.

        `total_observations`/`as_of` are faithfully reconstructed from the
        persisted rows themselves (a plain sum/max, same as
        `StudentTwin.current_state()` computes them) — `engagement`/
        `assessment_performance` are returned as empty defaults and
        `dropout_risk`/`performance_prediction` as `None`, since none of
        those are persisted by this repository (see module docstring).
        """
        with session_scope() as session:
            rows = (
                session.execute(
                    select(StudentKnowledgeState).where(
                        StudentKnowledgeState.student_id == student_id
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return None

            knowledge_states = {
                row.topic_id: KnowledgeState(
                    student_id=student_id,
                    topic_id=row.topic_id,
                    mastery_probability=row.mastery_probability,
                    observation_count=row.observation_count,
                    updated_at=row.updated_at,
                )
                for row in rows
            }

        return StudentTwinState(
            student_id=student_id,
            knowledge_states=knowledge_states,
            engagement=EngagementSummary(),
            assessment_performance=AssessmentPerformanceSummary(),
            dropout_risk=None,
            performance_prediction=None,
            total_observations=sum(ks.observation_count for ks in knowledge_states.values()),
            as_of=max(ks.updated_at for ks in knowledge_states.values()),
        )

    def save(self, state: StudentTwinState) -> None:
        """Upsert one row per `state.knowledge_states` entry, keyed on `(student_id, topic_id)`.

        A no-op for a student with no knowledge_states yet (nothing to
        write) — `get()` then correctly returns `None` for that student_id,
        exactly as if nothing had ever been saved. Topics already persisted
        for this student but absent from `state.knowledge_states` are left
        untouched: `StudentTwin.knowledge_states` only ever accumulates
        topics, never drops one, so this never needs to happen in practice,
        but this method makes no delete call regardless — it upserts what
        it's given, nothing more.
        """
        if not state.knowledge_states:
            return

        with session_scope() as session:
            for topic_id, knowledge_state in state.knowledge_states.items():
                insert_stmt = pg_insert(StudentKnowledgeState).values(
                    student_id=state.student_id,
                    topic_id=topic_id,
                    mastery_probability=knowledge_state.mastery_probability,
                    observation_count=knowledge_state.observation_count,
                    updated_at=knowledge_state.updated_at,
                )
                upsert_stmt = insert_stmt.on_conflict_do_update(
                    index_elements=[
                        StudentKnowledgeState.student_id,
                        StudentKnowledgeState.topic_id,
                    ],
                    set_={
                        "mastery_probability": insert_stmt.excluded.mastery_probability,
                        "observation_count": insert_stmt.excluded.observation_count,
                        "updated_at": insert_stmt.excluded.updated_at,
                    },
                )
                session.execute(upsert_stmt)


__all__ = ["PostgresStudentTwinRepository", "StudentTwinRepository"]
