"""FastAPI application entrypoint.

Routers are registered here once the corresponding domain module has
a working implementation.
"""

from fastapi import FastAPI

from digital_twin.api.routers import classrooms, students
from digital_twin.config import get_settings

settings = get_settings()

app = FastAPI(title="AI Digital Twin for a Smart Classroom", version="0.1.0")

app.include_router(students.router)
app.include_router(classrooms.router)

# TODO: include_router() calls go here as each remaining router
# (twin, analytics, agent) gets a working implementation.
