"""FastAPI application entrypoint.

Routers are registered here once the corresponding domain module has
a working implementation.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from digital_twin.api.routers import classrooms, demo, students
from digital_twin.config import get_settings

settings = get_settings()

app = FastAPI(title="AI Digital Twin for a Smart Classroom", version="0.1.0")

# Permissive by design: this API has no auth yet (pre-M9/real-data phase, see
# DECISIONS.md ADR-007) and is only ever run locally for development/demo —
# needed so the static dashboard (served from a different origin/port, or
# opened as a file://) can call it directly from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(students.router)
app.include_router(classrooms.router)
app.include_router(demo.router)

# TODO: include_router() calls go here as each remaining router
# (twin, analytics, agent) gets a working implementation.
