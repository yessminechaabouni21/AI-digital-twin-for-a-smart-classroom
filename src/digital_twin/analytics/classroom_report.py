"""Human-readable classroom skill-priority + resource-recommendation report.

Pure formatting over already-computed outputs from `analytics/skill_priority.py`
and `analytics/resource_recommendation.py` — no computation of its own, no
SQLAlchemy/scikit-learn import, per CLAUDE.md's module boundaries. Kept
separate so `scripts/classroom_skill_priority_demo.py` (and any future
caller) gets one shared, testable report format instead of ad hoc prints.
"""

from __future__ import annotations

from digital_twin.analytics.resource_recommendation import ClassroomResourceRecommendation
from digital_twin.analytics.skill_priority import SkillPriorityRecommendation
from digital_twin.twin_engine.classroom_twin import ClassroomTwinState


def format_classroom_priority_report(
    state: ClassroomTwinState,
    skill_priorities: list[SkillPriorityRecommendation],
    resource_recommendation: ClassroomResourceRecommendation | None,
    *,
    source_class_id: int | None = None,
    top_n: int = 3,
) -> str:
    """Render one concise report: classroom identity, top weak skills, recommended problems.

    `skill_priorities`/`resource_recommendation` are taken as already
    computed (by `skill_priority.recommend_skill_priorities` and
    `resource_recommendation.recommend_classroom_resource`) — this function
    only formats them, it never re-derives, re-ranks, or fabricates
    anything not already present in its inputs.
    """
    lines = [
        "=== Classroom Digital Twin Report ===",
        f"classroom_id (twin):        {state.classroom_id}",
        f"classroom_id (ASSISTments): {source_class_id if source_class_id is not None else 'n/a'}",
        f"students:                   {state.roster_size}",
        f"topics observed:            {len(state.average_mastery_by_topic)}",
        "",
        f"Top {top_n} weakest reliable skills:",
    ]

    top_priorities = skill_priorities[:top_n]
    if not top_priorities:
        lines.append("  (none met the minimum observation-count reliability threshold)")
    else:
        for rank, priority in enumerate(top_priorities, start=1):
            lines.append(
                f"  {rank}. {priority.topic_id:15s} "
                f"average_mastery={priority.average_mastery:.3f} "
                f"observation_count={priority.observation_count}"
            )

    lines.append("")
    if resource_recommendation is None:
        lines.append("Recommended problems: none (no skill met the reliability threshold)")
    else:
        lines.append(
            f"Recommended problems for top-priority skill '{resource_recommendation.topic_id}':"
        )
        if not resource_recommendation.recommended_problems:
            lines.append("  (no problem in the catalog had enough recorded answers to recommend)")
        else:
            for problem in resource_recommendation.recommended_problems:
                lines.append(
                    f"  problem_id={problem.problem_id:<8} "
                    f"mean_correct={problem.mean_correct:.3f} "
                    f"student_answer_count={problem.student_answer_count}"
                )

    return "\n".join(lines)


__all__ = ["format_classroom_priority_report"]
