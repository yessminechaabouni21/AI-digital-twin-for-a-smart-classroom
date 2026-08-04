# TODO

Near-term, actionable tasks only — reflects current work, not the full roadmap
(that's [PROJECT_PLAN.md](PROJECT_PLAN.md)). Update this file as tasks are
completed or added; don't let it go stale.

## Now — M1: Domain models & synthetic data

- [x] Research and select the public dataset combination that grounds the
      synthetic generators and validates the twin engine — see
      [docs/DATASETS.md](docs/DATASETS.md) and DECISIONS.md ADR-008.
- [ ] Download and inspect the core datasets locally (OULAD, UCI Dropout,
      xAPI-Edu-Data, ASSISTments corrected file, UCI Occupancy Detection,
      Spanish Classroom CO2, NYC DOE Attendance, NAB) into `data/raw/` —
      do not commit the raw files (already gitignored).
- [ ] Set up local dev environment: venv, `pip install -e ".[dev]"`, verify
      `pytest`, `ruff`, `mypy` all run cleanly on the current scaffold.
- [ ] Define `domain/knowledge_state.py`: `KnowledgeState` model (per-student,
      per-topic mastery representation — decide probability-based vs.
      categorical before implementing analytics/twin_engine against it).
- [ ] Define `domain/student.py`: `Student` model (id, profile, learning
      preferences).
- [ ] Define `domain/classroom.py`: `Classroom` model (id, subject, roster,
      schedule).
- [ ] Define `domain/interaction.py`: `Interaction` model (event type,
      timestamp, student/classroom refs, payload).
- [ ] Define `domain/assessment.py`: `Assessment` + `AssessmentResult` models.
- [ ] Implement `data/generators/synthetic.py` using Faker to produce
      consistent synthetic students, classrooms, interactions, and assessments
      that reference each other correctly, tuned to approximate the real
      distributions observed in the datasets selected in ADR-008.
- [ ] Unit tests for all of the above in `tests/unit/domain/` and
      `tests/unit/data/`.

## Next — groundwork for M2

- [ ] Decide on Postgres hosting for local dev (Docker container vs. local
      install) and document the choice in DECISIONS.md.
- [ ] Set up Alembic (`alembic init`) once `data/db/models.py` has a first
      real model to migrate.

## Housekeeping

- [ ] Add a GitHub Actions workflow (or equivalent CI) once there's code worth
      testing — lint + type-check + test on push. (Tracked here, not started;
      M7 in PROJECT_PLAN.md covers the full CI milestone.)
- [ ] Confirm `ANTHROPIC_API_KEY` handling — local `.env` only, never logged,
      never committed.
