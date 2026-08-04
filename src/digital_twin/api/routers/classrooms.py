"""Endpoints for classroom resources (roster, aggregate twin state)."""

from fastapi import APIRouter

router = APIRouter(prefix="/classrooms", tags=["classrooms"])

# TODO: implement endpoints once ClassroomRepository exists.
