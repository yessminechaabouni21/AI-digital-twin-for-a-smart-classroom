"""Packaging/provenance layer for cohort-level "contextual signals" with no legitimate
mapping to any StudentTwin or ClassroomTwin.

Some real datasets in this project (UCI Occupancy Detection, xAPI-Edu-Data,
independent environmental sensors) carry no shared identifier with the
twin-linked datasets (ASSISTments, OULAD) — see `domain/classroom.py`'s and
`domain/student.py`'s module docstrings for the verified absence of any such
mapping. Rather than silently dropping this information or, worse, guessing
a mapping, this module packages it as `ContextSignal`s: provenance-tagged
facts about an unrelated cohort/room/sensor, structurally incapable of being
mistaken for evidence about a specific classroom or student because a
`ContextSignal` has no `student_id`, `classroom_id`, or `twin_id` field at
all — only `source_dataset` + `scope_description`.

This is a packaging layer, not a new ML layer: every wrapper function here
takes an already-fetched, already-legitimate output (a repository fetch, a
domain-typed reading) and reshapes it — it trains no model, fits no
pipeline, and infers no cross-dataset identity link. Where no legitimate
runtime value exists for a source (see `occupancy_context_signal`'s
docstring), this module returns nothing rather than inventing one.

Independent of SQLAlchemy, database sessions, API routers, the Anthropic
SDK, `StudentTwin`, and `ClassroomTwin` — callers fetch data via
`data/repositories/` and pass already-fetched objects in.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from digital_twin.analytics.xapi_absence_risk import XapiAbsenceRiskPrediction
from digital_twin.domain.classroom import ClassroomEnvironmentReading
from digital_twin.twin_engine.student_twin import XapiEngagementCounts


class ContextSignal(BaseModel):
    """A provenance-tagged fact about an unrelated cohort/room/sensor.

    Deliberately has no `student_id`, `classroom_id`, or `twin_id` field —
    that is the structural guarantee that a `ContextSignal` can never be
    mistaken for twin-linked evidence, enforced by the type itself rather
    than by convention. `value` is real contextual information (a recorded
    reading, a recorded count) or, where explicitly noted, a model's
    prediction for a specific already-identified observation — never a
    model-quality metric (accuracy/precision/recall/F1/ROC-AUC belong to ML
    evaluation reporting, not here).
    """

    source_dataset: str
    scope_description: str
    metric_name: str
    value: float
    as_of: datetime | None = None


def occupancy_context_signal() -> None:
    """UCI Occupancy Detection has no runtime ContextSignal today — always returns None.

    `analytics/occupancy_detection.py` only trains and evaluates a baseline
    model (`train_baseline_model`, consumed by `predictive.py`'s
    `evaluate_model`); it defines no function that predicts occupancy for a
    specific new observation, and no "latest reading" fetch exists in
    `data/repositories/occupancy_readings.py` either. This module does not
    invent an inference pathway just to populate a signal (see this
    module's docstring). The model's accuracy/precision/recall/F1/ROC-AUC
    are real and reported separately as ML evaluation metadata — they
    describe model quality, not contextual information, and are
    deliberately not surfaced as a `ContextSignal.value`.
    """
    return None


def xapi_cohort_engagement_context_signals(
    counts: XapiEngagementCounts,
    *,
    class_section_scope: str,
) -> list[ContextSignal]:
    """Wrap one already-fetched xAPI-Edu-Data record's engagement counts as ContextSignals.

    `counts` must come from an explicit, caller-chosen xAPI record (e.g. via
    `data/repositories/xapi_engagement.fetch_xapi_engagement_counts(engine,
    record_id)`) — this function performs no record selection of its own and
    infers no mapping to any student or classroom; xAPI-Edu-Data has no
    student-identifying column and no shared identifier with
    ASSISTments/OULAD (see `xapi_engagement.py`'s docstring). `as_of` is
    always `None`: xAPI-Edu-Data records carry no timestamp.
    """
    scope_description = (
        f"xAPI-Edu-Data cohort/class-section context ({class_section_scope}); "
        "xAPI-Edu-Data has no student-identifying column and shares no "
        "identifier with ASSISTments or OULAD — this is not this classroom's "
        "or any specific student's data."
    )
    metrics = {
        "raised_hands": counts.raised_hands,
        "visited_resources": counts.visited_resources,
        "announcements_view": counts.announcements_view,
        "discussion": counts.discussion,
    }
    return [
        ContextSignal(
            source_dataset="xapi_edu_data",
            scope_description=scope_description,
            metric_name=metric_name,
            value=float(value),
            as_of=None,
        )
        for metric_name, value in metrics.items()
    ]


def environmental_sensor_context_signals(
    reading: ClassroomEnvironmentReading,
) -> list[ContextSignal]:
    """Wrap one already-fetched sensor reading as independent ContextSignals.

    `reading` must come from an explicit, caller-chosen `sensor_id` (e.g. via
    `data/repositories/co2_sensor_readings.fetch_co2_sensor_readings(engine,
    sensor_id)`) — this function infers no sensor-to-classroom mapping; none
    exists in the source data (see `domain/classroom.py`'s module
    docstring). If a real external sensor<->room assignment is ever
    established, the caller supplies the already-established identity
    itself; this function still never infers one.
    """
    scope_description = (
        f"Independent environmental sensor reading (sensor_id={reading.sensor_id!r}); "
        "no dataset links this sensor to any ASSISTments classroom or student."
    )
    metrics = {
        "co2_ppm": float(reading.co2_ppm),
        "temperature_c": reading.temperature_c,
        "humidity_pct": reading.humidity_pct,
    }
    return [
        ContextSignal(
            source_dataset="environmental_sensors",
            scope_description=scope_description,
            metric_name=metric_name,
            value=value,
            as_of=reading.recorded_at,
        )
        for metric_name, value in metrics.items()
    ]


def xapi_absence_risk_context_signal(
    prediction: XapiAbsenceRiskPrediction,
    *,
    class_section_scope: str,
) -> ContextSignal:
    """Wrap one already-computed xAPI absence-risk prediction as a ContextSignal.

    Deliberately NOT named/described as "attendance" anywhere in this
    function's output: `prediction` is a probability that xAPI-Edu-Data's
    own coarse `student_absence_days` bucket ("Above-7" vs "Under-7", a
    self-reported/administrative 2-bucket field) is "Above-7" — never a
    verified per-day attendance record, and `metric_name` below says so via
    `predicted_absence_risk`, not any "attendance" term.

    `prediction` must come from `analytics/xapi_absence_risk.py::predict`
    run on one explicitly-mapped record's own feature row (e.g. via
    `data/repositories/classroom_context_mapping.py::get_classroom_context_mapping`'s
    `xapi_record_id`) — this function selects no record and trains no model
    itself; it only reshapes an already-computed prediction. See
    `analytics/xapi_absence_risk.py`'s module docstring for the full
    terminology/limitation note.
    """
    scope_description = (
        f"xAPI-Edu-Data absence-risk model prediction for one explicitly "
        f"mapped record ({class_section_scope}); the underlying model predicts "
        "xAPI-Edu-Data's own coarse student_absence_days bucket, not a verified "
        "per-day attendance record. xAPI-Edu-Data has no student-identifying "
        "column and shares no identifier with ASSISTments or OULAD — this is "
        "not this classroom's or any specific student's data."
    )
    return ContextSignal(
        source_dataset="xapi_edu_data",
        scope_description=scope_description,
        metric_name="predicted_absence_risk",
        value=prediction.absence_risk_probability,
        as_of=None,
    )


__all__ = [
    "ContextSignal",
    "environmental_sensor_context_signals",
    "occupancy_context_signal",
    "xapi_absence_risk_context_signal",
    "xapi_cohort_engagement_context_signals",
]
