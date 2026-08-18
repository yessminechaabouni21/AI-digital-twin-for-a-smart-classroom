"""Focused tests for derive_student_id's determinism and cross-dataset separation."""

from __future__ import annotations

from uuid import UUID

from digital_twin.domain.student import derive_student_id


def test_derive_student_id_is_deterministic() -> None:
    first = derive_student_id("assistments", 52964)
    second = derive_student_id("assistments", 52964)
    assert first == second
    assert isinstance(first, UUID)


def test_derive_student_id_differs_by_source_dataset_for_same_native_id() -> None:
    """Same numeric id, different dataset -> different twin id: no cross-dataset merge."""
    assistments_id = derive_student_id("assistments", 52964)
    oulad_id = derive_student_id("oulad", 52964)
    assert assistments_id != oulad_id


def test_derive_student_id_differs_by_source_id_within_same_dataset() -> None:
    first = derive_student_id("assistments", 52964)
    second = derive_student_id("assistments", 52965)
    assert first != second
