"""Calibrates BKT parameters from real ASSISTments data and compares against the fixed defaults.

Fetches a deterministic sample of ASSISTments students, splits them
train/test at the student level (no leakage), fits P(L0)/P(T)/P(S)/P(G) via
EM on the train split only (`analytics.bkt_calibration.fit_bkt_em`), then
scores both the fitted and the fixed-parameter (0.3, 0.2, 0.1, 0.25) BKT on
the held-out test split with response log-loss/accuracy. Prints both so the
better-performing parameterization can be kept — calibration is not assumed
to win.

Run as: python -m scripts.calibrate_bkt
"""

from __future__ import annotations

import random

from digital_twin.analytics.bkt_calibration import (
    BktEvaluationResult,
    BktParameters,
    evaluate_bkt_identified,
    evaluate_constant_probability_baseline,
    evaluate_persistence_baseline,
    fit_bkt_em,
    fit_empirical_rate,
    flatten_sequences,
    split_student_ids,
)
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_attempt_sequences,
    fetch_assistments_student_ids,
)

SAMPLE_SIZE = 2000
RANDOM_STATE = 42
N_EM_ITERATIONS = 20

# The strategy's current, pre-calibration defaults — the comparison
# baseline this script evaluates the fitted parameters against.
FIXED_PARAMETERS = BktParameters(prior_mastery=0.3, p_transit=0.2, p_slip=0.1, p_guess=0.25)

# The strategy's current shipped defaults (see `BayesianKnowledgeTracingStrategy`'s
# own docstring) — what decision support actually predicts with today. Evaluated
# here purely as a read-only comparison point; this script never writes back to
# `update_strategies.py`.
CURRENT_PRODUCTION_PARAMETERS = BktParameters(
    prior_mastery=0.5639, p_transit=0.0274, p_slip=0.1870, p_guess=0.3521
)


def _print_result(label: str, result: BktEvaluationResult) -> None:
    print(f"\n--- {label} ---")
    print(f"n_sequences:   {result.n_sequences}")
    print(f"n_predictions: {result.n_predictions}")
    if result.n_students is not None:
        print(f"n_students:    {result.n_students}")
    if result.n_skills is not None:
        print(f"n_skills:      {result.n_skills}")
    print(f"log_loss:      {result.log_loss:.4f}")
    print(f"rmse:          {result.rmse:.4f}")
    print(f"brier_score:   {result.brier_score:.4f}")
    print(f"accuracy:      {result.accuracy:.4f}")
    print(f"auc:           {result.auc:.4f}" if result.auc is not None else "auc:           n/a")


def main() -> None:
    configure_logging()
    engine = get_engine()

    all_student_ids = fetch_assistments_student_ids(engine)
    sampled = random.Random(RANDOM_STATE).sample(
        all_student_ids, k=min(SAMPLE_SIZE, len(all_student_ids))
    )
    train_ids, test_ids = split_student_ids(sampled, random_state=RANDOM_STATE)
    print(
        f"Population: {len(all_student_ids)} students; sampled {len(sampled)} "
        f"-> train {len(train_ids)}, test {len(test_ids)}"
    )

    sequences_by_student = fetch_assistments_attempt_sequences(engine, sampled)
    train_by_student = {
        sid: sequences_by_student[sid] for sid in train_ids if sid in sequences_by_student
    }
    test_by_student = {
        sid: sequences_by_student[sid] for sid in test_ids if sid in sequences_by_student
    }
    train_sequences = flatten_sequences(train_by_student)
    test_sequences = flatten_sequences(test_by_student)
    print(f"(student, topic) sequences: train {len(train_sequences)}, test {len(test_sequences)}")

    fitted = fit_bkt_em(train_sequences, n_iter=N_EM_ITERATIONS)
    empirical_rate = fit_empirical_rate(train_sequences)
    print(f"\nFitted parameters after {N_EM_ITERATIONS} EM iterations: {fitted}")
    print(f"Fixed-default (literature) parameters: {FIXED_PARAMETERS}")
    print(f"Current production parameters: {CURRENT_PRODUCTION_PARAMETERS}")
    print(f"Empirical correctness rate (train): {empirical_rate:.4f}")

    print("\n=== Held-out test evaluation: one-step-ahead P(correct), pre-update ===")
    for label, params in (
        ("literature-default", FIXED_PARAMETERS),
        ("current-production", CURRENT_PRODUCTION_PARAMETERS),
        ("freshly-fitted", fitted),
    ):
        _print_result(f"BKT ({label})", evaluate_bkt_identified(params, test_by_student))

    _print_result(
        "baseline: empirical correctness rate",
        evaluate_constant_probability_baseline(empirical_rate, test_sequences),
    )
    _print_result(
        "baseline: persistence (predict previous outcome)",
        evaluate_persistence_baseline(test_sequences, first_attempt_probability=empirical_rate),
    )


if __name__ == "__main__":
    main()
