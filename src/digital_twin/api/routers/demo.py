"""Demo/simulation endpoints, fully orthogonal to real-mode decision support.

This module never imports or constructs a `ClassroomDecisionContext`,
`ClassroomDecisionSupport`, or `RuleBasedDecisionSupportProvider`, and never
reads or writes `classroom_context_mappings` — the real, deterministic
`GET /classrooms/{twin_id}/decision-support` endpoint is completely
unaffected by anything in this file. Two, deliberately separate endpoints:

- `GET /demo/classroom-scenario` (primary, for the dashboard's Demo Mode):
  a fabricated, `provenance="synthetic_demo"` Smart-Classroom scenario
  (environment/engagement/absence-risk) for one caller-supplied classroom —
  see `analytics/synthetic_context.py`'s module docstring for why this is
  a distinct type from `ContextSignal`, never confusable with real data.
  Its `absence_risk` field runs the real, already-trained xAPI absence-risk
  model on the scenario's synthetic engagement counts (reusing the same
  cached model `GET /demo/context-signals` trains below), which is the only
  reason this endpoint needs a database connection — it still builds no
  `ClassroomTwin` and reads no `classroom_context_mappings`.
- `GET /demo/context-signals` (secondary, benchmark/model-validation
  evidence): real xAPI-Edu-Data and UCI Occupancy Detection data, carrying
  no classroom identity at all, shown to validate the underlying models —
  never the source of the synthetic scenario above.

xAPI-Edu-Data: reuses `analytics/context_signals.py`'s
`xapi_cohort_engagement_context_signals`/`xapi_absence_risk_context_signal`
unchanged, against one explicitly-chosen `xapi_record_id` (never inferred).
The absence-risk model/snapshot caching below intentionally duplicates
`api/routers/classrooms.py`'s private `_get_xapi_absence_risk_model_and_snapshot`
rather than sharing it — keeping this router's only dependency on
`classrooms.py`-adjacent code at zero, so nothing here can be broken by, or
break, that module's decision-support logic.

UCI Occupancy Detection: trains/evaluates the same baseline model
`analytics/occupancy_detection.py` and `scripts/occupancy_detection_demo.py`
already use, unchanged, and reports the result as
`schemas/demo.py::DemoOccupancyBenchmarkOut` — model-quality metrics only,
never a `ContextSignal` and never a prediction for a specific classroom or
current observation (see that dataset's own module docstring for why no
such prediction exists in this system).
"""

from __future__ import annotations

from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sklearn.pipeline import Pipeline
from sqlalchemy import Engine

from digital_twin.analytics.context_signals import (
    ContextSignal,
    xapi_absence_risk_context_signal,
    xapi_cohort_engagement_context_signals,
)
from digital_twin.analytics.occupancy_detection import (
    chronological_train_test_split,
    transition_event_mask,
)
from digital_twin.analytics.occupancy_detection import (
    split_features_and_target as split_occupancy_features_and_target,
)
from digital_twin.analytics.occupancy_detection import (
    train_baseline_model as train_occupancy_baseline_model,
)
from digital_twin.analytics.predictive import ClassificationMetrics, evaluate_model
from digital_twin.analytics.synthetic_context import (
    synthetic_absence_risk_indicator,
    synthetic_classroom_environment,
    synthetic_engagement,
)
from digital_twin.analytics.xapi_absence_risk import (
    FEATURE_COLUMNS as XAPI_FEATURE_COLUMNS,
)
from digital_twin.analytics.xapi_absence_risk import (
    drop_duplicate_rows as drop_duplicate_xapi_rows,
)
from digital_twin.analytics.xapi_absence_risk import (
    predict as predict_xapi_absence_risk,
)
from digital_twin.analytics.xapi_absence_risk import (
    split_features_and_target as split_xapi_features_and_target,
)
from digital_twin.analytics.xapi_absence_risk import (
    train_baseline_model as train_xapi_absence_risk_model,
)
from digital_twin.api.deps import get_db_engine
from digital_twin.data.repositories.occupancy_readings import fetch_occupancy_readings
from digital_twin.data.repositories.xapi_engagement import fetch_xapi_engagement_counts
from digital_twin.data.repositories.xapi_snapshot import fetch_xapi_snapshot
from digital_twin.schemas.demo import (
    ClassificationMetricsOut,
    DemoClassroomScenarioOut,
    DemoContextSignalsOut,
    DemoOccupancyBenchmarkOut,
    DemoXapiContextSignalOut,
    SyntheticAbsenceRiskIndicatorOut,
    SyntheticClassroomEnvironmentOut,
    SyntheticEngagementOut,
)

router = APIRouter(prefix="/demo", tags=["demo"])

DbEngine = Annotated[Engine, Depends(get_db_engine)]

# The smallest real, always-present xAPI-Edu-Data surrogate key (record_id
# is a DB-generated identity column starting at 1) — an explicit, documented
# default, not a guess at "which record belongs to a classroom" (none does).
DEFAULT_XAPI_RECORD_ID = 1

# Process-wide caches, same lazy-singleton posture as
# `api/routers/classrooms.py`'s `_xapi_absence_risk_state` — trained once,
# never retrained per request. Deliberately separate globals from that
# module's (see this module's docstring for why they are not shared).
_xapi_absence_risk_state: tuple[Pipeline, pd.DataFrame] | None = None
_occupancy_benchmark_cache: DemoOccupancyBenchmarkOut | None = None


def _get_xapi_absence_risk_model_and_snapshot(engine: Engine) -> tuple[Pipeline, pd.DataFrame]:
    global _xapi_absence_risk_state
    if _xapi_absence_risk_state is None:
        snapshot = fetch_xapi_snapshot(engine)
        training_snapshot = drop_duplicate_xapi_rows(snapshot)
        x_train, y_train = split_xapi_features_and_target(training_snapshot)
        model = train_xapi_absence_risk_model(x_train, y_train)
        _xapi_absence_risk_state = (model, snapshot)
    return _xapi_absence_risk_state


def _to_metrics_out(metrics: ClassificationMetrics) -> ClassificationMetricsOut:
    return ClassificationMetricsOut(**metrics.model_dump())


def _get_occupancy_benchmark(engine: Engine) -> DemoOccupancyBenchmarkOut:
    """Train/evaluate the UCI Occupancy Detection baseline once per process and cache it.

    Mirrors `scripts/occupancy_detection_demo.py`'s train/test split and
    headline + transition-event evaluation exactly, reusing
    `analytics/occupancy_detection.py`/`analytics/predictive.py` unchanged.
    """
    global _occupancy_benchmark_cache
    if _occupancy_benchmark_cache is not None:
        return _occupancy_benchmark_cache

    readings = fetch_occupancy_readings(engine)
    train_df, test_df = chronological_train_test_split(readings)
    x_train, y_train = split_occupancy_features_and_target(train_df)
    x_test, y_test = split_occupancy_features_and_target(test_df)
    model = train_occupancy_baseline_model(x_train, y_train)
    headline_metrics = evaluate_model(model, x_test, y_test)

    y_test_reset = y_test.reset_index(drop=True)
    x_test_reset = x_test.reset_index(drop=True)
    transition_mask = transition_event_mask(y_test_reset)
    n_transitions = int(transition_mask.sum())
    transition_metrics = (
        evaluate_model(model, x_test_reset[transition_mask], y_test_reset[transition_mask])
        if n_transitions > 0
        else None
    )

    result = DemoOccupancyBenchmarkOut(
        description=(
            "UCI Occupancy Detection: binary room-occupancy classification for the "
            "single room this 2015 benchmark dataset monitored. This is the model's "
            "own held-out evaluation, not a prediction for any classroom, student, "
            "or currently observed room — occupancy_readings carries no student or "
            "class identity and shares no identifier with any ASSISTments classroom."
        ),
        train_row_count=len(train_df),
        test_row_count=len(test_df),
        headline_metrics=_to_metrics_out(headline_metrics),
        transition_event_count=n_transitions,
        transition_event_metrics=(
            _to_metrics_out(transition_metrics) if transition_metrics is not None else None
        ),
        limitations=[
            "Headline row-level accuracy is inflated by strong autocorrelation "
            "between ~1-minute-apart readings; a naive persistence baseline "
            "(predict 'same as the previous reading') scores nearly identically "
            "on raw accuracy.",
            "transition_event_metrics isolates only the readings where occupancy "
            "actually changed since the previous reading — a harder, more "
            "informative evaluation than headline accuracy alone.",
            "This model has no classroom, student, or attendance meaning: it "
            "predicts room occupancy for one 2015 benchmark deployment only.",
        ],
    )
    _occupancy_benchmark_cache = result
    return result


@router.get("/context-signals", response_model=DemoContextSignalsOut)
def get_demo_context_signals(
    engine: DbEngine,
    xapi_record_id: int = Query(
        DEFAULT_XAPI_RECORD_ID,
        ge=1,
        description=(
            "Which xAPI-Edu-Data record to show (its own surrogate record_id). "
            "Never resolved from, or associated with, any classroom or class_id."
        ),
    ),
) -> DemoContextSignalsOut:
    scope = (
        f"unlinked xAPI-Edu-Data benchmark record (record_id={xapi_record_id}), shown for "
        "demonstration purposes only — not associated with any classroom or student twin"
    )

    xapi_signals: list[ContextSignal] = []
    absence_signal: ContextSignal | None = None
    counts = fetch_xapi_engagement_counts(engine, xapi_record_id)
    if counts is None:
        xapi_note = f"No xAPI-Edu-Data record exists with record_id={xapi_record_id}."
    else:
        xapi_signals = xapi_cohort_engagement_context_signals(counts, class_section_scope=scope)

        model, snapshot = _get_xapi_absence_risk_model_and_snapshot(engine)
        record_rows = snapshot.loc[snapshot["record_id"] == xapi_record_id]
        if not record_rows.empty:
            x_row = record_rows[XAPI_FEATURE_COLUMNS]
            prediction = predict_xapi_absence_risk(model, x_row)[0]
            absence_signal = xapi_absence_risk_context_signal(prediction, class_section_scope=scope)

        xapi_note = (
            "Real xAPI-Edu-Data values for one unlinked benchmark record, shown to "
            "illustrate the pipeline only — not this or any classroom's data."
        )

    return DemoContextSignalsOut(
        xapi_record_id=xapi_record_id,
        xapi_context_signals=[
            DemoXapiContextSignalOut(**signal.model_dump()) for signal in xapi_signals
        ],
        xapi_absence_risk_signal=(
            DemoXapiContextSignalOut(**absence_signal.model_dump())
            if absence_signal is not None
            else None
        ),
        xapi_note=xapi_note,
        occupancy_benchmark=_get_occupancy_benchmark(engine),
    )


@router.get("/classroom-scenario", response_model=DemoClassroomScenarioOut)
def get_demo_classroom_scenario(
    engine: DbEngine,
    class_id: int = Query(
        ..., description="The classroom to build an illustrative synthetic scenario for."
    ),
    source_dataset: str = Query("assistments"),
) -> DemoClassroomScenarioOut:
    """A fabricated Smart-Classroom scenario for one classroom.

    `environment`/`engagement` are deterministic per `(source_dataset,
    class_id)` (see `data/generators/synthetic_classroom_scenario.py`), so
    reloading the same classroom always shows the same synthetic story.
    `absence_risk` runs those same synthetic engagement counts through the
    real, already-trained xAPI absence-risk model (`_get_xapi_absence_risk_model_and_snapshot`,
    the same cached model `GET /demo/context-signals` uses — trained once,
    never retrained here) — this endpoint therefore does need a database
    connection, only to obtain that already-fitted model. Never builds a
    `ClassroomTwin`, never calls BKT, and never reads
    `classroom_context_mappings` — this is not this classroom's real data,
    only an illustration of how live sensor/engagement signals, and a real
    trained model's output on them, could participate in its Digital Twin.
    """
    environment = synthetic_classroom_environment(source_dataset, class_id)
    engagement = synthetic_engagement(source_dataset, class_id)
    model, _ = _get_xapi_absence_risk_model_and_snapshot(engine)
    absence_risk = synthetic_absence_risk_indicator(engagement, model=model)

    return DemoClassroomScenarioOut(
        source_dataset=source_dataset,
        source_class_id=class_id,
        scenario_note=(
            "The environment and engagement values below are entirely synthetic: they "
            "illustrate how a live sensor/engagement feed could participate in this "
            "classroom's Digital Twin in the future, and are not real sensor readings "
            "or real xAPI-Edu-Data. The absence-risk prediction is different: it is the "
            "real, already-trained xAPI absence-risk model's actual output when given "
            "this synthetic engagement input — see its own scope_description. Neither "
            "is a real observation of, or prediction for, this classroom's actual "
            "students; see this classroom's deterministic decision support (built from "
            "real ASSISTments data) for its actual, real learning state."
        ),
        environment=SyntheticClassroomEnvironmentOut(**environment.model_dump()),
        engagement=SyntheticEngagementOut(**engagement.model_dump()),
        absence_risk=SyntheticAbsenceRiskIndicatorOut(**absence_risk.model_dump()),
    )


__all__ = ["router"]
