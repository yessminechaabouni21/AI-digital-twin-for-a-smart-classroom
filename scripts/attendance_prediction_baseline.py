"""Runs the NYC DOE school-day attendance-risk baseline end-to-end.

Fetches the school-day snapshot from Postgres (10 trailing school days of
absence-rate history required per row, target = that day's own absence rate
exceeding 10%), trains the logistic-regression baseline, and prints
train/val/test metrics. Diagnostic/experiment script, not a persisted
pipeline.

Run as: python -m scripts.attendance_prediction_baseline
"""

from __future__ import annotations

from digital_twin.analytics.attendance_prediction import (
    split_features_and_target,
    train_baseline_model,
)
from digital_twin.analytics.predictive import (
    ClassificationMetrics,
    evaluate_model,
    train_val_test_split,
)
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.nyc_attendance_features import fetch_nyc_attendance_snapshot


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
    snapshot = fetch_nyc_attendance_snapshot(engine)
    print(f"Snapshot: {snapshot.shape[0]} school-days, {snapshot.shape[1]} columns")

    x, y = split_features_and_target(snapshot)
    x_train, x_val, x_test, y_train, y_val, y_test = train_val_test_split(x, y)
    print(f"Train: {len(x_train)}  Val: {len(x_val)}  Test: {len(x_test)}")

    model = train_baseline_model(x_train, y_train)

    print("\n=== Logistic Regression (attendance-risk baseline) ===")
    for split_name, split_x, split_y in (
        ("train", x_train, y_train),
        ("validation", x_val, y_val),
        ("test", x_test, y_test),
    ):
        metrics = evaluate_model(model, split_x, split_y)
        _print_metrics(split_name, metrics)


if __name__ == "__main__":
    main()
