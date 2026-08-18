"""Integration test: PostgresStudentTwinRepository round-trips real BKT-derived twin state.

Requires a live PostgreSQL instance — skipped automatically if unreachable,
per CLAUDE.md's rule that integration tests must be skippable without DB
access. Creates `student_knowledge_states` on first use (`Base.metadata.create_all`,
the same idempotent pattern every `data/preprocessing/load_*.py` loader
already uses) and cleans up every row it writes, so repeated runs never
accumulate test data in a real database.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete, func, select

from digital_twin.data.db.models import Base, StudentKnowledgeState
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_problem_attempts,
)
from digital_twin.data.repositories.student_twin_repository import (
    PostgresStudentTwinRepository,
)
from digital_twin.domain.classroom import Classroom
from digital_twin.domain.student import Student, derive_student_id
from digital_twin.twin_engine.classroom_twin import ClassroomTwin
from digital_twin.twin_engine.student_twin import StudentTwin
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

ASSISTMENTS_STUDENT_ID_1 = 52964
ASSISTMENTS_STUDENT_ID_2 = 90766


@pytest.fixture
def engine() -> Engine:
    db_engine = get_engine()
    try:
        with db_engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable, skipping integration test: {exc}")
    Base.metadata.create_all(db_engine)
    return db_engine


@pytest.fixture
def repository(engine: Engine) -> PostgresStudentTwinRepository:
    return PostgresStudentTwinRepository()


@pytest.fixture
def cleanup_student_ids(engine: Engine) -> Iterator[list[UUID]]:
    """Yield a list the test appends persisted student_ids to; deletes their rows afterward."""
    student_ids: list[UUID] = []
    yield student_ids
    with session_scope() as session:
        for student_id in student_ids:
            session.execute(
                delete(StudentKnowledgeState).where(StudentKnowledgeState.student_id == student_id)
            )


def _real_bkt_twin(engine: Engine, assistments_student_id: int, student_id: UUID) -> StudentTwin:
    student = Student(student_id=student_id)
    twin = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())
    attempts = fetch_assistments_problem_attempts(
        engine, assistments_student_id, twin_student_id=student.student_id
    )
    for interaction in attempts:
        twin.apply_interaction(interaction)
    return twin


def test_get_returns_none_when_nothing_saved(
    repository: PostgresStudentTwinRepository,
) -> None:
    never_saved_id = derive_student_id("assistments", -1)
    assert repository.get(never_saved_id) is None


def test_save_empty_state_is_noop_and_get_still_returns_none(
    repository: PostgresStudentTwinRepository,
    cleanup_student_ids: list[UUID],
) -> None:
    student = Student()
    empty_twin = StudentTwin(student)
    cleanup_student_ids.append(student.student_id)

    repository.save(empty_twin.current_state())

    assert repository.get(student.student_id) is None


def test_save_then_get_round_trip_reconstructs_real_bkt_knowledge_states(
    engine: Engine,
    repository: PostgresStudentTwinRepository,
    cleanup_student_ids: list[UUID],
) -> None:
    student_id = derive_student_id("assistments", ASSISTMENTS_STUDENT_ID_1)
    cleanup_student_ids.append(student_id)

    twin = _real_bkt_twin(engine, ASSISTMENTS_STUDENT_ID_1, student_id)
    original_state = twin.current_state()
    assert original_state.knowledge_states, "expected fixture student to have BKT mastery"

    repository.save(original_state)

    # Reload with no reference to the in-memory twin or ASSISTments data at all.
    reloaded = repository.get(student_id)

    assert reloaded is not None
    assert reloaded.student_id == student_id
    assert set(reloaded.knowledge_states) == set(original_state.knowledge_states)
    for topic_id, original_ks in original_state.knowledge_states.items():
        reloaded_ks = reloaded.knowledge_states[topic_id]
        assert reloaded_ks.mastery_probability == pytest.approx(original_ks.mastery_probability)
        assert reloaded_ks.observation_count == original_ks.observation_count
        assert reloaded_ks.updated_at == original_ks.updated_at
    assert reloaded.total_observations == original_state.total_observations
    assert reloaded.as_of == original_state.as_of

    # Not persisted by this repository — never fabricated on reload.
    assert reloaded.engagement.total_interactions == 0
    assert reloaded.assessment_performance.total_results == 0
    assert reloaded.dropout_risk is None
    assert reloaded.performance_prediction is None


def test_repeated_saves_upsert_latest_state_not_duplicate_rows(
    engine: Engine,
    repository: PostgresStudentTwinRepository,
    cleanup_student_ids: list[UUID],
) -> None:
    student_id = derive_student_id("assistments", ASSISTMENTS_STUDENT_ID_1)
    cleanup_student_ids.append(student_id)

    full_twin = _real_bkt_twin(engine, ASSISTMENTS_STUDENT_ID_1, student_id)
    interactions = list(full_twin.interaction_history)
    midpoint = len(interactions) // 2
    assert 0 < midpoint < len(interactions), "expected fixture student to have multiple attempts"

    strategy = BayesianKnowledgeTracingStrategy()
    incremental_twin = StudentTwin(Student(student_id=student_id), strategy=strategy)
    for interaction in interactions[:midpoint]:
        incremental_twin.apply_interaction(interaction)
    repository.save(incremental_twin.current_state())
    partial_observation_total = incremental_twin.current_state().total_observations

    for interaction in interactions[midpoint:]:
        incremental_twin.apply_interaction(interaction)
    full_state = incremental_twin.current_state()
    repository.save(full_state)

    reloaded = repository.get(student_id)
    assert reloaded is not None
    # The second save's values win — not a merge/accumulation of both saves.
    assert reloaded.total_observations == full_state.total_observations
    assert reloaded.total_observations > partial_observation_total
    for topic_id, full_ks in full_state.knowledge_states.items():
        assert reloaded.knowledge_states[topic_id].observation_count == full_ks.observation_count
        assert reloaded.knowledge_states[topic_id].mastery_probability == pytest.approx(
            full_ks.mastery_probability
        )

    with session_scope() as session:
        row_count = session.execute(
            select(func.count())
            .select_from(StudentKnowledgeState)
            .where(StudentKnowledgeState.student_id == student_id)
        ).scalar_one()
    assert row_count == len(full_state.knowledge_states)


def test_classroom_twin_reconstructable_purely_from_persisted_student_twins(
    engine: Engine,
    repository: PostgresStudentTwinRepository,
    cleanup_student_ids: list[UUID],
) -> None:
    """ClassroomTwin needs no persistence of its own: aggregating persisted
    StudentTwinStates (fetched with zero re-reads of ASSISTments data) reproduces
    the same aggregate a live-data run would produce."""
    student_id_1 = derive_student_id("assistments", ASSISTMENTS_STUDENT_ID_1)
    student_id_2 = derive_student_id("assistments", ASSISTMENTS_STUDENT_ID_2)
    cleanup_student_ids.extend([student_id_1, student_id_2])

    twin_1 = _real_bkt_twin(engine, ASSISTMENTS_STUDENT_ID_1, student_id_1)
    twin_2 = _real_bkt_twin(engine, ASSISTMENTS_STUDENT_ID_2, student_id_2)
    repository.save(twin_1.current_state())
    repository.save(twin_2.current_state())

    reconstructed_classroom_twin = ClassroomTwin(Classroom())
    for student_id in (student_id_1, student_id_2):
        reloaded_state = repository.get(student_id)
        assert reloaded_state is not None
        reconstructed_classroom_twin.attach_student_state(reloaded_state)

    reconstructed = reconstructed_classroom_twin.current_state()

    live_classroom_twin = ClassroomTwin(Classroom())
    live_classroom_twin.attach_student_state(twin_1.current_state())
    live_classroom_twin.attach_student_state(twin_2.current_state())
    live = live_classroom_twin.current_state()

    assert reconstructed.roster_size == live.roster_size == 2
    assert reconstructed.average_mastery_by_topic == pytest.approx(live.average_mastery_by_topic)
    assert reconstructed.topic_observation_counts == live.topic_observation_counts
