"""Endpoints for reading/triggering digital twin state updates."""

from fastapi import APIRouter

router = APIRouter(prefix="/twin", tags=["twin"])

# TODO: implement endpoints once twin_engine/ has a working update loop.
