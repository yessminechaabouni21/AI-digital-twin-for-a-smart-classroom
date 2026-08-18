"""Real-data demo: one CO2 sensor's readings aggregated onto a ClassroomTwin.

    1. Load one real Spanish Classroom CO2 sensor's readings
       (`co2_sensor_readings`, via `fetch_co2_sensor_readings`).
    2. Build a `ClassroomTwin` and apply every reading via
       `ClassroomTwin.apply_environment_reading()`.
    3. Print the resulting `ClassroomTwinState.environment` summary.

IMPORTANT — this demo does NOT claim the sensor belongs to any ASSISTments
classroom. Per the audit in domain/classroom.py's module docstring and
docs/datasets/spanish-co2-preprocessing-plan.md, `co2_sensor_readings` has no
classroom/class_id column and no shared identifier with ASSISTments'
`assist_classes` — that link does not exist in the source data and is never
fabricated here. The `Classroom` this script constructs is a purely
illustrative, caller-supplied placeholder (no `source_class_id`) so
`ClassroomTwin` has somewhere to attach the readings; it does not represent
a real classroom that this sensor was installed in.

Run as: python -m scripts.classroom_environment_demo [sensor_id]
"""

from __future__ import annotations

import sys

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.co2_sensor_readings import fetch_co2_sensor_readings
from digital_twin.domain.classroom import Classroom
from digital_twin.twin_engine.classroom_twin import ClassroomTwin

DEFAULT_SENSOR_ID = "CO2_01"


def main() -> None:
    configure_logging()
    engine = get_engine()

    sensor_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SENSOR_ID

    # 1. Load one real, independent CO2 sensor's readings.
    readings = fetch_co2_sensor_readings(engine, sensor_id)
    print(f"[1/3] CO2 sensor_id={sensor_id!r}: {len(readings)} real readings loaded")
    print(
        "      NOTE: this sensor is not linked to any ASSISTments classroom in the "
        "source data — no such mapping exists "
        "(see docs/datasets/spanish-co2-preprocessing-plan.md)."
    )

    # 2. Attach the readings to a ClassroomTwin.
    # Illustrative placeholder classroom only — not a real ASSISTments class_id.
    classroom_twin = ClassroomTwin(Classroom())
    for reading in readings:
        classroom_twin.apply_environment_reading(reading)
    print(f"[2/3] applied {len(readings)} readings to one illustrative ClassroomTwin")

    # 3. Print the resulting environment summary.
    state = classroom_twin.current_state()
    print("[3/3] environment summary:")
    print(f"      reading_count:          {state.environment.reading_count}")
    print(f"      average_temperature_c:  {state.environment.average_temperature_c}")
    print(f"      average_humidity_pct:   {state.environment.average_humidity_pct}")
    print(f"      average_co2_ppm:        {state.environment.average_co2_ppm}")
    print(f"      latest_battery_pct:     {state.environment.latest_battery_pct}")
    print(f"      last_recorded_at:       {state.environment.last_recorded_at}")


if __name__ == "__main__":
    main()
