"""Real-data demo: room-occupancy classification on UCI Occupancy Detection.

    1. Load every real UCI Occupancy Detection reading
       (`occupancy_readings`, via `fetch_occupancy_readings`), ordered
       chronologically.
    2. Chronological train/(earlier)/test(later) split — see
       `analytics/occupancy_detection.chronological_train_test_split` for
       why a random split would leak temporally-adjacent readings across
       train/test.
    3. Train the logistic-regression baseline on temperature/humidity/CO2/
       light only.
    4. Evaluate on the held-out, chronologically later test split and print
       accuracy/precision/recall/F1/ROC-AUC/confusion matrix.

IMPORTANT — this demo predicts binary **room occupancy** for the single
room this 2015 UCI benchmark deployment monitored. It is NOT a prediction of
any individual student's attendance (this dataset carries no student/class
identity at all), and its output is NEVER attached to a `ClassroomTwin`:
`occupancy_readings` shares no identifier with ASSISTments' `assist_classes`
— see docs/datasets/occupancy-preprocessing-plan.md and
domain/classroom.py's module docstring for the verified absence of that
mapping.

Run as: python -m scripts.occupancy_detection_demo
"""

from __future__ import annotations

from digital_twin.analytics.occupancy_detection import (
    chronological_train_test_split,
    split_features_and_target,
    train_baseline_model,
    transition_event_mask,
)
from digital_twin.analytics.predictive import ClassificationMetrics, evaluate_model
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.occupancy_readings import fetch_occupancy_readings


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

    readings = fetch_occupancy_readings(engine)
    print(f"[1/4] loaded {len(readings)} real UCI Occupancy Detection readings")
    print(
        "      NOTE: this is a single monitored room, not any ASSISTments classroom — "
        "no such mapping exists in the source data. Output is room occupancy, not "
        "individual student attendance."
    )

    train_df, test_df = chronological_train_test_split(readings)
    print(
        f"[2/4] chronological split: train={len(train_df)} "
        f"({train_df['recorded_at'].min()} to {train_df['recorded_at'].max()}), "
        f"test={len(test_df)} ({test_df['recorded_at'].min()} to {test_df['recorded_at'].max()})"
    )

    x_train, y_train = split_features_and_target(train_df)
    x_test, y_test = split_features_and_target(test_df)

    model = train_baseline_model(x_train, y_train)
    print("[3/4] trained logistic-regression baseline on temperature/humidity/CO2/light")

    print("[4/4] evaluation:")
    _print_metrics("train", evaluate_model(model, x_train, y_train))
    _print_metrics("test (chronologically later, held out)", evaluate_model(model, x_test, y_test))

    # Persistence baseline: predict "same as the immediately preceding reading".
    y_test_reset = y_test.reset_index(drop=True)
    y_persistence_pred = y_test_reset.shift(1)
    y_persistence_pred.iloc[0] = y_test_reset.iloc[0]
    persistence_accuracy = (y_persistence_pred == y_test_reset).mean()
    print(
        f"\n--- persistence baseline (predict previous reading), test split ---\n"
        f"accuracy:  {persistence_accuracy:.3f}\n"
        "NOTE: this baseline scores nearly identically to the trained model above on "
        "raw row-level accuracy — readings are ~1 minute apart and occupancy is "
        "strongly autocorrelated, so row-level accuracy alone overstates the "
        "environmental features' independent predictive skill. See the "
        "transition-event evaluation below for a harder, more informative comparison."
    )

    transition_mask = transition_event_mask(y_test_reset)
    n_transitions = int(transition_mask.sum())
    print(f"\n--- transition-event-only evaluation, test split ({n_transitions} events) ---")
    if n_transitions > 0:
        x_test_reset = x_test.reset_index(drop=True)
        _print_metrics(
            "test, transition events only",
            evaluate_model(model, x_test_reset[transition_mask], y_test_reset[transition_mask]),
        )
        transition_persistence_accuracy = (
            y_persistence_pred[transition_mask] == y_test_reset[transition_mask]
        ).mean()
        print(
            f"persistence baseline accuracy on transition events ONLY: "
            f"{transition_persistence_accuracy:.3f} "
            "(guaranteed wrong by construction — included for contrast, not as a "
            "meaningful comparison point)"
        )
    else:
        print("no occupancy transitions in the test split — nothing to evaluate here")


if __name__ == "__main__":
    main()
