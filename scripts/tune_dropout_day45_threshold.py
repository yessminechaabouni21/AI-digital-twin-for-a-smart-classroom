"""Tune the day-45 Random Forest's decision threshold for early-warning recall.

Same feature set, `train_val_test_split`/`random_state=42`, and
`train_random_forest_model` config as `scripts/train_dropout_day45_experiment.py`
— no retraining, no redesign. Only the decision threshold applied to
`predict_proba` changes.

Threshold selection uses the validation set only: candidate thresholds in
[0.20, 0.50] are scored, and the one with the best recall improvement over
the 0.5 baseline while keeping precision/F1 reasonably close to that
baseline is frozen. The test set is touched exactly once, after the
threshold is frozen, to report the final comparison.

Run as: python -m scripts.tune_dropout_day45_threshold
"""

from __future__ import annotations

from digital_twin.analytics.predictive import (
    ClassificationMetrics,
    evaluate_model,
    split_features_and_target,
    train_random_forest_model,
    train_val_test_split,
)
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.oulad_dropout_features import fetch_oulad_dropout_snapshot

CUTOFF_DAY = 45
BASELINE_THRESHOLD = 0.5
CANDIDATE_THRESHOLDS = [round(0.20 + 0.01 * step, 2) for step in range(31)]

# Precision/F1 must stay within this fraction of the 0.5-threshold
# validation baseline for a candidate threshold to be considered — "reasonably
# better" is interpreted as "recall improves without precision/F1 collapsing".
MAX_METRIC_REGRESSION = 0.10


def _print_metrics(label: str, metrics: ClassificationMetrics) -> None:
    print(f"\n--- {label} ---")
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

    model = train_random_forest_model(x_train, y_train)

    val_baseline = evaluate_model(model, x_val, y_val, threshold=BASELINE_THRESHOLD)
    _print_metrics(f"validation @ threshold={BASELINE_THRESHOLD:.2f} (baseline)", val_baseline)

    print("\n=== Validation threshold sweep ===")
    print(f"{'threshold':>9} {'precision':>10} {'recall':>8} {'f1':>6} {'roc_auc':>8}")
    sweep: list[tuple[float, ClassificationMetrics]] = []
    for threshold in CANDIDATE_THRESHOLDS:
        metrics = evaluate_model(model, x_val, y_val, threshold=float(threshold))
        sweep.append((float(threshold), metrics))
        print(
            f"{threshold:9.2f} {metrics.precision:10.3f} {metrics.recall:8.3f} "
            f"{metrics.f1:6.3f} {metrics.roc_auc:8.3f}"
        )

    min_precision = val_baseline.precision * (1 - MAX_METRIC_REGRESSION)
    min_f1 = val_baseline.f1 * (1 - MAX_METRIC_REGRESSION)
    eligible = [
        (threshold, metrics)
        for threshold, metrics in sweep
        if metrics.recall > val_baseline.recall
        and metrics.precision >= min_precision
        and metrics.f1 >= min_f1
    ]
    if not eligible:
        raise RuntimeError(
            "no candidate threshold improved recall while keeping precision/f1 "
            f"within {MAX_METRIC_REGRESSION:.0%} of the 0.5 baseline"
        )
    selected_threshold, selected_val_metrics = max(eligible, key=lambda item: item[1].recall)

    print(
        f"\nSelected threshold: {selected_threshold:.2f} "
        f"(validation recall {val_baseline.recall:.3f} -> {selected_val_metrics.recall:.3f}, "
        f"precision {val_baseline.precision:.3f} -> {selected_val_metrics.precision:.3f}, "
        f"f1 {val_baseline.f1:.3f} -> {selected_val_metrics.f1:.3f})"
    )

    print("\n=== Frozen threshold — single test-set evaluation ===")
    test_baseline = evaluate_model(model, x_test, y_test, threshold=BASELINE_THRESHOLD)
    _print_metrics(f"test @ threshold={BASELINE_THRESHOLD:.2f} (current)", test_baseline)

    test_selected = evaluate_model(model, x_test, y_test, threshold=selected_threshold)
    _print_metrics(f"test @ threshold={selected_threshold:.2f} (selected)", test_selected)


if __name__ == "__main__":
    main()
