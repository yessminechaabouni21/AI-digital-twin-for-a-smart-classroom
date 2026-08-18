"""Assessment/quiz result entity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Assessment(BaseModel):
    """A formal, weighted graded task (exam, quiz, assignment).

    Shape follows OULAD's assessments/assessment_submissions split (the
    strongest real precedent for "graded outcome with weight and due date"
    in the project's dataset combination) without copying its schema —
    this is twin vocabulary, not a mirror of data/db/models.py::Assessment.
    """

    assessment_id: UUID = Field(default_factory=uuid4)
    title: str
    weight: float = Field(ge=0.0, le=1.0)
    due_at: datetime | None = None


class AssessmentResult(BaseModel):
    """One student's outcome on one Assessment.

    Carries no provenance/banked-score flag: OULAD's persistence layer
    already excludes banked scores (a previous presentation's effort) from
    the twin's read path (see AssessmentSubmission's docstring in
    data/db/models.py) — the domain layer should never see one to begin
    with, not re-filter it here.
    """

    student_id: UUID
    assessment_id: UUID
    score: float = Field(ge=0.0)
    submitted_at: datetime
