# AI Digital Twin for a Smart Classroom

An intelligent virtual replica of students and classrooms for personalized learning,
classroom analytics, and academic decision support.

> **Status:** early scaffolding stage. Project structure, documentation, and tooling
> are in place; core logic has not been implemented yet. See [TODO.md](TODO.md) for
> the first implementation tasks and [PROJECT_PLAN.md](PROJECT_PLAN.md) for the
> milestone roadmap.

## What this is

A "digital twin" here is a continuously-updated state model of each student
(knowledge mastery per topic, engagement history, learning trajectory), rolled up
into a classroom-level view. The system uses that state to:

1. **Personalize learning** — an LLM-based tutor agent that grounds its answers in
   a student's actual twin state.
2. **Surface classroom analytics** — descriptive and predictive statistics
   (engagement trends, at-risk detection, learning-style clustering).
3. **Support academic decisions** — an LLM-based decision-support agent that turns
   analytics into narrative recommendations for teachers and administrators.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  API Layer (FastAPI) — students / classrooms / analytics /   │
│  twin / agent routers. Thin: validates, delegates, responds. │
└───────────────┬─────────────────────────────────────────────┘
                 │
   ┌─────────────┼───────────────┬───────────────────┐
   ▼              ▼               ▼                   ▼
┌────────┐  ┌──────────┐   ┌────────────┐   ┌──────────────────┐
│  Twin  │  │Analytics │   │   Agents   │   │  Data Layer       │
│ Engine │  │ Engine   │   │ (LLM, via  │   │  domain models,   │
│ (state │  │(descrip- │   │  Claude)   │   │  db + repos,      │
│ update │  │tive/pre- │   │  tutor +   │   │  Public datasets
                                               LMS adapters
                                               Sensor adapters
                                               Repositories     │
│ logic) │  │dictive)  │   │  decision- │   │,                  │
│        │  │          │   │  support)  │   │  source adapters  │
└────┬───┘  └────┬─────┘   └─────┬──────┘   └──────────────────┘
     └────────────┴───────────────┴─────────► via repositories
```

This is a **modular monolith**: one deployable Python service with strict internal
module boundaries, rather than separate microservices. It can be split into
services later if scale requires it — see [DECISIONS.md](DECISIONS.md) (ADR-001).

**Data strategy**:The system is built using publicly available educational, attendance, and classroom datasets. The architecture abstracts data access through adapters and repositories so that real LMS or IoT classroom data can be integrated in the future without modifying the core Digital Twin engine.

**AI approach**: classical ML (scikit-learn) for analytics/prediction, and
LLM agents (Anthropic Claude) for tutoring dialogue and decision-support
narratives (ADR-003).

## Project structure

```
src/digital_twin/
├── api/            # FastAPI routers (HTTP layer only)
├── core/           # cross-cutting: config, logging, security
├── domain/         # framework-free domain models (Student, Classroom, ...)
├── twin_engine/    # digital twin state + update logic (the core IP)
├── analytics/      # descriptive/predictive ML, clustering
├── agents/         # LLM-based tutor & decision-support agents
├── data/
│   ├── generators/    # synthetic data generation
│   ├── adapters/      # interfaces for real external data sources
│   ├── repositories/  # repository pattern — only layer touching the DB
│   └── db/             # SQLAlchemy models + session
├── schemas/        # API request/response models (Pydantic)
├── config.py       # Settings (env-driven)
└── main.py         # FastAPI app entrypoint

tests/              # unit/ + integration/
notebooks/          # exploratory analysis
scripts/            # one-off / operational scripts
docs/               # extended documentation
data/               # local data artifacts (gitignored, see .gitkeep files)
```

See [CLAUDE.md](CLAUDE.md) for detailed module boundaries and conventions.

## Tech stack

- **API**: FastAPI + Uvicorn
- **Data validation**: Pydantic v2 / pydantic-settings
- **Persistence**: PostgreSQL via SQLAlchemy 2.x + Alembic migrations
- **Analytics/ML**: pandas, numpy, scikit-learn
- **LLM agents**: Anthropic SDK (Claude)
- **Testing**: pytest, pytest-asyncio, pytest-cov
- **Quality**: ruff (lint), black (format), mypy (types)

## Getting started

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# 3. Configure environment
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
# then fill in ANTHROPIC_API_KEY and DATABASE_URL

# 4. Run tests (once implementation begins)
pytest

# 5. Run the API (once routes are implemented)
uvicorn digital_twin.main:app --reload --app-dir src
```

## Documentation

- [CLAUDE.md](CLAUDE.md) — conventions and guidance for AI-assisted development
- [PROJECT_PLAN.md](PROJECT_PLAN.md) — milestone roadmap
- [TODO.md](TODO.md) — current implementation tasks
- [DECISIONS.md](DECISIONS.md) — architectural decision records
- [CHANGELOG.md](CHANGELOG.md) — release history

## Privacy note
The system is designed around a data abstraction layer that currently uses publicly available datasets. The same architecture allows future integration with real classroom or Learning Management System (LMS) data while preserving the separation between data acquisition, analytics, and the Digital Twin engine.