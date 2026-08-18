"""Tests for StudentTwin: routing interactions to per-topic KnowledgeState."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from digital_twin.domain.interaction import Interaction, InteractionType
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _attempt(student_id: UUID, topic_id: str, outcome: bool) -> Interaction:
    return Interaction(
        student_id=student_id,
        occurred_at=NOW,
        interaction_type=InteractionType.PROBLEM_ATTEMPT,
        topic_id=topic_id,
        outcome=outcome,
    )


def test_correct_attempt_increases_mastery() -> None:
    student = Student()
    twin = StudentTwin(student)
    twin.apply_interaction(_attempt(student.student_id, "algebra", outcome=True))
    assert twin.mastery_for("algebra") is not None
    assert twin.mastery_for("algebra") > 0.5


def test_incorrect_attempt_decreases_mastery() -> None:
    student = Student()
    twin = StudentTwin(student)
    twin.apply_interaction(_attempt(student.student_id, "algebra", outcome=False))
    assert twin.mastery_for("algebra") is not None
    assert twin.mastery_for("algebra") < 0.5


def test_mastery_bounded_within_zero_and_one() -> None:
    student = Student()
    twin = StudentTwin(student)
    for _ in range(50):
        twin.apply_interaction(_attempt(student.student_id, "algebra", outcome=True))
    mastery = twin.mastery_for("algebra")
    assert mastery is not None
    assert 0.0 <= mastery <= 1.0

    for _ in range(50):
        twin.apply_interaction(_attempt(student.student_id, "algebra", outcome=False))
    mastery = twin.mastery_for("algebra")
    assert mastery is not None
    assert 0.0 <= mastery <= 1.0


def test_different_topics_maintain_separate_knowledge_states() -> None:
    student = Student()
    twin = StudentTwin(student)

    twin.apply_interaction(_attempt(student.student_id, "algebra", outcome=True))
    twin.apply_interaction(_attempt(student.student_id, "geometry", outcome=False))

    algebra_mastery = twin.mastery_for("algebra")
    geometry_mastery = twin.mastery_for("geometry")
    assert algebra_mastery is not None
    assert geometry_mastery is not None
    assert algebra_mastery > 0.5
    assert geometry_mastery < 0.5
    assert algebra_mastery != geometry_mastery


def test_resource_view_interaction_does_not_update_mastery() -> None:
    student = Student()
    twin = StudentTwin(student)
    result = twin.apply_interaction(
        Interaction(
            student_id=student.student_id,
            occurred_at=NOW,
            interaction_type=InteractionType.RESOURCE_VIEW,
        )
    )
    assert result is None
    assert twin.mastery_for("algebra") is None


def test_apply_interaction_rejects_other_students_interaction() -> None:
    student = Student()
    twin = StudentTwin(student)
    other_student_interaction = _attempt(uuid4(), "algebra", outcome=True)
    with pytest.raises(ValueError, match="does not match"):
        twin.apply_interaction(other_student_interaction)
