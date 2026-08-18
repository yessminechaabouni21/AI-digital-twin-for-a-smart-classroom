"""Demonstrates: OULAD VLE clicks -> StudentTwin -> engagement.

Small, read-only example wiring one real OULAD student's VLE clickstream
into a StudentTwin as RESOURCE_VIEW interactions.

This demo does not use xAPI-Edu-Data because that dataset has no
student-identifying column and therefore cannot be legitimately associated
with this OULAD student.

Run as:
    python -m scripts.engagement_oulad_xapi_demo [id_student] \
        [code_module] [code_presentation]
"""

from __future__ import annotations

import sys

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.oulad_vle_interactions import (
    fetch_oulad_vle_interactions,
)
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin


DEFAULT_ID_STUDENT = 557710
DEFAULT_CODE_MODULE = "FFF"
DEFAULT_CODE_PRESENTATION = "2013B"


def main() -> None:
    configure_logging()

    id_student = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ID_STUDENT
    code_module = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CODE_MODULE
    code_presentation = (
        sys.argv[3] if len(sys.argv) > 3 else DEFAULT_CODE_PRESENTATION
    )

    student = Student(display_name=f"engagement-demo-{id_student}")
    twin = StudentTwin(student)

    engine = get_engine()
    interactions = fetch_oulad_vle_interactions(
        engine,
        id_student,
        code_module,
        code_presentation,
        twin_student_id=student.student_id,
    )

    print(
        f"OULAD id_student={id_student} "
        f"{code_module}/{code_presentation}: "
        f"{len(interactions)} VLE-click interactions"
    )

    for interaction in interactions:
        twin.apply_interaction(interaction)

    engagement = twin.current_state().engagement

    print("\n=== StudentTwin Engagement ===")
    print(f"total_interactions:        {engagement.total_interactions}")
    print(
        f"resource_interaction_days: "
        f"{engagement.resource_interaction_days}"
    )
    print(f"problem_attempts:          {engagement.problem_attempts}")
    print(f"active_days:               {engagement.active_days}")
    print(f"trend:                     {engagement.trend}")
    print(f"last_interaction_at:       {engagement.last_interaction_at}")


if __name__ == "__main__":
    main()