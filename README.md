# AI Digital Twin for a Smart Classroom

An AI-enabled Digital Twin framework for student learning and smart-classroom decision support, combining Bayesian Knowledge Tracing, machine learning, real educational datasets, and an optional LLM explanation layer.

## What's implemented

- **Student Twin** (`twin_engine/student_twin.py`) — per-student mastery
  state, updated per problem attempt via
  `BayesianKnowledgeTracingStrategy` (`twin_engine/update_strategies.py`),
  built from real ASSISTments attempt sequences
  (`data/repositories/assistments_problem_attempts.py`).
- **Classroom Twin** (`twin_engine/classroom_twin.py`) — aggregates a
  classroom's Student Twins into a roster-level view (mastery by topic,
  engagement, assessment performance), feeding a deterministic,
  rule-based decision-support layer (`analytics/decision_support.py`):
  priority skill, recommended resources, evidence, limitations. No LLM
  involved in computing any of it.
- **Optional LLM explanation** (`agents/decision_support_agent.py`) — a
  Claude agent that explains the deterministic decision-support result in
  plain language, on request (`POST .../decision-support/explanation`). It
  never computes mastery, priority, or recommendations itself; it narrates
  numbers that already exist.
- **OULAD Student Twin perspective** (`GET /students/oulad-demo`) — a
  second, independent student-level view built from real OULAD
  assessment/dropout/performance data. OULAD has no shared identifier with
  ASSISTments — this demonstrates the same StudentTwin architecture on a
  second real dataset, not a link to the classroom above. Dropout-risk and
  pass-probability predictions are only ever shown for a student whose row
  fell in the underlying model's own held-out test split (see DECISIONS.md
  ADR-010); otherwise the response says so instead of guessing.
- **Smart-classroom demonstration scenario**
  (`data/generators/synthetic_classroom_scenario.py`) — a deterministic,
  clearly-labeled *synthetic* environment/engagement scenario, illustrating
  how a live sensor/engagement feed could plug into a classroom's twin.
  Never presented as a real observation.
- **Benchmark evidence** — xAPI-Edu-Data (behavioral engagement +
  absence-risk model) and UCI Occupancy Detection (room-occupancy
  classifier). Both real datasets, both shown explicitly as benchmark /
  model-validation evidence — neither shares an identifier with any
  ASSISTments classroom, so neither is ever presented as this classroom's
  actual attendance or actual occupancy.
- **Dashboard** (`dashboard/`) — static HTML/JS/CSS over the FastAPI
  backend. No build step, no framework.



## Architecture

```
ASSISTments  ->  StudentTwin (BKT)  ->  ClassroomTwin
                                             |
                                             v
                              Deterministic decision support
                                             |
                                             v
                            Optional LLM explanation (Claude)

OULAD               ->  Student Twin (dropout / performance), independent
CO2 sensors         ->  Classroom environment, only when explicitly linked
xAPI-Edu-Data       ->  Benchmark / contextual evidence, not classroom-linked
UCI Occupancy       ->  Benchmark / model validation, not classroom-linked
Synthetic scenario  ->  Demonstration only, clearly labeled
```

Modular monolith: one FastAPI service with enforced internal module
boundaries (`api/`, `twin_engine/`, `analytics/`, `agents/`, `data/`)
rather than microservices — see [DECISIONS.md](DECISIONS.md) ADR-001.

## Knowledge-tracing research (M1-M4)

`scripts/run_kt_experiment.py` runs a controlled, leakage-free comparison of
knowledge-tracing models on real ASSISTments data: student-level train/
validation/test split, 11,828 held-out one-step-ahead predictions, 400 test
students, 281 skills. Frozen results (Log Loss is the primary metric):

| Model | Log Loss | Brier | RMSE | Accuracy | ROC-AUC |
|---|---|---|---|---|---|
| Persistence baseline | 5.6257 | 0.3078 | 0.5548 | 66.45% | 0.6387 |
| Empirical-rate baseline | 0.6394 | 0.2236 | 0.4728 | 66.33% | 0.5000 |
| Literature-default BKT | 0.6341 | 0.2167 | 0.4655 | 65.29% | 0.6624 |
| Train-fitted BKT | 0.5968 | 0.2045 | 0.4522 | 68.64% | 0.6731 |
| BKT + historical features (LR) | 0.5825 | 0.1983 | 0.4453 | 70.05% | 0.6995 |
| Historical features (GBM) | 0.5779 | 0.1966 | 0.4434 | 70.47% | 0.7056 |

Both feature-based models achieved lower test-set log loss than train-fitted BKT, with student-level bootstrap 95% confidence intervals for the log-loss difference excluding zero. (LR: −0.0144 [−0.0190, −0.0098]; GBM:
−0.0190 [−0.0242, −0.0138]). These numbers are frozen: nothing in this repo,
including the dashboard, re-runs or re-tunes the experiment — the dashboard
shows them as static constants, clearly separated from the live decision
support above.

Log loss was defined as the primary evaluation metric because the task is probabilistic next-attempt prediction; accuracy, Brier score, RMSE and ROC-AUC were reported as secondary metrics.

## Running it (Windows)

Requires Python 3.11+ and a local PostgreSQL instance with the datasets
above already loaded (see [docs/DATASETS.md](docs/DATASETS.md) and
[docs/datasets/](docs/datasets/) for the per-dataset preprocessing plans and
loader scripts.

```powershell
# 1. Virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2. Install
pip install -e ".[dev]"

# 3. Configure
copy .env.example .env
# edit .env: DATABASE_URL for your local Postgres, ANTHROPIC_API_KEY if you
# want the optional LLM explanation feature (everything else works without it)

# 4. Run the backend
uvicorn digital_twin.main:app --reload --app-dir src
```

Backend: `http://127.0.0.1:8000`. Interactive API docs (Swagger UI):
**http://127.0.0.1:8000/docs**.

### Dashboard

Static files, no build step. With the backend running:

```powershell
# Simplest: open directly in a browser
start dashboard\index.html

# Or serve it (equivalent, useful for some tooling/browser setups):
cd dashboard
python -m http.server 8080
# then open http://127.0.0.1:8080/index.html
```

`dashboard/app.js`'s `API_BASE` constant points at
`http://127.0.0.1:8000` — edit it if the backend runs elsewhere. The
backend's CORS is intentionally permissive (`allow_origins=["*"]`) so the
dashboard can call it from a `file://` page or a different port.

### Tests

```powershell
pytest tests/unit          # no database required
pytest tests/integration   # requires the live Postgres instance above; each test skips cleanly if it's unreachable
```

## Repository structure

```
src/digital_twin/
├── api/            FastAPI routers actually wired in: students, classrooms, demo
├── analytics/      classical ML/stats — BKT calibration + the knowledge-tracing
│                    experiment, OULAD dropout/performance models, occupancy
│                    detection, xAPI absence-risk, skill priority, decision-support
│                    formatting
├── agents/         Claude-backed decision-support explanation agent
├── twin_engine/    StudentTwin / ClassroomTwin state + update strategies (BKT)
├── domain/         framework-free pydantic domain models
├── data/
│   ├── repositories/  the only layer that touches Postgres/SQLAlchemy
│   ├── generators/    synthetic classroom-scenario generator (demo only)
│   ├── adapters/      interface stub for a future real LMS/sensor source
│   └── db/             SQLAlchemy models + session
├── schemas/        API request/response models (Pydantic)
└── main.py         FastAPI app entrypoint

dashboard/          static HTML/JS/CSS research/demo UI (no build step)
scripts/            one-off operational and experiment scripts
tests/              unit/ (no DB) + integration/ (live Postgres)
docs/               dataset research and preprocessing plans
```

## Documentation

- [PROJECT_PLAN.md](PROJECT_PLAN.md) — milestone roadmap
- [DECISIONS.md](DECISIONS.md) — architectural decision records
- [CHANGELOG.md](CHANGELOG.md) — change history
- [docs/DATASETS.md](docs/DATASETS.md) — dataset documentation index
