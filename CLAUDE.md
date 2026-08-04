# CLAUDE.md

Guidance for AI-assisted (and human) development on this repository. Read this
before implementing anything. Also read [DECISIONS.md](DECISIONS.md) for the
reasoning behind constraints stated here as fact.

## What this project is

A modular-monolith Python service that maintains a "digital twin" (continuously
updated state model) of students and classrooms, exposes analytics over that
state, and layers LLM agents on top for tutoring and decision support. See
[README.md](README.md) for the architecture diagram and [PROJECT_PLAN.md](PROJECT_PLAN.md)
for where we are in the roadmap.

## Module boundaries — do not violate these

- `domain/` — pure data models. No imports from `api/`, `data/db/`, `agents/`,
  or any framework beyond pydantic. This is the shared vocabulary; if you need
  a new concept, add it here first.
- `twin_engine/` — the only place twin *state-update* logic lives. Analytics and
  agents may **read** twin state (via repositories) but must not reimplement or
  duplicate update logic.
- `analytics/` — classical ML/stats only (scikit-learn, pandas). No Anthropic
  SDK calls here.
- `agents/` — the only place Anthropic SDK calls live. Agents call into
  `twin_engine/` and `analytics/` through defined tools (`agents/tools.py`), they
  don't reach into `data/db/` directly.
- `data/db/` and `data/repositories/` — the only layers allowed to talk to the
  database. Nothing else imports SQLAlchemy directly.
- `data/adapters/` — interface + implementations for *real* external data
  sources (LMS, SIS, sensors). `data/generators/` is synthetic data only. Both
  produce the same `domain/` types, so downstream code can't tell which one fed
  it — keep it that way.
- `api/` — thin. Routers validate input, call a repository/service, return a
  response. No business logic in route handlers.

## Conventions

- **Python 3.11+**, full type hints everywhere, `mypy --strict` must pass.
- **src-layout**: importable code lives under `src/digital_twin/`, import as
  `from digital_twin.xxx import ...`.
- **Pydantic v2** for domain models and API schemas. Keep `domain/` models and
  `schemas/` (API request/response) separate even when they look identical
  today — they will diverge (API versioning, field renaming) and coupling them
  makes that painful later.
- **No comments explaining *what* code does** — name things well instead. A
  comment is only warranted for a non-obvious *why* (a workaround, a subtle
  invariant). This matches the TODO-style placeholders currently in the
  scaffolded files — replace the TODO with real code, not with an explanation
  of the TODO.
- **Repository pattern** for all persistence — services/routers depend on
  repository interfaces, not on SQLAlchemy sessions directly.
- **Formatting/linting**: `ruff` (lint) + `black` (format) + `mypy` (types).
  Run all three before considering work done. Configs are in `pyproject.toml`.
- **Tests**: pytest. Unit tests in `tests/unit/` mirror the `src/digital_twin/`
  package layout 1:1. Integration tests (DB, API, real Anthropic calls) go in
  `tests/integration/` and should be skippable without credentials/DB access.

## LLM / Anthropic usage

- Use the `anthropic` Python SDK, not raw HTTP.
- Default model: `claude-sonnet-5` (see `Settings.anthropic_model` in
  `config.py`). Don't hardcode model strings in `agents/` — read from settings.
- Agents should be **grounded**: pull actual twin/analytics state via tools
  (`agents/tools.py`) rather than letting the model free-associate about a
  student. If the data needed to answer isn't available, the agent should say
  so rather than fabricate it — this matters more here than in most projects
  because outputs may influence real academic decisions.
- Prompt templates live in `agents/prompts/`, not inlined as strings in agent
  modules.

## Data & privacy

- Synthetic data (`data/generators/`) is the default and safe to use freely in
  tests, notebooks, and local dev.
- Anything under `data/adapters/` that talks to a real data source must assume
  it is handling real student data and treat it accordingly (no logging of PII,
  no committing sample real data into the repo, no writing real data into
  `notebooks/` outputs). See ADR-007 in DECISIONS.md.
- Never commit `.env`, database dumps, or exported student data. `.gitignore`
  already excludes `data/raw/`, `data/processed/`, `data/synthetic/` contents
  (structure is kept via `.gitkeep`).

## Workflow expectations

- Update [TODO.md](TODO.md) as tasks are completed/added — it should reflect
  actual near-term work, not aspirational scope (that belongs in
  PROJECT_PLAN.md).
- Log non-trivial architectural choices in [DECISIONS.md](DECISIONS.md) as a
  new ADR entry — don't just make the change silently.
- Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]` for user-visible or
  API-visible changes.
- Don't jump ahead of the current milestone in PROJECT_PLAN.md (e.g., don't
  build the agent layer before `domain/` and `twin_engine/` have working,
  tested implementations) — later layers depend on earlier ones being stable.

## What NOT to do

- Don't add a frontend/dashboard folder speculatively — it's a later milestone
  (see PROJECT_PLAN.md) and isn't scoped yet.
- Don't introduce a message queue, microservices split, or new datastore
  without discussing it first — current architecture is deliberately a single
  Postgres-backed monolith (ADR-001, ADR-005).
- Don't implement real LMS/sensor adapters against assumed schemas — wait
  until a real integration target is chosen; build against `data/adapters/base.py`'s
  interface using synthetic data until then.
