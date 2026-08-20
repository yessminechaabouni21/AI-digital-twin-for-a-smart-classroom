"""Deterministic synthetic "Smart Classroom" scenario generator — demo/simulation only.

Produces plausible-looking environmental/engagement numbers for one
classroom, seeded entirely from `(source_dataset, class_id, category)` so the
same classroom always tells the same synthetic story across repeated demo
runs (no run-to-run flicker), while different classrooms look different.
Nothing here reads real sensor, xAPI, or occupancy data, and nothing here
touches the database — this module has no dependency beyond the standard
library, per CLAUDE.md's "data/generators/ is synthetic data only" boundary.

Deliberately does NOT generate an absence-risk value: that number now comes
from running `generate_engagement_counts`' output through the real, already-
trained `analytics/xapi_absence_risk.py` model (see
`analytics/synthetic_context.py::synthetic_absence_risk_indicator`) — a
fabricated-from-scratch absence-risk number would compete with, and could be
confused for, that real model's actual prediction on this synthetic input.

`analytics/synthetic_context.py` is responsible for tagging this output with
its `provenance="synthetic_demo"` label before it is ever surfaced via the
API — nothing returned by this module is safe to show a caller un-tagged.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class SyntheticEnvironmentReading:
    temperature_c: float
    humidity_pct: float
    co2_ppm: int
    occupied: bool


@dataclass(frozen=True)
class SyntheticEngagementCounts:
    raised_hands: int
    visited_resources: int
    announcements_view: int
    discussion: int


def _seeded_random(source_dataset: str, class_id: int, category: str) -> random.Random:
    """A `random.Random` seeded from a plain string.

    `random.seed`/`random.Random(...)` hash str/bytes seeds via a fixed
    algorithm (unlike the builtin `hash()`, which `PYTHONHASHSEED`
    randomizes per-process) — so this is deterministic across processes and
    runs, not just within one. `category` keeps the environment/engagement
    draws independent of each other for the same classroom, rather than
    both depending on the same call-order-sensitive stream.
    """
    return random.Random(f"{source_dataset}:{class_id}:{category}")


def generate_environment_reading(source_dataset: str, class_id: int) -> SyntheticEnvironmentReading:
    """A fabricated temperature/humidity/CO2/occupancy reading, in the same
    plausible ranges as the real Spanish Classroom CO2 sensor feed and UCI
    Occupancy Detection dataset — but generated, not read from either."""
    rng = _seeded_random(source_dataset, class_id, "environment")
    return SyntheticEnvironmentReading(
        temperature_c=round(rng.uniform(19.0, 26.0), 1),
        humidity_pct=round(rng.uniform(30.0, 60.0), 1),
        co2_ppm=rng.randint(450, 1600),
        occupied=rng.random() < 0.7,
    )


def generate_engagement_counts(source_dataset: str, class_id: int) -> SyntheticEngagementCounts:
    """Fabricated behavioral-engagement counts, shaped like xAPI-Edu-Data's own
    raised_hands/visited_resources/announcements_view/discussion columns —
    but generated, not read from that dataset."""
    rng = _seeded_random(source_dataset, class_id, "engagement")
    return SyntheticEngagementCounts(
        raised_hands=rng.randint(0, 80),
        visited_resources=rng.randint(0, 80),
        announcements_view=rng.randint(0, 40),
        discussion=rng.randint(0, 60),
    )


__all__ = [
    "SyntheticEngagementCounts",
    "SyntheticEnvironmentReading",
    "generate_engagement_counts",
    "generate_environment_reading",
]
