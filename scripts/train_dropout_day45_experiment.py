"""Controlled day-45 cutoff experiment for the OULAD dropout-risk models.

Same methodology as `scripts/train_dropout_baseline.py` (identical feature
set, preprocessing, `train_val_test_split`/`random_state=42`, Logistic
Regression baseline, and the tuned Random Forest config from
`train_random_forest_model`) — the only thing that changes is the cutoff day
passed to `fetch_oulad_dropout_snapshot`, 30 -> 45. That function already
parameterizes every time-filtered aggregate (`assessment_submissions.date_submitted
<= :cutoff_day`, `vle_interactions.date <= :cutoff_day`) and the eligibility
population (`date_unregistration IS NULL OR date_unregistration > :cutoff_day`)
by `cutoff_day`, so passing 45 here recomputes every time-dependent feature
from data available up to day 45 with no code change to the query itself —
no day-30 feature value leaks into this run. `final_result`/`date_unregistration`
remain excluded as features, exactly as in the day-30 baseline (see
docs/datasets/dropout-prediction-feature-design.md); the day-45 population
is independently determined by the same eligibility rule, evaluated at day
45 instead of day 30.

Does not modify or re-run the day-30 baseline — run both scripts and diff
their printed output to compare cutoffs directly, same metrics/format.

Run as: python -m scripts.train_dropout_day45_experiment
"""

from __future__ import annotations

from sklearn.pipeline import Pipeline

from digital_twin.analytics.predictive import (
    ClassificationMetrics,
    evaluate_model,
    split_features_and_target,
    train_baseline_model,
    train_random_forest_model,
    train_val_test_split,
)
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.oulad_dropout_features import fetch_oulad_dropout_snapshot

CUTOFF_DAY = 45


def _print_metrics(split_name: str, metrics: ClassificationMetrics) -> None:
    print(f"\n--- {split_name} ---")
    print(f"class distribution: {metrics.class_distribution}")
    print(f"accuracy:  {metrics.accuracy:.3f}")
    print(f"precision: {metrics.precision:.3f}")
    print(f"recall:    {metrics.recall:.3f}")
    print(f"f1:        {metrics.f1:.3f}")
    print(f"roc_auc:   {metrics.roc_auc:.3f}")
    print(f"confusion matrix (rows=actual, cols=predicted): {metrics.confusion_matrix}")


def main() -> None:
    configure_logging()

    engine = get_engine()
    snapshot = fetch_oulad_dropout_snapshot(engine, cutoff_day=CUTOFF_DAY)
    print(f"Cutoff day: {CUTOFF_DAY}")
    print(f"Snapshot: {snapshot.shape[0]} enrollments, {snapshot.shape[1]} columns")

    x, y = split_features_and_target(snapshot)
    x_train, x_val, x_test, y_train, y_val, y_test = train_val_test_split(x, y)
    print(f"Train: {len(x_train)}  Val: {len(x_val)}  Test: {len(x_test)}")

    models: dict[str, Pipeline] = {
        "Logistic Regression (baseline)": train_baseline_model(x_train, y_train),
        "Random Forest": train_random_forest_model(x_train, y_train),
    }

    for model_name, model in models.items():
        print(f"\n=== {model_name} (day-{CUTOFF_DAY} cutoff) ===")
        for split_name, split_x, split_y in (
            ("train", x_train, y_train),
            ("validation", x_val, y_val),
            ("test", x_test, y_test),
        ):
            metrics = evaluate_model(model, split_x, split_y)
            _print_metrics(split_name, metrics)


if __name__ == "__main__":
    main()
