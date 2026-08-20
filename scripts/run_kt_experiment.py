"""Runs the H1-H4 knowledge-tracing experiment on real ASSISTments data.

Reuses the exact same sampled population and outer student-level split
(`SAMPLE_SIZE=2000`, `random_state=42`) that produced the frozen, immutable
baseline numbers in `scripts/calibrate_bkt.py` — so this script's test set is
identical to the one those numbers were computed on, and the reported
literature-default/current-production/empirical-rate/persistence rows below
are read-only constants, never recomputed here.

This script adds the scientifically controlled comparisons: M2 (a
train-fitted BKT whose EM iteration count is selected on a validation split,
never on test), M3 (BKT + leakage-free historical features -> logistic
regression), M4 (the same features -> gradient-boosted trees). Every
model-selection decision uses train-fit/val only; the frozen test split is
scored exactly once per model, at the end.

Run as: python -m scripts.run_kt_experiment
"""

from __future__ import annotations

import random

from digital_twin.analytics.bkt_calibration import (
    BktEvaluationResult,
    predict_correct_probability,
)
from digital_twin.analytics.knowledge_tracing_experiment import (
    ExperimentEvaluationResult,
    bootstrap_log_loss_difference,
    evaluate_m2_bkt_rowwise,
    score_predictions,
    select_and_fit_bkt,
    select_and_fit_gbm,
    select_and_fit_logistic_regression,
    split_train_fit_val_test,
    subset_attempts,
)
from digital_twin.analytics.knowledge_tracing_features import (
    build_feature_rows,
    compute_skill_train_difficulty,
    to_dense_matrix,
)
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_chronological_attempts,
    fetch_assistments_student_ids,
)
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

SAMPLE_SIZE = 2000
RANDOM_STATE = 42

# Frozen, immutable baseline numbers (scripts/calibrate_bkt.py, same
# population/split) — read-only constants. Never recomputed here.
FROZEN_BASELINE = {
    "literature-default BKT": BktEvaluationResult(
        n_predictions=11828,
        n_sequences=0,
        n_students=400,
        n_skills=281,
        log_loss=0.6341,
        brier_score=0.2167,
        rmse=0.4655,
        accuracy=0.6529,
        auc=0.6624,
    ),
    "current-production BKT (historical, test-selected — not a controlled H2 result)": (
        BktEvaluationResult(
            n_predictions=11828,
            n_sequences=0,
            n_students=400,
            n_skills=281,
            log_loss=0.5968,
            brier_score=0.2045,
            rmse=0.4522,
            accuracy=0.6864,
            auc=0.6734,
        )
    ),
    "empirical-rate baseline": BktEvaluationResult(
        n_predictions=11828,
        n_sequences=0,
        n_students=400,
        n_skills=281,
        log_loss=0.6394,
        brier_score=0.2236,
        rmse=0.4728,
        accuracy=0.6633,
        auc=0.5000,
    ),
    "persistence baseline": BktEvaluationResult(
        n_predictions=11828,
        n_sequences=0,
        n_students=400,
        n_skills=281,
        log_loss=5.6257,
        brier_score=0.3078,
        rmse=0.5548,
        accuracy=0.6645,
        auc=0.6387,
    ),
}


def _print_frozen(label: str, result: BktEvaluationResult) -> None:
    print(f"\n--- {label} [FROZEN] ---")
    print(f"n_predictions: {result.n_predictions}")
    print(f"n_students:    {result.n_students}")
    print(f"n_skills:      {result.n_skills}")
    print(f"log_loss:      {result.log_loss:.4f}")
    print(f"rmse:          {result.rmse:.4f}")
    print(f"brier_score:   {result.brier_score:.4f}")
    print(f"accuracy:      {result.accuracy:.4f}")
    print(f"auc:           {result.auc:.4f}" if result.auc is not None else "auc:           n/a")


def _print_result(label: str, result: ExperimentEvaluationResult) -> None:
    print(f"\n--- {label} ---")
    print(f"n_predictions: {result.n_predictions}")
    print(f"n_students:    {result.n_students}")
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
    split = split_train_fit_val_test(sampled, outer_random_state=RANDOM_STATE)
    print(
        f"Population: {len(all_student_ids)} students; sampled {len(sampled)} "
        f"-> train-fit {len(split.train_fit_ids)}, val {len(split.val_ids)}, "
        f"test {len(split.test_ids)}"
    )

    all_attempts = fetch_assistments_chronological_attempts(engine, sampled)
    train_fit_attempts = subset_attempts(all_attempts, split.train_fit_ids)
    val_attempts = subset_attempts(all_attempts, split.val_ids)
    test_attempts = subset_attempts(all_attempts, split.test_ids)
    combined_attempts = subset_attempts(all_attempts, split.train_fit_ids + split.val_ids)

    print("\n=== M2: train-fitted BKT (EM iterations selected on val) ===")
    m2_selection = select_and_fit_bkt(train_fit_attempts, val_attempts)
    print(f"val log_loss by n_iter: {m2_selection.val_log_loss_by_n_iter}")
    print(f"selected n_iter: {m2_selection.selected_n_iter}")
    print(f"final parameters (train-fit+val): {m2_selection.parameters}")

    skill_train_difficulty = compute_skill_train_difficulty(train_fit_attempts)
    bkt_strategy = BayesianKnowledgeTracingStrategy(
        prior_mastery=m2_selection.parameters.prior_mastery,
        p_transit=m2_selection.parameters.p_transit,
        p_slip=m2_selection.parameters.p_slip,
        p_guess=m2_selection.parameters.p_guess,
    )

    train_fit_rows = build_feature_rows(
        train_fit_attempts,
        skill_train_difficulty=skill_train_difficulty,
        bkt_strategy=bkt_strategy,
    )
    val_rows = build_feature_rows(
        val_attempts, skill_train_difficulty=skill_train_difficulty, bkt_strategy=bkt_strategy
    )
    combined_rows = build_feature_rows(
        combined_attempts,
        skill_train_difficulty=skill_train_difficulty,
        bkt_strategy=bkt_strategy,
    )
    test_rows = build_feature_rows(
        test_attempts, skill_train_difficulty=skill_train_difficulty, bkt_strategy=bkt_strategy
    )

    print("\n=== M3: BKT + historical features -> logistic regression ===")
    lr_model, selected_c = select_and_fit_logistic_regression(
        train_fit_rows, val_rows, combined_rows
    )
    print(f"selected C: {selected_c}")

    print("\n=== M4: historical features -> gradient-boosted trees ===")
    gbm_model, selected_config = select_and_fit_gbm(train_fit_rows, val_rows, combined_rows)
    print(f"selected config: {selected_config}")

    print("\n=== Held-out TEST evaluation (scored once, all models) ===")

    for label, result in FROZEN_BASELINE.items():
        _print_frozen(label, result)

    m2_test_result = evaluate_m2_bkt_rowwise(m2_selection.parameters, test_attempts)
    _print_result("M2: train-fitted BKT (val-selected)", m2_test_result)

    m2_test_pred = [
        predict_correct_probability(
            row.bkt_mastery_before, bkt_strategy.p_slip, bkt_strategy.p_guess
        )
        for row in test_rows
    ]

    x_test_lr, _y_test = to_dense_matrix(test_rows, for_model="lr")
    m3_test_pred = lr_model.predict_proba(x_test_lr)[:, 1].tolist()
    m3_test_result = score_predictions(_y_test, m3_test_pred, test_rows)
    _print_result("M3: BKT + historical features (logistic regression)", m3_test_result)

    x_test_gbm, _y_test_gbm = to_dense_matrix(test_rows, for_model="gbm")
    m4_test_pred = gbm_model.predict_proba(x_test_gbm)[:, 1].tolist()
    m4_test_result = score_predictions(_y_test_gbm, m4_test_pred, test_rows)
    _print_result("M4: historical features (gradient-boosted trees)", m4_test_result)

    print("\n=== Student-level bootstrap 95% CI, log-loss difference vs M2 (reference) ===")
    challengers = (
        ("M3 (logistic regression)", m3_test_pred),
        ("M4 (GBM)", m4_test_pred),
    )
    for label, challenger_pred in challengers:
        point, ci_low, ci_high = bootstrap_log_loss_difference(
            test_rows, m2_test_pred, test_rows, challenger_pred
        )
        direction = "better" if point < 0 else "worse"
        print(
            f"{label} vs M2: delta_log_loss={point:+.4f} "
            f"(95% CI [{ci_low:+.4f}, {ci_high:+.4f}]) -> {direction} than M2"
        )


if __name__ == "__main__":
    main()
