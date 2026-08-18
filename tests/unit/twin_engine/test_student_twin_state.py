"""Tests for StudentTwin's chronological event processing and current-state snapshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from digital_twin.analytics.performance_prediction import StudentPerformancePrediction
from digital_twin.analytics.predictive import DropoutPrediction
from digital_twin.domain.assessment import AssessmentResult
from digital_twin.domain.interaction import Interaction, InteractionType
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin, TwinEvent, XapiEngagementCounts

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _interaction(
    student_id: UUID,
    minute: int,
    topic_id: str | None,
    outcome: bool | None,
    interaction_type: InteractionType = InteractionType.PROBLEM_ATTEMPT,
) -> Interaction:
    return Interaction(
        student_id=student_id,
        occurred_at=BASE_TIME + timedelta(minutes=minute),
        interaction_type=interaction_type,
        topic_id=topic_id,
        outcome=outcome,
    )


def _day_interaction(student_id: UUID, day: int) -> Interaction:
    """A RESOURCE_VIEW Interaction on BASE_TIME + `day` days, for active-day/trend tests."""
    return Interaction(
        student_id=student_id,
        occurred_at=BASE_TIME + timedelta(days=day),
        interaction_type=InteractionType.RESOURCE_VIEW,
    )


def _result(student_id: UUID, minute: int, score: float) -> AssessmentResult:
    return AssessmentResult(
        student_id=student_id,
        assessment_id=uuid4(),
        score=score,
        submitted_at=BASE_TIME + timedelta(minutes=minute),
    )


def test_new_student_twin_has_empty_state() -> None:
    student = Student()
    twin = StudentTwin(student)
    state = twin.current_state()

    assert state.student_id == student.student_id
    assert state.knowledge_states == {}
    assert state.engagement.total_interactions == 0
    assert state.engagement.active_days == 0
    assert state.engagement.trend is None
    assert state.engagement.xapi_behavioral_counts is None
    assert state.assessment_performance.total_results == 0
    assert state.assessment_performance.average_score is None
    assert state.assessment_performance.recent_average_score is None
    assert state.assessment_performance.trend is None
    assert state.dropout_risk is None
    assert state.performance_prediction is None
    assert state.total_observations == 0
    assert state.as_of is None


def test_process_events_applies_out_of_order_events_chronologically() -> None:
    student = Student()
    twin = StudentTwin(student)

    # Passed out of chronological order on purpose.
    events: list[TwinEvent] = [
        _interaction(student.student_id, minute=10, topic_id="algebra", outcome=True),
        _interaction(student.student_id, minute=0, topic_id="algebra", outcome=False),
    ]
    twin.process_events(events)

    # Chronological order is incorrect (minute 0) then correct (minute 10):
    # 0.5 -> 0.5 + 0.3*(0-0.5) = 0.35 -> 0.35 + 0.3*(1-0.35) = 0.545.
    # Applying the list's given order would instead land on 0.455 — this
    # value only comes out right if process_events actually sorts first.
    state = twin.current_state()
    assert state.knowledge_states["algebra"].observation_count == 2
    assert state.knowledge_states["algebra"].mastery_probability == pytest.approx(0.545)
    assert state.as_of == BASE_TIME + timedelta(minutes=10)


def test_assessment_result_updates_summary_not_mastery() -> None:
    student = Student()
    twin = StudentTwin(student)
    twin.apply_assessment_result(_result(student.student_id, minute=0, score=80.0))
    twin.apply_assessment_result(_result(student.student_id, minute=5, score=90.0))

    state = twin.current_state()
    assert state.assessment_performance.total_results == 2
    assert state.assessment_performance.average_score == pytest.approx(85.0)
    assert state.assessment_performance.last_assessment_at == BASE_TIME + timedelta(minutes=5)
    assert state.knowledge_states == {}


def test_single_assessment_result_has_no_trend_yet() -> None:
    """One result can't be split into a "recent window" and "everything before it"."""
    student = Student()
    twin = StudentTwin(student)
    twin.apply_assessment_result(_result(student.student_id, minute=0, score=80.0))

    performance = twin.current_state().assessment_performance
    assert performance.total_results == 1
    assert performance.average_score == pytest.approx(80.0)
    assert performance.recent_average_score == pytest.approx(80.0)
    assert performance.trend is None


def test_assessment_trend_detects_improving_performance() -> None:
    student = Student()
    twin = StudentTwin(student)
    for minute, score in enumerate([50.0, 50.0, 50.0, 90.0, 90.0, 90.0]):
        twin.apply_assessment_result(_result(student.student_id, minute, score))

    performance = twin.current_state().assessment_performance
    assert performance.total_results == 6
    assert performance.recent_average_score == pytest.approx(90.0)
    assert performance.trend == "improving"


def test_assessment_trend_detects_declining_performance() -> None:
    student = Student()
    twin = StudentTwin(student)
    for minute, score in enumerate([90.0, 90.0, 90.0, 50.0, 50.0, 50.0]):
        twin.apply_assessment_result(_result(student.student_id, minute, score))

    performance = twin.current_state().assessment_performance
    assert performance.recent_average_score == pytest.approx(50.0)
    assert performance.trend == "declining"


def test_assessment_trend_reports_stable_for_flat_performance() -> None:
    student = Student()
    twin = StudentTwin(student)
    for minute, score in enumerate([80.0, 81.0, 79.0, 80.0, 80.5, 79.5]):
        twin.apply_assessment_result(_result(student.student_id, minute, score))

    assert twin.current_state().assessment_performance.trend == "stable"


def test_assessment_summary_orders_by_submission_time_not_insertion_order() -> None:
    """apply_assessment_result (unlike process_events) doesn't sort — the summary must."""
    student = Student()
    twin = StudentTwin(student)
    # Inserted out of chronological order on purpose.
    twin.apply_assessment_result(_result(student.student_id, minute=10, score=90.0))
    twin.apply_assessment_result(_result(student.student_id, minute=0, score=50.0))

    performance = twin.current_state().assessment_performance
    assert performance.last_assessment_at == BASE_TIME + timedelta(minutes=10)
    # Chronologically, minute=0 (score 50) came before minute=10 (score 90);
    # with only 2 results and a window of 3, both fall in the recent window.
    assert performance.recent_average_score == pytest.approx(70.0)


def test_engagement_summary_counts_interaction_types_and_outcomes() -> None:
    student = Student()
    twin = StudentTwin(student)
    twin.apply_interaction(
        _interaction(student.student_id, 0, None, None, InteractionType.RESOURCE_VIEW)
    )
    twin.apply_interaction(_interaction(student.student_id, 1, "algebra", True))
    twin.apply_interaction(_interaction(student.student_id, 2, "algebra", False))

    summary = twin.current_state().engagement
    assert summary.total_interactions == 3
    assert summary.resource_interaction_days == 1
    assert summary.problem_attempts == 2
    assert summary.correct_attempts == 1
    assert summary.incorrect_attempts == 1
    assert summary.last_interaction_at == BASE_TIME + timedelta(minutes=2)
    # All 3 interactions occurred within the same minute-scale BASE_TIME day.
    assert summary.active_days == 1


def test_active_days_counts_distinct_calendar_dates_not_interactions() -> None:
    student = Student()
    twin = StudentTwin(student)
    # Two interactions on day 0, one on day 1: 3 interactions, 2 active days.
    twin.apply_interaction(_day_interaction(student.student_id, 0))
    twin.apply_interaction(_interaction(student.student_id, 5, None, None))
    twin.apply_interaction(_day_interaction(student.student_id, 1))

    summary = twin.current_state().engagement
    assert summary.total_interactions == 3
    assert summary.active_days == 2


def test_engagement_summary_orders_by_occurred_at_not_insertion_order() -> None:
    """apply_interaction (unlike process_events) doesn't sort — the summary must."""
    student = Student()
    twin = StudentTwin(student)
    # Inserted out of chronological order on purpose.
    twin.apply_interaction(_day_interaction(student.student_id, 10))
    twin.apply_interaction(_day_interaction(student.student_id, 0))

    summary = twin.current_state().engagement
    assert summary.last_interaction_at == BASE_TIME + timedelta(days=10)


def test_single_active_day_has_no_engagement_trend_yet() -> None:
    student = Student()
    twin = StudentTwin(student)
    twin.apply_interaction(_day_interaction(student.student_id, 0))

    assert twin.current_state().engagement.trend is None


def test_engagement_trend_detects_increasing_activity() -> None:
    student = Student()
    twin = StudentTwin(student)
    # Earlier days: 1 interaction/day. Recent 3 days: 4 interactions/day.
    for day in range(3):
        twin.apply_interaction(_day_interaction(student.student_id, day))
    for day in range(3, 6):
        for _ in range(4):
            twin.apply_interaction(_day_interaction(student.student_id, day))

    summary = twin.current_state().engagement
    assert summary.active_days == 6
    assert summary.trend == "increasing"


def test_engagement_trend_detects_decreasing_activity() -> None:
    student = Student()
    twin = StudentTwin(student)
    for day in range(3):
        for _ in range(4):
            twin.apply_interaction(_day_interaction(student.student_id, day))
    for day in range(3, 6):
        twin.apply_interaction(_day_interaction(student.student_id, day))

    assert twin.current_state().engagement.trend == "decreasing"


def test_engagement_trend_reports_stable_for_flat_activity() -> None:
    student = Student()
    twin = StudentTwin(student)
    for day in range(6):
        twin.apply_interaction(_day_interaction(student.student_id, day))

    assert twin.current_state().engagement.trend == "stable"


def test_attach_xapi_engagement_counts_is_independent_of_interaction_history() -> None:
    student = Student()
    twin = StudentTwin(student)
    counts = XapiEngagementCounts(
        raised_hands=10, visited_resources=20, announcements_view=1, discussion=5
    )

    twin.attach_xapi_engagement_counts(counts)
    empty_history_summary = twin.current_state().engagement
    assert empty_history_summary.xapi_behavioral_counts == counts
    assert empty_history_summary.total_interactions == 0

    twin.apply_interaction(_day_interaction(student.student_id, 0))
    with_history_summary = twin.current_state().engagement
    assert with_history_summary.xapi_behavioral_counts == counts
    assert with_history_summary.total_interactions == 1


def test_attach_xapi_engagement_counts_replaces_not_accumulates() -> None:
    student = Student()
    twin = StudentTwin(student)
    first = XapiEngagementCounts(
        raised_hands=1, visited_resources=1, announcements_view=1, discussion=1
    )
    second = XapiEngagementCounts(
        raised_hands=9, visited_resources=9, announcements_view=9, discussion=9
    )

    twin.attach_xapi_engagement_counts(first)
    twin.attach_xapi_engagement_counts(second)

    assert twin.current_state().engagement.xapi_behavioral_counts == second


def test_attach_dropout_risk_is_independent_of_interaction_history() -> None:
    student = Student()
    twin = StudentTwin(student)
    prediction = DropoutPrediction(dropout_probability=0.73, predicted_class=1)

    twin.attach_dropout_risk(prediction)
    empty_history_state = twin.current_state()
    assert empty_history_state.dropout_risk == prediction
    assert empty_history_state.total_observations == 0

    twin.apply_interaction(_day_interaction(student.student_id, 0))
    with_history_state = twin.current_state()
    assert with_history_state.dropout_risk == prediction


def test_attach_dropout_risk_replaces_not_accumulates() -> None:
    student = Student()
    twin = StudentTwin(student)
    first = DropoutPrediction(dropout_probability=0.2, predicted_class=0)
    second = DropoutPrediction(dropout_probability=0.9, predicted_class=1)

    twin.attach_dropout_risk(first)
    twin.attach_dropout_risk(second)

    assert twin.current_state().dropout_risk == second


def test_attach_performance_prediction_is_independent_of_interaction_history() -> None:
    student = Student()
    twin = StudentTwin(student)
    prediction = StudentPerformancePrediction(pass_probability=0.64, predicted_class=1)

    twin.attach_performance_prediction(prediction)
    empty_history_state = twin.current_state()
    assert empty_history_state.performance_prediction == prediction
    assert empty_history_state.total_observations == 0

    twin.apply_interaction(_day_interaction(student.student_id, 0))
    with_history_state = twin.current_state()
    assert with_history_state.performance_prediction == prediction


def test_attach_performance_prediction_replaces_not_accumulates() -> None:
    student = Student()
    twin = StudentTwin(student)
    first = StudentPerformancePrediction(pass_probability=0.1, predicted_class=0)
    second = StudentPerformancePrediction(pass_probability=0.95, predicted_class=1)

    twin.attach_performance_prediction(first)
    twin.attach_performance_prediction(second)

    assert twin.current_state().performance_prediction == second


def test_dropout_risk_and_performance_prediction_are_independent_of_each_other() -> None:
    student = Student()
    twin = StudentTwin(student)
    dropout = DropoutPrediction(dropout_probability=0.4, predicted_class=0)
    performance = StudentPerformancePrediction(pass_probability=0.6, predicted_class=1)

    twin.attach_dropout_risk(dropout)
    twin.attach_performance_prediction(performance)

    state = twin.current_state()
    assert state.dropout_risk == dropout
    assert state.performance_prediction == performance


def test_process_events_rejects_event_for_another_student() -> None:
    student = Student()
    twin = StudentTwin(student)
    other_student_event = _interaction(uuid4(), 0, "algebra", True)
    with pytest.raises(ValueError, match="does not match"):
        twin.process_events([other_student_event])


def test_apply_assessment_result_rejects_mismatched_student() -> None:
    student = Student()
    twin = StudentTwin(student)
    with pytest.raises(ValueError, match="does not match"):
        twin.apply_assessment_result(_result(uuid4(), 0, 50.0))


def test_state_bounded_and_consistent_after_mixed_stream() -> None:
    student = Student()
    twin = StudentTwin(student)
    events: list[TwinEvent] = [
        _interaction(student.student_id, m, "algebra", outcome=(m % 3 != 0)) for m in range(30)
    ]
    events.append(_result(student.student_id, 30, score=70.0))

    twin.process_events(events)
    state = twin.current_state()

    mastery = state.knowledge_states["algebra"].mastery_probability
    assert 0.0 <= mastery <= 1.0
    assert state.total_observations == 30
    assert state.assessment_performance.total_results == 1
    assert state.as_of == BASE_TIME + timedelta(minutes=30)


def test_topics_remain_independent_through_process_events() -> None:
    student = Student()
    twin = StudentTwin(student)
    events: list[TwinEvent] = [
        _interaction(student.student_id, 0, "algebra", outcome=True),
        _interaction(student.student_id, 1, "geometry", outcome=False),
    ]
    twin.process_events(events)

    algebra = twin.current_state().knowledge_states["algebra"]
    geometry = twin.current_state().knowledge_states["geometry"]
    assert algebra.mastery_probability > 0.5
    assert geometry.mastery_probability < 0.5
    assert algebra.observation_count == 1
    assert geometry.observation_count == 1
