"""Endpoints for interacting with the tutor / decision-support agents."""

from fastapi import APIRouter

router = APIRouter(prefix="/agent", tags=["agent"])

# TODO: implement endpoints once agents/ is wired to the Anthropic client.
