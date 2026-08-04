# Architectural Decision Records

Lightweight ADR log. Each entry: context, decision, consequences. Add a new
entry rather than editing history when a decision changes — mark the old one
superseded.

---

## ADR-001: Modular monolith over microservices

**Context:** the system has several distinct concerns (twin state, analytics,
LLM agents, API) that *could* be separate services.

**Decision:** build as a single deployable Python service (FastAPI) with
strict internal module boundaries (`api/`, `twin_engine/`, `analytics/`,
`agents/`, `data/`), not as separate microservices.

**Consequences:** much simpler to build, test, and deploy at this stage; no
network/serialization overhead between components; module boundaries are
enforced by convention/review rather than process isolation, so discipline in
CLAUDE.md matters. Can be split into services later if a specific component
(e.g., the twin engine) needs independent scaling — the module boundaries are
drawn so that split stays plausible.

---

## ADR-002: Hybrid data strategy — synthetic first, adapter interface for real data later

**Context:** no real classroom/LMS data source is available yet, but the
system must eventually work with real data.

**Decision:** development starts entirely on synthetic data
(`data/generators/`). A `data/adapters/base.py` interface is defined up front
so real data sources (LMS exports, SIS, sensors) can be implemented later as
adapters producing the same `domain/` types — no downstream code should need
to know or care which source fed it.

**Consequences:** twin engine, analytics, and agents can be built and tested
now without waiting on data-sharing agreements or compliance review. Real
integration work (M9) is scoped to writing adapters, not redesigning the
system. Risk: synthetic data may not capture real-world messiness (missing
data, inconsistent timestamps, outliers) — adapters and downstream code should
be revisited for robustness once real data is connected, not assumed correct
by construction.

---

## ADR-003: LLM agents (Claude) + classical ML for analytics — not LLM-only

**Context:** personalization and decision support could be built LLM-first
(reasoning over raw data in-context) or with a classical ML analytics layer
feeding a thinner LLM layer.

**Decision:** classical ML/statistics (scikit-learn, pandas) own analytics —
descriptive stats, predictive models (at-risk detection), clustering. LLM
agents (Anthropic Claude, via the `anthropic` SDK) own natural-language
reasoning — tutoring dialogue and turning analytics output into narrative
recommendations. Agents call into analytics/twin_engine via tools rather than
reasoning over raw data directly.

**Consequences:** predictions are reproducible, testable, and auditable
(important for anything influencing academic decisions); LLM usage is scoped
to what LLMs are actually good at (language, synthesis, dialogue) rather than
numerical prediction. Slightly more integration work (defining tool schemas)
than an LLM-first approach.

---

## ADR-004: FastAPI as the API framework

**Context:** need a Python API framework with good async support, automatic
schema generation, and a low ceremony-to-capability ratio.

**Decision:** FastAPI + Uvicorn.

**Consequences:** built-in OpenAPI docs, native Pydantic integration (shared
validation story with `domain/`/`schemas/`), async support for I/O-bound work
(DB, Anthropic API calls). Standard choice, minimal risk.

---

## ADR-005: PostgreSQL + SQLAlchemy for persistence

**Context:** need durable storage for student/classroom/interaction/assessment
data and derived twin state.

**Decision:** PostgreSQL as the primary datastore, accessed via SQLAlchemy 2.x
with Alembic migrations, behind a repository pattern (`data/repositories/`) —
no other layer imports SQLAlchemy directly.

**Consequences:** relational model fits the entity relationships well
(students ↔ classrooms ↔ interactions ↔ assessments); repository pattern keeps
persistence swappable and keeps business logic testable without a real DB. No
vector store included yet — if agents later need retrieval over unstructured
content (course materials, notes), that will be a separate ADR when the need
is concrete rather than speculative.

---

## ADR-006: src-layout Python packaging

**Context:** how to lay out the Python package to avoid import ambiguity and
support clean packaging/testing.

**Decision:** `src/digital_twin/` layout (not a flat top-level package),
installed editable (`pip install -e .`) for development.

**Consequences:** prevents accidentally importing from the working directory
instead of the installed package (a common source of subtle test bugs);
standard, well-supported pattern with `pyproject.toml` + hatchling.

---

## ADR-007: Privacy-by-design for student data, even before real data exists

**Context:** the project's long-term purpose is to work with real student
data (M9), which implicates FERPA (US) and/or GDPR (EU) depending on
deployment context, even though current development uses only synthetic data.

**Decision:** treat the `data/adapters/` boundary as the point where real
student data enters the system, and require (from ADR inception, not
retroactively) that: no real data is ever committed to the repo; any code path
touching real data avoids logging PII; anonymization/consent handling is
designed into adapters, not bolted on after M9 begins.

**Consequences:** slightly more upfront discipline in `data/adapters/` design
even though there's no real adapter yet (see `data/adapters/base.py`). Avoids
a costly retrofit of the twin/analytics/agent layers later if privacy
requirements would otherwise have leaked into them. Actual legal/compliance
review is deferred to M9 when a real data source and deployment context are
known — this ADR sets engineering posture, not a compliance sign-off.
