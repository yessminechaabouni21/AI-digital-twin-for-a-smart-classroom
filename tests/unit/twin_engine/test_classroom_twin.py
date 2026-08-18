"""Tests for ClassroomTwin: aggregating classroom + already-computed student state."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from digital_twin.domain.classroom import Classroom, ClassroomEnvironmentReading
from digital_twin.domain.knowledge_state import KnowledgeState
from digital_twin.twin_engine.classroom_twin import ClassroomTwin
from digital_twin.twin_engine.student_twin import (
    AssessmentPerformanceSummary,
    EngagementSummary,
    StudentTwinState,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _student_state(
    *,
    mastery: dict[str, float] | None = None,
    observation_counts: dict[str, int] | None = None,
    total_interactions: int = 0,
    correct_attempts: int = 0,
    incorrect_attempts: int = 0,
    active_days: int = 0,
    average_score: float | None = None,
    as_of: datetime | None = NOW,
) -> StudentTwinState:
    student_id = uuid4()
    knowledge_states = {
        topic_id: KnowledgeState(
            student_id=student_id,
            topic_id=topic_id,
            mastery_probability=probability,
            observation_count=(observation_counts or {}).get(topic_id, 0),
            updated_at=NOW,
        )
        for topic_id, probability in (mastery or {}).items()
    }
    return StudentTwinState(
        student_id=student_id,
        knowledge_states=knowledge_states,
        engagement=EngagementSummary(
            total_interactions=total_interactions,
            correct_attempts=correct_attempts,
            incorrect_attempts=incorrect_attempts,
            active_days=active_days,
        ),
        assessment_performance=AssessmentPerformanceSummary(average_score=average_score),
        dropout_risk=None,
        performance_prediction=None,
        total_observations=0,
        as_of=as_of,
    )


def _reading(
    sensor_id: str, temperature_c: float, co2_ppm: int, battery_pct: float
) -> ClassroomEnvironmentReading:
    return ClassroomEnvironmentReading(
        sensor_id=sensor_id,
        recorded_at=NOW,
        temperature_c=temperature_c,
        humidity_pct=40.0,
        co2_ppm=co2_ppm,
        battery_pct=battery_pct,
    )


def test_empty_classroom_twin_has_no_roster_or_environment() -> None:
    twin = ClassroomTwin(Classroom(student_count=25))
    state = twin.current_state()

    assert state.roster_size == 0
    assert state.source_student_count == 25
    assert state.average_mastery_by_topic == {}
    assert state.topic_observation_counts == {}
    assert state.engagement.students_with_interactions == 0
    assert state.assessment_performance.students_with_results == 0
    assert state.environment.reading_count == 0
    assert state.as_of is None


def test_attach_student_state_is_keyed_by_student_id() -> None:
    twin = ClassroomTwin(Classroom())
    state = _student_state(mastery={"algebra": 0.8})

    twin.attach_student_state(state)
    twin.attach_student_state(state)  # re-attach: replace, not accumulate

    assert twin.current_state().roster_size == 1


def test_average_mastery_by_topic_averages_across_students() -> None:
    twin = ClassroomTwin(Classroom())
    twin.attach_student_states(
        [
            _student_state(mastery={"algebra": 0.8, "geometry": 0.4}),
            _student_state(mastery={"algebra": 0.4}),
        ]
    )

    mastery = twin.current_state().average_mastery_by_topic
    assert mastery["algebra"] == pytest.approx(0.6)
    assert mastery["geometry"] == pytest.approx(0.4)


def test_topic_observation_counts_sums_across_students() -> None:
    twin = ClassroomTwin(Classroom())
    twin.attach_student_states(
        [
            _student_state(
                mastery={"algebra": 0.8, "geometry": 0.4},
                observation_counts={"algebra": 5, "geometry": 2},
            ),
            _student_state(mastery={"algebra": 0.4}, observation_counts={"algebra": 3}),
        ]
    )

    counts = twin.current_state().topic_observation_counts
    assert counts["algebra"] == 8
    assert counts["geometry"] == 2


def test_engagement_summary_only_counts_students_with_interactions() -> None:
    twin = ClassroomTwin(Classroom())
    twin.attach_student_states(
        [
            _student_state(
                total_interactions=10, correct_attempts=6, incorrect_attempts=4, active_days=5
            ),
            _student_state(total_interactions=0),
        ]
    )

    engagement = twin.current_state().engagement
    assert engagement.students_with_interactions == 1
    assert engagement.total_interactions == 10
    assert engagement.total_correct_attempts == 6
    assert engagement.total_incorrect_attempts == 4
    assert engagement.average_active_days == 5


def test_assessment_summary_is_mean_of_per_student_averages() -> None:
    twin = ClassroomTwin(Classroom())
    twin.attach_student_states(
        [
            _student_state(average_score=80.0),
            _student_state(average_score=60.0),
            _student_state(average_score=None),
        ]
    )

    performance = twin.current_state().assessment_performance
    assert performance.students_with_results == 2
    assert performance.average_score == 70.0


def test_environment_summary_averages_readings_and_keeps_latest_battery() -> None:
    twin = ClassroomTwin(Classroom())
    twin.apply_environment_reading(
        _reading("sensor-01", temperature_c=20.0, co2_ppm=600, battery_pct=90.0)
    )
    twin.apply_environment_reading(
        _reading("sensor-01", temperature_c=22.0, co2_ppm=800, battery_pct=85.0)
    )

    environment = twin.current_state().environment
    assert environment.reading_count == 2
    assert environment.average_temperature_c == 21.0
    assert environment.average_co2_ppm == 700.0
    assert environment.latest_battery_pct == 85.0
    assert environment.last_recorded_at == NOW


def test_as_of_is_latest_across_student_states_and_environment_readings() -> None:
    from datetime import timedelta

    twin = ClassroomTwin(Classroom())
    twin.attach_student_state(_student_state(as_of=NOW))
    later_reading = ClassroomEnvironmentReading(
        sensor_id="sensor-01",
        recorded_at=NOW + timedelta(hours=1),
        temperature_c=20.0,
        humidity_pct=40.0,
        co2_ppm=600,
        battery_pct=90.0,
    )
    twin.apply_environment_reading(later_reading)

    assert twin.current_state().as_of == NOW + timedelta(hours=1)
