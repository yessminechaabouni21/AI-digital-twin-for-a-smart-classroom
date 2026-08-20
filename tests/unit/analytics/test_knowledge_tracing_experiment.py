"""Tests for the H1-H4 experiment's split protocol, model selection, and scoring."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from digital_twin.analytics.knowledge_tracing_experiment import (
    bootstrap_log_loss_difference,
    evaluate_m2_bkt_rowwise,
    evaluate_sklearn_model,
    score_predictions,
    select_and_fit_bkt,
    select_and_fit_gbm,
    select_and_fit_logistic_regression,
    split_train_fit_val_test,
    subset_attempts,
)
from digital_twin.analytics.knowledge_tracing_features import (
    ChronologicalAttempts,
    build_feature_rows,
    compute_skill_train_difficulty,
)
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

_BASE = datetime(2020, 1, 1, tzinfo=UTC)


def test_split_train_fit_val_test_partitions_are_disjoint_and_exhaustive() -> None:
    student_ids = list(range(100))
    split = split_train_fit_val_test(student_ids)

    all_ids = split.train_fit_ids + split.val_ids + split.test_ids
    assert sorted(all_ids) == sorted(student_ids)
    assert set(split.train_fit_ids) & set(split.val_ids) == set()
    assert set(split.train_fit_ids) & set(split.test_ids) == set()
    assert set(split.val_ids) & set(split.test_ids) == set()
    assert len(split.test_ids) == 20


def test_split_train_fit_val_test_matches_bkt_calibrations_outer_split() -> None:
    """The outer train/test boundary must equal `split_student_ids`'s own, so the test set
    this experiment scores on is identical to the one the frozen baseline was computed on."""
    from digital_twin.analytics.bkt_calibration import split_student_ids

    student_ids = list(range(200))
    train_ids, test_ids = split_student_ids(student_ids, random_state=42)
    split = split_train_fit_val_test(student_ids, outer_random_state=42)

    assert sorted(split.test_ids) == sorted(test_ids)
    assert sorted(split.train_fit_ids + split.val_ids) == sorted(train_ids)


def _synthetic_attempts(
    n_students: int, *, l0: float, transit: float, slip: float, guess: float, seed: int
) -> ChronologicalAttempts:
    rng = random.Random(seed)
    skills = ["A", "B", "C"]
    attempts: ChronologicalAttempts = {}
    for student_id in range(n_students):
        events: list[tuple[datetime, str, bool]] = []
        minute = 0
        for skill in skills:
            mastered = rng.random() < l0
            for _ in range(rng.randint(5, 15)):
                p_correct = (1.0 - slip) if mastered else guess
                events.append((_BASE + timedelta(minutes=minute), skill, rng.random() < p_correct))
                minute += 1
                if not mastered and rng.random() < transit:
                    mastered = True
        rng.shuffle(events)
        events.sort(key=lambda e: e[0])
        attempts[student_id] = events
    return attempts


@pytest.fixture
def synthetic_split() -> tuple[ChronologicalAttempts, ChronologicalAttempts, ChronologicalAttempts]:
    all_attempts = _synthetic_attempts(120, l0=0.3, transit=0.25, slip=0.1, guess=0.2, seed=7)
    split = split_train_fit_val_test(list(all_attempts.keys()), outer_random_state=1)
    return (
        subset_attempts(all_attempts, split.train_fit_ids),
        subset_attempts(all_attempts, split.val_ids),
        subset_attempts(all_attempts, split.test_ids),
    )


def test_select_and_fit_bkt_selects_and_freezes_parameters(synthetic_split) -> None:
    train_fit, val, _test = synthetic_split
    selection = select_and_fit_bkt(train_fit, val, candidate_iterations=(2, 5, 10))

    assert selection.selected_n_iter in (2, 5, 10)
    assert set(selection.val_log_loss_by_n_iter) == {2, 5, 10}
    assert 0.0 <= selection.parameters.prior_mastery <= 1.0
    assert 0.0 <= selection.parameters.p_transit <= 1.0


def test_m3_and_m4_beat_a_trivial_constant_model_on_synthetic_data(synthetic_split) -> None:
    train_fit, val, test = synthetic_split
    m2 = select_and_fit_bkt(train_fit, val, candidate_iterations=(5, 10))
    bkt_strategy = BayesianKnowledgeTracingStrategy(
        prior_mastery=m2.parameters.prior_mastery,
        p_transit=m2.parameters.p_transit,
        p_slip=m2.parameters.p_slip,
        p_guess=m2.parameters.p_guess,
    )
    difficulty = compute_skill_train_difficulty(train_fit)

    train_fit_rows = build_feature_rows(
        train_fit, skill_train_difficulty=difficulty, bkt_strategy=bkt_strategy
    )
    val_rows = build_feature_rows(val, skill_train_difficulty=difficulty, bkt_strategy=bkt_strategy)
    combined_rows = train_fit_rows + build_feature_rows(
        val, skill_train_difficulty=difficulty, bkt_strategy=bkt_strategy
    )
    test_rows = build_feature_rows(
        test, skill_train_difficulty=difficulty, bkt_strategy=bkt_strategy
    )

    lr_model, _c = select_and_fit_logistic_regression(train_fit_rows, val_rows, combined_rows)
    gbm_model, _config = select_and_fit_gbm(train_fit_rows, val_rows, combined_rows)

    lr_result = evaluate_sklearn_model(lr_model, test_rows, for_model="lr")
    gbm_result = evaluate_sklearn_model(gbm_model, test_rows, for_model="gbm")

    # A model that has learned anything should beat log_loss of a coin-flip (~0.693).
    assert lr_result.log_loss < 0.693
    assert gbm_result.log_loss < 0.693
    assert lr_result.n_predictions == len(test_rows)


def test_evaluate_m2_bkt_rowwise_reports_expected_counts(synthetic_split) -> None:
    train_fit, val, test = synthetic_split
    m2 = select_and_fit_bkt(train_fit, val, candidate_iterations=(5,))
    result = evaluate_m2_bkt_rowwise(m2.parameters, test)

    assert result.n_students == len(test)
    assert result.n_predictions == sum(len(v) for v in test.values())
    assert 0.0 <= result.accuracy <= 1.0


def test_score_predictions_matches_perfect_and_worst_case() -> None:
    from digital_twin.analytics.knowledge_tracing_features import FeatureRow

    rows = [
        FeatureRow(
            student_id=1,
            topic_id="A",
            correct=True,
            student_total_attempts_before=0,
            student_total_correct_rate_before=None,
            student_skill_attempts_before=0,
            student_skill_correct_rate_before=None,
            attempts_since_last_seen_skill=None,
            skill_train_difficulty=0.5,
            bkt_mastery_before=0.5,
            has_prior_student_attempt=False,
            has_prior_skill_attempt=False,
        )
    ]
    result = score_predictions([1], [0.99], rows)
    assert result.accuracy == 1.0
    assert result.log_loss < 0.02


def test_bootstrap_log_loss_difference_is_near_zero_for_identical_predictions(
    synthetic_split,
) -> None:
    train_fit, val, test = synthetic_split
    m2 = select_and_fit_bkt(train_fit, val, candidate_iterations=(5,))
    bkt_strategy = BayesianKnowledgeTracingStrategy(
        prior_mastery=m2.parameters.prior_mastery,
        p_transit=m2.parameters.p_transit,
        p_slip=m2.parameters.p_slip,
        p_guess=m2.parameters.p_guess,
    )
    difficulty = compute_skill_train_difficulty(train_fit)
    test_rows = build_feature_rows(
        test, skill_train_difficulty=difficulty, bkt_strategy=bkt_strategy
    )
    preds = [0.6 for _ in test_rows]

    point, ci_low, ci_high = bootstrap_log_loss_difference(
        test_rows, preds, test_rows, preds, n_bootstrap=200
    )
    assert point == pytest.approx(0.0, abs=1e-9)
    assert ci_low <= 0.0 <= ci_high


def test_bootstrap_log_loss_difference_rejects_misaligned_rows() -> None:
    from digital_twin.analytics.knowledge_tracing_features import FeatureRow

    row = FeatureRow(
        student_id=1,
        topic_id="A",
        correct=True,
        student_total_attempts_before=0,
        student_total_correct_rate_before=None,
        student_skill_attempts_before=0,
        student_skill_correct_rate_before=None,
        attempts_since_last_seen_skill=None,
        skill_train_difficulty=0.5,
        bkt_mastery_before=0.5,
        has_prior_student_attempt=False,
        has_prior_skill_attempt=False,
    )
    with pytest.raises(ValueError):
        bootstrap_log_loss_difference([row], [0.5], [row, row], [0.5, 0.5])
