"""End-to-end real-data demo: the complete Classroom Digital Twin flow.

    1. Load one real ASSISTments classroom's roster (`assist_student_classes`).
    2. Build each student's StudentTwin from their real problem-attempt
       history, updated via Bayesian Knowledge Tracing -> per-topic
       KnowledgeState.
    3. Aggregate all attached StudentTwinState snapshots into one
       ClassroomTwin -> ClassroomTwinState (average_mastery_by_topic,
       topic_observation_counts).
    4. Rank topics with `analytics/skill_priority.recommend_skill_priorities`
       — a rule-based ranking over already-computed BKT mastery, gated by a
       minimum pooled observation count so a topic with only a handful of
       attempts can't outrank a well-observed one (see the audit this
       implements: ASSISTments has no independently recorded "optimal
       resource" label, so a supervised model here would be either
       redundant with BKT or trained on a circular/fabricated target).
    5. For the single highest-priority topic, look up real ASSISTments
       problems tagged with it and rank them by closeness to a
       desirable-difficulty target using their own recorded `mean_correct`
       (`analytics/resource_recommendation.recommend_classroom_resource`).

Every step after loading is rule-based over real, already-recorded
ASSISTments statistics — no ML, no fabricated or causal "this resource is
optimal" claim. All of this logic lives in `analytics/`, never in
`twin_engine`, which only builds/aggregates twin state.

Capped to `max_students` real students from the class roster (default
`MAX_STUDENTS`, overridable via a second CLI argument) to keep this a small
demo, not a full-class batch job — always the same fixed, lowest-`student_id`
slice of the real roster (`fetch_assistments_student_ids_for_class`'s own
`ORDER BY al.student_id`), never a random sample. The printed report states
how many of the class's real eligible students were actually used, so a
capped run is never mistaken for a complete roster.

Run as: python -m scripts.classroom_skill_priority_demo [class_id] [max_students]
"""

from __future__ import annotations

import sys

from digital_twin.analytics.classroom_report import format_classroom_priority_report
from digital_twin.analytics.resource_recommendation import recommend_classroom_resource
from digital_twin.analytics.skill_priority import recommend_skill_priorities
from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_problem_attempts,
    fetch_assistments_problems_for_skill,
    fetch_assistments_student_ids_for_class,
)
from digital_twin.domain.classroom import Classroom
from digital_twin.domain.student import Student
from digital_twin.twin_engine.classroom_twin import ClassroomTwin
from digital_twin.twin_engine.student_twin import StudentTwin
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

DEFAULT_CLASS_ID = 19723
MAX_STUDENTS = 15
TOP_N = 3


def _roster_status_line(used: int, eligible: int) -> str:
    """Report how many of this class's real eligible students were actually used.

    e.g. 'students used: 15 / 148 eligible (capped)' when `used < eligible`,
    or 'students used: 5 / 5 eligible' for a complete roster.
    """
    suffix = " (capped)" if used < eligible else ""
    return f"students used: {used} / {eligible} eligible{suffix}"


def main() -> None:
    configure_logging()
    engine = get_engine()

    class_id = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CLASS_ID
    max_students = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_STUDENTS

    # 1. Load one real classroom's roster.
    eligible_student_ids = fetch_assistments_student_ids_for_class(engine, class_id)
    student_ids = eligible_student_ids[:max_students]
    print(f"[1/5] ASSISTments class_id={class_id}: {len(student_ids)} students (roster loaded)")

    # 2-3. Build each student's twin, aggregate onto one ClassroomTwin.
    classroom_twin = ClassroomTwin(Classroom(source_class_id=class_id))
    for assistments_student_id in student_ids:
        student = Student(display_name=f"class-{class_id}-student-{assistments_student_id}")
        student_twin = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())

        attempts = fetch_assistments_problem_attempts(
            engine, assistments_student_id, twin_student_id=student.student_id
        )
        for interaction in attempts:
            student_twin.apply_interaction(interaction)

        classroom_twin.attach_student_state(student_twin.current_state())

    state = classroom_twin.current_state()
    print(
        f"[2/5] built {state.roster_size} StudentTwins (BKT) and attached them "
        f"to one ClassroomTwin"
    )
    print(f"[3/5] classroom aggregate: {len(state.average_mastery_by_topic)} topics observed")

    # 4. Rank topics by lowest reliable average mastery.
    skill_priorities = recommend_skill_priorities(state)
    print(f"[4/5] ranked {len(skill_priorities)} reliably-observed topics by priority")

    # 5. Recommend problems for the single highest-priority topic.
    resource_recommendation = None
    if skill_priorities:
        top_topic_id = skill_priorities[0].topic_id
        problem_candidates = fetch_assistments_problems_for_skill(engine, top_topic_id)
        resource_recommendation = recommend_classroom_resource(
            skill_priorities, {top_topic_id: problem_candidates}
        )
        print(
            f"[5/5] found {len(problem_candidates)} catalog problems tagged '{top_topic_id}', "
            f"ranked by desirable difficulty"
        )
    else:
        print("[5/5] no topic met the reliability threshold; skipping problem lookup")

    print()
    print(
        format_classroom_priority_report(
            state,
            skill_priorities,
            resource_recommendation,
            source_class_id=class_id,
            top_n=TOP_N,
        )
    )
    print(_roster_status_line(len(student_ids), len(eligible_student_ids)))


if __name__ == "__main__":
    main()
