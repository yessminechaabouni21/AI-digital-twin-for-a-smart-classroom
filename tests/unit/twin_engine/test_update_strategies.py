"""Tests for the UpdateStrategy implementations: Simple and Bayesian Knowledge Tracing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from digital_twin.domain.interaction import Interaction, InteractionType
from digital_twin.domain.knowledge_state import KnowledgeState
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin
from digital_twin.twin_engine.update_strategies import (
    BayesianKnowledgeTracingStrategy,
    SimpleIncrementalUpdateStrategy,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _attempt(
    student_id: UUID, topic_id: str, outcome: bool, occurred_at: datetime = NOW
) -> Interaction:
    return Interaction(
        student_id=student_id,
        occurred_at=occurred_at,
        interaction_type=InteractionType.PROBLEM_ATTEMPT,
        topic_id=topic_id,
        outcome=outcome,
    )


def test_correct_attempt_increases_mastery() -> None:
    strategy = SimpleIncrementalUpdateStrategy(learning_rate=0.3, initial_mastery=0.5)
    student_id = uuid4()
    updated = strategy.update(None, _attempt(student_id, "8.F.B.5", outcome=True))
    assert updated.mastery_probability > 0.5


def test_incorrect_attempt_decreases_mastery() -> None:
    strategy = SimpleIncrementalUpdateStrategy(learning_rate=0.3, initial_mastery=0.5)
    student_id = uuid4()
    updated = strategy.update(None, _attempt(student_id, "8.F.B.5", outcome=False))
    assert updated.mastery_probability < 0.5


def test_mastery_stays_within_bounds_after_many_correct_attempts() -> None:
    strategy = SimpleIncrementalUpdateStrategy(learning_rate=0.9, initial_mastery=0.5)
    student_id = uuid4()
    state: KnowledgeState | None = None
    for _ in range(20):
        state = strategy.update(state, _attempt(student_id, "8.F.B.5", outcome=True))
    assert state is not None
    assert 0.0 <= state.mastery_probability <= 1.0
    assert state.mastery_probability == pytest.approx(1.0, abs=1e-9)


def test_mastery_stays_within_bounds_after_many_incorrect_attempts() -> None:
    strategy = SimpleIncrementalUpdateStrategy(learning_rate=0.9, initial_mastery=0.5)
    student_id = uuid4()
    state: KnowledgeState | None = None
    for _ in range(20):
        state = strategy.update(state, _attempt(student_id, "8.F.B.5", outcome=False))
    assert state is not None
    assert 0.0 <= state.mastery_probability <= 1.0
    assert state.mastery_probability == pytest.approx(0.0, abs=1e-9)


def test_observation_count_increments() -> None:
    strategy = SimpleIncrementalUpdateStrategy()
    student_id = uuid4()
    first = strategy.update(None, _attempt(student_id, "8.F.B.5", outcome=True))
    assert first.observation_count == 1
    second = strategy.update(first, _attempt(student_id, "8.F.B.5", outcome=True))
    assert second.observation_count == 2


def test_raises_without_topic_id() -> None:
    strategy = SimpleIncrementalUpdateStrategy()
    interaction = Interaction(
        student_id=uuid4(),
        occurred_at=NOW,
        interaction_type=InteractionType.PROBLEM_ATTEMPT,
        outcome=True,
    )
    with pytest.raises(ValueError, match="topic_id"):
        strategy.update(None, interaction)


def test_raises_without_outcome() -> None:
    strategy = SimpleIncrementalUpdateStrategy()
    interaction = Interaction(
        student_id=uuid4(),
        occurred_at=NOW,
        interaction_type=InteractionType.RESOURCE_VIEW,
        topic_id="8.F.B.5",
    )
    with pytest.raises(ValueError, match="outcome"):
        strategy.update(None, interaction)


def test_raises_on_mismatched_previous_state() -> None:
    strategy = SimpleIncrementalUpdateStrategy()
    other_student_state = KnowledgeState(
        student_id=uuid4(),
        topic_id="8.F.B.5",
        mastery_probability=0.5,
        updated_at=NOW,
    )
    with pytest.raises(ValueError, match="does not match"):
        strategy.update(other_student_state, _attempt(uuid4(), "8.F.B.5", outcome=True))


def test_invalid_learning_rate_rejected() -> None:
    with pytest.raises(ValueError, match="learning_rate"):
        SimpleIncrementalUpdateStrategy(learning_rate=0.0)
    with pytest.raises(ValueError, match="learning_rate"):
        SimpleIncrementalUpdateStrategy(learning_rate=1.5)


# --- BayesianKnowledgeTracingStrategy ---


def test_bkt_correct_attempt_increases_mastery() -> None:
    strategy = BayesianKnowledgeTracingStrategy(prior_mastery=0.3)
    student_id = uuid4()
    updated = strategy.update(None, _attempt(student_id, "8.F.B.5", outcome=True))
    assert updated.mastery_probability > 0.3


def test_bkt_incorrect_attempt_decreases_mastery_relative_to_a_correct_one() -> None:
    strategy = BayesianKnowledgeTracingStrategy(prior_mastery=0.5)
    student_id = uuid4()
    after_correct = strategy.update(None, _attempt(student_id, "8.F.B.5", outcome=True))
    after_incorrect = strategy.update(None, _attempt(student_id, "8.F.B.5", outcome=False))
    assert after_incorrect.mastery_probability < after_correct.mastery_probability


def test_bkt_mastery_never_decreases_below_prior_transit_floor() -> None:
    """Even a wrong answer can't push mastery below what pure learning-transit alone gives.

    BKT's transit step (P(L|evidence) + (1-P(L|evidence))*p_transit) always
    adds some probability mass back in, so an all-incorrect run should still
    stay in [0, 1] and never go negative or NaN.
    """
    strategy = BayesianKnowledgeTracingStrategy(prior_mastery=0.5)
    student_id = uuid4()
    state: KnowledgeState | None = None
    for i in range(20):
        state = strategy.update(
            state, _attempt(student_id, "8.F.B.5", outcome=False, occurred_at=NOW + timedelta(i))
        )
    assert state is not None
    assert 0.0 <= state.mastery_probability <= 1.0


def test_bkt_mastery_converges_toward_one_with_many_correct_attempts() -> None:
    strategy = BayesianKnowledgeTracingStrategy(prior_mastery=0.3)
    student_id = uuid4()
    state: KnowledgeState | None = None
    for i in range(20):
        state = strategy.update(
            state, _attempt(student_id, "8.F.B.5", outcome=True, occurred_at=NOW + timedelta(i))
        )
    assert state is not None
    assert 0.0 <= state.mastery_probability <= 1.0
    assert state.mastery_probability > 0.95


def test_bkt_different_topics_maintain_independent_mastery() -> None:
    """The strategy itself is stateless per call — independence is enforced by the
    caller (StudentTwin) tracking one KnowledgeState per topic_id and always
    passing the matching `previous` back in, which this test simulates directly.
    """
    strategy = BayesianKnowledgeTracingStrategy(prior_mastery=0.3)
    student_id = uuid4()

    weak_topic_state = strategy.update(None, _attempt(student_id, "topic-a", outcome=False))
    strong_topic_state = strategy.update(None, _attempt(student_id, "topic-b", outcome=True))

    assert weak_topic_state.topic_id == "topic-a"
    assert strong_topic_state.topic_id == "topic-b"
    assert weak_topic_state.mastery_probability != strong_topic_state.mastery_probability

    # Continuing to update "topic-a" must not touch "topic-b"'s already-computed state.
    weak_topic_state_2 = strategy.update(
        weak_topic_state, _attempt(student_id, "topic-a", outcome=False, occurred_at=NOW)
    )
    assert weak_topic_state_2.mastery_probability != strong_topic_state.mastery_probability
    assert strong_topic_state.observation_count == 1


def test_bkt_processes_out_of_order_events_chronologically_via_student_twin() -> None:
    """StudentTwin.process_events sorts by occurred_at before applying — verify BKT
    sees the same final mastery regardless of the order interactions are passed in.
    """
    student = Student()
    events_in_order = [
        _attempt(student.student_id, "8.F.B.5", outcome=True, occurred_at=NOW + timedelta(0)),
        _attempt(student.student_id, "8.F.B.5", outcome=False, occurred_at=NOW + timedelta(1)),
        _attempt(student.student_id, "8.F.B.5", outcome=True, occurred_at=NOW + timedelta(2)),
    ]

    twin_in_order = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())
    twin_in_order.process_events(events_in_order)

    twin_shuffled = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())
    twin_shuffled.process_events(reversed(events_in_order))

    mastery_in_order = twin_in_order.mastery_for("8.F.B.5")
    mastery_shuffled = twin_shuffled.mastery_for("8.F.B.5")
    assert mastery_in_order is not None
    assert mastery_in_order == pytest.approx(mastery_shuffled)


def test_bkt_raises_without_topic_id() -> None:
    strategy = BayesianKnowledgeTracingStrategy()
    interaction = Interaction(
        student_id=uuid4(),
        occurred_at=NOW,
        interaction_type=InteractionType.PROBLEM_ATTEMPT,
        outcome=True,
    )
    with pytest.raises(ValueError, match="topic_id"):
        strategy.update(None, interaction)


def test_bkt_raises_without_outcome() -> None:
    strategy = BayesianKnowledgeTracingStrategy()
    interaction = Interaction(
        student_id=uuid4(),
        occurred_at=NOW,
        interaction_type=InteractionType.RESOURCE_VIEW,
        topic_id="8.F.B.5",
    )
    with pytest.raises(ValueError, match="outcome"):
        strategy.update(None, interaction)


def test_bkt_raises_on_mismatched_previous_state() -> None:
    strategy = BayesianKnowledgeTracingStrategy()
    other_student_state = KnowledgeState(
        student_id=uuid4(),
        topic_id="8.F.B.5",
        mastery_probability=0.5,
        updated_at=NOW,
    )
    with pytest.raises(ValueError, match="does not match"):
        strategy.update(other_student_state, _attempt(uuid4(), "8.F.B.5", outcome=True))


def test_bkt_invalid_parameters_rejected() -> None:
    with pytest.raises(ValueError, match="prior_mastery"):
        BayesianKnowledgeTracingStrategy(prior_mastery=1.5)
    with pytest.raises(ValueError, match="p_transit"):
        BayesianKnowledgeTracingStrategy(p_transit=-0.1)
    with pytest.raises(ValueError, match="p_slip"):
        BayesianKnowledgeTracingStrategy(p_slip=0.0)
    with pytest.raises(ValueError, match="p_guess"):
        BayesianKnowledgeTracingStrategy(p_guess=1.0)


def test_bkt_default_parameters_are_the_calibrated_ones_not_literature_defaults() -> None:
    """Defaults must come from analytics.bkt_calibration's EM fit on ASSISTments data
    (see scripts/calibrate_bkt.py), not the original 0.3/0.2/0.1/0.25 literature values —
    this pins the values documented in the class docstring against silent drift.
    """
    strategy = BayesianKnowledgeTracingStrategy()

    assert strategy.prior_mastery == pytest.approx(0.5639)
    assert strategy.p_transit == pytest.approx(0.0274)
    assert strategy.p_slip == pytest.approx(0.1870)
    assert strategy.p_guess == pytest.approx(0.3521)

    literature_defaults = (0.3, 0.2, 0.1, 0.25)
    assert (
        strategy.prior_mastery,
        strategy.p_transit,
        strategy.p_slip,
        strategy.p_guess,
    ) != literature_defaults
