"""Student entity: identity, profile, learning preferences."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from pydantic import BaseModel, Field


class Student(BaseModel):
    """Canonical twin-tracked student identity.

    student_id is minted by this system (the synthetic generator today, a
    real adapter later per ADR-002) — never an OULAD id_student, an
    ASSISTments student_id, or a dropout_records row. None of those are
    global person identifiers (OULAD's and ASSISTments' are scoped to their
    own dataset and reused across a student's own enrollments/classes;
    dropout_records has no identifier at all), so none of them are safe to
    adopt as the twin's own identity. This model never joins to any of
    those tables by id.
    """

    student_id: UUID = Field(default_factory=uuid4)
    display_name: str | None = None
    grade_level: str | None = None
    enrolled_at: datetime | None = None


def derive_student_id(source_dataset: str, source_id: int | str) -> UUID:
    """Deterministic twin `student_id` for one real `(source_dataset, source_id)` pair.

    Opt-in alternative to `Student`'s default `uuid4()` mint, for callers
    that want the *same* twin identity back across separate runs/processes
    (e.g. to persist and later reload a twin via
    `data/repositories/student_twin_repository.py`) — a random `uuid4()`
    can never be reproduced, so nothing saved under one could ever be found
    again. Same `uuid5` derivation `data/repositories/oulad_assessment_results.py`
    already uses for `assessment_id`, applied here to `student_id`.

    `source_dataset` is part of the hashed name (`f"{source_dataset}:{source_id}"`),
    not just `source_id` alone: this is what keeps two different datasets'
    same-valued native id (e.g. ASSISTments `student_id=52964` and some
    unrelated OULAD `id_student=52964`) from ever colliding onto the same
    twin identity. This function never joins or infers a relationship
    between datasets — it only gives one dataset's own id a reproducible
    twin-shaped name; whether two calls with different `source_dataset`
    values happen to represent the same real person is never decided here
    and must never be assumed.
    """
    return uuid5(NAMESPACE_DNS, f"{source_dataset}:{source_id}")
