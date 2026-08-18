"""Focused tests for analytics/context_signals.py: provenance packaging, no identity fields,
no fabricated signals when legitimate data is unavailable."""

from __future__ import annotations

from datetime import UTC, datetime

from digital_twin.analytics.context_signals import (
    ContextSignal,
    environmental_sensor_context_signals,
    occupancy_context_signal,
    xapi_absence_risk_context_signal,
    xapi_cohort_engagement_context_signals,
)
from digital_twin.analytics.xapi_absence_risk import XapiAbsenceRiskPrediction
from digital_twin.domain.classroom import ClassroomEnvironmentReading
from digital_twin.twin_engine.student_twin import XapiEngagementCounts

FORBIDDEN_IDENTITY_FIELDS = {"student_id", "classroom_id", "twin_id"}


def test_context_signal_has_no_identity_fields() -> None:
    assert FORBIDDEN_IDENTITY_FIELDS.isdisjoint(ContextSignal.model_fields.keys())


def test_context_signal_requires_provenance_fields() -> None:
    assert set(ContextSignal.model_fields.keys()) == {
        "source_dataset",
        "scope_description",
        "metric_name",
        "value",
        "as_of",
    }


def test_occupancy_context_signal_is_unavailable_by_design() -> None:
    """No predict-on-new-observation function exists in occupancy_detection.py;
    this must not be invented just to populate a signal."""
    assert occupancy_context_signal() is None


def test_xapi_context_signals_carry_no_identity_and_correct_provenance() -> None:
    counts = XapiEngagementCounts(
        raised_hands=12, visited_resources=25, announcements_view=3, discussion=7
    )

    signals = xapi_cohort_engagement_context_signals(
        counts, class_section_scope="stage=MiddleSchool, grade=G-07, section=A, topic=Math"
    )

    assert len(signals) == 4
    for signal in signals:
        assert signal.source_dataset == "xapi_edu_data"
        assert "not this classroom" in signal.scope_description
        assert "no student-identifying column" in signal.scope_description
        assert signal.as_of is None
        assert not FORBIDDEN_IDENTITY_FIELDS & signal.model_dump().keys()

    values_by_metric = {s.metric_name: s.value for s in signals}
    assert values_by_metric == {
        "raised_hands": 12.0,
        "visited_resources": 25.0,
        "announcements_view": 3.0,
        "discussion": 7.0,
    }


def test_environmental_sensor_context_signals_carry_no_identity_and_correct_provenance() -> None:
    reading = ClassroomEnvironmentReading(
        sensor_id="CO2_01",
        recorded_at=datetime(2020, 3, 1, 12, 0, tzinfo=UTC),
        temperature_c=21.5,
        humidity_pct=40.0,
        co2_ppm=650,
        battery_pct=87.0,
    )

    signals = environmental_sensor_context_signals(reading)

    assert len(signals) == 3
    for signal in signals:
        assert signal.source_dataset == "environmental_sensors"
        assert "CO2_01" in signal.scope_description
        assert (
            "no dataset links this sensor to any ASSISTments classroom" in signal.scope_description
        )
        assert signal.as_of == reading.recorded_at
        assert not FORBIDDEN_IDENTITY_FIELDS & signal.model_dump().keys()

    values_by_metric = {s.metric_name: s.value for s in signals}
    assert values_by_metric == {
        "co2_ppm": 650.0,
        "temperature_c": 21.5,
        "humidity_pct": 40.0,
    }


def test_xapi_absence_risk_context_signal_carries_no_identity_and_correct_provenance() -> None:
    prediction = XapiAbsenceRiskPrediction(absence_risk_probability=0.82, predicted_class=1)

    signal = xapi_absence_risk_context_signal(
        prediction, class_section_scope="xapi_record_id=42 (explicitly configured)"
    )

    assert signal.source_dataset == "xapi_edu_data"
    assert signal.metric_name == "predicted_absence_risk"
    assert signal.value == 0.82
    assert signal.as_of is None
    assert "xapi_record_id=42" in signal.scope_description
    assert "not a verified per-day attendance record" in signal.scope_description
    assert "not this classroom's or any specific student's data" in signal.scope_description
    assert not FORBIDDEN_IDENTITY_FIELDS & signal.model_dump().keys()
