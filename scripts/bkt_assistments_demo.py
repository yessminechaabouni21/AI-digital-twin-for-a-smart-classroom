"""Demonstrates: ASSISTments problem attempt -> Interaction -> BKT -> KnowledgeState.

Small, read-only example wiring the new `BayesianKnowledgeTracingStrategy`
into a `StudentTwin`, fed by one real ASSISTments student's chronological
problem attempts. Not a persisted pipeline, not a repository beyond the one
small query in `data/repositories/assistments_problem_attempts.py` — just
proof that the pieces connect end-to-end: real data in, per-topic mastery
out.

Run as: python -m scripts.bkt_assistments_demo [assistments_student_id]
"""

from __future__ import annotations

import sys

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.assistments_problem_attempts import (
    fetch_assistments_problem_attempts,
)
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

DEFAULT_ASSISTMENTS_STUDENT_ID = 52964


def main() -> None:
    configure_logging()

    assistments_student_id = (
        int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ASSISTMENTS_STUDENT_ID
    )

    student = Student(display_name=f"assistments-demo-{assistments_student_id}")

    engine = get_engine()
    interactions = fetch_assistments_problem_attempts(
        engine, assistments_student_id, twin_student_id=student.student_id
    )
    print(
        f"ASSISTments student_id={assistments_student_id}: "
        f"{len(interactions)} scorable problem attempts"
    )
    if not interactions:
        print("No scorable attempts found for this student_id.")
        return

    twin = StudentTwin(student, strategy=BayesianKnowledgeTracingStrategy())

    for interaction in interactions:
        # `interactions` is already chronological (see fetch_assistments_problem_attempts);
        # apply_interaction, not process_events, to avoid a redundant re-sort.
        twin.apply_interaction(interaction)

    print(f"\nTopics observed: {len(twin.knowledge_states)}")
    for topic_id, state in sorted(twin.knowledge_states.items()):
        print(
            f"  {topic_id:20s} mastery={state.mastery_probability:.3f} "
            f"observations={state.observation_count}"
        )


if __name__ == "__main__":
    main()
