"""Integration tests for GET /students/{twin_id} and /students/{twin_id}/state.

Requires a live PostgreSQL instance — skipped automatically if unreachable,
per CLAUDE.md's rule. Persists one real ASSISTments-derived twin via
PostgresStudentTwinRepository before each test that needs it, and cleans up
every row it writes afterward.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete

from digital_twin.data.db.models import Base, StudentKnowledgeState
from digital_twin.data.db.session import get_engine, session_scope
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_problem_attempts,
)
from digital_twin.data.repositories.student_twin_repository import (
    PostgresStudentTwinRepository,
)
from digital_twin.domain.student import Student, derive_student_id
from digital_twin.main import app
from digital_twin.twin_engine.student_twin import StudentTwin
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

ASSISTMENTS_STUDENT_ID = 52964


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
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def cleanup_student_ids(engine: Engine) -> Iterator[list[UUID]]:
    student_ids: list[UUID] = []
    yield student_ids
    with session_scope() as session:
        for student_id in student_ids:
            session.execute(
                delete(StudentKnowledgeState).where(StudentKnowledgeState.student_id == student_id)
            )


@pytest.fixture
def persisted_twin_id(engine: Engine, cleanup_student_ids: list[UUID]) -> UUID:
    """Persist one real ASSISTments-derived StudentTwin's knowledge state and return its twin_id."""
    student_id = derive_student_id("assistments", ASSISTMENTS_STUDENT_ID)
    cleanup_student_ids.append(student_id)

    student = Student(student_id=student_id)
    twin = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())
    attempts = fetch_assistments_problem_attempts(
        engine, ASSISTMENTS_STUDENT_ID, twin_student_id=student_id
    )
    for interaction in attempts:
        twin.apply_interaction(interaction)
    state = twin.current_state()
    assert state.knowledge_states, "expected fixture student to have BKT mastery"

    PostgresStudentTwinRepository().save(state)
    return student_id


def test_get_student_twin_summary_returns_persisted_provenance(
    client: TestClient, persisted_twin_id: UUID
) -> None:
    response = client.get(f"/students/{persisted_twin_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["twin_id"] == str(persisted_twin_id)
    assert body["topics_tracked"] > 0
    assert body["total_observations"] > 0
    assert body["as_of"] is not None


def test_get_student_twin_state_returns_real_knowledge_states(
    client: TestClient, persisted_twin_id: UUID
) -> None:
    response = client.get(f"/students/{persisted_twin_id}/state")

    assert response.status_code == 200
    body = response.json()
    assert body["twin_id"] == str(persisted_twin_id)
    assert len(body["knowledge_states"]) > 0
    for knowledge_state in body["knowledge_states"].values():
        assert 0.0 <= knowledge_state["mastery_probability"] <= 1.0
        assert knowledge_state["observation_count"] >= 0

    # Never persisted by this repository: must never be fabricated on read.
    assert body["engagement"]["total_interactions"] == 0
    assert body["assessment_performance"]["total_results"] == 0
    assert body["dropout_risk"] is None
    assert body["performance_prediction"] is None


def test_get_student_twin_returns_404_for_never_persisted_twin_id(client: TestClient) -> None:
    never_saved_id = uuid4()

    response = client.get(f"/students/{never_saved_id}")

    assert response.status_code == 404
    assert str(never_saved_id) in response.json()["detail"]


def test_get_student_twin_state_returns_404_for_never_persisted_twin_id(
    client: TestClient,
) -> None:
    never_saved_id = uuid4()

    response = client.get(f"/students/{never_saved_id}/state")

    assert response.status_code == 404


def test_get_student_twin_rejects_non_uuid_path_param_with_422(client: TestClient) -> None:
    """A raw ASSISTments/OULAD integer id must never be silently accepted as a twin_id."""
    response = client.get("/students/52964")

    assert response.status_code == 422


def test_get_student_twin_returns_404_after_cleanup_empty_state(
    client: TestClient, engine: Engine, cleanup_student_ids: list[UUID]
) -> None:
    """A twin with no knowledge_states ever saved (StudentTwinRepository.save is a no-op
    for it) is indistinguishable from a twin_id that never existed — both 404."""
    student = Student()
    empty_twin = StudentTwin(student)
    cleanup_student_ids.append(student.student_id)

    PostgresStudentTwinRepository().save(empty_twin.current_state())

    response = client.get(f"/students/{student.student_id}")

    assert response.status_code == 404
