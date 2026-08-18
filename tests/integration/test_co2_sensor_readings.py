"""Integration test: fetch one real CO2 sensor's readings and aggregate onto a ClassroomTwin.

Requires a live PostgreSQL instance with `co2_sensor_readings` loaded —
skipped automatically if the database is unreachable, per CLAUDE.md's rule
that integration tests must be skippable without DB access.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.co2_sensor_readings import fetch_co2_sensor_readings
from digital_twin.domain.classroom import Classroom
from digital_twin.twin_engine.classroom_twin import ClassroomTwin

SENSOR_ID = "CO2_01"


@pytest.fixture
def engine() -> Engine:
    db_engine = get_engine()
    try:
        with db_engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable, skipping integration test: {exc}")
    return db_engine


def test_fetch_co2_sensor_readings_returns_readings_for_that_sensor_only(engine: Engine) -> None:
    readings = fetch_co2_sensor_readings(engine, SENSOR_ID)

    assert readings, "expected fixture sensor to have real readings"
    assert all(reading.sensor_id == SENSOR_ID for reading in readings)
    timestamps = [reading.recorded_at for reading in readings]
    assert timestamps == sorted(timestamps)


def test_co2_sensor_readings_aggregate_onto_classroom_twin_environment_summary(
    engine: Engine,
) -> None:
    readings = fetch_co2_sensor_readings(engine, SENSOR_ID)
    assert readings, "expected fixture sensor to have real readings"

    classroom_twin = ClassroomTwin(Classroom())
    for reading in readings:
        classroom_twin.apply_environment_reading(reading)

    state = classroom_twin.current_state()

    assert state.environment.reading_count == len(readings)
    assert state.environment.average_co2_ppm == pytest.approx(
        sum(r.co2_ppm for r in readings) / len(readings)
    )
    ordered = sorted(readings, key=lambda r: r.recorded_at)
    assert state.environment.last_recorded_at == ordered[-1].recorded_at
    assert state.environment.latest_battery_pct == ordered[-1].battery_pct
