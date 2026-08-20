"""Packaging layer for a synthetic, classroom-scoped "Smart Classroom scenario" —
demo/simulation data only, structurally distinct from `context_signals.py`'s
`ContextSignal`.

`ContextSignal`'s defining property is that it CANNOT carry a classroom
identity — that is the safeguard for real, unlinked xAPI-Edu-Data/UCI
Occupancy/environmental-sensor data (see `context_signals.py`'s module
docstring). A synthetic demo scenario needs the opposite property: it IS
deliberately associated with the classroom currently being demonstrated
(illustrating how a live signal *could* participate in that classroom's
Digital Twin), so it must not reuse `ContextSignal` without eroding that
safeguard. Every type here instead carries `provenance: Literal["synthetic_demo"]`
plus a classroom-scoped `scope_description`.

`SyntheticClassroomEnvironment`/`SyntheticEngagement` are entirely fabricated
— every field is produced by `data/generators/synthetic_classroom_scenario.py`'s
deterministic, seeded generator, with no repository/database access at all.

`SyntheticAbsenceRiskIndicator` is different, and deliberately so: its
`absence_risk_indicator` value is a REAL prediction from
`analytics/xapi_absence_risk.py`'s actual, already-trained model
(`predict()`, called unchanged — this module trains, retrains, recalibrates,
or fine-tunes nothing) run on this scenario's SYNTHETIC engagement counts.
Two distinct provenance facts, both surfaced explicitly on the type itself
so a caller never has to infer them from prose:

    input_provenance="synthetic_demo"          -> the engagement counts fed in
                                                   are fabricated, not observed
    model_provenance="real_xapi_trained_model" -> the model that produced the
                                                   prediction is real, trained
                                                   only on real xAPI-Edu-Data

See `synthetic_absence_risk_indicator`'s docstring for the categorical
context features the real model also expects but this scenario has no
synthetic equivalent for, and exactly how they are handled (left missing,
not guessed).
"""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field
from sklearn.pipeline import Pipeline

from digital_twin.analytics.xapi_absence_risk import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
)
from digital_twin.analytics.xapi_absence_risk import (
    predict as predict_xapi_absence_risk,
)
from digital_twin.data.generators.synthetic_classroom_scenario import (
    generate_engagement_counts,
    generate_environment_reading,
)

SYNTHETIC_DEMO_PROVENANCE: Literal["synthetic_demo"] = "synthetic_demo"


class SyntheticClassroomEnvironment(BaseModel):
    """A fabricated, illustrative temperature/humidity/CO2/occupancy reading.

    Not derived from any real CO2 sensor reading or the UCI Occupancy
    Detection dataset/model — deterministically generated per
    `(source_dataset, class_id)` so the same classroom always shows the same
    synthetic story.
    """

    provenance: Literal["synthetic_demo"] = SYNTHETIC_DEMO_PROVENANCE
    temperature_c: float
    humidity_pct: float
    co2_ppm: int
    occupied: bool
    scope_description: str


class SyntheticEngagement(BaseModel):
    """Fabricated, illustrative behavioral-engagement counts.

    Shaped like xAPI-Edu-Data's own raised_hands/visited_resources/
    announcements_view/discussion columns purely so the demo scenario reads
    naturally, and so they can be fed as this model's own numeric features
    (see `synthetic_absence_risk_indicator`) — never because these values
    came from that dataset.
    """

    provenance: Literal["synthetic_demo"] = SYNTHETIC_DEMO_PROVENANCE
    raised_hands: int
    visited_resources: int
    announcements_view: int
    discussion: int
    scope_description: str


class SyntheticAbsenceRiskIndicator(BaseModel):
    """The REAL, already-trained xAPI absence-risk model's prediction on SYNTHETIC input.

    Deliberately named `absence_risk_indicator`, not `absence_risk_probability`
    (`analytics/xapi_absence_risk.py::XapiAbsenceRiskPrediction`'s own field
    name), so a caller can never mistake this for
    `ContextSignalOut`'s real, explicitly-classroom-mapped
    `predicted_absence_risk` metric
    (`context_signals.py::xapi_absence_risk_context_signal`) — same model,
    same probability space, but this one's INPUT is fabricated; that one's
    input is a real, explicitly-mapped xAPI-Edu-Data record.

    `input_provenance` and `model_provenance` make the two distinct facts
    machine-readable rather than left to prose:

    - `input_provenance="synthetic_demo"`: the four engagement counts fed
      into the model came from this scenario's synthetic generator, not a
      real observation.
    - `model_provenance="real_xapi_trained_model"`: the model itself is
      `analytics/xapi_absence_risk.py`'s actual fitted pipeline, trained
      only on real xAPI-Edu-Data — never retrained, recalibrated, or
      fine-tuned on synthetic data.

    See `synthetic_absence_risk_indicator`'s docstring for how this model's
    other expected features (categorical context: school stage/grade/
    section/topic/semester/parent involvement, none of which this scenario
    generates) are handled.
    """

    provenance: Literal["synthetic_demo"] = SYNTHETIC_DEMO_PROVENANCE
    input_provenance: Literal["synthetic_demo"] = "synthetic_demo"
    model_provenance: Literal["real_xapi_trained_model"] = "real_xapi_trained_model"
    absence_risk_indicator: float = Field(ge=0.0, le=1.0)
    scope_description: str


def synthetic_classroom_environment(
    source_dataset: str, class_id: int
) -> SyntheticClassroomEnvironment:
    reading = generate_environment_reading(source_dataset, class_id)
    return SyntheticClassroomEnvironment(
        temperature_c=reading.temperature_c,
        humidity_pct=reading.humidity_pct,
        co2_ppm=reading.co2_ppm,
        occupied=reading.occupied,
        scope_description=(
            f"Synthetic/demo environment reading illustrating how a live sensor feed "
            f"could participate in {source_dataset} class_id={class_id}'s Digital Twin "
            "in the future. Not a real sensor reading, and not derived from the UCI "
            "Occupancy Detection dataset or model."
        ),
    )


def synthetic_engagement(source_dataset: str, class_id: int) -> SyntheticEngagement:
    counts = generate_engagement_counts(source_dataset, class_id)
    return SyntheticEngagement(
        raised_hands=counts.raised_hands,
        visited_resources=counts.visited_resources,
        announcements_view=counts.announcements_view,
        discussion=counts.discussion,
        scope_description=(
            f"Synthetic/demo engagement counts illustrating how a live engagement feed "
            f"could participate in {source_dataset} class_id={class_id}'s Digital Twin "
            "in the future. Not real xAPI-Edu-Data, and not derived from any real "
            "student in this or any classroom."
        ),
    )


def _synthetic_feature_row(engagement: SyntheticEngagement) -> pd.DataFrame:
    """One-row input exactly matching `analytics/xapi_absence_risk.py::FEATURE_COLUMNS`.

    Numeric columns (raised_hands/visited_resources/announcements_view/
    discussion) are `engagement`'s synthetic counts — the real model's own
    numeric preprocessing (median-impute + StandardScaler) applies to them
    exactly as it would to a real xAPI-Edu-Data row; no special-casing.

    Categorical columns (stage_id/grade_id/section_id/topic/semester/
    parent_answering_survey/parent_school_satisfaction) have no synthetic
    equivalent: this scenario generator produces no school-stage, grade,
    section, topic, semester, or parent-involvement data, and inventing a
    plausible-looking category for any of them would be exactly the kind of
    unjustified assumption this system avoids elsewhere. They are left as
    `math.nan` (a genuine missing value, not a guessed category), which the
    model's own already-fitted preprocessing then handles through machinery
    it already has: `SimpleImputer(strategy="constant", fill_value="Unknown")`
    fills them with the literal string "Unknown", and the downstream
    `OneHotEncoder(handle_unknown="ignore")` — which never saw "Unknown"
    during training, since the real xAPI-Edu-Data training set has zero
    missing categorical values (verified in this module's training data
    audit) — treats it as an unseen category and encodes it as an all-zero
    one-hot row. Each of those 7 features therefore contributes no signal to
    the prediction, rather than a fabricated one: the resulting prediction
    is informed only by the four synthetic engagement counts, not by
    invented classroom context. This is surfaced to callers via
    `SyntheticAbsenceRiskIndicator.scope_description`.
    """
    row: dict[str, object] = dict.fromkeys(CATEGORICAL_FEATURES, math.nan)
    row["raised_hands"] = engagement.raised_hands
    row["visited_resources"] = engagement.visited_resources
    row["announcements_view"] = engagement.announcements_view
    row["discussion"] = engagement.discussion
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


def synthetic_absence_risk_indicator(
    engagement: SyntheticEngagement, *, model: Pipeline
) -> SyntheticAbsenceRiskIndicator:
    """Run the real, already-trained xAPI absence-risk model on synthetic engagement counts.

    `model` must be an already-fitted `Pipeline` from
    `analytics/xapi_absence_risk.py::train_baseline_model`, trained only on
    real xAPI-Edu-Data — this function trains nothing, and never retrains,
    recalibrates, or fine-tunes it on synthetic data; it only calls
    `analytics/xapi_absence_risk.py::predict` unchanged, on a synthetic
    feature row (see `_synthetic_feature_row`). `engagement` should be the
    same `SyntheticEngagement` already generated/displayed for this
    scenario (see `synthetic_engagement`), so the model's input exactly
    matches the numbers shown alongside this prediction — never a second,
    independently-generated set of counts.
    """
    feature_row = _synthetic_feature_row(engagement)
    prediction = predict_xapi_absence_risk(model, feature_row)[0]
    return SyntheticAbsenceRiskIndicator(
        absence_risk_indicator=prediction.absence_risk_probability,
        scope_description=(
            "Real analytics/xapi_absence_risk.py model (trained only on real "
            "xAPI-Edu-Data, never retrained or recalibrated on synthetic data) applied "
            "to this scenario's fabricated engagement counts (raised_hands/"
            "visited_resources/announcements_view/discussion). The model's other "
            "expected features — school stage, grade, section, topic, semester, and "
            "parent-involvement — have no synthetic equivalent in this scenario and "
            "are passed as missing/unknown, so this prediction reflects engagement "
            "signal only, not full classroom context. This is a real model's output on "
            "a fabricated input, not a real attendance observation or prediction for "
            "this or any specific classroom's actual students."
        ),
    )


__all__ = [
    "SYNTHETIC_DEMO_PROVENANCE",
    "SyntheticAbsenceRiskIndicator",
    "SyntheticClassroomEnvironment",
    "SyntheticEngagement",
    "synthetic_absence_risk_indicator",
    "synthetic_classroom_environment",
    "synthetic_engagement",
]
