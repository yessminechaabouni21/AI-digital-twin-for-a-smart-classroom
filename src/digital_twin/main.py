"""FastAPI application entrypoint.

Routers are registered here once the corresponding domain module has
a working implementation. Intentionally empty until then.
"""

from fastapi import FastAPI

from digital_twin.config import get_settings

settings = get_settings()

app = FastAPI(title="AI Digital Twin for a Smart Classroom", version="0.1.0")

# TODO: include_router() calls go here as each router is implemented
# (see src/digital_twin/api/routers/).
