"""Fetches one real CO2 sensor's readings from Postgres as ClassroomEnvironmentReadings.

The only place this pipeline touches SQLAlchemy/Postgres (CLAUDE.md: only
data/db/ and data/repositories/ talk to the database) — mirrors
`assistments_problem_attempts.py`'s pattern for a different real dataset.

`co2_sensor_readings` carries a `sensor_id`, never a classroom/class_id: no
dataset in this project links a CO2 sensor to an ASSISTments class_id or any
other classroom entity (see domain/classroom.py's module docstring and
docs/datasets/spanish-co2-preprocessing-plan.md). This module fetches by
`sensor_id` only; any sensor-to-classroom association is the caller's to
supply, not this repository's to invent.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from digital_twin.domain.classroom import ClassroomEnvironmentReading

_QUERY = text("""
    SELECT sensor_id, recorded_at, temperature_c, humidity_pct, co2_ppm, battery_pct
    FROM co2_sensor_readings
    WHERE sensor_id = :sensor_id
    ORDER BY recorded_at
""")


def fetch_co2_sensor_readings(engine: Engine, sensor_id: str) -> list[ClassroomEnvironmentReading]:
    """Return one real CO2 sensor's readings, oldest first.

    Reads `co2_sensor_readings` for one real `sensor_id` (e.g. `"CO2_01"`).
    Every returned `ClassroomEnvironmentReading` carries that same
    `sensor_id`, never a classroom identity — this table has no
    classroom-linking column to read one from.
    """
    with engine.connect() as conn:
        rows = conn.execute(_QUERY, {"sensor_id": sensor_id}).fetchall()

    return [
        ClassroomEnvironmentReading(
            sensor_id=sensor_id,
            recorded_at=recorded_at,
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            co2_ppm=co2_ppm,
            battery_pct=battery_pct,
        )
        for _sensor_id, recorded_at, temperature_c, humidity_pct, co2_ppm, battery_pct in rows
    ]


__all__ = ["fetch_co2_sensor_readings"]
