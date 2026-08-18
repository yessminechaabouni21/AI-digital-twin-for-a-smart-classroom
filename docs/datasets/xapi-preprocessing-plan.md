# xAPI-Edu-Data Preprocessing Plan

Plan only — no code written yet. Unlike `oulad-preprocessing-plan.md`, there is
no separate `xapi.md`/`data-quality-audit.md` profiling pass on disk for this
dataset yet; the findings below come from direct inspection of
`data/raw/xAPI-Edu-Data/xAPI-Edu-Data.csv` (480 rows, 17 columns) done as part
of this plan. Every cleaning/key/duplicate decision below is a direct
consequence of a finding stated explicitly in this document — nothing is
assumed from the OULAD pass.

Target schema being populated (new, independent of OULAD's): `xapi_class_sections`
(root, derived from the five class-context columns) and `xapi_student_records`
(one row per source row, FK'd to `xapi_class_sections`). No table in this
schema is joined to any OULAD table — this is a second, independent
population with no shared identifier (see "Resolved scope decisions").

---

## Source profile

- 480 rows, 17 columns, **zero nulls in any column** — confirmed by direct
  inspection, not assumed; the load script still asserts this rather than
  skipping the check, per the same "re-verify, don't trust" rule OULAD's plan
  used.
- No column is a student identifier. Each row is a single cross-sectional
  snapshot: demographics + parent-engagement + behavioral counts + one
  outcome label, with no timestamp, session, or enrollment axis connecting
  any two rows.
- **4 fully-duplicate rows** (all 17 columns identical, all sharing the same
  class context: Jordan / `Above-7` / `L`). This proves no combination of
  source columns — not even the full row — can serve as a natural key.
- **(StageID, GradeID, SectionID, Topic, Semester)** has 74 distinct
  combinations across the 480 rows (~6.5 students/combo). Verified unique
  post-dedup — this 5-tuple is the one legitimate natural key in the
  dataset, structurally playing the same role `courses` plays for OULAD.
- `GradeID` does **not** determine `StageID` (`G-07` maps to two different
  `StageID` values) — both columns are independent and must be kept.
- `NationalITy` and `PlaceofBirth` correlate but are not 1:1 (e.g. `Jordan`
  nationality spans 7 distinct birthplaces) — both are independent signal,
  neither is dropped as redundant.
- `raisedhands`, `VisITedResources`, `AnnouncementsView`, `Discussion` are
  integers observed in [0, 100], no nulls.
- `StudentAbsenceDays` is pre-bucketed (`Under-7`/`Above-7`) in the source —
  no continuous absence count is available. Documented dataset limitation,
  not something to reconstruct.
- `Class` (target) is clean: exactly `L`/`M`/`H`, no nulls.
- Source column names are inconsistently cased (`NationalITy`,
  `VisITedResources`, `AnnouncementsView`, `ParentschoolSatisfaction`) — a
  naming cleanup only, same category as OULAD's `imd_band` `%`-suffix fix,
  not a data-content change.

---

## Guiding rules for this pass

1. **Preprocessing order = FK dependency order = Postgres load order**, same
   principle as OULAD: `xapi_class_sections` must exist and be validated
   before `xapi_student_records` can check its FK against it.
2. **Never collapse the 4 duplicate rows.** There is no column, and no
   combination of columns, that distinguishes a data-entry duplicate from
   two different students who coincidentally share every bucketed value.
   Dropping them would silently destroy signal the same way de-duplicating
   `studentVle.csv` before summing would have — keep all 4 as independent
   rows, each with its own surrogate key.
3. **No natural key exists for the per-student grain — use a surrogate.** The
   4 duplicate rows are the proof, not an assumption: if even all 17 columns
   together fail to be unique, no subset can be either. A content-hash key
   was considered and rejected for the same reason a dedup pass was rejected
   — it would collide on exactly those 4 rows and silently merge students the
   data gives no reason to treat as the same.
4. **Persist raw categorical values, not encodings** — same rule as OULAD.
   `gender`, `nationality`, `relation`, `parent_answering_survey`,
   `parent_school_satisfaction`, `student_absence_days`, `class_label` stay
   as their source strings (after the casing/naming fix below). No lookup
   tables, no ordinal/one-hot encoding — that is an `analytics/` concern.
5. **Re-verify every claim in this document at load time**, exactly as
   OULAD's validation layer does — the 74-combination and zero-null findings
   above are point-in-time observations; the load script asserts them rather
   than trusting this document on a future re-download.

---

## Pipeline — 2 stages, in order

### Stage 1 — `xAPI-Edu-Data.csv` → `xapi_class_sections`

- **Cleaning:** select the five class-context columns and
  `drop_duplicates()` on them.
- **Renaming:** `StageID` → `stage_id`, `GradeID` → `grade_id`, `SectionID`
  → `section_id`, `Topic` → `topic`, `Semester` → `semester`. Casing
  cleanup only, no value changes.
- **Missing values:** none present.
- **Duplicates:** resolved by construction (`drop_duplicates`); assert the
  composite key `(stage_id, grade_id, section_id, topic, semester)` is
  unique afterward anyway, as a load-time guard.
- **Dtype conversions:** all five columns → `string`.
- **FK validation:** none — this is the root table, same role `courses`
  plays for OULAD.
- **Load into Postgres:** **first.** Nothing else can validate its FK until
  this table exists.

### Stage 2 — `xAPI-Edu-Data.csv` → `xapi_student_records`

- **Cleaning:** select all 17 source columns from the same file (no join
  needed — everything lives in one CSV, unlike OULAD's multi-file merges).
- **Renaming:** `NationalITy` → `nationality`, `PlaceofBirth` →
  `place_of_birth`, `VisITedResources` → `visited_resources`,
  `AnnouncementsView` → `announcements_view`, `ParentAnsweringSurvey` →
  `parent_answering_survey`, `ParentschoolSatisfaction` →
  `parent_school_satisfaction`, `StudentAbsenceDays` →
  `student_absence_days`, `Class` → `class_label` (`class` is a
  Python-reserved-adjacent word — never used as the attribute or column
  name), plus the same five class-context renames as Stage 1.
- **Missing values:** none present — asserted, not assumed.
- **Duplicates:** **no deduplication step.** The 4 fully-duplicate source
  rows are loaded as 4 separate records, each receiving its own surrogate
  `record_id`. See Guiding rule 2.
- **Row-count guard:** assert `len(df) == 480` — nothing in this stage is
  expected to aggregate or drop rows, unlike OULAD's VLE stage.
- **Dtype conversions:** `raised_hands`, `visited_resources`,
  `announcements_view`, `discussion` → `int64`; every other column →
  `string`; `record_id` is DB-generated (see Primary key strategy), not
  assigned in pandas.
- **Range check:** `raised_hands`, `visited_resources`,
  `announcements_view`, `discussion` observed in [0, 100] — logged as a
  warning if a future re-download violates this, not a hard failure (the
  range is an observation, not a schema-enforced source constraint).
- **Duplicate-count check (new, non-fatal):** log the number of
  fully-duplicate source rows found (expect 4). Not a rejection — a future
  re-download producing, say, 200 duplicates should surface for human
  review rather than load silently. This is a new small helper alongside
  `assert_unique`/`assert_foreign_key`/`assert_row_count_preserved` in
  `validation.py`, not a change to any existing rule.
- **FK validation:** every row's `(stage_id, grade_id, section_id, topic,
  semester)` must exist in the Stage 1 output — true by construction
  (Stage 1 is derived from these same rows), asserted anyway as a
  derivation-bug guard, same discipline OULAD applies throughout.
- **Load into Postgres:** after `xapi_class_sections`.

---

## PostgreSQL load order

```
1. xapi_class_sections
2. xapi_student_records   (depends on xapi_class_sections)
```

Flatter than OULAD's 6-stage/5-table graph — a direct consequence of this
dataset having no assessment or clickstream sub-entities, and no cross-file
merge to perform (everything lives in one CSV).

---

## Primary key strategy

No natural student ID exists in the source, and none can be constructed:

- **`xapi_class_sections`: natural composite key**
  `(stage_id, grade_id, section_id, topic, semester)`. Verified unique at
  profiling time (74 distinct combinations, 74 after dedup) and re-verified
  programmatically at load time — same justification and same discipline
  OULAD uses for `courses`.
- **`xapi_student_records`: surrogate autoincrement integer** `record_id`,
  Postgres-generated at insert time. Proven necessary, not just convenient:
  the 4 fully-duplicate rows show that even all 17 source columns together
  fail to be unique, so no natural or composite subset can be either. A
  content-hash key was considered and rejected — it would collide on those
  4 rows and silently merge distinct students the data gives no evidence to
  treat as the same. The surrogate key is never derived from row content.

---

## Features preserved for the Student Digital Twin (static)

xAPI supports a **static** Student Digital Twin, not a **dynamic** one — the
distinction matters and is the key architectural difference from OULAD:

- **OULAD is dynamic:** `enrollments` + `assessment_submissions` +
  `vle_interactions` give a timeline — multiple observations per student
  over the course of a presentation, which is what lets `twin_engine/`
  perform continuous state updates (per CLAUDE.md, that is the only place
  twin *update* logic lives).
- **xAPI is static:** there is no student ID, timestamp, or session axis, so
  no student is ever observed twice. One `xapi_student_records` row is not a
  point in a trajectory — it is the entire observation. There is nothing
  for `twin_engine/`'s update logic to update, and it should not be asked
  to.
- **It is still a valid twin, just a static one.** A single
  `xapi_student_records` row is a complete, coherent snapshot of a
  student's current state at one point in time: profile (`gender`,
  `nationality`, `place_of_birth`, `relation`), engagement
  (`raised_hands`, `visited_resources`, `announcements_view`,
  `discussion`), parent involvement (`parent_answering_survey`,
  `parent_school_satisfaction`), attendance (`student_absence_days`), and
  outcome (`class_label`). That is enough to instantiate a twin's *current
  state* — just not to animate its history.
- **Practical use:** a static Student Digital Twin instantiated from a
  `xapi_student_records` row is well-suited to `analytics/`-layer
  performance prediction (`class_label` as the supervised target, the rest
  as features) and to any agent workflow that only needs "what does this
  student look like right now," but it cannot support any twin behavior
  that assumes a prior state to update from.
- **Not read by this twin:** any other `xapi_student_records` row, and
  never an OULAD `enrollments` row — there is no shared identifier, so a
  static xAPI twin and an OULAD twin are never the same entity (see
  "Resolved scope decisions").

## Features preserved for the Classroom Digital Twin

This is the dataset's natural fit — one twin instance = one
`xapi_class_sections` row, exactly parallel to OULAD's Classroom Twin
mapping to one `(code_module, code_presentation)`:

- **`xapi_class_sections`** (its one row): `stage_id`, `grade_id`,
  `section_id`, `topic`, `semester` — the class context itself.
- **`xapi_student_records`** (all rows sharing the key), aggregated: roster
  size, demographic mix (`gender`/`nationality`/`relation` distribution),
  mean/median engagement across all four behavioral columns, outcome
  distribution (`class_label` counts), parent-engagement rate
  (`parent_answering_survey` Yes-rate, `parent_school_satisfaction`
  Good-rate), absenteeism rate (`student_absence_days` Above-7 rate).

Structurally identical in shape to OULAD's Classroom Twin section — many
students' rows reduced, not one student's rows in sequence.

---

## Resolved scope decisions

1. **Independent schema, no join to OULAD.** `xapi_class_sections` and
   `xapi_student_records` share no identifier with any OULAD table
   (`id_student`, `code_module`/`code_presentation`, or otherwise). They are
   never joined, and no code should be written that assumes a shared
   student across the two datasets.
2. **`xapi_` table prefix.** Unlike OULAD's generically-named tables,
   `class_sections`/`student_records` are exactly the kind of name a future
   generic domain concept could also want — prefixing keeps this dataset's
   persistence tables visibly scoped, consistent with `models.py`'s existing
   "persistence-only, `domain/` is a separate concern" framing.
3. **Duplicates kept, not dropped.** The 4 fully-duplicate rows are loaded
   as-is; no evidence in the data supports treating them as erroneous.
4. **Surrogate integer PK for `xapi_student_records`.** Confirmed necessary
   by direct evidence (the duplicate rows), not a default choice.
5. **Static, not dynamic, Student Digital Twin.** xAPI feeds
   `analytics/`-layer prediction and one-shot "current state" twin reads; it
   is not routed through `twin_engine/`'s update logic, which has no signal
   to act on here.
6. **Code location:** same `data/preprocessing/` module as OULAD
   (`preprocess_xapi_class_sections.py`, `preprocess_xapi_student_records.py`,
   plus a `load_xapi.py` orchestrator mirroring `load_oulad.py`), reusing
   the existing `validation.py` helpers plus the one new non-fatal
   duplicate-count check described in Stage 2.

Stopping here for approval before any code is written.
