# OULAD Preprocessing Plan

Plan only — no code written yet. Builds directly on the findings in
[oulad.md](oulad.md) (per-file inspection + finalized target schema),
[schema-validation.md](schema-validation.md), and
[data-quality-audit.md](data-quality-audit.md). Every cleaning/missing-value/
duplicate decision below is a direct consequence of a finding already
documented in those three files — nothing new is being discovered here, this
is turning those findings into an ordered, executable plan.

Target schema being populated (unchanged from oulad.md): `courses`,
`vle_sites`, `assessments`, `enrollments` (merge of `studentInfo` +
`studentRegistration`), `assessment_submissions` (from `studentAssessment`),
`vle_interactions` (from `studentVle`, aggregated).

---

## Guiding rules for this pass

1. **Preprocessing order = FK dependency order = Postgres load order.** All
   three questions the user asked ("preprocessing order," "load order into
   Postgres") have the same answer, because every downstream table's
   cleaning step needs its parent table's keys already validated to check
   its own foreign keys against. So there's one pipeline, not two.
2. **Never impute a null that the audit already classified as structurally
   meaningful.** `date_unregistration`, `imd_band`, `assessments.date`
   (Exam rows), and `studentAssessment.score` all have documented reasons
   for their nulls (oulad.md ##2-5). Imputing any of them would destroy
   signal the twin engine needs (e.g. "still enrolled," "ungraded
   submission"). They stay `NULL` in Postgres, not a sentinel value.
3. **Re-verify, don't just trust, every FK/uniqueness claim from the audit
   docs at load time.** The audit was a point-in-time profiling pass; the
   load script should assert the same invariants (zero orphans, key
   uniqueness) programmatically and fail loudly if a future re-download of
   OULAD ever violates them.
4. **Persist raw categorical values, not encodings.** `final_result`,
   `imd_band`, `age_band`, `highest_education`, `disability`, `gender` stay
   as their source strings (after the one formatting fix below). Ordinal/
   one-hot encoding is an analytics-layer concern, not a preprocessing/
   persistence one — keeps `data/db` decoupled from any one model's
   feature representation.

---

## Pipeline — 6 stages, in order

### Stage 1 — `courses.csv` → `courses`

- **Cleaning:** none needed. 22 rows, 3 columns, already clean.
- **Missing values:** none present.
- **Duplicates:** none present; assert `(code_module, code_presentation)` is
  unique as a load-time guard anyway.
- **Dtype conversions:** `code_module` → str, `code_presentation` → str,
  `module_presentation_length` → int.
- **FK validation:** none — this is the root table everything else joins to.
- **Load into Postgres:** **first.** Nothing else can validate its FKs until
  this table exists.

### Stage 2 — `vle.csv` → `vle_sites`

- **Cleaning:** drop `week_from`, `week_to` (82% null on both — decided
  in oulad.md as too sparse to keep as a general feature).
- **Missing values:** none on the 4 retained columns.
- **Duplicates:** none; assert `id_site` unique.
- **Dtype conversions:** `id_site` → int (PK), `code_module`/
  `code_presentation` → str, `activity_type` → category.
- **FK validation:** every `(code_module, code_presentation)` must exist in
  `courses` — assert zero orphans.
- **Load into Postgres:** after `courses` (Stage 1). Independent of
  `assessments`/`enrollments`.

### Stage 3 — `assessments.csv` → `assessments`

- **Cleaning:** none — keep all 6 columns.
- **Missing values:** `date` null for 11 rows, all `assessment_type = Exam`
  — leave `NULL` (documented OULAD behavior: final exam dates withheld/
  variable), do not impute or drop.
- **Duplicates:** none; assert `id_assessment` globally unique.
- **Dtype conversions:** `id_assessment` → int (PK), `code_module`/
  `code_presentation` → str, `assessment_type` → category
  (TMA/CMA/Exam), `date` → nullable int, `weight` → float.
- **FK validation:** every `(code_module, code_presentation)` must exist in
  `courses`.
- **Load into Postgres:** after `courses`. Independent of `vle_sites`/
  `enrollments` — Stages 2 and 3 can run in either order or in parallel.

### Stage 4 — `studentInfo.csv` + `studentRegistration.csv` → `enrollments` (merge)

The one merge in the schema — both files share the exact same grain and key
set (verified in oulad.md), so this is a lossless 1:1 join, not a
denormalization risk.

- **Cleaning:**
  - Drop `region` from `studentInfo` (UK-specific, no analog in a generic
    classroom twin — oulad.md #3).
  - Fix the `imd_band` formatting inconsistency: one category is `"10-20"`
    without the trailing `%` while every other bucket is `"XX-XX%"`.
    Normalize to `"10-20%"` before persisting, so it sorts/encodes
    consistently as an ordinal category later. This must happen *before*
    the null check below, not after, so the fix isn't mistaken for a
    distinct valid category.
  - Join `studentInfo` and `studentRegistration` on the full composite key
    `(code_module, code_presentation, id_student)`.
- **Missing values:**
  - `imd_band`: 1,111 nulls (3.4%) — leave `NULL` (SES proxy; imputing risks
    encoding bias into a field that may correlate with the outcome).
  - `date_registration`: 45 nulls (0.14%) — leave `NULL` (unknown
    registration date, not zero).
  - `date_unregistration`: 22,521 nulls (69%) — leave `NULL`. This is the
    single most important null-handling rule in the whole dataset: `NULL`
    here means "did not withdraw," not "unknown." Never impute, never treat
    as 0.
- **Duplicates:** none expected; assert the merged table's composite key
  `(code_module, code_presentation, id_student)` is still unique post-join
  (guards against a fan-out bug in the join itself, not just source dupes).
- **Row-count guard:** assert `len(merged) == len(studentInfo) ==
  len(studentRegistration)` — any drop or duplication here means the join
  key assumption broke on this download of the data.
- **Dtype conversions:** `id_student` → int, `code_module`/
  `code_presentation` → str, `gender` → category, `highest_education` →
  category, `imd_band` → category (nullable), `age_band` → category,
  `num_of_prev_attempts` → int, `studied_credits` → int, `disability` →
  category (`Y`/`N`, kept as source string, not cast to bool at this layer),
  `date_registration` → nullable int, `date_unregistration` → nullable int,
  `final_result` → category (target, kept as-is: Pass/Fail/Withdrawn/
  Distinction — no ordinal/binary encoding here).
- **FK validation:** every `(code_module, code_presentation)` must exist in
  `courses`.
- **Load into Postgres:** after `courses`. Independent of `vle_sites`/
  `assessments`, but must complete **before** Stage 5 and Stage 6, since
  both downstream tables FK into `enrollments`.

### Stage 5 — `studentAssessment.csv` → `assessment_submissions`

- **Cleaning:** join through `assessments` first to recover
  `code_module`/`code_presentation` for each row (the source file doesn't
  carry them). Decide on `is_banked`: **keep the column in the persisted
  table** (cheap, informational, and dropping it silently would lose
  provenance), but exclude it from the Student Digital Twin's feature read
  path — a banked score reflects a *previous* presentation's effort, not
  this one, so blending it into a knowledge-state update without flagging
  it would misrepresent current engagement.
- **Missing values:** `score` — 173 nulls (0.1%), genuinely missing/
  ungraded. Leave `NULL` — do not impute to 0 (would read as "failed") and
  do not drop the row (the submission's existence + `date_submitted` is
  still a valid signal even without a score).
- **Duplicates:** none expected; assert `(id_assessment, id_student)`
  unique.
- **Dtype conversions:** `id_assessment` → int (FK), `id_student` → int,
  `date_submitted` → int, `score` → nullable float (0–100), `is_banked` →
  bool.
- **FK validation:** every `id_assessment` must exist in `assessments`
  (verified no orphans in the audit). Every `(code_module, code_presentation,
  id_student)` derived via the `assessments` join must exist in
  `enrollments` — this is a two-hop check (`studentAssessment` →
  `assessments` → `enrollments`), not a direct FK, so it needs to be
  validated explicitly in the load script rather than assumed from a
  simpler single-column check.
- **Load into Postgres:** after **both** `assessments` (Stage 3) and
  `enrollments` (Stage 4) exist.

### Stage 6 — `studentVle.csv` → `vle_interactions` (aggregated)

Largest and most involved step — 10,655,280 raw rows, 433MB, and the
dataset's one real data-quality defect lives here.

- **Cleaning — the critical operation:** group by the full 5-column key
  `(code_module, code_presentation, id_student, id_site, date)` and **sum**
  `sum_click` across all rows sharing that key, in a single pass. This one
  operation resolves both anomalies the audit found:
  - the 2,195,960 rows (20.6%) that share a key with a *different*
    `sum_click` value — these are genuinely separate partial contributions
    to the same day's total and must be summed;
  - the 787,170 fully-duplicate rows (7.4%) — these are the same
    partial-contribution pattern, just with two rows that happen to land on
    the same click count. **Decision: sum these too, do not de-duplicate
    them first.** Rationale: oulad.md's finding is that this file is *not*
    pre-aggregated despite `sum_click`'s name — each row is one partial
    contribution to a day's total, and there is no documented key in the
    public OULAD release that distinguishes "genuine duplicate log entry"
    from "two real contributions with matching counts." Treating exact
    duplicates as redundant (dropping one) would silently undercount
    exactly the rows the audit flagged as the dataset's main risk.
    Groupby-sum as one operation is the simplest rule that doesn't require
    guessing at that distinction. Flagging this explicitly as a judgment
    call to confirm before implementation, since it's the one genuinely
    ambiguous decision in this whole plan.
- **Missing values:** none on the 6 kept columns.
- **Duplicates:** fully handled by the aggregation above — there is no
  separate dedup step, the groupby-sum *is* the dedup step.
- **Dtype conversions:** `code_module`/`code_presentation` → str,
  `id_student` → int, `id_site` → int, `date` → int (day offset from course
  start), `sum_click` → int (post-aggregation).
- **FK validation:** every `id_site` must exist in `vle_sites`; every
  `(code_module, code_presentation, id_student)` must exist in
  `enrollments`.
- **Load into Postgres:** **last** — depends on both `vle_sites` (Stage 2)
  and `enrollments` (Stage 4).
- **Implementation note (not a schema decision, flagging now since it
  affects how Stage 6 is built):** at 10.6M raw rows, this should not be
  loaded as one in-memory pandas transform. Recommend either chunked
  `read_csv` with incremental groupby-accumulation, or a bulk `COPY` into an
  unlogged staging table followed by an `INSERT ... SELECT ... GROUP BY` in
  Postgres itself, then dropping the staging table. Worth deciding at
  implementation time, not blocking plan approval.

---

## PostgreSQL load order (= pipeline order above)

```
1. courses
2. vle_sites, assessments      (either order — both only depend on courses)
3. enrollments                 (depends on courses)
4. assessment_submissions      (depends on assessments + enrollments)
5. vle_interactions            (depends on vle_sites + enrollments — load last, largest)
```

---

## Features preserved for the Student Digital Twin

One twin instance = one `enrollments` row (per-enrollment, not
per-person — `id_student` is reused across 3,538 students' multiple
enrollments, so the composite key is the twin's real identity, per
oulad.md's identifier caveat).

- **`enrollments`** (own row): `gender`, `highest_education`, `imd_band`,
  `age_band`, `num_of_prev_attempts`, `studied_credits`, `disability`
  (profile) + `date_registration`, `date_unregistration` (timing) +
  `final_result` (outcome/target).
- **`assessment_submissions`** (all rows for this enrollment, ordered by
  `date_submitted`, joined to `assessments` for `assessment_type`/`weight`/
  due `date`): feeds the knowledge-state trajectory. `score` read as-is
  including nulls (ungraded ≠ zero). `is_banked` excluded from the feature
  read even though it's persisted.
- **`vle_interactions`** (all rows for this enrollment, ordered by `date`,
  optionally joined to `vle_sites` for `activity_type`): feeds the
  engagement history.
- **`courses`** (its one matching row): used only to normalize `date`
  values into "% through the course," not as a feature itself.

Not read by the Student twin: any other enrollment's rows, or the
`region`/`week_from`/`week_to`/`is_banked` columns dropped/excluded above.

## Features preserved for the Classroom Digital Twin

One twin instance = one `(code_module, code_presentation)` course
presentation, standing in for a physical classroom (OULAD has no room
concept — documented limitation, not an oversight).

- **`courses`** (its one row): `module_presentation_length`.
- **`enrollments`** (all rows sharing the key): roster size, demographic
  mix, `final_result` distribution across the cohort.
- **`assessments`** (all rows sharing the key): the shared assessment
  calendar/weighting.
- **`vle_sites`** (all rows sharing the key): the resource catalog.
- **`assessment_submissions`** and **`vle_interactions`**, aggregated
  (mean/median score per assessment, daily click-volume trend) across every
  enrollment in the cohort — the structural difference from the Student
  twin: many students' rows reduced, not one student's rows in sequence.

---

## Resolved scope decisions

This plan pulls the `enrollments` / `assessment_submissions` /
`vle_interactions` / `courses` / `assessments` / `vle_sites` tables and a
Postgres load step forward ahead of `PROJECT_PLAN.md`'s stated order
(M1 domain models → M2 persistence). That's a deliberate scope call the
user made explicitly ("start with real data... before implementing domain
models"), consistent with ADR-002/ADR-008's own point that the twin
engine's update logic needs something real to validate against.

Two module-boundary questions raised during planning, now decided:

1. **Code location: new `data/preprocessing/` module.** Kept separate from
   `data/adapters/` (interface for *live* real-source integrations —
   OULAD is real but static/historical, not a live LMS connection) and
   `data/generators/` (synthetic only). Holds the per-table cleaning
   functions (Stages 1–6 above) and the Postgres load/seed script.
2. **`PROJECT_PLAN.md`: no milestone edit.** Treated as within M1's existing
   scope (dataset selection/inspection was already tracked there) — proceed
   without inserting a formal M1.5 entry.

This does mean Stage 4–6's Postgres tables need SQLAlchemy models before
they can be loaded — a small, OULAD-scoped slice of `data/db/models.py`
pulled forward from M2, not the full M2 milestone (no repositories for
domain entities that don't exist yet).

Stopping here for approval before any code is written.
