"""Fetches the full UCI Occupancy Detection dataset for occupancy-classification modeling.

The only place this pipeline touches SQLAlchemy/Postgres directly (CLAUDE.md:
only data/db/ and data/repositories/ talk to the database) —
`analytics/occupancy_detection.py` consumes the plain pandas DataFrame this
returns and never imports SQLAlchemy itself.

`occupancy_readings` has no classroom/class_id column and no shared
identifier with any ASSISTments table (see domain/classroom.py's module
docstring and docs/datasets/occupancy-preprocessing-plan.md) — this
repository returns the dataset's own single-room reading stream as-is, with
no classroom identity attached or implied.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine, text

_QUERY = text("""
    SELECT source_file, recorded_at, temperature_c, humidity_pct, light_lux, co2_ppm, occupancy
    FROM occupancy_readings
    ORDER BY recorded_at
""")


def fetch_occupancy_readings(engine: Engine) -> pd.DataFrame:
    """Return every real UCI Occupancy Detection reading, ordered chronologically by `recorded_at`.

    Chronological order (not `source_file` grouping) is the point: the three
    source files' own date ranges are not monotonic in file order (`test`
    covers 2015-02-02 to 02-04, `training` covers 02-04 to 02-10, `test2`
    covers 02-11 to 02-18 — verified against the live table, not assumed
    from file naming), so a caller that wants a genuine chronological
    train/test split must sort by `recorded_at` itself rather than trust
    `source_file` as a time-ordered label.
    """
    return pd.read_sql(_QUERY, engine)


__all__ = ["fetch_occupancy_readings"]
