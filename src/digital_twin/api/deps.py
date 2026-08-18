"""Shared FastAPI dependencies (DB engine, LLM explanation provider)."""

from __future__ import annotations

from sqlalchemy import Engine

from digital_twin.agents.decision_support_agent import (
    AnthropicExplanationProvider,
    ExplanationProvider,
)
from digital_twin.data.db.session import get_engine


def get_db_engine() -> Engine:
    """FastAPI dependency: the process-wide SQLAlchemy engine.

    Thin wrapper over data/db/session.get_engine() so route handlers
    depend on this rather than importing data/db/session directly —
    CLAUDE.md's "routers call a repository/service" rule, without
    inventing new session-management machinery beyond what already exists.
    """
    return get_engine()


_explanation_provider: ExplanationProvider | None = None


def get_explanation_provider() -> ExplanationProvider:
    """FastAPI dependency: the process-wide LLM explanation provider.

    Routers depend on this, never on `AnthropicExplanationProvider`
    directly, so a future alternate provider needs no router change — and
    so tests can swap in a fake via `app.dependency_overrides` without
    needing a real `ANTHROPIC_API_KEY`. Construction is cheap
    (`AnthropicExplanationProvider.__init__` only reads the prompt file off
    disk; the Anthropic client itself is created lazily on first actual
    call), so no key is required unless the explanation endpoint is used.
    """
    global _explanation_provider
    if _explanation_provider is None:
        _explanation_provider = AnthropicExplanationProvider()
    return _explanation_provider


__all__ = ["get_db_engine", "get_explanation_provider"]
