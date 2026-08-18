"""Classroom entity and classroom-scoped environmental readings.

Grounded in the two dataset sources in this project that are actually
classroom-scoped (not student-scoped, not school-scoped):

- ASSISTments 2019-2020's `cdets.csv` (`assist_classes` in data/db/models.py)
  is the project's only real classroom *entity* — one row per class, with a
  teacher, a creation date, an enrolled student count, and assigned-work
  counts. `Classroom` below carries exactly those fields, nothing invented
  (no subject/schedule concept exists in any dataset this project loads).
- The Spanish Classroom CO2 sensor feed (`co2_sensor_readings` in
  data/db/models.py) is explicitly classroom-scoped ("one classroom sensor",
  per that table's docstring). `ClassroomEnvironmentReading` carries exactly
  its fields.

These two sources have no shared identifier (verified in
docs/datasets/assist-preprocessing-plan.md and
docs/datasets/spanish-co2-preprocessing-plan.md) and are never joined — see
`ClassroomEnvironmentReading`'s docstring for how that shapes this model.

NYC DOE daily attendance and UCI Occupancy Detection were deliberately not
used here: the former is school-scoped, not classroom-scoped (see
data/db/models.py::NycDailyAttendance), and the latter documents itself as a
single monitored room with no classroom identity at all (see
docs/datasets/occupancy-preprocessing-plan.md) — neither is safe to relabel
as "classroom" data without fabricating a meaning the source doesn't state.
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from pydantic import BaseModel, Field


class Classroom(BaseModel):
    """Canonical twin-tracked classroom identity.

    `classroom_id` is minted by this system, the same posture
    `Student.student_id` takes: ASSISTments' `class_id` is scoped to its own
    dataset release, not a global classroom identifier, so it is never
    adopted as this model's own identity. `source_class_id` retains it for
    traceability only, exactly as `AssessmentSubmission`/`XapiStudentRecord`
    retain source-scoped identifiers elsewhere in this project without
    treating them as this system's own key.

    `teacher_id` stays a plain, optional attribute rather than a reference to
    a `Teacher` model: no teacher entity exists anywhere in this project's
    domain vocabulary or datasets (ASSISTments' `cdets.csv` has no teacher
    table either — see `AssistClass` in data/db/models.py).
    """

    classroom_id: UUID = Field(default_factory=uuid4)
    source_class_id: int | None = None
    teacher_id: int | None = None
    created_at: datetime | None = None
    # Source-reported enrollment count (ASSISTments cdets.student_count) —
    # kept separate from ClassroomTwin's own count of attached
    # StudentTwinState objects, which may cover a different subset of the
    # roster than the source reported.
    student_count: int | None = Field(default=None, ge=0)
    problem_sets_assigned: int | None = Field(default=None, ge=0)
    skill_builders_assigned: int | None = Field(default=None, ge=0)


def derive_classroom_id(source_dataset: str, source_id: int | str) -> UUID:
    """Deterministic twin `classroom_id` for one real `(source_dataset, source_id)` pair.

    Same `uuid5` derivation as `domain/student.py::derive_student_id`, applied
    to classroom identity instead of student identity — lets an API caller
    (or any other caller) name a specific real classroom's twin without a
    persisted twin_id -> source_class_id lookup table existing anywhere:
    given the same `(source_dataset, source_id)`, this always recomputes the
    same UUID, so a caller-supplied `twin_id` can be verified by
    recomputation rather than trusted blindly. `source_dataset` is part of
    the hashed name, the same cross-dataset-collision guard
    `derive_student_id` documents — this function never asserts or infers
    that two different datasets' classrooms are "the same" real room/section.
    """
    return uuid5(NAMESPACE_DNS, f"{source_dataset}:{source_id}")


class ClassroomEnvironmentReading(BaseModel):
    """One classroom sensor's temperature/humidity/CO2/battery snapshot.

    Carries `sensor_id` (the CO2 feed's own identifier) rather than a
    `classroom_id` foreign key: no dataset in this project links a CO2
    sensor to an ASSISTments class_id or any other classroom entity (see
    this module's docstring), so inventing that link here would fabricate a
    relationship the source data doesn't support. A `ClassroomTwin` accepts
    these readings on the assumption that the caller has already established
    which physical classroom a given sensor belongs to — the same
    caller-establishes-identity posture `StudentTwin.apply_interaction`
    takes for `student_id`, except here there is no field to validate
    against, so no such check is performed.
    """

    reading_id: UUID = Field(default_factory=uuid4)
    sensor_id: str
    recorded_at: datetime
    temperature_c: float
    humidity_pct: float
    co2_ppm: int
    battery_pct: float
