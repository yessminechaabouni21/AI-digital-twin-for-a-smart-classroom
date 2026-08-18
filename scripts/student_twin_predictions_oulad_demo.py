"""Demonstrates: OULAD dropout-risk + performance predictions -> StudentTwin.

Small, mostly-read-only example wiring one real OULAD student's model
predictions into a StudentTwin, then reading back `dropout_risk`/
`performance_prediction` from `StudentTwinState` alongside the assessment-
performance summary from `scripts/assessment_performance_oulad_demo.py`'s
same wiring. Trains both models fresh (same `train_val_test_split`/
`train_random_forest_model` calls the baseline comparison scripts already
use — no new ML logic here), then locates this one student's feature row to
predict from. Not a persisted pipeline.

The demoed student's own row is removed from the snapshot *before* any
split/training happens (`_exclude_student_row`), not just left to chance
in whichever fold a random split assigns it to — otherwise the model could
be fit on this exact student's own label and the "prediction" printed below
would be in-sample, not a genuine held-out estimate.

Run as:
    python -m scripts.student_twin_predictions_oulad_demo [id_student] \\
        [code_module] [code_presentation]
"""

from __future__ import annotations

import sys

import pandas as pd

from digital_twin.analytics import performance_prediction as perf
from digital_twin.analytics import predictive as dropout
from digital_twin.analytics.predictive import train_val_test_split
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.oulad_assessment_results import (
    fetch_oulad_assessment_results,
)
from digital_twin.data.repositories.oulad_dropout_features import fetch_oulad_dropout_snapshot
from digital_twin.data.repositories.oulad_performance_features import (
    fetch_oulad_performance_snapshot,
)
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin

DEFAULT_ID_STUDENT = 441201
DEFAULT_CODE_MODULE = "DDD"
DEFAULT_CODE_PRESENTATION = "2013B"


def _student_row(
    snapshot: pd.DataFrame, id_student: int, code_module: str, code_presentation: str
) -> pd.DataFrame | None:
    """Locate this (id_student, code_module, code_presentation)'s single row, if eligible.

    Returns None rather than raising: a student can be absent from a
    snapshot for a legitimate reason (dropout snapshot excludes nothing by
    outcome; performance snapshot excludes Withdrawn), not a bug — the
    caller decides what "no prediction available" means for that model.
    """
    match = snapshot[
        (snapshot["id_student"] == id_student)
        & (snapshot["code_module"] == code_module)
        & (snapshot["code_presentation"] == code_presentation)
    ]
    return match if not match.empty else None


def _exclude_student_row(
    snapshot: pd.DataFrame, id_student: int, code_module: str, code_presentation: str
) -> pd.DataFrame:
    """Return `snapshot` with this (id_student, code_module, code_presentation)'s row removed.

    Applied before any train/val/test split, not after — the demoed
    student's own label must never be available to fit the model whose
    prediction is then read back for that same student, regardless of
    which split a random train_val_test_split would otherwise assign it to.
    """
    is_this_student = (
        (snapshot["id_student"] == id_student)
        & (snapshot["code_module"] == code_module)
        & (snapshot["code_presentation"] == code_presentation)
    )
    return snapshot[~is_this_student]


def main() -> None:
    configure_logging()

    id_student = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ID_STUDENT
    code_module = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CODE_MODULE
    code_presentation = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_CODE_PRESENTATION
    print(f"OULAD id_student={id_student} {code_module}/{code_presentation}")

    engine = get_engine()
    student = Student(display_name=f"oulad-demo-{id_student}")
    twin = StudentTwin(student)

    results = fetch_oulad_assessment_results(
        engine, id_student, code_module, code_presentation, twin_student_id=student.student_id
    )
    for result in results:
        twin.apply_assessment_result(result)
    print(f"Applied {len(results)} assessment result(s) to the twin.")

    dropout_snapshot = fetch_oulad_dropout_snapshot(engine)
    dropout_row = _student_row(dropout_snapshot, id_student, code_module, code_presentation)
    dropout_training_pool = _exclude_student_row(
        dropout_snapshot, id_student, code_module, code_presentation
    )
    dropout_x, dropout_y = dropout.split_features_and_target(dropout_training_pool)
    dropout_x_train, _, _, dropout_y_train, _, _ = train_val_test_split(dropout_x, dropout_y)
    dropout_model = dropout.train_random_forest_model(dropout_x_train, dropout_y_train)

    if dropout_row is not None:
        dropout_prediction = dropout.predict(dropout_model, dropout_row[dropout.FEATURE_COLUMNS])[0]
        twin.attach_dropout_risk(dropout_prediction)
        print(
            f"Dropout risk: probability={dropout_prediction.dropout_probability:.3f} "
            f"predicted_class={dropout_prediction.predicted_class}"
        )
    else:
        print("No dropout-risk prediction available for this student/course.")

    performance_snapshot = fetch_oulad_performance_snapshot(engine)
    performance_row = _student_row(performance_snapshot, id_student, code_module, code_presentation)
    performance_training_pool = _exclude_student_row(
        performance_snapshot, id_student, code_module, code_presentation
    )
    performance_x, performance_y = perf.split_features_and_target(performance_training_pool)
    performance_x_train, _, _, performance_y_train, _, _ = train_val_test_split(
        performance_x, performance_y
    )
    performance_model = perf.train_random_forest_model(performance_x_train, performance_y_train)

    if performance_row is not None:
        performance_prediction = perf.predict(
            performance_model, performance_row[perf.FEATURE_COLUMNS]
        )[0]
        twin.attach_performance_prediction(performance_prediction)
        pass_probability = performance_prediction.pass_probability
        print(
            f"Performance prediction: pass_probability={pass_probability:.3f} "
            f"predicted_class={performance_prediction.predicted_class}"
        )
    else:
        print("No performance prediction available for this student/course (e.g. Withdrawn).")

    state = twin.current_state()
    print("\n--- StudentTwinState ---")
    print(f"assessment_performance: {state.assessment_performance}")
    print(f"dropout_risk:           {state.dropout_risk}")
    print(f"performance_prediction: {state.performance_prediction}")


if __name__ == "__main__":
    main()
