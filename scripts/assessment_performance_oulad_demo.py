"""Demonstrates: OULAD assessment submission -> AssessmentResult -> StudentTwin -> summary.

Small, read-only example wiring one real OULAD student's assessment
submissions into a StudentTwin, then reading back the derived
`AssessmentPerformanceSummary` (count, average, recent average, trend) from
`StudentTwinState`. Not a persisted pipeline, not a repository beyond the
one small query in `data/repositories/oulad_assessment_results.py` — proof
that the pieces connect end-to-end.

Run as:
    python -m scripts.assessment_performance_oulad_demo [id_student] \\
        [code_module] [code_presentation]
"""

from __future__ import annotations

import sys

from digital_twin.core.logging import configure_logging
from digital_twin.data.db.session import get_engine
from digital_twin.data.repositories.oulad_assessment_results import (
    fetch_oulad_assessment_results,
)
from digital_twin.domain.student import Student
from digital_twin.twin_engine.student_twin import StudentTwin

DEFAULT_ID_STUDENT = 441201
DEFAULT_CODE_MODULE = "DDD"
DEFAULT_CODE_PRESENTATION = "2013B"


def main() -> None:
    configure_logging()

    id_student = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ID_STUDENT
    code_module = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CODE_MODULE
    code_presentation = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_CODE_PRESENTATION

    student = Student(display_name=f"oulad-demo-{id_student}")

    engine = get_engine()
    results = fetch_oulad_assessment_results(
        engine,
        id_student,
        code_module,
        code_presentation,
        twin_student_id=student.student_id,
    )
    print(
        f"OULAD id_student={id_student} {code_module}/{code_presentation}: "
        f"{len(results)} graded, non-banked submissions"
    )
    if not results:
        print("No scoreable assessment results found for this student/course.")
        return

    twin = StudentTwin(student)
    for result in results:
        twin.apply_assessment_result(result)

    performance = twin.current_state().assessment_performance
    print(f"\ntotal_results:        {performance.total_results}")
    print(f"average_score:        {performance.average_score:.2f}")
    print(f"recent_average_score: {performance.recent_average_score:.2f}")
    print(f"trend:                {performance.trend}")
    print(f"last_assessment_at:   {performance.last_assessment_at}")


if __name__ == "__main__":
    main()
