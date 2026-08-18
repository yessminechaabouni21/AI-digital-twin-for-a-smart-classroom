"""Focused tests for the rule-based ASSISTments problem recommendation layer."""

from __future__ import annotations

import pytest

from digital_twin.analytics.resource_recommendation import (
    AssistmentsProblemCandidate,
    recommend_classroom_resource,
    recommend_problems_for_skill,
)
from digital_twin.analytics.skill_priority import SkillPriorityRecommendation


def _candidate(
    problem_id: int, mean_correct: float, student_answer_count: int = 50
) -> AssistmentsProblemCandidate:
    return AssistmentsProblemCandidate(
        problem_id=problem_id,
        mean_correct=mean_correct,
        mean_time_on_task=None,
        student_answer_count=student_answer_count,
    )


def _skill_priority(
    topic_id: str, average_mastery: float, observation_count: int = 10
) -> SkillPriorityRecommendation:
    return SkillPriorityRecommendation(
        topic_id=topic_id,
        priority_score=1.0 - average_mastery,
        average_mastery=average_mastery,
        observation_count=observation_count,
    )


def test_recommend_problems_for_skill_ranks_by_closeness_to_target() -> None:
    candidates = [
        _candidate(1, mean_correct=0.95),  # too easy
        _candidate(2, mean_correct=0.66),  # closest to default target 0.65
        _candidate(3, mean_correct=0.10),  # too hard
    ]

    recommendations = recommend_problems_for_skill(candidates)

    assert [r.problem_id for r in recommendations] == [2, 1, 3]
    assert recommendations[0].distance_from_target == pytest.approx(0.01)


def test_recommend_problems_for_skill_excludes_thin_data() -> None:
    candidates = [
        _candidate(1, mean_correct=0.65, student_answer_count=5),
        _candidate(2, mean_correct=0.40, student_answer_count=25),
    ]

    recommendations = recommend_problems_for_skill(candidates, min_student_answer_count=20)

    assert [r.problem_id for r in recommendations] == [2]


def test_recommend_problems_for_skill_respects_limit() -> None:
    candidates = [_candidate(i, mean_correct=0.65) for i in range(10)]

    recommendations = recommend_problems_for_skill(candidates, limit=2)

    assert len(recommendations) == 2


def test_recommend_problems_for_skill_empty_candidates_returns_empty() -> None:
    assert recommend_problems_for_skill([]) == []


def test_recommend_classroom_resource_returns_none_for_empty_priorities() -> None:
    assert recommend_classroom_resource([], {}) is None


def test_recommend_classroom_resource_uses_top_ranked_skill_only() -> None:
    priorities = [
        _skill_priority("geometry", average_mastery=0.3),
        _skill_priority("algebra", average_mastery=0.8),
    ]
    candidates_by_topic = {
        "geometry": [_candidate(1, mean_correct=0.65)],
        "algebra": [_candidate(2, mean_correct=0.65)],
    }

    recommendation = recommend_classroom_resource(priorities, candidates_by_topic)

    assert recommendation is not None
    assert recommendation.topic_id == "geometry"
    assert recommendation.average_mastery == 0.3
    assert [p.problem_id for p in recommendation.recommended_problems] == [1]


def test_recommend_classroom_resource_missing_catalog_entry_yields_no_fabricated_problems() -> None:
    priorities = [_skill_priority("geometry", average_mastery=0.3)]

    recommendation = recommend_classroom_resource(priorities, {})

    assert recommendation is not None
    assert recommendation.topic_id == "geometry"
    assert recommendation.recommended_problems == []
