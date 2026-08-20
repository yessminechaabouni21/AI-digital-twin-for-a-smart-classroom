"""Causality and correctness tests for the H3/H4 experiment's feature engineering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from digital_twin.analytics.knowledge_tracing_features import (
    ChronologicalAttempts,
    build_feature_rows,
    compute_skill_train_difficulty,
    to_dense_matrix,
)
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

_BASE = datetime(2020, 1, 1, tzinfo=UTC)


def _attempts(student_id: int, spec: list[tuple[str, bool]]) -> ChronologicalAttempts:
    return {
        student_id: [
            (_BASE + timedelta(minutes=i), topic, correct)
            for i, (topic, correct) in enumerate(spec)
        ]
    }


def _strategy() -> BayesianKnowledgeTracingStrategy:
    return BayesianKnowledgeTracingStrategy(
        prior_mastery=0.3, p_transit=0.2, p_slip=0.1, p_guess=0.25
    )


def test_feature_row_at_t_is_unchanged_when_future_outcomes_are_perturbed() -> None:
    """Flipping any outcome at index >= i must not change row i's feature vector."""
    base_spec = [("A", True), ("A", False), ("B", True), ("A", True), ("B", False)]
    perturbed_spec = [("A", True), ("A", False), ("B", False), ("A", False), ("B", True)]

    difficulty = {"A": 0.5, "B": 0.5}
    base_rows = build_feature_rows(
        _attempts(1, base_spec), skill_train_difficulty=difficulty, bkt_strategy=_strategy()
    )
    perturbed_rows = build_feature_rows(
        _attempts(1, perturbed_spec), skill_train_difficulty=difficulty, bkt_strategy=_strategy()
    )

    for i in range(2):
        b, p = base_rows[i], perturbed_rows[i]
        assert b.student_total_attempts_before == p.student_total_attempts_before
        assert b.student_total_correct_rate_before == p.student_total_correct_rate_before
        assert b.student_skill_attempts_before == p.student_skill_attempts_before
        assert b.student_skill_correct_rate_before == p.student_skill_correct_rate_before
        assert b.attempts_since_last_seen_skill == p.attempts_since_last_seen_skill
        assert b.bkt_mastery_before == p.bkt_mastery_before


def test_first_attempt_has_no_history() -> None:
    rows = build_feature_rows(
        _attempts(1, [("A", True), ("A", False)]),
        skill_train_difficulty={"A": 0.6},
        bkt_strategy=_strategy(),
    )
    first = rows[0]
    assert first.student_total_attempts_before == 0
    assert first.student_total_correct_rate_before is None
    assert first.student_skill_attempts_before == 0
    assert first.student_skill_correct_rate_before is None
    assert first.attempts_since_last_seen_skill is None
    assert first.has_prior_student_attempt is False
    assert first.has_prior_skill_attempt is False
    assert first.bkt_mastery_before == pytest.approx(0.3)


def test_cumulative_counts_and_rates_update_correctly() -> None:
    spec = [("A", True), ("B", False), ("A", False), ("A", True)]
    rows = build_feature_rows(
        _attempts(1, spec), skill_train_difficulty={"A": 0.5, "B": 0.5}, bkt_strategy=_strategy()
    )

    assert rows[2].student_total_attempts_before == 2
    assert rows[2].student_total_correct_rate_before == pytest.approx(0.5)
    assert rows[2].student_skill_attempts_before == 1
    assert rows[2].student_skill_correct_rate_before == pytest.approx(1.0)
    assert rows[2].attempts_since_last_seen_skill == 2

    assert rows[3].student_total_attempts_before == 3
    assert rows[3].student_total_correct_rate_before == pytest.approx(1 / 3)
    assert rows[3].student_skill_attempts_before == 2
    assert rows[3].student_skill_correct_rate_before == pytest.approx(0.5)
    assert rows[3].attempts_since_last_seen_skill == 1


def test_cross_skill_interleaving_is_preserved_not_bucketed() -> None:
    """A student alternating skills must see the true global attempt index, not per-skill."""
    spec = [("A", True), ("B", True), ("A", True), ("B", True), ("A", True)]
    rows = build_feature_rows(
        _attempts(1, spec), skill_train_difficulty={"A": 0.5, "B": 0.5}, bkt_strategy=_strategy()
    )
    assert [r.student_total_attempts_before for r in rows] == [0, 1, 2, 3, 4]
    assert [r.student_skill_attempts_before for r in rows] == [0, 0, 1, 1, 2]


def test_compute_skill_train_difficulty_pools_only_given_students() -> None:
    train_fit = {
        1: [(_BASE, "A", True), (_BASE + timedelta(minutes=1), "A", False)],
        2: [(_BASE, "A", True)],
    }
    difficulty = compute_skill_train_difficulty(train_fit)
    assert difficulty["A"] == pytest.approx(2 / 3)


def test_skill_train_difficulty_never_influenced_by_val_or_test_students() -> None:
    train_fit = {1: [(_BASE, "A", False), (_BASE, "A", False)]}
    difficulty_train_only = compute_skill_train_difficulty(train_fit)

    with_test_student_mixed_in = {
        1: [(_BASE, "A", False), (_BASE, "A", False)],
        999: [(_BASE, "A", True), (_BASE, "A", True)],
    }
    difficulty_contaminated = compute_skill_train_difficulty(with_test_student_mixed_in)

    assert difficulty_train_only["A"] == pytest.approx(0.0)
    assert difficulty_contaminated["A"] == pytest.approx(0.5)
    assert difficulty_train_only["A"] != difficulty_contaminated["A"]


def test_to_dense_matrix_gbm_leaves_nan_lr_zero_fills_with_indicator() -> None:
    rows = build_feature_rows(
        _attempts(1, [("A", True)]), skill_train_difficulty={"A": 0.5}, bkt_strategy=_strategy()
    )
    gbm_matrix, gbm_labels = to_dense_matrix(rows, for_model="gbm")
    lr_matrix, lr_labels = to_dense_matrix(rows, for_model="lr")

    assert gbm_labels == lr_labels == [1]
    # student_total_correct_rate_before is index 1 in NUMERIC_FEATURE_COLUMNS
    assert gbm_matrix[0][1] != gbm_matrix[0][1]  # NaN != NaN
    assert lr_matrix[0][1] == 0.0


def test_to_dense_matrix_rejects_unknown_model() -> None:
    with pytest.raises(ValueError):
        to_dense_matrix([], for_model="lstm")
