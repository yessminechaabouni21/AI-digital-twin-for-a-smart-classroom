"""A single student interaction event (question asked, resource viewed, etc.)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class InteractionType(StrEnum):
    """Discriminates the two real-data flavors this model unifies.

    RESOURCE_VIEW matches OULAD's per-day VLE click engagement (no
    correctness signal). PROBLEM_ATTEMPT matches ASSISTments' per-problem
    attempts (a correct/incorrect signal via `outcome`). One generic event
    shape, not two dataset-shaped ones.
    """

    RESOURCE_VIEW = "resource_view"
    PROBLEM_ATTEMPT = "problem_attempt"


class Interaction(BaseModel):
    """One atomic engagement/attempt event for a student.

    `topic_id` reuses ASSISTments' existing skill identifiers where
    available rather than inventing a cross-dataset taxonomy; it is left
    unset for OULAD-shaped (RESOURCE_VIEW) events, since OULAD has no
    topic/skill concept at all. No relationship is forced between OULAD
    course/module identifiers and ASSISTments skill identifiers — they
    stay in their own independent tables in data/db/models.py.
    """

    interaction_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    occurred_at: datetime
    interaction_type: InteractionType
    topic_id: str | None = None
    # Correctness signal for PROBLEM_ATTEMPT events; always None for
    # RESOURCE_VIEW events, which carry no correctness.
    outcome: bool | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
