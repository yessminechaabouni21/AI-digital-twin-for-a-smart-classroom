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
    BktParameters,
    evaluate_bkt,
    fit_bkt_em,
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
    train_sequences = flatten_sequences(
        {sid: sequences_by_student[sid] for sid in train_ids if sid in sequences_by_student}
    )
    test_sequences = flatten_sequences(
        {sid: sequences_by_student[sid] for sid in test_ids if sid in sequences_by_student}
    )
    print(f"(student, topic) sequences: train {len(train_sequences)}, test {len(test_sequences)}")

    fitted = fit_bkt_em(train_sequences, n_iter=N_EM_ITERATIONS)
    print(f"\nFitted parameters after {N_EM_ITERATIONS} EM iterations: {fitted}")
    print(f"Fixed-default parameters: {FIXED_PARAMETERS}")

    print("\n=== Held-out test evaluation ===")
    for label, params in (("fixed-default", FIXED_PARAMETERS), ("fitted", fitted)):
        result = evaluate_bkt(params, test_sequences)
        print(f"\n--- {label} ---")
        print(f"n_sequences:   {result.n_sequences}")
        print(f"n_predictions: {result.n_predictions}")
        print(f"log_loss:      {result.log_loss:.4f}")
        print(f"accuracy:      {result.accuracy:.4f}")


if __name__ == "__main__":
    main()
