"""Tests for the Classroom and ClassroomEnvironmentReading domain models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from digital_twin.domain.classroom import Classroom, ClassroomEnvironmentReading

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_classroom_mints_its_own_identity_by_default() -> None:
    first = Classroom()
    second = Classroom()
    assert first.classroom_id != second.classroom_id


def test_classroom_carries_assist_classes_fields() -> None:
    classroom = Classroom(
        source_class_id=12345,
        teacher_id=987,
        created_at=NOW,
        student_count=28,
        problem_sets_assigned=4,
        skill_builders_assigned=2,
    )
    assert classroom.source_class_id == 12345
    assert classroom.teacher_id == 987
    assert classroom.student_count == 28


def test_classroom_student_count_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        Classroom(student_count=-1)


def test_classroom_environment_reading_requires_sensor_id_not_classroom_id() -> None:
    reading = ClassroomEnvironmentReading(
        sensor_id="sensor-01",
        recorded_at=NOW,
        temperature_c=21.5,
        humidity_pct=45.0,
        co2_ppm=650,
        battery_pct=87.0,
    )
    assert reading.sensor_id == "sensor-01"
    assert not hasattr(reading, "classroom_id")
