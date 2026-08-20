"""Response schemas for GET /demo/context-signals and GET /demo/classroom-scenario.

Deliberately its own module, orthogonal to `schemas/classrooms.py`: none of
these schemas are produced by or fed into `analytics/decision_support.py`.

Two distinct kinds of response live here, kept structurally separate exactly
like their underlying analytics types are:

- `DemoContextSignalsOut` (GET /demo/context-signals): real xAPI-Edu-Data and
  UCI Occupancy Detection data, deliberately carrying no `twin_id`/`class_id`/
  `source_class_id` field at all — shown for demonstration purposes only,
  never attached to any classroom.
- `DemoClassroomScenarioOut` (GET /demo/classroom-scenario): a fabricated,
  `provenance="synthetic_demo"` scenario deliberately scoped to one
  `source_class_id` (that association is intentional — it's the demo
  narrative), mirroring `analytics/synthetic_context.py`'s types field-for-
  field. Its `environment`/`engagement` are entirely fabricated; its
  `absence_risk` is the real, already-trained xAPI absence-risk model's
  actual prediction run on that fabricated engagement input (see
  `SyntheticAbsenceRiskIndicatorOut`). Never confuse this endpoint's
  synthetic inputs with `DemoContextSignalsOut`'s real, unlinked xAPI/UCI
  data.

`ClassificationMetricsOut` mirrors `analytics/predictive.py::ClassificationMetrics`
field-for-field (response shaping only, same reasoning as every other
`*Out` schema in this package). `DemoOccupancyBenchmarkOut` is deliberately
NOT a `ContextSignalOut`/`ContextSignal`: model-quality metrics
(accuracy/precision/recall/f1/roc_auc) describe the model, not a fact about
a room or a cohort, so packaging them as a `ContextSignal.value` would be
exactly the misuse `analytics/context_signals.py::occupancy_context_signal`'s
docstring warns against.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DEMO_MODE_DISCLAIMER = "DEMONSTRATION MODE — BENCHMARK / NOT CLASSROOM OBSERVED"


class DemoXapiContextSignalOut(BaseModel):
    """One real xAPI-Edu-Data signal for one explicitly-chosen, unlinked record.

    Same 5 substantive fields as `analytics/context_signals.py::ContextSignal`,
    plus a `provenance` literal this endpoint always stamps — so a client
    can tell this response apart from a real classroom's (structurally
    different, `ContextSignalOut`-typed) `context_signals` at the type
    level, not just by reading `scope_description`.
    """

    source_dataset: str
    scope_description: str
    metric_name: str
    value: float
    as_of: datetime | None
    provenance: Literal["benchmark_research"] = "benchmark_research"


class ClassificationMetricsOut(BaseModel):
    """Mirrors `analytics/predictive.py::ClassificationMetrics` — model-quality only."""

    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    class_distribution: dict[int, int]
    confusion_matrix: list[list[int]]


class DemoOccupancyBenchmarkOut(BaseModel):
    """UCI Occupancy Detection baseline-model quality, for one monitored room, 2015 benchmark.

    Never a classroom-specific or "current occupancy" prediction: no
    inference-on-a-new-observation function exists for this dataset (see
    `analytics/context_signals.py::occupancy_context_signal`'s docstring),
    and `occupancy_readings` shares no identifier with any ASSISTments
    classroom (verified, not assumed — see `domain/classroom.py`'s module
    docstring). This is the model's own held-out evaluation, nothing else.
    """

    source_dataset: Literal["uci_occupancy"] = "uci_occupancy"
    provenance: Literal["benchmark_research"] = "benchmark_research"
    description: str
    train_row_count: int = Field(ge=0)
    test_row_count: int = Field(ge=0)
    headline_metrics: ClassificationMetricsOut
    transition_event_count: int = Field(
        ge=0,
        description=(
            "Rows in the held-out test split where occupancy differs from the "
            "immediately preceding reading — the harder, autocorrelation-free "
            "evaluation subset."
        ),
    )
    transition_event_metrics: ClassificationMetricsOut | None = Field(
        description="None only if the test split contained zero transition events."
    )
    limitations: list[str]


class DemoContextSignalsOut(BaseModel):
    """The entire response of GET /demo/context-signals — always demo-mode, always unlinked.

    No field on this schema, at any nesting level, carries a `twin_id`,
    `class_id`, or `source_class_id` — that absence is the structural
    guarantee that this response can never be read as belonging to a
    specific classroom.
    """

    mode: Literal["demo"] = "demo"
    disclaimer: str = DEMO_MODE_DISCLAIMER
    xapi_record_id: int
    xapi_context_signals: list[DemoXapiContextSignalOut]
    xapi_absence_risk_signal: DemoXapiContextSignalOut | None
    xapi_note: str
    occupancy_benchmark: DemoOccupancyBenchmarkOut


class SyntheticClassroomEnvironmentOut(BaseModel):
    """Mirrors `analytics/synthetic_context.py::SyntheticClassroomEnvironment`."""

    provenance: Literal["synthetic_demo"] = "synthetic_demo"
    temperature_c: float
    humidity_pct: float
    co2_ppm: int
    occupied: bool
    scope_description: str


class SyntheticEngagementOut(BaseModel):
    """Mirrors `analytics/synthetic_context.py::SyntheticEngagement`."""

    provenance: Literal["synthetic_demo"] = "synthetic_demo"
    raised_hands: int
    visited_resources: int
    announcements_view: int
    discussion: int
    scope_description: str


class SyntheticAbsenceRiskIndicatorOut(BaseModel):
    """Mirrors `analytics/synthetic_context.py::SyntheticAbsenceRiskIndicator`.

    `absence_risk_indicator` IS a real prediction from
    `analytics/xapi_absence_risk.py`'s trained model (see
    `model_provenance`), run on this scenario's synthetic engagement counts
    (see `input_provenance`) — never retrained/recalibrated on synthetic
    data. Deliberately not named/shaped like `ContextSignalOut`'s
    absence-risk counterpart (`metric_name="predicted_absence_risk"`): that
    one's input is a real, explicitly-mapped xAPI-Edu-Data record; this
    one's input is fabricated.
    """

    provenance: Literal["synthetic_demo"] = "synthetic_demo"
    input_provenance: Literal["synthetic_demo"] = "synthetic_demo"
    model_provenance: Literal["real_xapi_trained_model"] = "real_xapi_trained_model"
    absence_risk_indicator: float
    scope_description: str


class DemoClassroomScenarioOut(BaseModel):
    """The entire response of GET /demo/classroom-scenario — a fabricated,
    illustrative Smart-Classroom scenario for one explicitly-supplied classroom.

    Every field under `environment`/`engagement`/`absence_risk` is stamped
    `provenance="synthetic_demo"`. `environment`/`engagement` trace entirely
    to `data/generators/synthetic_classroom_scenario.py`'s seeded generator —
    never a real sensor or real xAPI-Edu-Data. `absence_risk` is different:
    its `input` (the engagement counts feeding the model) is synthetic, but
    its prediction is the real, already-trained
    `analytics/xapi_absence_risk.py` model's actual output — see
    `SyntheticAbsenceRiskIndicatorOut`'s own docstring. None of this touches
    the real, deterministic ASSISTments/BKT decision-support output (see
    `ClassroomDecisionSupportOut` in `schemas/classrooms.py` for that,
    unchanged and untouched by this endpoint).
    """

    mode: Literal["demo"] = "demo"
    disclaimer: str = DEMO_MODE_DISCLAIMER
    source_dataset: str
    source_class_id: int
    scenario_note: str
    environment: SyntheticClassroomEnvironmentOut
    engagement: SyntheticEngagementOut
    absence_risk: SyntheticAbsenceRiskIndicatorOut


__all__ = [
    "DEMO_MODE_DISCLAIMER",
    "ClassificationMetricsOut",
    "DemoClassroomScenarioOut",
    "DemoContextSignalsOut",
    "DemoOccupancyBenchmarkOut",
    "DemoXapiContextSignalOut",
    "SyntheticAbsenceRiskIndicatorOut",
    "SyntheticClassroomEnvironmentOut",
    "SyntheticEngagementOut",
]
