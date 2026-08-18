"""Per-student twin: current knowledge state, engagement history, update methods."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from digital_twin.analytics.performance_prediction import StudentPerformancePrediction
from digital_twin.analytics.predictive import DropoutPrediction
from digital_twin.domain.assessment import AssessmentResult
from digital_twin.domain.interaction import Interaction, InteractionType
from digital_twin.domain.knowledge_state import KnowledgeState
from digital_twin.domain.student import Student
from digital_twin.twin_engine.update_strategies import (
    SimpleIncrementalUpdateStrategy,
    UpdateStrategy,
)

TwinEvent = Interaction | AssessmentResult

# Number of most-recent AssessmentResults compared against everything before
# them to derive `AssessmentPerformanceSummary.trend` — simple, explainable
# arithmetic (not a fitted model), matching this component's first-pass scope.
RECENT_ASSESSMENT_WINDOW = 3
# Minimum score-point delta (results are 0-100, OULAD's own scale) between
# recent and earlier averages before calling it a trend rather than noise.
TREND_EPSILON = 1.0

# Number of most-recent active days (distinct interaction dates) compared
# against every earlier active day to derive `EngagementSummary.trend` —
# same simple, explainable "recent vs. earlier average" posture as
# RECENT_ASSESSMENT_WINDOW, applied to interactions-per-day instead of score.
RECENT_ENGAGEMENT_WINDOW_DAYS = 3
# Minimum interactions-per-day delta between recent and earlier active days
# before calling it a trend rather than day-to-day noise.
ENGAGEMENT_TREND_EPSILON = 1.0


class XapiEngagementCounts(BaseModel):
    """Raw per-student behavioral counts from one xAPI-Edu-Data snapshot row.

    xAPI-Edu-Data has no timestamp and no natural per-student identifier
    (see `XapiStudentRecord`'s docstring in data/db/models.py): one row is
    a whole-semester behavioral summary, not a stream of dated events like
    OULAD's VLE interactions. Kept as its own typed block on
    `EngagementSummary` rather than blended into `total_interactions`/
    `active_days`, which are derived from timestamped Interactions and not
    a comparable unit to these semester totals.
    """

    raised_hands: int = Field(ge=0)
    visited_resources: int = Field(ge=0)
    announcements_view: int = Field(ge=0)
    discussion: int = Field(ge=0)


class EngagementSummary(BaseModel):
    """Derived counts over a student's processed Interaction history.

    `resource_interaction_days` counts RESOURCE_VIEW Interactions, i.e. one
    per OULAD `vle_interactions` row — a `(id_site, date)` SUM-aggregated
    click-count record, not a raw click or a verified page view (OULAD's own
    `sum_click` is preserved on each Interaction's `metadata` but not summed
    here). `active_days` is the number of distinct calendar dates with at
    least one Interaction. `trend` compares the average interactions-per-day over
    the most recent `RECENT_ENGAGEMENT_WINDOW_DAYS` active days against the
    average over every earlier active day — `None` until there are enough
    active days before that window to make the comparison meaningful (the
    same posture as `AssessmentPerformanceSummary.trend`).
    `xapi_behavioral_counts` is populated only if
    `StudentTwin.attach_xapi_engagement_counts` was called; it is
    independent of (not derived from) the OULAD-shaped Interaction history.
    """

    total_interactions: int = 0
    resource_interaction_days: int = 0
    problem_attempts: int = 0
    correct_attempts: int = 0
    incorrect_attempts: int = 0
    active_days: int = 0
    trend: Literal["increasing", "decreasing", "stable"] | None = None
    last_interaction_at: datetime | None = None
    xapi_behavioral_counts: XapiEngagementCounts | None = None


class AssessmentPerformanceSummary(BaseModel):
    """Derived stats over a student's processed AssessmentResult history.

    `recent_average_score` is the mean of the last `RECENT_ASSESSMENT_WINDOW`
    results (chronologically, by `submitted_at`); `trend` compares it against
    the mean of every result before that window. Both are `None` until there
    are enough results before the window to make the comparison meaningful
    (see `StudentTwin._assessment_summary`) — no result is ever compared
    against itself.
    """

    total_results: int = 0
    average_score: float | None = None
    recent_average_score: float | None = None
    trend: Literal["improving", "declining", "stable"] | None = None
    last_assessment_at: datetime | None = None


class StudentTwinState(BaseModel):
    """A read-only snapshot of a StudentTwin's current derived state.

    Deliberately separate from StudentTwin's raw history
    (interaction_history/assessment_results): this is the "current state"
    view — mastery + summaries as of `as_of` — not the event log that
    produced it.

    `dropout_risk`/`performance_prediction` are `None` until a caller
    attaches one via `StudentTwin.attach_dropout_risk`/
    `attach_performance_prediction` — the twin never computes them itself
    (no SQLAlchemy/scikit-learn dependency here, per CLAUDE.md's module
    boundaries; a fitted model and an OULAD feature snapshot only exist on
    the analytics/repository side). Same attach-don't-compute posture as
    `attach_xapi_engagement_counts` below.
    """

    student_id: UUID
    knowledge_states: dict[str, KnowledgeState]
    engagement: EngagementSummary
    assessment_performance: AssessmentPerformanceSummary
    dropout_risk: DropoutPrediction | None
    performance_prediction: StudentPerformancePrediction | None
    total_observations: int
    as_of: datetime | None


def _event_timestamp(event: TwinEvent) -> datetime:
    if isinstance(event, Interaction):
        return event.occurred_at
    return event.submitted_at


class StudentTwin:
    """Current state for one student: knowledge, engagement, and assessment history.

    Pure in-memory state over domain types — no PostgreSQL/SQLAlchemy
    dependency, per CLAUDE.md's module boundaries (persistence is a
    repository's job, not twin_engine's). The mastery-update rule itself
    lives in `update_strategies.py`'s pluggable UpdateStrategy, not here;
    this class owns routing events to that strategy and keeping the raw
    history + derived state, so the strategy can be replaced (Bayesian
    Knowledge Tracing, IRT, a learned model) without touching this class.

    Three things are deliberately kept separate:
    - raw history (`interaction_history`, `assessment_results`) — every
      event processed, in the order it was applied;
    - current state (`knowledge_states`) — the live per-topic mastery,
      mutated in place as events arrive;
    - derived summaries (`current_state()` -> StudentTwinState) — computed
      fresh from the above on demand, never stored redundantly.
    """

    def __init__(self, student: Student, strategy: UpdateStrategy | None = None) -> None:
        self.student = student
        self.strategy: UpdateStrategy = strategy or SimpleIncrementalUpdateStrategy()
        self.knowledge_states: dict[str, KnowledgeState] = {}
        self.interaction_history: list[Interaction] = []
        self.assessment_results: list[AssessmentResult] = []
        self.xapi_engagement_counts: XapiEngagementCounts | None = None
        self.dropout_risk: DropoutPrediction | None = None
        self.performance_prediction: StudentPerformancePrediction | None = None

    def attach_xapi_engagement_counts(self, counts: XapiEngagementCounts) -> None:
        """Attach one xAPI-Edu-Data behavioral snapshot to this twin's engagement summary.

        Not chronological history like `apply_interaction`/
        `apply_assessment_result`: xAPI-Edu-Data is a single whole-semester
        snapshot per student (see `XapiEngagementCounts`'s docstring), so
        this replaces any previously attached counts rather than
        accumulating a sequence.
        """
        self.xapi_engagement_counts = counts

    def attach_dropout_risk(self, prediction: DropoutPrediction) -> None:
        """Attach one externally-computed dropout-risk prediction to this twin.

        The twin never fits or calls the model itself — `prediction` comes
        from `analytics/predictive.py`'s `predict()` run over a row of
        `data/repositories/oulad_dropout_features.py`'s snapshot. A point-
        in-time result, not a history: replaces any previously attached
        prediction rather than accumulating a sequence, same posture as
        `attach_xapi_engagement_counts`.
        """
        self.dropout_risk = prediction

    def attach_performance_prediction(self, prediction: StudentPerformancePrediction) -> None:
        """Attach one externally-computed Pass/Fail prediction to this twin.

        The twin never fits or calls the model itself — `prediction` comes
        from `analytics/performance_prediction.py`'s `predict()` run over a
        row of `data/repositories/oulad_performance_features.py`'s
        snapshot. A point-in-time result, not a history: replaces any
        previously attached prediction rather than accumulating a
        sequence, same posture as `attach_xapi_engagement_counts`.
        """
        self.performance_prediction = prediction

    def apply_interaction(self, interaction: Interaction) -> KnowledgeState | None:
        """Record `interaction` and update its topic's KnowledgeState, if scorable.

        Returns None for interactions the strategy can't score (no
        topic_id, no outcome — e.g. a RESOURCE_VIEW event) instead of
        raising, so a caller can feed a mixed interaction stream without
        pre-filtering it first. The interaction is still recorded in
        `interaction_history` either way.
        """
        if interaction.student_id != self.student.student_id:
            raise ValueError("Interaction.student_id does not match this twin's student")

        self.interaction_history.append(interaction)

        if interaction.topic_id is None or interaction.outcome is None:
            return None

        previous = self.knowledge_states.get(interaction.topic_id)
        updated = self.strategy.update(previous, interaction)
        self.knowledge_states[interaction.topic_id] = updated
        return updated

    def apply_assessment_result(self, result: AssessmentResult) -> None:
        """Record one AssessmentResult in this student's history.

        Does not affect `knowledge_states` in this MVP: `UpdateStrategy`
        only takes an Interaction (see update_strategies.py). Feeding
        formal assessment outcomes into mastery updates is a deliberate
        later extension, not implemented here.
        """
        if result.student_id != self.student.student_id:
            raise ValueError("AssessmentResult.student_id does not match this twin's student")
        self.assessment_results.append(result)

    def process_events(self, events: Iterable[TwinEvent]) -> None:
        """Apply a stream of Interaction/AssessmentResult events in chronological order.

        Events are sorted by their own timestamp (`occurred_at` for
        Interaction, `submitted_at` for AssessmentResult) before being
        applied, rather than trusting caller ordering — a stable sort, so
        same-timestamp events keep their relative input order.
        """
        for event in sorted(events, key=_event_timestamp):
            if isinstance(event, Interaction):
                self.apply_interaction(event)
            else:
                self.apply_assessment_result(event)

    def mastery_for(self, topic_id: str) -> float | None:
        """Current mastery_probability for `topic_id`, or None if unobserved."""
        state = self.knowledge_states.get(topic_id)
        return state.mastery_probability if state is not None else None

    def current_state(self) -> StudentTwinState:
        """A read-only snapshot of this twin's current derived state."""
        return StudentTwinState(
            student_id=self.student.student_id,
            knowledge_states=dict(self.knowledge_states),
            engagement=self._engagement_summary(),
            assessment_performance=self._assessment_summary(),
            dropout_risk=self.dropout_risk,
            performance_prediction=self.performance_prediction,
            total_observations=sum(ks.observation_count for ks in self.knowledge_states.values()),
            as_of=self._as_of(),
        )

    def _engagement_summary(self) -> EngagementSummary:
        if not self.interaction_history:
            return EngagementSummary(xapi_behavioral_counts=self.xapi_engagement_counts)

        # Sorted explicitly, same defensive posture as _assessment_summary:
        # apply_interaction doesn't sort (only process_events does).
        ordered = sorted(self.interaction_history, key=lambda i: i.occurred_at)

        daily_counts: dict[date, int] = {}
        for interaction in ordered:
            day = interaction.occurred_at.date()
            daily_counts[day] = daily_counts.get(day, 0) + 1
        active_days_chronological = sorted(daily_counts)

        trend: Literal["increasing", "decreasing", "stable"] | None = None
        recent_days = active_days_chronological[-RECENT_ENGAGEMENT_WINDOW_DAYS:]
        earlier_days = active_days_chronological[:-RECENT_ENGAGEMENT_WINDOW_DAYS]
        if earlier_days:
            recent_average = sum(daily_counts[d] for d in recent_days) / len(recent_days)
            earlier_average = sum(daily_counts[d] for d in earlier_days) / len(earlier_days)
            delta = recent_average - earlier_average
            if delta > ENGAGEMENT_TREND_EPSILON:
                trend = "increasing"
            elif delta < -ENGAGEMENT_TREND_EPSILON:
                trend = "decreasing"
            else:
                trend = "stable"

        return EngagementSummary(
            total_interactions=len(ordered),
            resource_interaction_days=sum(
                1 for i in ordered if i.interaction_type == InteractionType.RESOURCE_VIEW
            ),
            problem_attempts=sum(
                1 for i in ordered if i.interaction_type == InteractionType.PROBLEM_ATTEMPT
            ),
            correct_attempts=sum(1 for i in ordered if i.outcome is True),
            incorrect_attempts=sum(1 for i in ordered if i.outcome is False),
            active_days=len(daily_counts),
            trend=trend,
            last_interaction_at=ordered[-1].occurred_at,
            xapi_behavioral_counts=self.xapi_engagement_counts,
        )

    def _assessment_summary(self) -> AssessmentPerformanceSummary:
        if not self.assessment_results:
            return AssessmentPerformanceSummary()

        # Sorted explicitly rather than trusting insertion order: callers may
        # invoke apply_assessment_result directly (out of order), unlike
        # process_events, which already sorts before applying.
        ordered = sorted(self.assessment_results, key=lambda r: r.submitted_at)
        scores = [r.score for r in ordered]

        recent_scores = scores[-RECENT_ASSESSMENT_WINDOW:]
        earlier_scores = scores[:-RECENT_ASSESSMENT_WINDOW]
        recent_average_score = sum(recent_scores) / len(recent_scores)

        trend: Literal["improving", "declining", "stable"] | None = None
        if earlier_scores:
            earlier_average_score = sum(earlier_scores) / len(earlier_scores)
            delta = recent_average_score - earlier_average_score
            if delta > TREND_EPSILON:
                trend = "improving"
            elif delta < -TREND_EPSILON:
                trend = "declining"
            else:
                trend = "stable"

        return AssessmentPerformanceSummary(
            total_results=len(ordered),
            average_score=sum(scores) / len(scores),
            recent_average_score=recent_average_score,
            trend=trend,
            last_assessment_at=ordered[-1].submitted_at,
        )

    def _as_of(self) -> datetime | None:
        timestamps = [i.occurred_at for i in self.interaction_history]
        timestamps += [r.submitted_at for r in self.assessment_results]
        return max(timestamps) if timestamps else None
