# Project Plan

Milestone roadmap for the AI Digital Twin for a Smart Classroom. Each milestone
lists its goal, key deliverables, and exit criteria. Milestones are meant to be
built roughly in order — later layers (analytics, agents, API) depend on
earlier ones (domain models, twin engine) being stable.

## M0 — Project scaffolding ✅ (2026-08-04)

**Goal:** a professional, navigable project skeleton before any logic is written.

- Deliverables: directory structure, README, CLAUDE.md, PROJECT_PLAN.md,
  TODO.md, DECISIONS.md, CHANGELOG.md, requirements.txt, pyproject.toml,
  .gitignore, .env.example, git repository initialized.
- Exit criteria: repo clones clean, `pip install -e ".[dev]"` succeeds,
  structure matches README.

## M1 — Domain models & synthetic data

**Goal:** a shared vocabulary (Student, Classroom, Interaction, Assessment,
KnowledgeState) and the ability to generate realistic fake data for everything
downstream to develop against.

- Deliverables: `domain/` models (pydantic), `data/generators/synthetic.py`
  producing consistent synthetic students/classrooms/interactions/assessments,
  unit tests for both.
- Exit criteria: can generate a synthetic classroom of N students with a
  history of interactions/assessments, fully typed and validated.

## M2 — Persistence layer

**Goal:** durable storage for domain entities.

- Deliverables: SQLAlchemy models in `data/db/models.py`, session management
  in `data/db/session.py`, Alembic migrations set up, repository
  implementations in `data/repositories/` for each domain entity.
- Exit criteria: synthetic data can be generated and persisted, then read back
  via repositories; migrations run cleanly against a fresh Postgres instance.

## M3 — Digital twin engine (core)

**Goal:** the actual state-update logic — this is the core of the project.

- Deliverables: `twin_engine/student_twin.py` (per-student state + update
  method), `twin_engine/classroom_twin.py` (aggregation), at least one working
  `update_strategies.py` implementation (e.g., a simple Bayesian knowledge
  tracing or IRT-style update).
- Exit criteria: feeding a sequence of synthetic interactions/assessments
  through the twin produces a knowledge-state trajectory that responds
  sensibly to correct/incorrect performance (validated with unit tests, not
  just eyeballing).

## M4 — Analytics engine

**Goal:** descriptive and predictive insight over twin state + raw data.

- Deliverables: `analytics/descriptive.py` (engagement/performance summaries),
  `analytics/predictive.py` (at-risk / performance forecasting model),
  `analytics/clustering.py` (learning-pattern grouping).
- Exit criteria: given a synthetic classroom's history, analytics functions
  produce reasonable, tested outputs; predictive model has a documented
  baseline accuracy/metric.

## M5 — LLM agent layer

**Goal:** Claude-based tutoring and decision-support, grounded in real twin/
analytics state via tool use.

- Deliverables: `agents/tools.py` (tool schemas over twin_engine/analytics),
  `agents/tutor_agent.py`, `agents/decision_support_agent.py`, prompt templates
  in `agents/prompts/`.
- Exit criteria: tutor agent answers a question about a specific synthetic
  student using that student's actual twin state (not hallucinated); decision-
  support agent produces a narrative recommendation traceable to specific
  analytics output.

## M6 — API layer

**Goal:** expose everything above over HTTP.

- Deliverables: implemented routers in `api/routers/` (students, classrooms,
  analytics, twin, agent), request/response schemas in `schemas/`, dependency
  wiring in `api/deps.py`.
- Exit criteria: end-to-end request against a running instance (backed by
  synthetic data) exercises twin update → analytics → agent response through
  the HTTP API.

## M7 — Testing & CI

**Goal:** confidence the system stays correct as it grows.

- Deliverables: unit test coverage for domain/twin_engine/analytics, integration
  tests for API + DB, CI pipeline (lint, type-check, test) on every push.
- Exit criteria: CI green on main; coverage tracked (target documented once
  baseline is measured).

## M8 — Dashboard / frontend (stretch)

**Goal:** a usable interface for teachers/admins, not just raw API.

- Deliverables: TBD (Streamlit for a fast internal tool, or a proper React
  frontend) — decision deferred until M6 API surface is stable.
- Exit criteria: TBD.

## M9 — Real data integration (stretch)

**Goal:** connect to a real LMS/SIS/sensor source instead of synthetic data.

- Deliverables: a concrete `data/adapters/` implementation for a chosen real
  source, privacy/compliance review (FERPA/GDPR — see DECISIONS.md ADR-007),
  data anonymization/consent handling as needed.
- Exit criteria: real (or realistic anonymized) data flows through the same
  twin/analytics/agent pipeline validated on synthetic data in M1-M5, with no
  changes required to those layers beyond the adapter itself.
