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

---

## ADR-008: Public dataset combination for M1 (grounding "synthetic-first" in real data)

**Context:** ADR-002 committed to starting on synthetic data, but the
synthetic generators need to model *realistic* distributions and the twin
engine's update logic needs to be validated against something real, not just
internally-consistent fake data. A systematic search compared 27 public
datasets (full research in [docs/DATASETS.md](docs/DATASETS.md)) across
academic performance, engagement/affect, environmental/occupancy, and
attendance/anomaly categories, scored on suitability, AI usefulness, ease of
implementation, data quality, public availability, documentation, and
internship-timeline feasibility.

**Decision:** adopt this dataset combination, each covering distinct project
objectives with no redundant overlap:

- **OULAD** (Open University Learning Analytics Dataset) as the spine —
  performance, engagement (VLE clicks), dropout, resource/VLE utilization.
- **UCI "Predict Students' Dropout and Academic Success"** — dropout
  refinement with socioeconomic/macro features.
- **xAPI-Edu-Data** — fine-grained behavioral engagement features.
- **ASSISTments 2009–2010 (corrected file)** — knowledge tracing /
  recommendation-system objective.
- **UCI Occupancy Detection Data Set** — clean supervised benchmark for the
  occupancy/environmental classification methodology.
- **Spanish Classroom CO2 dataset (Zenodo)** — real classroom-sourced
  environmental sensor data to apply that methodology to.
- **NYC DOE Daily Attendance** (via Kaggle mirror) — attendance forecasting.
- **Numenta Anomaly Benchmark (NAB)** — anomaly-detection algorithm
  validation, decoupled from whichever sensor stream it's later pointed at.

Optional stretch (not required for the core system): **Building Data Genome
Project 2** for a larger-scale resource/energy-utilization module.

Explicitly rejected for the core project, with reasons logged in
docs/DATASETS.md: DAiSEE and both IEEE Dataport candidates (access friction —
15GB data-use agreement / paywall — disproportionate to an internship
timeline), KDD Cup 2015/XuetangX (official access is broken — dead domain,
invite-only mirror), several Kaggle "toy"/synthetic datasets (fine as demos,
not as a system backbone), and OECD PISA (rigorous but not classroom/
time-series data, heavy SAS/SPSS format overhead for what it would add).

**Consequences:** every dataset in the combination has a verified,
currently-working, no-registration download and an unambiguous permissive
license (CC BY 4.0 dominant, MIT for NAB) — no milestone depends on an
access-gated or provenance-uncertain source. The combination mixes real
institutional data with real classroom-specific sensor data rather than
leaning entirely on generic-building stand-ins. It maps directly onto
existing module boundaries (`twin_engine/`, `analytics/`, `agents/tools.py`)
so M1–M5 in PROJECT_PLAN.md can each target a specific dataset rather than
inventing schemas speculatively. Risk: OULAD's UK distance-learning context
and the Spanish CO2 dataset's narrow COVID-reopening window are both
real-but-imperfect proxies for a "typical" physical classroom — this is an
accepted tradeoff given no perfect classroom-native, freely-licensed,
digital-twin-specific dataset was found (see docs/DATASETS.md's negative
finding). Synthetic generators (ADR-002) should be tuned to approximate the
real distributions observed in this combination, not invented from scratch.
