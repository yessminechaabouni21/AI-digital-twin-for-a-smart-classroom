"""Application-wide logging configuration."""

from __future__ import annotations

import logging

from digital_twin.config import get_settings

_configured = False


def configure_logging() -> None:
    """Configure stdlib logging once, driven by Settings.log_level.

    Idempotent — safe to call from multiple entry points (scripts, the API
    app, tests) without producing duplicate handlers.
    """
    global _configured
    if _configured:
        return

    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    _configured = True
