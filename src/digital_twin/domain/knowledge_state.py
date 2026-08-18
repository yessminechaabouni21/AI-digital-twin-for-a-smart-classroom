"""Per-student, per-topic mastery/knowledge state representation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeState(BaseModel):
    """Current mastery estimate for one student on one skill/topic.

    `mastery_probability` is deliberately simple: a single float in [0, 1],
    updateable by any strategy (Bayesian Knowledge Tracing, IRT, ...) that
    twin_engine/update_strategies.py implements later. This model defines
    only the shape, never the update logic — twin_engine is the only place
    that logic lives (see CLAUDE.md's module boundaries).

    `topic_id` reuses ASSISTments' existing skill identifiers where
    available (assist_problems.skills) rather than inventing a
    cross-dataset taxonomy. OULAD has no topic/skill concept at all, so no
    such identifier is invented for it, and no join is forced between the
    two.
    """

    student_id: UUID
    topic_id: str
    mastery_probability: float = Field(ge=0.0, le=1.0)
    observation_count: int = Field(default=0, ge=0)
    updated_at: datetime
