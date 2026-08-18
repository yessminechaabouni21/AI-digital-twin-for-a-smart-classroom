# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once a first release is tagged.

## [Unreleased]

### Added

- Deterministic decision-support layer: `analytics/decision_support.py`
  (new) turns already-computed `skill_priority.recommend_skill_priorities`/
  `resource_recommendation.recommend_classroom_resource` output into a
  structured, teacher-facing explanation (`summary`, `priority_skill`,
  `rationale`, `recommended_resources`, `evidence`, `limitations`,
  `suggested_action`) via a provider-independent `DecisionSupportProvider`
  Protocol and its first implementation, `RuleBasedDecisionSupportProvider`
  — plain template formatting, no external service, no Anthropic SDK
  import (stays inside `analytics/`'s CLAUDE.md boundary). Every number in
  the output is copied unmodified from its input; nothing here computes
  mastery, ranks resources, or picks students. A future LLM-backed
  provider satisfying the same Protocol belongs in
  `agents/decision_support_agent.py` (updated its TODO to point here) —
  not implemented, since no `ANTHROPIC_API_KEY` is configured in this
  environment. Exposed via `GET /classrooms/{twin_id}/decision-support`
  (`api/routers/classrooms.py`, `schemas/classrooms.py`'s new
  `ClassroomDecisionSupportOut`), which validates identity exactly like
  the existing classroom endpoints, builds the same live `ClassroomTwin`,
  and reuses a new shared `_skill_priorities_and_resource_recommendation`
  helper (extracted so the endpoint doesn't duplicate the ranking/lookup
  `/recommendations` already does) — no BKT/aggregation/ranking logic
  duplicated in the router. `domain/classroom.py` gained
  `derive_classroom_id`, mirroring `derive_student_id`, so a classroom
  `twin_id` can be independently verified against its claimed
  `(source_dataset, class_id)`. 6 new unit tests
  (`tests/unit/analytics/test_decision_support.py`: empty priorities,
  missing resource recommendation, a resource recommendation with no
  reliable problems, full real-shaped context, roster-capped limitation,
  and a scan of every output string for causal/optimal wording) + 4 new
  integration tests in `tests/integration/test_api_classrooms.py` (real
  class success, empty class, identity mismatch, unrelated twin_id).

- First working API layer, wired into the existing FastAPI scaffolding
  (`main.py`, `api/routers/`) rather than a new framework: `GET
  /students/{twin_id}`, `GET /students/{twin_id}/state`, `GET
  /classrooms/{twin_id}`, `GET /classrooms/{twin_id}/state`, `GET
  /classrooms/{twin_id}/priorities`, `GET /classrooms/{twin_id}/recommendations`.
  Every handler only calls existing repositories/twin_engine/analytics
  code — no business logic duplicated in `api/`. `twin_id` is always a
  typed `UUID` path parameter (FastAPI/pydantic reject a raw
  ASSISTments/OULAD integer id with 422 before a handler runs);
  `domain/classroom.py::derive_classroom_id` (new, mirrors
  `derive_student_id`) lets classroom handlers verify a caller-supplied
  `twin_id` against its claimed `(source_dataset, class_id)` by
  recomputation, so a mismatched or unrelated `twin_id` always 404s rather
  than silently serving the wrong classroom's data. `schemas/students.py`/
  `schemas/classrooms.py` (new) are the first real DTOs in `schemas/`,
  kept separate from `domain/`/`twin_engine/` per CLAUDE.md.
  `api/deps.py::get_db_engine` is the one new FastAPI dependency (thin
  wrapper over the existing `data/db/session.get_engine()`). Classroom
  endpoints are read-through, not persisted — `ClassroomTwin` still has no
  storage of its own (per the persistence work above), so each request
  rebuilds the roster's `StudentTwin`s from real ASSISTments data live,
  same composition `scripts/classroom_skill_priority_demo.py` already
  demonstrates. Recommendation responses carry no causal/optimality claim
  (`distance_from_target` only); the environment field is always empty
  through this API, since no CO2 sensor is linked to any real ASSISTments
  `class_id` in the source data — never fabricated, and UCI Occupancy
  Detection/attendance data is not exposed through any endpoint. 16 new
  integration tests (`tests/integration/test_api_students.py`,
  `tests/integration/test_api_classrooms.py`): success, 404 for
  never-persisted/mismatched/unrelated twin ids, 422 for a non-UUID path
  param, 400 for an unsupported `source_dataset`, and empty-class/
  empty-state responses.

- StudentTwin persistence: `student_knowledge_states` (new table,
  `data/db/models.py::StudentKnowledgeState`, created via the same
  `Base.metadata.create_all` pattern every loader already uses — no Alembic
  yet) stores one row per `(student_id, topic_id)`, upserted to the latest
  value — the derived output of BKT/`UpdateStrategy`, never a copy of the
  raw ASSISTments observations that produced it (those stay exactly where
  they already were, in `assist_problem_logs` etc., untouched).
  `PostgresStudentTwinRepository` (`data/repositories/student_twin_repository.py`)
  implements the existing `StudentTwinRepository` Protocol's `get`/`save`
  against it — `save()` persists only `knowledge_states` (never
  engagement/assessment summaries or attached predictions, which stay
  either cheaply recomputable from already-persisted raw logs or
  explicitly not replayable as observations), and is a no-op for a student
  with no knowledge_states yet. `domain/student.py::derive_student_id(source_dataset, source_id)`
  gives callers who want a twin identity findable again across processes a
  deterministic, `uuid5`-based, per-dataset-scoped id (same derivation
  `oulad_assessment_results.py` already uses for `assessment_id`) — a
  random `uuid4()` (still `Student`'s default) can never be looked up
  again, and two different datasets' same-valued native id can never
  collide onto the same twin id, so no cross-dataset identity is ever
  fabricated by this mechanism. `ClassroomTwin` gets no new persistence of
  its own: aggregating persisted `StudentTwinState`s (verified — see tests)
  reproduces the same aggregate a live-data run would, so it needs none.
  5 new integration tests (`tests/integration/test_student_twin_persistence.py`:
  empty-state no-op, real-data round-trip, repeated-save upsert-not-duplicate,
  pure reconstruction of a `ClassroomTwin` from persisted state alone) + 3
  new unit tests (`tests/unit/domain/test_student.py`) for `derive_student_id`.

### Fixed

- StudentTwin audit follow-up (D.1–D.4): removed `scripts/student_twin_full_demo.py`,
  which fabricated a single twin identity from two unrelated real students
  (ASSISTments `student_id=52964` + OULAD `id_student=134188`) — the
  single-source demos (`bkt_assistments_demo.py`,
  `assessment_performance_oulad_demo.py`,
  `student_twin_predictions_oulad_demo.py`) remain the canonical examples,
  each scoped to one real identity throughout. Fixed
  `student_twin_predictions_oulad_demo.py` to exclude the demoed student's
  own row from the dropout/performance training pool *before* any
  split/training (`_exclude_student_row`), so the printed prediction is
  genuinely out-of-sample rather than possibly in-sample by chance of a
  random split. Corrected two stale "Not wired into StudentTwin yet"
  docstrings in `analytics/performance_prediction.py`
  (`StudentTwin.attach_performance_prediction` has been wired and tested
  since that module was added). Added an integration test
  (`test_real_oulad_dropout_and_performance_predictions_attach_to_student_twin`
  in `tests/integration/test_student_twin_full_pipeline.py`) covering real
  OULAD-sourced `DropoutPrediction`/`StudentPerformancePrediction` attaching
  correctly to a `StudentTwin`'s `StudentTwinState`, trained out-of-sample
  the same way.

### Added

- UCI Occupancy Detection ML component: `data/repositories/occupancy_readings.py`
  fetches all 20,560 real readings ordered by `recorded_at`;
  `analytics/occupancy_detection.py` trains a class-weighted
  `LogisticRegression` baseline on `temperature_c`/`humidity_pct`/`co2_ppm`/
  `light_lux` only (verified schema columns; `humidity_ratio` excluded as a
  redundant deterministic function of temperature+humidity), reusing
  `predictive.py`'s generic `evaluate_model`. Split is a genuine
  chronological earlier-train/later-test holdout
  (`chronological_train_test_split`) rather than the dataset's own
  `source_file` labels, since those are not monotonic in time (`test`
  2015-02-02..02-04 precedes `training` 02-04..02-10, verified against the
  live table) — a random or file-based split would either shuffle
  autocorrelated, ~1-minute-interval readings across train/test or eval
  "later" data against an earlier split. `scripts/occupancy_detection_demo.py`
  runs it end-to-end (real-data ROC-AUC 0.998 on the held-out chronological
  test split). Per the environment/occupancy audit: this predicts room
  occupancy only, never individual student attendance, and its output is
  never attached to a `ClassroomTwin` — `occupancy_readings` has no shared
  identifier with ASSISTments' `assist_classes`. 8 new unit tests
  (`tests/unit/analytics/test_occupancy_detection.py`) + 2 new integration
  tests (`tests/integration/test_occupancy_readings.py`).
- Real-data Environmental Sensors integration:
  `data/repositories/co2_sensor_readings.py` fetches one real CO2 sensor's
  readings (`co2_sensor_readings`, by `sensor_id`) as
  `ClassroomEnvironmentReading`s. `scripts/classroom_environment_demo.py`
  applies them to a `ClassroomTwin` via `apply_environment_reading()` and
  prints the resulting `ClassroomTwinState.environment` summary. Per the
  environment/occupancy integration audit: the sensor is never linked to an
  ASSISTments `class_id` — no such mapping exists in either dataset's
  source data (verified, not assumed) — so the demo's `Classroom` is an
  explicitly illustrative placeholder, not a real classroom association.
  UCI Occupancy Detection remains unintegrated (no domain/repository/twin
  code touches it), per the same audit. 2 new integration tests in
  `tests/integration/test_co2_sensor_readings.py`.
- Decision-threshold tuning for the day-45 Random Forest early-warning
  model: `evaluate_model` in `analytics/predictive.py` now accepts an
  optional `threshold` (default 0.5, backward compatible) so the same
  fitted model can be scored at any cutoff on `predict_proba` without
  retraining. `scripts/tune_dropout_day45_threshold.py` sweeps thresholds
  0.20-0.50 on the validation split only (same feature set, split, model
  config, and `random_state=42` as `scripts/train_dropout_day45_experiment.py`
  — no retraining), selects the lowest threshold that improves recall over
  the 0.5 baseline while keeping validation precision/F1 within 10% of it,
  then evaluates that frozen threshold on the test split exactly once.
  Selected threshold 0.47: test recall improves 0.596 -> 0.683 (precision
  0.285 -> 0.268, F1 0.385 -> 0.385, ROC-AUC unchanged at 0.706, since
  ROC-AUC doesn't depend on the decision threshold). 1 new focused test in
  `tests/unit/analytics/test_predictive.py` asserting a lower threshold
  never decreases recall.
- First real student ML experiment: an OULAD dropout-risk baseline.
  `data/repositories/oulad_dropout_features.py` fetches a student-level,
  day-30-cutoff snapshot (the only place this pipeline touches
  SQLAlchemy/Postgres); `analytics/predictive.py` (feature/target split,
  imputation + one-hot/scaling preprocessing, a `LogisticRegression(class_weight="balanced")`
  baseline, accuracy/precision/recall/F1/ROC-AUC/confusion-matrix
  evaluation, and a `DropoutPrediction{dropout_probability, predicted_class}`
  output shape) has no SQLAlchemy or twin_engine/domain dependency, per
  CLAUDE.md's module boundaries. `scripts/train_dropout_baseline.py` runs
  the experiment end-to-end. See
  `docs/datasets/dropout-prediction-feature-design.md`: OULAD (not the
  anonymized, timeless `dropout_records` population, and not ASSISTments,
  which has no dropout-shaped target at all) trains this model, because it
  is the only dataset with a real per-student withdrawal label
  (`enrollments.final_result = 'Withdrawn'`), a real withdrawal-timing
  column, and day-level behavioral history to build a leakage-safe,
  fixed-cutoff snapshot from — the target-eligible population excludes
  enrollments already withdrawn by day 30. 27,466 eligible enrollments
  (18.3% dropout rate); test-set accuracy 0.630, precision 0.265, recall
  0.572, F1 0.362, ROC-AUC 0.644. 8 focused unit tests in
  `tests/unit/analytics/test_predictive.py`, including a static assertion
  that no identifier or target column can enter the feature set.
- Stronger dropout-risk baseline comparison: `train_random_forest_model` in
  `analytics/predictive.py` (`RandomForestClassifier(class_weight="balanced")`,
  `max_depth=8`/`min_samples_leaf=10` — constrained after a validation-set
  grid check, since unbounded defaults overfit the training split while
  generalizing worse than logistic regression) trained on the identical
  day-30 feature matrix, identifier/target exclusions, and train/val/test
  splits as the logistic regression baseline, via the same
  `evaluate_model`/`ClassificationMetrics` path. `scripts/train_dropout_baseline.py`
  now trains and reports both models. On the held-out test split, random
  forest improves recall (0.604 vs. 0.572), precision (0.270 vs. 0.265), F1
  (0.373 vs. 0.362), and ROC-AUC (0.665 vs. 0.644) over logistic regression,
  with accuracy essentially unchanged (0.628 vs. 0.630) — selected as the
  better model for an early-warning use case, where recall/precision matter
  more than accuracy on an imbalanced target. XGBoost/LightGBM were
  considered but not added, since neither is a project dependency
  (pyproject.toml). `DropoutPrediction`'s output interface is unchanged. 2
  new focused tests in `tests/unit/analytics/test_predictive.py`.
- Controlled day-45 cutoff experiment for the OULAD dropout models:
  `scripts/train_dropout_day45_experiment.py` mirrors
  `scripts/train_dropout_baseline.py` exactly (same feature set,
  preprocessing, `train_val_test_split`/`random_state=42`, Logistic
  Regression baseline, and Random Forest config) and only changes
  `fetch_oulad_dropout_snapshot`'s `cutoff_day` from 30 to 45 — the query
  already parameterizes every time-filtered feature and the eligibility
  population by `cutoff_day`, so every time-dependent feature is
  recomputed from data available up to day 45 with no query change and no
  leakage. Day-30 script and models are untouched; run both scripts and
  diff their identically-formatted output to compare cutoffs directly.
  26,921 eligible enrollments at day 45 (16.7% dropout rate) vs. 27,466
  (18.3%) at day 30.
- First real Knowledge Tracing model: `BayesianKnowledgeTracingStrategy` in
  `twin_engine/update_strategies.py`, classic Corbett & Anderson (1994)
  Bayesian Knowledge Tracing — a slip/guess-conditioned Bayesian update of
  per-topic P(mastered) followed by a learning-transit step — implementing
  the same `UpdateStrategy` protocol as the existing, unchanged
  `SimpleIncrementalUpdateStrategy` baseline, so `StudentTwin` swaps
  between them via its existing `strategy` constructor argument with no
  other code change. No PostgreSQL/SQLAlchemy dependency, per CLAUDE.md's
  module boundaries. `data/repositories/assistments_problem_attempts.py`
  (the one new place touching SQLAlchemy for this) fetches one real
  ASSISTments student's chronological, skill-tagged problem attempts as
  `Interaction`s — the ASSISTments `student_id` is used only to select and
  order rows, never reused as or joined onto the returned Interactions'
  (freshly minted) Student Twin identity. `scripts/bkt_assistments_demo.py`
  demonstrates the full path end-to-end: real problem attempt ->
  `Interaction` -> BKT -> per-topic `KnowledgeState.mastery_probability`.
  15 new focused tests in `tests/unit/twin_engine/test_update_strategies.py`
  covering mastery bounds, correct/incorrect direction, per-topic
  independence, out-of-order-input chronology (via
  `StudentTwin.process_events`), and parameter/interaction validation; all
  pre-existing StudentTwin and SimpleIncrementalUpdateStrategy tests pass
  unmodified.
- Student Digital Twin MVP: `twin_engine/update_strategies.py`
  (`UpdateStrategy` protocol + `SimpleIncrementalUpdateStrategy`, an
  explainable exponential-moving-average mastery update, deliberately not
  BKT/IRT yet) and `twin_engine/student_twin.py` (`StudentTwin` — per-topic
  `knowledge_states`, raw `interaction_history`/`assessment_results`,
  chronological `process_events()`, and a `current_state()` snapshot
  exposing mastery-by-topic, engagement/assessment summaries, and
  observation counts, kept separate from the raw history that produced
  them). `StudentTwinRepository` (`data/repositories/student_twin_repository.py`)
  is a Protocol interface only — no Postgres implementation yet. All of it
  independent of PostgreSQL/SQLAlchemy. 23 focused unit tests in
  `tests/unit/twin_engine/`.
- Student Digital Twin domain layer: `domain/student.py` (`Student`),
  `domain/assessment.py` (`Assessment`, `AssessmentResult`),
  `domain/interaction.py` (`Interaction`, `InteractionType`),
  `domain/knowledge_state.py` (`KnowledgeState`, `mastery_probability` in
  [0,1] per topic). Pure pydantic vocabulary, no persistence dependency and
  no duplication of `data/db/models.py`'s schemas; `Student.student_id` is
  twin-minted, never an OULAD `id_student`/ASSISTments `student_id`/
  `dropout_records` row, since none of those are cross-dataset person
  identifiers.
- UCI Occupancy Detection preprocessing pipeline
  (`data/preprocessing/preprocess_occupancy.py`, `load_occupancy.py`) and a
  standalone single-table SQLAlchemy schema (`OccupancyReading`,
  `occupancy_readings` in `data/db/models.py`), independent of OULAD/xAPI/
  ASSISTments and distinct from `co2_sensor_readings` (the Spanish Classroom
  CO2 dataset — no shared identifier, never joined). Implements
  `docs/datasets/occupancy-preprocessing-plan.md`: combines the three raw
  files (`datatraining.txt`, `datatest.txt`, `datatest2.txt`), verified
  time-disjoint segments of one sensor deployment rather than independent
  samples, into one logical table while preserving each row's originating
  split via a new `source_file` column; uses natural composite PK
  `(source_file, recorded_at)` (no surrogate key needed — verified
  collision-free within and across files). Adds `assert_allowed_values` to
  `data/preprocessing/validation.py` (a fatal finite-domain check, distinct
  from the existing non-fatal `warn_out_of_range`) to enforce `occupancy` is
  restricted to `{0, 1}`. Loaded end-to-end against local Postgres: 20,560
  rows (8,143 + 2,665 + 9,752 across the three source splits, all
  preserved), zero PK collisions, zero nulls.
- Spanish Classroom CO2 sensor preprocessing pipeline
  (`data/preprocessing/preprocess_environmental_sensors.py`,
  `load_environmental_sensors.py`) and a standalone single-table SQLAlchemy
  schema (`Co2SensorReading`, `co2_` prefix in `data/db/models.py`),
  independent of OULAD/xAPI/ASSISTments and distinct from the (not yet
  modeled) UCI Occupancy Detection dataset. Implements
  `docs/datasets/spanish-co2-preprocessing-plan.md`: fixes the source file's
  non-standard whole-line-double-quoted CSV framing, drops 413 fully-
  duplicate rows (sensor retransmissions, not independent readings) which
  makes `(sensor_id, recorded_at)` a genuine natural composite key, and
  drops six columns (`date_time` and five sub-fields) verified to be 100%
  derivable from the kept `recorded_at` timestamp. Loaded end-to-end against
  local Postgres: 38,477 rows, 6 sensors, zero PK collisions, zero nulls.
- ASSISTments 2019-2020 school year preprocessing pipeline
  (`data/preprocessing/preprocess_assist_*.py`, `load_assistments.py`) and
  a normalized 7-table SQLAlchemy schema (`assist_` prefix in
  `data/db/models.py`), independent of OULAD and xAPI (no shared
  identifier, no join to either). Implements
  `docs/datasets/assist-preprocessing-plan.md` exactly: drops 392
  `pdets.csv` rows with no `problem_id` rather than inventing one, uses a
  composite key for `assist_student_classes` (`student_id` is reused
  across classes, same shape as OULAD's `id_student`), a DB-generated
  surrogate key for `assist_problem_logs` (no natural key exists — proven
  by 508 genuine same-problem-retry rows), and leaves `assist_districts`
  fully unlinked (no district-linking column exists anywhere else in this
  release — verified, not assumed). Loaded end-to-end against local
  Postgres: assist_districts 1,822, assist_classes 17,003, assist_problems
  134,263, assist_student_classes 286,592, assist_assignments 197,022,
  assist_assignment_logs 2,505,225, assist_problem_logs 20,752,836 rows.
  Zero unexpected FK/PK violations; the one documented, expected gap
  (172,865 `assist_problem_logs` rows referencing a `problem_id` absent
  from `assist_problems`, because that problem's own detail row had no id)
  surfaced exactly as predicted via the new non-fatal `warn_foreign_key`
  check, not a hard failure.
- Two new non-fatal validation helpers in `data/preprocessing/validation.py`
  (`warn_foreign_key`, alongside xAPI's existing `warn_on_duplicate_rows`/
  `warn_out_of_range`) for the one ASSISTments relationship that's real but
  not always present, plus an NA-safety fix to `warn_out_of_range` for
  nullable (`Float64`) columns.
- xAPI-Edu-Data preprocessing pipeline (`data/preprocessing/
  preprocess_xapi_*.py`, `load_xapi.py`) and a 2-table SQLAlchemy schema
  (`XapiClassSection`, `XapiStudentRecord` in `data/db/models.py`),
  independent of OULAD. Implements
  `docs/datasets/xapi-preprocessing-plan.md`: surrogate integer primary
  key for `XapiStudentRecord` (no natural key exists — proven by 4
  fully-duplicate source rows), duplicates kept rather than dropped.
  Loaded end-to-end: xapi_class_sections 74, xapi_student_records 480
  rows.
- OULAD's pipeline (below) run end-to-end against a live local Postgres
  instance: courses 22, vle_sites 6,364, assessments 206, enrollments
  32,593, assessment_submissions 173,912, vle_interactions 8,459,320 rows —
  matches the preprocessing audit's numbers exactly.
- OULAD preprocessing pipeline (`data/preprocessing/`): one cleaning/
  validation module per source file (`preprocess_courses.py`,
  `preprocess_vle.py`, `preprocess_assessments.py`,
  `preprocess_enrollments.py`, `preprocess_student_assessment.py`,
  `preprocess_student_vle.py`), plus `load_oulad.py` to run all six stages
  in dependency order and batch-load the result into PostgreSQL. Implements
  `docs/datasets/oulad-preprocessing-plan.md` exactly: preserves
  structurally-meaningful nulls (`date_unregistration`, `imd_band`,
  `assessments.date`, `score`), fixes the `imd_band` `"10-20"` formatting
  inconsistency, merges `studentInfo` + `studentRegistration` into
  `enrollments`, and resolves `studentVle.csv`'s duplicate-key aggregation
  issue via chunked groupby-sum. Dry-run against the real raw files
  reproduces the earlier audit's counts exactly (1,111 `imd_band` nulls,
  22,521 `date_unregistration` nulls, 173 `score` nulls; the 10.66M raw
  `studentVle` rows collapse to 8,459,320 aggregated rows, a reduction of
  exactly the 2,195,960 duplicate-key rows the audit flagged).
- SQLAlchemy ORM models (`data/db/models.py`) for the finalized 6-table
  OULAD schema (`Course`, `VleSite`, `Assessment`, `Enrollment`,
  `AssessmentSubmission`, `VleInteraction`), matching
  `docs/datasets/oulad.md`'s relational design including its composite
  primary/foreign keys.
- `data/db/session.py`: SQLAlchemy engine/session-factory setup, driven by
  `Settings.database_url`.
- `core/logging.py`: basic stdlib logging configuration driven by
  `Settings.log_level`.
- `docs/DATASETS.md`: research and comparison of 27 public datasets against
  the project's 8 objectives, with a scored ranking table and a recommended
  dataset combination (OULAD as spine + 7 targeted supplements).
- DECISIONS.md ADR-008 recording the dataset combination decision.
- Initial project scaffolding: directory structure for `src/digital_twin/`
  (api, core, domain, twin_engine, analytics, agents, data, schemas), tests,
  notebooks, scripts, docs, data folders.
- Documentation: README.md, CLAUDE.md, PROJECT_PLAN.md, TODO.md,
  DECISIONS.md (ADR-001 through ADR-007).
- Tooling: requirements.txt, pyproject.toml (hatchling build, ruff/black/mypy
  config, pytest config), .gitignore, .env.example.
- Git repository initialized.
