# TODO

Near-term, actionable tasks only — reflects current work, not the full roadmap
(that's [PROJECT_PLAN.md](PROJECT_PLAN.md)). Update this file as tasks are
completed or added; don't let it go stale.

## Now — M1: Domain models 

- [x] Research and select the public dataset combination that grounds the
      synthetic generators and validates the twin engine — see
      [docs/DATASETS.md](docs/DATASETS.md) and DECISIONS.md ADR-008.
- [x] Download and inspect the core datasets locally (OULAD, UCI Dropout,
      xAPI-Edu-Data, ASSISTments corrected file, UCI Occupancy Detection,
      Spanish Classroom CO2, NYC DOE Attendance, NAB) into `data/raw/` —
      do not commit the raw files (already gitignored).
- [x] Set up local dev environment: venv, `pip install -e ".[dev]"`; `ruff`,
      `black`, `mypy --strict` verified clean against the code written so
      far. `pytest` runs cleanly but collects 0 tests — none written yet.
- [x] Preprocess OULAD and load it into PostgreSQL: SQLAlchemy models for
      the 6-table schema (`data/db/models.py`), one cleaning/validation
      module per source file plus the merge/aggregation stages
      (`data/preprocessing/`), and an end-to-end `load_oulad.py` loader —
      see [docs/datasets/oulad-preprocessing-plan.md](docs/datasets/oulad-preprocessing-plan.md).
      Loaded end-to-end against a live local Postgres instance: courses 22,
      vle_sites 6,364, assessments 206, enrollments 32,593,
      assessment_submissions 173,912, vle_interactions 8,459,320 rows —
      matches the preprocessing audit's numbers exactly, zero FK/PK
      violations.
- [x] Preprocess xAPI-Edu-Data and load it into PostgreSQL: 2-table schema
      (`XapiClassSection`, `XapiStudentRecord`, surrogate PK — no natural
      key exists), independent of OULAD, no join between them — see
      [docs/datasets/xapi-preprocessing-plan.md](docs/datasets/xapi-preprocessing-plan.md).
      Loaded end-to-end: xapi_class_sections 74, xapi_student_records 480
      rows (4 documented full-row duplicates kept, not dropped).
- [x] Preprocess ASSISTments 2019-2020 school year and load it into
      PostgreSQL: 7-table normalized schema (`assist_` prefix), independent
      of OULAD/xAPI — see
      [docs/datasets/assist-preprocessing-plan.md](docs/datasets/assist-preprocessing-plan.md).
      Loaded end-to-end: assist_districts 1,822 (standalone, no FK to
      anything in this release), assist_classes 17,003, assist_problems
      134,263 (392 identifier-less rows dropped, not invented), 
      assist_student_classes 286,592, assist_assignments 197,022,
      assist_assignment_logs 2,505,225, assist_problem_logs 20,752,836
      (392 problem_ids / 172,865 rows validated with a warning, not a hard
      FK — those problems' pdets row itself had no id). Zero unexpected
      FK/PK violations.
- [x] Preprocess the Spanish Classroom CO2 sensor dataset and load it into
      PostgreSQL: single-table schema (`co2_sensor_readings`, `co2_` prefix),
      natural composite PK `(sensor_id, recorded_at)`, independent of
      OULAD/xAPI/ASSISTments and of the UCI Occupancy Detection dataset — see
      [docs/datasets/spanish-co2-preprocessing-plan.md](docs/datasets/spanish-co2-preprocessing-plan.md).
      Loaded end-to-end: 38,477 rows (413 fully-duplicate retransmission rows
      dropped from the 38,890-row source), 6 sensors, zero PK collisions,
      zero nulls.
- [x] Preprocess the UCI Occupancy Detection dataset and load it into
      PostgreSQL: single-table schema (`occupancy_readings`), natural
      composite PK `(source_file, recorded_at)`, independent of OULAD/xAPI/
      ASSISTments and of the Spanish Classroom CO2 dataset — see
      [docs/datasets/occupancy-preprocessing-plan.md](docs/datasets/occupancy-preprocessing-plan.md).
      Combines the three time-disjoint source files (`datatraining.txt`,
      `datatest.txt`, `datatest2.txt`) into one logical table while
      preserving each row's originating split via `source_file`. Loaded
      end-to-end: 20,560 rows (8,143 + 2,665 + 9,752, none dropped), zero PK
      collisions, zero nulls, `occupancy` verified restricted to `{0, 1}`.
- [ ] Preprocess the UCI Dropout Prediction and NYC DOE Attendance datasets
      into PostgreSQL (`dropout_records`, `nyc_daily_attendance` —
      standalone, no shared identifier with any other schema).
- [ ] Unit tests for `data/preprocessing/` (validation helper edge cases,
      each stage's cleaning/null-handling rules, across all dataset
      pipelines) — not written yet, was out of scope for the initial
      preprocessing pipeline implementations.
- [x] Define `domain/student.py`, `domain/assessment.py` (`Assessment` +
      `AssessmentResult`), `domain/interaction.py` (`Interaction` +
      `InteractionType`), `domain/knowledge_state.py` (`KnowledgeState`,
      `mastery_probability` in [0,1] per topic — resolved probability-based,
      not categorical). Pure pydantic, no persistence/framework
      dependencies, no duplication of `data/db/models.py`'s schemas.
      `topic_id` reuses ASSISTments' existing skill identifiers where
      available rather than inventing a cross-dataset taxonomy; OULAD has
      no topic/skill concept, so none is invented for it either.
- [x] Define `domain/classroom.py`: `Classroom` (grounded in ASSISTments
      `assist_classes` — no subject/schedule field exists in any dataset
      this project loads, so none is invented) and
      `ClassroomEnvironmentReading` (grounded in the Spanish Classroom CO2
      sensor feed). `twin_engine/classroom_twin.py`'s `ClassroomTwin`
      aggregates attached `StudentTwinState` snapshots plus environment
      readings into a `ClassroomTwinState`.
- [x] Audit the environment/occupancy integration and wire the CO2 sensor
      feed to a real repository: `data/repositories/co2_sensor_readings.py`
      fetches one real `sensor_id`'s `co2_sensor_readings` rows as
      `ClassroomEnvironmentReading`s; `scripts/classroom_environment_demo.py`
      applies them to a `ClassroomTwin` and prints the environment summary.
      Verified (not assumed) that neither the CO2 feed nor UCI Occupancy
      Detection has any shared identifier with ASSISTments' `class_id` — no
      classroom association is fabricated; the demo's `Classroom` is an
      explicit illustrative placeholder. UCI Occupancy Detection remains
      unintegrated beyond its `occupancy_readings` table at that point (no
      domain/repository/twin code touches it yet).
- [x] UCI Occupancy Detection ML component, classroom-independent per the
      audit above: `data/repositories/occupancy_readings.py` fetches all
      20,560 real readings ordered by `recorded_at`;
      `analytics/occupancy_detection.py` (class-weighted
      `LogisticRegression` baseline on verified schema columns
      `temperature_c`/`humidity_pct`/`co2_ppm`/`light_lux` only,
      `chronological_train_test_split` — an earlier-train/later-test
      holdout, not the dataset's own non-monotonic `source_file` labels or
      a random split, since ~1-minute-interval readings are strongly
      autocorrelated — reusing `predictive.py`'s `evaluate_model`) +
      `scripts/occupancy_detection_demo.py`. Real-data test-split ROC-AUC
      0.998. Predicts room occupancy only, never individual student
      attendance, and is never attached to a `ClassroomTwin` (no shared
      identifier with `assist_classes`). 8 new unit tests + 2 new
      integration tests.
- [x] Implement the Student Digital Twin MVP: `twin_engine/update_strategies.py`
      (`UpdateStrategy` protocol + `SimpleIncrementalUpdateStrategy`, a
      simple explainable exponential-moving-average baseline, swappable for
      BKT/IRT/a learned model later without changing callers) and
      `twin_engine/student_twin.py` (`StudentTwin` — per-student
      `knowledge_states`/`interaction_history`/`assessment_results`, chronological
      `process_events()`, and a `current_state()` snapshot exposing mastery
      by topic, engagement/assessment summaries, and observation counts).
      Independent of PostgreSQL/SQLAlchemy. `StudentTwinRepository` (Protocol
      interface only, `data/repositories/student_twin_repository.py`) — no
      Postgres implementation yet. 23 focused unit tests in
      `tests/unit/twin_engine/`.
- [x] First real student ML experiment: OULAD dropout-risk baseline.
      `data/repositories/oulad_dropout_features.py` (the only place this
      pipeline touches SQLAlchemy — a day-30-cutoff snapshot query) +
      `analytics/predictive.py` (feature/target split, imputation +
      encoding pipeline, `LogisticRegression(class_weight="balanced")`
      baseline, evaluation, `DropoutPrediction` output shape) +
      `scripts/train_dropout_baseline.py` orchestrator. See
      [docs/datasets/dropout-prediction-feature-design.md](docs/datasets/dropout-prediction-feature-design.md)
      for why OULAD (not `dropout_records` or ASSISTments) trains this
      model, the leakage-safe day-30 cutoff, and the full feature list.
      27,466 eligible enrollments, 18.3% dropout rate; test-set ROC-AUC
      ~0.64, recall ~0.57. 8 focused unit tests in `tests/unit/analytics/`.
- [x] Compare stronger baselines against the dropout logistic regression:
      added `train_random_forest_model` (`analytics/predictive.py`,
      `class_weight="balanced"`, depth/leaf-size constrained after a
      validation-set grid check to avoid overfitting) trained on the
      identical day-30 feature matrix and splits. `scripts/train_dropout_baseline.py`
      now trains and reports both. Random forest selected: test-set
      recall 0.604 vs. 0.572, precision 0.270 vs. 0.265, F1 0.373 vs.
      0.362, ROC-AUC 0.665 vs. 0.644 (accuracy ~tied). XGBoost/LightGBM
      not added — neither is a project dependency. 2 new focused tests in
      `tests/unit/analytics/`.
- [x] Day-45 cutoff experiment for the dropout models:
      `scripts/train_dropout_day45_experiment.py`, identical methodology/
      features/split/`random_state=42` as the day-30 baseline, only
      `fetch_oulad_dropout_snapshot(engine, cutoff_day=45)` differs — the
      query already parameterizes every time-filtered aggregate and the
      eligibility population by `cutoff_day`, so no query change was
      needed. Day-30 script/model untouched; run both and diff the printed
      output to compare cutoffs. 26,921 eligible enrollments at day 45
      (16.7% dropout rate, vs. 27,466/18.3% at day 30).
- [x] First Knowledge Tracing model: `BayesianKnowledgeTracingStrategy`
      (`twin_engine/update_strategies.py`, classic Corbett & Anderson BKT —
      slip/guess-conditioned Bayes update + a learning-transit step, per
      topic, no PostgreSQL/SQLAlchemy dependency) implements the same
      `UpdateStrategy` protocol as `SimpleIncrementalUpdateStrategy`
      (unchanged, kept as the baseline) — drop-in via `StudentTwin(student,
      strategy=...)`. `data/repositories/assistments_problem_attempts.py`
      (the only new place touching SQLAlchemy) fetches one real
      ASSISTments student's chronological, skill-tagged problem attempts as
      `Interaction`s, minting a fresh twin `student_id` rather than reusing
      ASSISTments' own (dataset-scoped, non-identity) `student_id`.
      `scripts/bkt_assistments_demo.py` wires the two together end-to-end:
      real attempt -> Interaction -> BKT -> per-topic mastery. 15 new
      focused tests in `tests/unit/twin_engine/test_update_strategies.py`
      (bounds, correct/incorrect direction, topic independence,
      out-of-order-input chronology via `StudentTwin.process_events`,
      validation errors); all pre-existing StudentTwin/Simple-strategy
      tests still pass unmodified.
- [x] Tune the day-45 Random Forest's decision threshold for the
      early-warning objective: `evaluate_model` (`analytics/predictive.py`)
      gained an optional `threshold` param (default 0.5, no behavior change
      for existing callers); `scripts/tune_dropout_day45_threshold.py`
      sweeps 0.20-0.50 on the validation split only (same feature set,
      split, model, `random_state=42` as the day-45 experiment — no
      retraining), then evaluates the frozen threshold on the test split
      once. Selected threshold 0.47: test recall 0.596 -> 0.683, precision
      0.285 -> 0.268, F1 0.385 -> 0.385, ROC-AUC unchanged 0.706. 1 new
      focused test in `tests/unit/analytics/`.
- [ ] Feed `code_module`/`code_presentation` into the dropout model as
      categorical features (left out of the first baseline deliberately —
      see dropout-prediction-feature-design.md).
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
