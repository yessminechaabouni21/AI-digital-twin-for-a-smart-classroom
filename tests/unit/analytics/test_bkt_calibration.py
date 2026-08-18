"""Focused tests for BKT parameter fitting (EM) and held-out evaluation."""

from __future__ import annotations

import random

import pytest

from digital_twin.analytics.bkt_calibration import (
    BktParameters,
    evaluate_bkt,
    fit_bkt_em,
    flatten_sequences,
    split_student_ids,
)


def _synthetic_sequences(
    n: int, *, l0: float, transit: float, slip: float, guess: float, seed: int = 0
) -> list[list[bool]]:
    """Generate BKT-consistent sequences from known ground-truth parameters."""
    rng = random.Random(seed)
    sequences = []
    for _ in range(n):
        mastered = rng.random() < l0
        length = rng.randint(3, 12)
        seq = []
        for _ in range(length):
            p_correct = (1.0 - slip) if mastered else guess
            seq.append(rng.random() < p_correct)
            if not mastered and rng.random() < transit:
                mastered = True
        sequences.append(seq)
    return sequences


def test_fit_bkt_em_recovers_known_parameters_from_synthetic_data() -> None:
    """EM should approximately recover ground-truth parameters given enough sequences."""
    sequences = _synthetic_sequences(3000, l0=0.2, transit=0.3, slip=0.1, guess=0.2, seed=1)
    fitted = fit_bkt_em(sequences, n_iter=25)

    assert fitted.prior_mastery == pytest.approx(0.2, abs=0.05)
    assert fitted.p_transit == pytest.approx(0.3, abs=0.08)
    assert fitted.p_slip == pytest.approx(0.1, abs=0.05)
    assert fitted.p_guess == pytest.approx(0.2, abs=0.05)


def test_fit_bkt_em_parameters_stay_within_valid_ranges() -> None:
    sequences = _synthetic_sequences(200, l0=0.5, transit=0.5, slip=0.3, guess=0.4, seed=2)
    fitted = fit_bkt_em(sequences, n_iter=10)

    assert 0.0 <= fitted.prior_mastery <= 1.0
    assert 0.0 <= fitted.p_transit <= 1.0
    assert 0.0 < fitted.p_slip < 1.0
    assert 0.0 < fitted.p_guess < 1.0


def test_fit_bkt_em_raises_on_empty_input() -> None:
    with pytest.raises(ValueError, match="non-empty sequence"):
        fit_bkt_em([])
    with pytest.raises(ValueError, match="non-empty sequence"):
        fit_bkt_em([[]])


def test_evaluate_bkt_reports_valid_metrics() -> None:
    sequences = _synthetic_sequences(100, l0=0.3, transit=0.2, slip=0.1, guess=0.25, seed=3)
    params = BktParameters(prior_mastery=0.3, p_transit=0.2, p_slip=0.1, p_guess=0.25)

    result = evaluate_bkt(params, sequences)

    assert result.n_sequences == len(sequences)
    assert result.n_predictions == sum(len(s) for s in sequences)
    assert result.log_loss > 0.0
    assert 0.0 <= result.accuracy <= 1.0


def test_evaluate_bkt_prefers_correctly_specified_parameters() -> None:
    """A parameter set matching the true generative process should log-loss-beat a bad one."""
    sequences = _synthetic_sequences(1500, l0=0.15, transit=0.4, slip=0.05, guess=0.15, seed=4)

    good_params = BktParameters(prior_mastery=0.15, p_transit=0.4, p_slip=0.05, p_guess=0.15)
    bad_params = BktParameters(prior_mastery=0.9, p_transit=0.01, p_slip=0.4, p_guess=0.4)

    good_result = evaluate_bkt(good_params, sequences)
    bad_result = evaluate_bkt(bad_params, sequences)

    assert good_result.log_loss < bad_result.log_loss


def test_flatten_sequences_keeps_topics_independent_and_drops_empty() -> None:
    sequences_by_student = {
        1: {"topic-a": [True, False], "topic-b": [True]},
        2: {"topic-a": [False, False, True], "topic-c": []},
    }
    flattened = flatten_sequences(sequences_by_student)

    assert [True, False] in flattened
    assert [True] in flattened
    assert [False, False, True] in flattened
    assert [] not in flattened
    assert len(flattened) == 3


def test_split_student_ids_has_no_overlap_and_is_deterministic() -> None:
    student_ids = list(range(100))

    train_a, test_a = split_student_ids(student_ids, random_state=42)
    train_b, test_b = split_student_ids(student_ids, random_state=42)

    assert set(train_a).isdisjoint(set(test_a))
    assert set(train_a) | set(test_a) == set(student_ids)
    assert train_a == train_b
    assert test_a == test_b


def test_split_student_ids_different_seeds_can_differ() -> None:
    student_ids = list(range(100))
    train_a, _ = split_student_ids(student_ids, random_state=42)
    train_b, _ = split_student_ids(student_ids, random_state=7)
    assert train_a != train_b
