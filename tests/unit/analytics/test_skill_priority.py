"""Focused tests for the rule-based classroom skill priority ranking."""

from __future__ import annotations

from uuid import uuid4

from digital_twin.analytics.skill_priority import (
    DEFAULT_MIN_OBSERVATIONS,
    recommend_skill_priorities,
)
from digital_twin.twin_engine.classroom_twin import (
    ClassroomAssessmentSummary,
    ClassroomEngagementSummary,
    ClassroomEnvironmentSummary,
    ClassroomTwinState,
)


def _state(
    average_mastery_by_topic: dict[str, float], topic_observation_counts: dict[str, int]
) -> ClassroomTwinState:
    return ClassroomTwinState(
        classroom_id=uuid4(),
        source_student_count=None,
        roster_size=len(average_mastery_by_topic),
        average_mastery_by_topic=average_mastery_by_topic,
        topic_observation_counts=topic_observation_counts,
        engagement=ClassroomEngagementSummary(),
        assessment_performance=ClassroomAssessmentSummary(),
        environment=ClassroomEnvironmentSummary(),
        as_of=None,
    )


def test_ranks_lowest_mastery_first() -> None:
    state = _state(
        {"algebra": 0.8, "geometry": 0.3, "fractions": 0.5},
        {"algebra": 10, "geometry": 10, "fractions": 10},
    )

    recommendations = recommend_skill_priorities(state)

    assert [r.topic_id for r in recommendations] == ["geometry", "fractions", "algebra"]


def test_priority_score_is_one_minus_average_mastery() -> None:
    state = _state({"algebra": 0.3}, {"algebra": 10})

    [recommendation] = recommend_skill_priorities(state)

    assert recommendation.average_mastery == 0.3
    assert recommendation.priority_score == 0.7
    assert recommendation.observation_count == 10


def test_excludes_topics_below_min_observations() -> None:
    state = _state(
        {"algebra": 0.1, "geometry": 0.9},
        {"algebra": DEFAULT_MIN_OBSERVATIONS - 1, "geometry": DEFAULT_MIN_OBSERVATIONS},
    )

    recommendations = recommend_skill_priorities(state)

    assert [r.topic_id for r in recommendations] == ["geometry"]


def test_min_observations_is_configurable() -> None:
    state = _state({"algebra": 0.1}, {"algebra": 1})

    assert recommend_skill_priorities(state, min_observations=1) != []
    assert recommend_skill_priorities(state, min_observations=2) == []


def test_ties_in_mastery_broken_by_higher_observation_count() -> None:
    state = _state(
        {"algebra": 0.5, "geometry": 0.5},
        {"algebra": 20, "geometry": 5},
    )

    recommendations = recommend_skill_priorities(state)

    assert [r.topic_id for r in recommendations] == ["algebra", "geometry"]


def test_empty_classroom_state_returns_no_recommendations() -> None:
    state = _state({}, {})

    assert recommend_skill_priorities(state) == []
