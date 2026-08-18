"""Repository for `classroom_context_mappings`: the one explicit, authoritative link from a
real classroom to a contextual data source (CO2 sensor, xAPI-Edu-Data record).

The only place this pipeline touches SQLAlchemy/Postgres (CLAUDE.md: only
data/db/ and data/repositories/ talk to the database). This repository
performs no inference of its own: `get_classroom_context_mapping` returns
exactly what was previously written by `upsert_classroom_context_mapping`
(or `None`) — never a guessed or computed relationship. See
`data/db/models.py::ClassroomContextMapping`'s docstring for the identity
guarantee this table exists to make explicit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import Engine, text

_SELECT_QUERY = text("""
    SELECT source_dataset, class_id, sensor_id, xapi_record_id, updated_at
    FROM classroom_context_mappings
    WHERE source_dataset = :source_dataset AND class_id = :class_id
""")

_UPSERT_QUERY = text("""
    INSERT INTO classroom_context_mappings
        (source_dataset, class_id, sensor_id, xapi_record_id, updated_at)
    VALUES (:source_dataset, :class_id, :sensor_id, :xapi_record_id, :updated_at)
    ON CONFLICT (source_dataset, class_id)
    DO UPDATE SET sensor_id = EXCLUDED.sensor_id,
                  xapi_record_id = EXCLUDED.xapi_record_id,
                  updated_at = EXCLUDED.updated_at
""")

_DELETE_QUERY = text("""
    DELETE FROM classroom_context_mappings
    WHERE source_dataset = :source_dataset AND class_id = :class_id
""")


class ClassroomContextMappingRecord(BaseModel):
    """One classroom's currently configured contextual-data links, or lack thereof."""

    source_dataset: str
    class_id: int
    sensor_id: str | None
    xapi_record_id: int | None
    updated_at: datetime


def get_classroom_context_mapping(
    engine: Engine, source_dataset: str, class_id: int
) -> ClassroomContextMappingRecord | None:
    """Return `class_id`'s explicitly configured mapping, or None if none was ever set.

    A `None` result must be read as "no legitimate contextual data source is
    configured for this classroom" — never as "look one up automatically."
    """
    with engine.connect() as conn:
        row = conn.execute(
            _SELECT_QUERY, {"source_dataset": source_dataset, "class_id": class_id}
        ).fetchone()
    if row is None:
        return None
    return ClassroomContextMappingRecord(
        source_dataset=row.source_dataset,
        class_id=row.class_id,
        sensor_id=row.sensor_id,
        xapi_record_id=row.xapi_record_id,
        updated_at=row.updated_at,
    )


def upsert_classroom_context_mapping(
    engine: Engine,
    source_dataset: str,
    class_id: int,
    *,
    sensor_id: str | None = None,
    xapi_record_id: int | None = None,
) -> None:
    """Create or replace `class_id`'s explicit contextual-data mapping.

    The caller is asserting a real-world fact this repository cannot itself
    verify — see `ClassroomContextMapping`'s docstring. Passing `sensor_id`/
    `xapi_record_id` as `None` clears that half of the mapping rather than
    leaving a stale previous value in place.
    """
    with engine.begin() as conn:
        conn.execute(
            _UPSERT_QUERY,
            {
                "source_dataset": source_dataset,
                "class_id": class_id,
                "sensor_id": sensor_id,
                "xapi_record_id": xapi_record_id,
                "updated_at": datetime.now(UTC),
            },
        )


def delete_classroom_context_mapping(engine: Engine, source_dataset: str, class_id: int) -> None:
    """Remove `class_id`'s mapping entirely, reverting it to "nothing configured"."""
    with engine.begin() as conn:
        conn.execute(_DELETE_QUERY, {"source_dataset": source_dataset, "class_id": class_id})


__all__ = [
    "ClassroomContextMappingRecord",
    "delete_classroom_context_mapping",
    "get_classroom_context_mapping",
    "upsert_classroom_context_mapping",
]
