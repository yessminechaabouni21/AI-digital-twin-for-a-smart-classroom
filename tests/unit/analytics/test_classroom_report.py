"""Focused tests for the classroom priority + resource recommendation report formatter."""

from __future__ import annotations

from uuid import uuid4

from digital_twin.analytics.classroom_report import format_classroom_priority_report
from digital_twin.analytics.resource_recommendation import (
    ClassroomResourceRecommendation,
    ProblemRecommendation,
)
from digital_twin.analytics.skill_priority import SkillPriorityRecommendation
from digital_twin.twin_engine.classroom_twin import (
    ClassroomAssessmentSummary,
    ClassroomEngagementSummary,
    ClassroomEnvironmentSummary,
    ClassroomTwinState,
)


def _state(
    roster_size: int = 15, average_mastery_by_topic: dict[str, float] | None = None
) -> ClassroomTwinState:
    return ClassroomTwinState(
        classroom_id=uuid4(),
        source_student_count=None,
        roster_size=roster_size,
        average_mastery_by_topic=average_mastery_by_topic or {},
        topic_observation_counts={},
        engagement=ClassroomEngagementSummary(),
        assessment_performance=ClassroomAssessmentSummary(),
        environment=ClassroomEnvironmentSummary(),
        as_of=None,
    )


def _priority(
    topic_id: str, average_mastery: float, observation_count: int
) -> SkillPriorityRecommendation:
    return SkillPriorityRecommendation(
        topic_id=topic_id,
        priority_score=1.0 - average_mastery,
        average_mastery=average_mastery,
        observation_count=observation_count,
    )


def test_report_includes_classroom_identity_and_roster_size() -> None:
    state = _state(roster_size=15)

    report = format_classroom_priority_report(state, [], None, source_class_id=19723)

    assert str(state.classroom_id) in report
    assert "19723" in report
    assert "students:                   15" in report


def test_report_lists_top_n_weak_skills_with_mastery_and_observations() -> None:
    state = _state(average_mastery_by_topic={"geometry": 0.29, "algebra": 0.8})
    priorities = [
        _priority("geometry", 0.29, 248),
        _priority("algebra", 0.20, 14),
    ]

    report = format_classroom_priority_report(state, priorities, None, top_n=1)

    assert "1. geometry" in report
    assert "average_mastery=0.290" in report
    assert "observation_count=248" in report
    # top_n=1 must exclude the second entry even though it's ranked higher.
    assert "algebra" not in report


def test_report_lists_recommended_problems_with_difficulty_and_sample_count() -> None:
    state = _state()
    resource_recommendation = ClassroomResourceRecommendation(
        topic_id="geometry",
        priority_score=0.71,
        average_mastery=0.29,
        observation_count=248,
        recommended_problems=[
            ProblemRecommendation(
                problem_id=90161,
                mean_correct=0.658,
                student_answer_count=114,
                distance_from_target=0.008,
            )
        ],
    )

    report = format_classroom_priority_report(
        state, [_priority("geometry", 0.29, 248)], resource_recommendation
    )

    assert "problem_id=90161" in report
    assert "mean_correct=0.658" in report
    assert "student_answer_count=114" in report


def test_report_handles_no_reliable_skills() -> None:
    state = _state()

    report = format_classroom_priority_report(state, [], None)

    assert "none met the minimum observation-count reliability threshold" in report
    assert "Recommended problems: none" in report


def test_report_handles_reliable_skill_with_no_catalog_matches() -> None:
    state = _state(average_mastery_by_topic={"geometry": 0.29})
    resource_recommendation = ClassroomResourceRecommendation(
        topic_id="geometry",
        priority_score=0.71,
        average_mastery=0.29,
        observation_count=248,
        recommended_problems=[],
    )

    report = format_classroom_priority_report(
        state, [_priority("geometry", 0.29, 248)], resource_recommendation
    )

    assert "no problem in the catalog had enough recorded answers" in report
