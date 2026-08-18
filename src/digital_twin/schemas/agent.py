"""Typed HTTP response schemas for LLM explanation endpoints.

Deliberately separate from `agents/decision_support_agent.py`'s
`LLMDecisionExplanation` (same reasoning as `schemas/classrooms.py`'s
separation from `analytics/decision_support.py`'s types): response shapes
only, so API versioning/field-renaming never forces a change to the
agent-internal type.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class LLMDecisionExplanationOut(BaseModel):
    """Structured, teacher-facing explanation of an already-computed classroom analysis.

    Every field is produced by `agents/decision_support_agent.py`'s
    `ExplanationProvider` from an already-computed `ClassroomDecisionSupport`
    — this schema adds no new computation, only response shaping. `mode`
    is `"real"` for a genuine classroom or `"demo"` for a demonstration
    request; when `"demo"`, `summary` begins with "DEMONSTRATION MODE" (see
    `agents/prompts/decision_support_explanation.md`).
    """

    twin_id: UUID
    source_dataset: str
    source_class_id: int
    mode: Literal["real", "demo"]
    summary: str
    reasoning: str
    recommended_actions: list[str]
    evidence_used: list[str]
    limitations: list[str]


__all__ = ["LLMDecisionExplanationOut"]
