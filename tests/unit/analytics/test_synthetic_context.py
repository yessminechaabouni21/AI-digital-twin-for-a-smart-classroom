"""Focused tests for analytics/synthetic_context.py: synthetic-demo provenance packaging,
determinism, value ranges, structural distinctness from ContextSignal, and — for
absence-risk — that the real, already-trained xAPI absence-risk model (not a
second fabricated number) actually produces the displayed value.

No database access: the "trained model" here is a real
`analytics/xapi_absence_risk.py::train_baseline_model` fit on a small, hand-built
in-memory frame (not the deployed 480-row real dataset) — enough to exercise the
real pipeline/preprocessing/predict code path deterministically, without a live
Postgres instance. `tests/integration/test_api_demo.py` cross-checks the actual
deployed model.
"""

from __future__ import annotations

import pandas as pd
from sklearn.pipeline import Pipeline

from digital_twin.analytics.context_signals import ContextSignal
from digital_twin.analytics.synthetic_context import (
    SyntheticAbsenceRiskIndicator,
    SyntheticClassroomEnvironment,
    SyntheticEngagement,
    _synthetic_feature_row,
    synthetic_absence_risk_indicator,
    synthetic_classroom_environment,
    synthetic_engagement,
)
from digital_twin.analytics.xapi_absence_risk import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    train_baseline_model,
)
from digital_twin.analytics.xapi_absence_risk import (
    predict as predict_xapi_absence_risk,
)


def _fit_test_model() -> Pipeline:
    """A real `train_baseline_model` fit on a small synthetic-for-testing-only frame
    where low engagement -> high absence risk and high engagement -> low absence
    risk, so the fitted model has a real, checkable monotonic relationship."""
    low_engagement_rows = 10
    high_engagement_rows = 10
    frame = pd.DataFrame(
        {
            "stage_id": (["lowerlevel", "MiddleSchool"] * 10),
            "grade_id": (["G-02", "G-07"] * 10),
            "section_id": (["A", "B"] * 10),
            "topic": (["Math", "Science"] * 10),
            "semester": (["F", "S"] * 10),
            "parent_answering_survey": (["Yes", "No"] * 10),
            "parent_school_satisfaction": (["Good", "Bad"] * 10),
            "raised_hands": ([2] * low_engagement_rows + [90] * high_engagement_rows),
            "visited_resources": ([3] * low_engagement_rows + [85] * high_engagement_rows),
            "announcements_view": ([1] * low_engagement_rows + [35] * high_engagement_rows),
            "discussion": ([2] * low_engagement_rows + [55] * high_engagement_rows),
        }
    )
    target = pd.Series(
        [1] * low_engagement_rows + [0] * high_engagement_rows, name="is_high_absence_risk"
    )
    return train_baseline_model(frame[FEATURE_COLUMNS], target)


def _engagement(
    *,
    raised_hands: int = 10,
    visited_resources: int = 10,
    announcements_view: int = 5,
    discussion: int = 5,
) -> SyntheticEngagement:
    return SyntheticEngagement(
        raised_hands=raised_hands,
        visited_resources=visited_resources,
        announcements_view=announcements_view,
        discussion=discussion,
        scope_description="test engagement",
    )


# ---------------------------------------------------------------------------
# Provenance / structural distinctness
# ---------------------------------------------------------------------------


def test_synthetic_types_carry_synthetic_demo_provenance() -> None:
    model = _fit_test_model()
    environment = synthetic_classroom_environment("assistments", 1679)
    engagement = synthetic_engagement("assistments", 1679)
    absence_risk = synthetic_absence_risk_indicator(engagement, model=model)

    assert environment.provenance == "synthetic_demo"
    assert engagement.provenance == "synthetic_demo"
    assert absence_risk.provenance == "synthetic_demo"


def test_synthetic_types_are_structurally_distinct_from_context_signal() -> None:
    """ContextSignal carries no classroom identity and no provenance field at all —
    the synthetic types are the deliberate opposite (scoped, tagged) and must never
    collapse into the same shape."""
    context_signal_fields = set(ContextSignal.model_fields.keys())
    for synthetic_type in (
        SyntheticClassroomEnvironment,
        SyntheticEngagement,
        SyntheticAbsenceRiskIndicator,
    ):
        assert set(synthetic_type.model_fields.keys()) != context_signal_fields
        assert "provenance" in synthetic_type.model_fields


def test_absence_risk_indicator_has_distinct_input_and_model_provenance() -> None:
    model = _fit_test_model()
    engagement = _engagement()

    result = synthetic_absence_risk_indicator(engagement, model=model)

    assert result.input_provenance == "synthetic_demo"
    assert result.model_provenance == "real_xapi_trained_model"
    # Deliberately not the real model's own field name (see docstring) — never
    # confusable with ContextSignalOut's predicted_absence_risk for a real record.
    assert not hasattr(result, "absence_risk_probability")


# ---------------------------------------------------------------------------
# Environment / engagement: unchanged behavior (entirely fabricated)
# ---------------------------------------------------------------------------


def test_environment_reading_is_deterministic_per_classroom() -> None:
    first = synthetic_classroom_environment("assistments", 1679)
    second = synthetic_classroom_environment("assistments", 1679)

    assert first.model_dump() == second.model_dump()


def test_different_classrooms_get_different_scenarios() -> None:
    class_1679 = synthetic_classroom_environment("assistments", 1679)
    class_27834 = synthetic_classroom_environment("assistments", 27834)

    assert class_1679.model_dump(exclude={"scope_description"}) != class_27834.model_dump(
        exclude={"scope_description"}
    )


def test_environment_reading_values_are_in_plausible_ranges() -> None:
    reading = synthetic_classroom_environment("assistments", 1679)

    assert 19.0 <= reading.temperature_c <= 26.0
    assert 30.0 <= reading.humidity_pct <= 60.0
    assert 450 <= reading.co2_ppm <= 1600
    assert isinstance(reading.occupied, bool)


def test_engagement_counts_are_non_negative_and_deterministic() -> None:
    first = synthetic_engagement("assistments", 1679)
    second = synthetic_engagement("assistments", 1679)

    assert first.model_dump() == second.model_dump()
    assert first.raised_hands >= 0
    assert first.visited_resources >= 0
    assert first.announcements_view >= 0
    assert first.discussion >= 0


def test_environment_scope_description_names_the_classroom_and_disclaims_real_sources() -> None:
    reading = synthetic_classroom_environment("assistments", 1679)

    assert "assistments class_id=1679" in reading.scope_description
    assert "Not a real sensor reading" in reading.scope_description
    assert "UCI Occupancy Detection" in reading.scope_description


def test_engagement_scope_description_disclaims_real_xapi_data() -> None:
    engagement = synthetic_engagement("assistments", 1679)

    assert "Not real xAPI-Edu-Data" in engagement.scope_description


# ---------------------------------------------------------------------------
# Absence risk: a REAL model prediction on SYNTHETIC input
# ---------------------------------------------------------------------------


def test_feature_row_carries_engagement_values_and_marks_categorical_features_missing() -> None:
    """Exactly the transformation real inference input gets: numeric features are the
    synthetic values verbatim; categorical features (no synthetic equivalent) are
    genuinely missing (NaN), not a guessed category."""
    engagement = _engagement(
        raised_hands=11, visited_resources=22, announcements_view=33, discussion=44
    )

    row = _synthetic_feature_row(engagement)

    assert list(row.columns) == FEATURE_COLUMNS
    assert row.loc[0, "raised_hands"] == 11
    assert row.loc[0, "visited_resources"] == 22
    assert row.loc[0, "announcements_view"] == 33
    assert row.loc[0, "discussion"] == 44
    for categorical_feature in CATEGORICAL_FEATURES:
        assert pd.isna(row.loc[0, categorical_feature])


def test_absence_risk_indicator_equals_the_real_model_predict_output() -> None:
    """The displayed value must be exactly what analytics/xapi_absence_risk.py::predict
    returns for this synthetic feature row — not an independently generated number."""
    model = _fit_test_model()
    engagement = _engagement(
        raised_hands=3, visited_resources=4, announcements_view=1, discussion=2
    )

    result = synthetic_absence_risk_indicator(engagement, model=model)

    expected_row = _synthetic_feature_row(engagement)
    expected_prediction = predict_xapi_absence_risk(model, expected_row)[0]
    assert result.absence_risk_indicator == expected_prediction.absence_risk_probability


def test_absence_risk_indicator_is_deterministic_for_the_same_engagement() -> None:
    model = _fit_test_model()
    engagement = _engagement()

    first = synthetic_absence_risk_indicator(engagement, model=model)
    second = synthetic_absence_risk_indicator(engagement, model=model)

    assert first.absence_risk_indicator == second.absence_risk_indicator


def test_absence_risk_indicator_is_bounded() -> None:
    model = _fit_test_model()
    result = synthetic_absence_risk_indicator(_engagement(), model=model)

    assert 0.0 <= result.absence_risk_indicator <= 1.0


def test_changing_synthetic_engagement_changes_the_prediction() -> None:
    """The whole point of routing through the real model: different synthetic inputs
    must actually move the prediction, following the model's real, fitted
    (low engagement -> high risk, high engagement -> low risk) relationship."""
    model = _fit_test_model()
    low_engagement = _engagement(
        raised_hands=1, visited_resources=1, announcements_view=0, discussion=1
    )
    high_engagement = _engagement(
        raised_hands=95, visited_resources=90, announcements_view=38, discussion=58
    )

    low_engagement_result = synthetic_absence_risk_indicator(low_engagement, model=model)
    high_engagement_result = synthetic_absence_risk_indicator(high_engagement, model=model)

    low_value = low_engagement_result.absence_risk_indicator
    high_value = high_engagement_result.absence_risk_indicator
    assert low_value != high_value
    assert low_value > high_value


def test_calling_the_function_never_mutates_or_retrains_the_model() -> None:
    """No retraining/recalibration on synthetic data — the fitted classifier's own
    learned parameters must be byte-identical before and after."""
    model = _fit_test_model()
    coefficients_before = model.named_steps["classifier"].coef_.copy()

    synthetic_absence_risk_indicator(_engagement(raised_hands=50), model=model)
    synthetic_absence_risk_indicator(_engagement(raised_hands=5), model=model)

    assert (model.named_steps["classifier"].coef_ == coefficients_before).all()


def test_absence_risk_scope_description_distinguishes_real_model_from_synthetic_input() -> None:
    model = _fit_test_model()
    result = synthetic_absence_risk_indicator(_engagement(), model=model)

    assert "Real analytics/xapi_absence_risk.py model" in result.scope_description
    assert "trained only on real xAPI-Edu-Data" in result.scope_description
    assert "never retrained or recalibrated on synthetic data" in result.scope_description
    assert "fabricated engagement counts" in result.scope_description
    assert "not a real attendance observation" in result.scope_description
    assert "any specific classroom's actual students" in result.scope_description
