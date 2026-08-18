"""Integration tests for classroom_context_mappings: the one explicit, authoritative link
from a real classroom to a contextual data source.

Requires a live PostgreSQL instance — skipped automatically if unreachable,
per CLAUDE.md's rule. Uses a dedicated, clearly-fake class_id
(TEST_CLASS_ID) so these tests never touch a real class_id's row, and
always clean up after themselves.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import Engine

from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.classroom_context_mapping import (
    delete_classroom_context_mapping,
    get_classroom_context_mapping,
    upsert_classroom_context_mapping,
)

# A class_id that will never collide with a real ASSISTments class_id.
TEST_CLASS_ID = 900_000_001


@pytest.fixture
def engine() -> Engine:
    db_engine = get_engine()
    try:
        with db_engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable, skipping integration test: {exc}")
    return db_engine


@pytest.fixture(autouse=True)
def _cleanup(engine: Engine) -> Generator[None, None, None]:
    delete_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID)
    yield
    delete_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID)


def test_get_returns_none_when_no_mapping_configured(engine: Engine) -> None:
    assert get_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID) is None


def test_upsert_then_get_round_trips_sensor_and_xapi_record(engine: Engine) -> None:
    upsert_classroom_context_mapping(
        engine, "assistments", TEST_CLASS_ID, sensor_id="CO2_01", xapi_record_id=1
    )

    mapping = get_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID)

    assert mapping is not None
    assert mapping.source_dataset == "assistments"
    assert mapping.class_id == TEST_CLASS_ID
    assert mapping.sensor_id == "CO2_01"
    assert mapping.xapi_record_id == 1


def test_upsert_replaces_previous_mapping_not_merges(engine: Engine) -> None:
    upsert_classroom_context_mapping(
        engine, "assistments", TEST_CLASS_ID, sensor_id="CO2_01", xapi_record_id=1
    )
    upsert_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID, sensor_id="CO2_02")

    mapping = get_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID)

    assert mapping is not None
    assert mapping.sensor_id == "CO2_02"
    assert mapping.xapi_record_id is None  # cleared, not left stale from the first upsert


def test_mapping_is_scoped_by_source_dataset_and_class_id(engine: Engine) -> None:
    """A mapping for one (source_dataset, class_id) must never leak to another —
    e.g. a real class_id must never accidentally see a test class_id's mapping."""
    upsert_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID, sensor_id="CO2_01")

    assert get_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID + 1) is None
    assert get_classroom_context_mapping(engine, "oulad", TEST_CLASS_ID) is None


def test_delete_reverts_to_unconfigured(engine: Engine) -> None:
    upsert_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID, sensor_id="CO2_01")
    delete_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID)

    assert get_classroom_context_mapping(engine, "assistments", TEST_CLASS_ID) is None
