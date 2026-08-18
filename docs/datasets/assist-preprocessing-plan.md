# ASSISTments 2019–2020 School Year — Preprocessing Plan

Plan only for this section — code follows immediately after, per the approved
workflow (unlike OULAD/xAPI, this plan and its implementation are being
produced in the same pass, at the user's request). As with
`xapi-preprocessing-plan.md`, there is no separate profiling doc on disk;
every finding below comes from direct inspection of the seven raw files under
`data/raw/2019-2020_school_year/`.

Target schema (new, independent of OULAD and xAPI — no shared identifier, no
join to either): `assist_districts`, `assist_classes`,
`assist_student_classes` (from `sdets.csv`), `assist_assignments` (from
`adets.csv`), `assist_problems` (from `pdets.csv`), `assist_assignment_logs`
(from `alogs.csv`), `assist_problem_logs` (from `plogs.csv`).

---

## Source profile

Seven CSVs, three orders of magnitude apart in size (1,822 rows to 20.75M
rows):

| File | Rows | Maps to |
|---|---|---|
| `ddets.csv` | 1,822 | `assist_districts` |
| `cdets.csv` | 17,003 | `assist_classes` |
| `sdets.csv` | 286,592 | `assist_student_classes` |
| `adets.csv` | 197,022 | `assist_assignments` |
| `pdets.csv` | 134,655 | `assist_problems` |
| `alogs.csv` | 2,505,225 | `assist_assignment_logs` |
| `plogs.csv` | 20,752,836 | `assist_problem_logs` |

Key findings, each verified programmatically, not assumed:

- **`ddets.district_id` is unique, but no other file carries a
  `district_id` or any other district-linking column.** `cdets.csv` has no
  `district_id`/`school_id`; neither does any other file. There is no
  teacher→district or class→district mapping anywhere in this release.
  `assist_districts` is therefore a **standalone table with no FK from or
  to any other ASSISTments table** — not an oversight, a verified absence,
  documented rather than bridged with an invented key.
- **`cdets.class_id` is unique** (17,003 rows). `teacher_id` has no
  corresponding teacher table in this release, so it stays a plain
  attribute, not a foreign key.
- **`sdets.student_id` is *not* unique** — 286,592 rows, 277,512 distinct
  `student_id` values; 8,560 students appear under more than one
  `class_id`. The natural key is the composite `(student_id, class_id)`,
  verified unique. This is the same shape as OULAD's `id_student` reuse
  across enrollments — one student, several class memberships, no single
  row is "the" student.
- **`adets.assignment_id` is unique** (197,022 rows); every row's
  `class_id` exists in `cdets` (0 orphans).
- **`pdets.problem_id` is *not* unique as loaded — because 392 rows have
  `problem_id = NaN`.** Every one of those 392 rows also has
  `content_source = "['Undetermined']"` and null `skills`/`problem_type`/
  `tutoring_types` — a coherent "unidentified problem" bucket, not random
  corruption. A table row with no identifier cannot be a primary-keyed
  persisted row and no ID may be invented for it (explicit project rule),
  so these 392 rows are **excluded** from `assist_problems`. The remaining
  134,263 rows have a verified-unique `problem_id`.
- **`alogs.log_id` is unique** (2,505,225 rows); every row's
  `assignment_id` exists in `adets` and every `student_id` exists in
  `sdets` (0 orphans on both).
- **`plogs.log_id` is a foreign key to `alogs.log_id`, not a primary key of
  `plogs` itself.** Distinct `log_id` count in `plogs` (2,505,225) exactly
  matches the row count of `alogs` — one assignment-attempt session
  (`alogs` row) produces many problem-level rows in `plogs`. Verified 0
  orphans: every `plogs.log_id` exists in `alogs`.
- **`plogs.student_id` and `plogs.assignment_id` are redundant** — verified
  to match their parent `alogs` row's values on all 20,752,836 rows, 0
  mismatches. Dropped from the persisted table; reachable via
  `log_id → assist_assignment_logs`, the same normalization OULAD applies
  to `assessment_submissions` dropping `code_module`/`code_presentation`.
- **`(log_id, problem_id)` is *not* unique in `plogs`** — 508 rows collide.
  Inspecting an example pair shows genuinely different events (different
  `start_time`, different `correct`, different `answer_before_tutoring`) —
  a student retrying the same problem within the same assignment session on
  a different day. Not a duplicate-data artifact; a surrogate primary key
  is required because no source column combination is unique, proven by
  these 508 rows, not assumed.
- **`plogs.problem_id` has 0 nulls, but 392 distinct values (172,865 of
  20,752,836 rows, 0.83%) don't exist in `assist_problems`.** These are
  exactly the 392 problems whose `pdets` row has no `problem_id` — the
  detail table lost the identifier, but individual attempt logs still
  recorded the real ID. This is a genuine, explainable data-quality gap:
  dropping 172,865 real attempt-events to satisfy a hard FK constraint
  would destroy verified event history over a metadata gap in a different
  table. **`problem_id` is persisted as a plain integer column, not a
  database-enforced foreign key** — validated with a warning, not an
  assertion (see Validation rules).
- Nullable columns with no clean causal rule: `plogs.correct` (25.9% null)
  correlates loosely but not deterministically with `problem_completed`;
  `plogs.fraction_of_hints_used` (49.7% null) shows no clean correlation
  with `answer_before_tutoring`. Both are left `NULL`, not imputed — same
  rule as OULAD's `score`, but here the precise causal reason for
  missingness isn't recoverable from the data, and none is invented.
  `fraction_of_hints_used` also is **not** bounded to [0, 1] despite the
  name (observed up to 6.0) — no upper-bound range check is applied.
- `ddets.locale_description` is 97.5% null (1,776/1,822) — but unlike
  OULAD's `week_from`/`week_to` (dropped at 82% null for carrying no
  signal even when present), the populated values here are a real US
  Census-style rural/city/suburb/town classification (`"Town: Distant"`,
  `"Rural: Fringe"`, `"City: Large"`, …) — informative when present, simply
  absent for non-US/unclassified districts. Kept as a nullable column, not
  dropped — sparsity alone isn't the rule, whether the sparse value carries
  signal is.
- `adets.mean_correct` and `pdets.mean_correct` both observed in [0, 1]
  (fractions correct); `plogs.attempt_count` observed in [0, 228];
  `plogs.time_on_task` observed in [0.001, 6883.359] seconds — all
  non-negative, no negative-value violations found.
- All date/timestamp columns (`release_date`, `due_date`,
  `class_creation_date`, `account_creation_date`, `start_time` ×2) are real
  ISO-8601 timestamps with UTC offsets, in **mixed formats** (some with
  microseconds, some without — `format="ISO8601"` in pandas handles both).
  Unlike OULAD's integer day-offsets, these are genuine timestamps and are
  mapped to `DateTime(timezone=True)` (Postgres `timestamptz`), parsed as
  UTC — the absolute instant is preserved regardless of the originally
  recorded local offset.
- `pdets.content_source`, `skills`, `tutoring_types` contain Python-list-
  repr strings (e.g. `"['Certified Content', 'Engage New York']"`). Kept as
  raw opaque strings, not parsed into a normalized skills/tags junction
  table — consistent with the project's standing rule to persist raw
  categorical values and leave encoding/decomposition to `analytics/`, and
  with the instruction to minimize new abstractions.

---

## Guiding rules for this pass

1. **Preprocessing order = FK dependency order = Postgres load order**,
   same principle as OULAD and xAPI.
2. **Never invent an identifier or a relationship.** The 392 nulled
   `problem_id` rows are dropped, not assigned a synthetic ID; `ddets` is
   left unlinked, not joined via a guessed key; `teacher_id` stays a plain
   attribute, not a foreign key to a table that doesn't exist here.
3. **A hard FK constraint is only used where the data proves it always
   holds.** Every FK in this schema except one is a verified zero-orphan
   relationship. The one exception (`assist_problem_logs.problem_id`) is
   downgraded to a validated-but-unenforced column specifically because
   forcing it would require inventing an ID or discarding real event rows.
4. **Persist raw categorical/list-like values, not encodings or
   decompositions** — same rule as OULAD and xAPI.
5. **Re-verify every claim in this document at load time.**

---

## Pipeline — 7 stages, in dependency order

### Stage 1 — `ddets.csv` → `assist_districts`

- **Cleaning:** none needed.
- **Missing values:** `locale_description` null for ~97.5% of rows — leave
  `NULL` (see Source profile; informative when present).
- **Duplicates:** none; assert `district_id` unique.
- **Dtype conversions:** `district_id` → int (PK), `location` →
  string, `opportunity_zone` → string, `locale_description` → nullable
  string.
- **FK validation:** none — and none *to* this table either. Standalone.
- **Load into Postgres:** any time — no dependency edges in either
  direction. Loaded first for consistency with OULAD/xAPI's "root first"
  convention, not because anything requires it.

### Stage 2 — `cdets.csv` → `assist_classes`

- **Cleaning:** none needed.
- **Missing values:** none present.
- **Duplicates:** none; assert `class_id` unique.
- **Dtype conversions:** `class_id` → int (PK), `teacher_id` → int (plain
  attribute, no FK target), `class_creation_date` → timestamptz,
  `student_count`/`problem_sets_assigned`/`skill_builders_assigned` → int.
- **FK validation:** none — root table for everything class-scoped.
- **Load into Postgres:** independent of `assist_districts`/
  `assist_problems`; must precede Stage 3 and Stage 4.

### Stage 3 — `pdets.csv` → `assist_problems`

- **Cleaning:** drop the 392 rows with null `problem_id` (see Source
  profile — no ID may be invented for them).
- **Missing values:** `skills` (~65% null among retained rows),
  `tutoring_types` (~40% null), `mean_correct`, `mean_time_on_task` — all
  left `NULL`, none imputed.
- **Duplicates:** none among retained rows; assert `problem_id` unique.
- **Row-count guard:** assert `len(retained) == len(raw) - 392`.
- **Dtype conversions:** `problem_id` → int (PK, cast from float after
  dropping nulls), `content_source`/`skills`/`problem_type`/
  `tutoring_types` → nullable string (raw, unparsed), `student_answer_count`
  → int, `mean_correct`/`mean_time_on_task` → nullable float.
- **FK validation:** none — standalone content dimension, same role
  `assessments`/`vle_sites` play for OULAD.
- **Load into Postgres:** independent of `assist_classes`; only
  `assist_problem_logs` (Stage 7) references it, and only as a
  warning-validated soft reference, not a hard FK.

### Stage 4 — `sdets.csv` → `assist_student_classes`

- **Cleaning:** none needed.
- **Missing values:** `mean_problem_correctness` (6.9%),
  `mean_problem_time_on_task` (4.9%) — left `NULL`.
- **Duplicates:** none; assert composite key `(student_id, class_id)`
  unique.
- **Row-count guard:** assert `len(df) == 286,592` (no rows dropped).
- **Dtype conversions:** `student_id`/`class_id` → int (composite PK),
  `account_creation_date` → timestamptz, the five `*_count` columns → int,
  `mean_problem_correctness`/`mean_problem_time_on_task` → nullable float.
- **FK validation:** every `class_id` must exist in `assist_classes`.
- **Load into Postgres:** after `assist_classes`. Must complete before
  Stage 6 (`assist_assignment_logs` FKs into it via `student_id`).

### Stage 5 — `adets.csv` → `assist_assignments`

- **Cleaning:** none needed.
- **Missing values:** `mean_correct` (11.5%), `mean_time_on_task` (4.1%) —
  left `NULL`.
- **Duplicates:** none; assert `assignment_id` unique.
- **Dtype conversions:** `assignment_id` → int (PK), `class_id` → int (FK),
  `release_date`/`due_date` → timestamptz, `assignment_type` → string
  (`problem_set`/`skill_builder`), the three `*_count` columns → int,
  `mean_correct`/`mean_time_on_task` → nullable float.
- **FK validation:** every `class_id` must exist in `assist_classes`.
- **Load into Postgres:** after `assist_classes`. Independent of Stage 4;
  must complete before Stage 6.

### Stage 6 — `alogs.csv` → `assist_assignment_logs`

- **Cleaning:** none needed.
- **Missing values:** `mean_correct` (12.5%), `time_on_task` (5.6%) — left
  `NULL`.
- **Duplicates:** none; assert `log_id` unique.
- **Dtype conversions:** `log_id` → int (PK), `student_id`/`assignment_id`
  → int (FK), `start_time` → timestamptz, `mean_correct`/`time_on_task` →
  nullable float, `assignment_completed` → bool.
- **FK validation:** every `assignment_id` must exist in
  `assist_assignments`; every `student_id` must exist in
  `assist_student_classes` (single-column check against that table's
  distinct `student_id` values — the same shape as OULAD's
  `assessment_submissions` → `assessments` check, reusing
  `assert_foreign_key`'s existing dedup-on-key-columns behavior).
- **Load into Postgres:** after **both** `assist_assignments` (Stage 5)
  and `assist_student_classes` (Stage 4).

### Stage 7 — `plogs.csv` → `assist_problem_logs`

Largest and most involved stage — 20,752,836 raw rows. Read in chunks, same
approach as OULAD's `studentVle.csv` stage, but no aggregation is performed
here — this is an event log where every row is a distinct, meaningful
attempt, not a pre-fan-out count to be summed.

- **Cleaning:** drop `student_id`/`assignment_id` (redundant with the
  parent `alogs` row, verified 0 mismatches — see Source profile).
- **Missing values:** `time_on_task` (1.9%), `answer_before_tutoring`
  (1.5%), `fraction_of_hints_used` (49.7%), `correct` (25.9%) — all left
  `NULL`; no clean causal rule was found for any of them (see Source
  profile), so none is imputed and none is explained beyond what's
  verifiable.
- **Duplicates:** none dropped — the 508 `(log_id, problem_id)` collisions
  are genuine distinct events (see Source profile) and are both kept, each
  under its own surrogate key.
- **Row-count guard:** assert `len(df) == 20,752,836`.
- **Dtype conversions:** `id` → int (surrogate PK, DB-generated),
  `log_id` → int (FK), `problem_id` → int (validated, not FK-constrained),
  `start_time` → timestamptz, `time_on_task` → nullable float,
  `answer_before_tutoring` → nullable bool, `fraction_of_hints_used` →
  nullable float, `attempt_count` → int, `answer_given` → bool,
  `problem_completed` → bool, `correct` → nullable bool.
- **FK validation:** every `log_id` must exist in `assist_assignment_logs`
  (hard FK, verified 0 orphans on the full file). `problem_id` is checked
  against `assist_problems` with a **warning**, not an assertion — expect
  392 distinct missing IDs / 172,865 affected rows; a count materially
  larger than that on a future re-download should be investigated, but
  isn't rejected outright.
- **Implementation note:** chunked `read_csv` (`chunksize` similar to
  OULAD's VLE stage), no in-memory full-file load — at this row count the
  same reasoning from `oulad-preprocessing-plan.md` Stage 6 applies
  directly. No accumulation/groupby needed here since there's no
  aggregation step, just per-chunk cleaning, dtype casts, and append.

---

## PostgreSQL load order

```
1. assist_districts, assist_classes, assist_problems   (no dependencies among these three)
2. assist_student_classes, assist_assignments           (both depend on assist_classes)
3. assist_assignment_logs                                (depends on assist_assignments + assist_student_classes)
4. assist_problem_logs                                    (depends on assist_assignment_logs; soft-checks assist_problems — load last, largest)
```

`assist_districts` has no edges at all; it's placed in tier 1 by convention,
not by requirement.

---

## Primary key strategy

Three different strategies, each justified by what the data actually proves,
not chosen uniformly for consistency's own sake:

- **Natural single-column key** — `assist_districts.district_id`,
  `assist_classes.class_id`, `assist_assignments.assignment_id`,
  `assist_problems.problem_id` (post-drop). Each verified unique in its raw
  file.
- **Natural composite key** — `assist_student_classes(student_id,
  class_id)`. `student_id` alone is proven non-unique (8,560 students in
  >1 class); the pair is verified unique.
- **Surrogate autoincrement integer** — `assist_problem_logs.id`. No
  natural key exists: `log_id` alone repeats (one session, many problem
  rows, by design), and `(log_id, problem_id)` is proven non-unique by 508
  genuine same-problem-retry rows. Never derived from row content, for the
  same reason as xAPI's `record_id`: a content-based key would collide on
  exactly the rows shown to be legitimately distinct.

`assist_assignment_logs.log_id` is a natural key at its own grain (verified
unique in `alogs`) *and* the foreign key `assist_problem_logs` uses to reach
it — no surrogate needed there, only at the problem-log grain where the
natural composite fails.

---

## Validation rules

Reusing `data/preprocessing/validation.py`'s existing
`assert_unique`/`assert_foreign_key`/`assert_row_count_preserved` for every
hard constraint above. Two additions, both non-fatal (log, don't raise),
extending the pattern already established for xAPI
(`warn_on_duplicate_rows`, `warn_out_of_range`):

- **`warn_foreign_key`** (new): same left-merge-and-check shape as
  `assert_foreign_key`, but logs a warning with the orphan count instead of
  raising. Used exactly once — `assist_problem_logs.problem_id` against
  `assist_problems.problem_id` — because the gap is a verified, explained
  property of this dataset release, not an error to fail the load over.
- **`warn_out_of_range`** (existing, reused): non-negativity spot-checks on
  `attempt_count`, `time_on_task`, `mean_correct`-family columns. No upper
  bound is asserted on `fraction_of_hints_used`, since the data itself
  shows values above 1.0.

Every other relationship in this schema (7 of 8 FK edges) uses the existing
hard `assert_foreign_key`/`assert_unique` unchanged.

---

## Mapping into the Digital Twin architecture

Unlike xAPI, this dataset supports a **dynamic** Student Digital Twin, the
same category as OULAD — it has the temporal ingredient xAPI lacks:

- **Student Digital Twin — dynamic.** One twin instance = one
  `assist_student_classes` row `(student_id, class_id)`, the same
  per-enrollment-not-per-person identity convention as OULAD (`student_id`
  reused across classes, so the composite is the real identity). Its
  trajectory is built from `assist_assignment_logs` (all rows for that
  `student_id`, ordered by `start_time` — one row per assignment attempt
  session) and, two hops down, `assist_problem_logs` (via `log_id`,
  ordered by `start_time` — one row per problem attempted within a
  session): attempt counts, hint usage, correctness, and completion over
  the school year are exactly the kind of continuously-arriving signal
  `twin_engine/`'s update logic is for.
- **Classroom Digital Twin.** One twin instance = one `assist_classes` row.
  Roster and demographics from `assist_student_classes` (all rows sharing
  `class_id`); assignment calendar from `assist_assignments`; aggregated
  engagement (mean correctness, completion rates, hint usage) from
  `assist_assignment_logs`/`assist_problem_logs` rolled up across every
  student in the class.
- **`assist_problems`** — a shared, read-only curriculum-content
  dimension, the same role OULAD's `assessments`/`vle_sites` play: joined
  via `assist_problem_logs.problem_id` for `problem_type`/`content_source`
  context, never a twin instance itself. The 0.83% of problem-log rows
  whose `problem_id` isn't in this catalog should still contribute to a
  twin's raw event count/trajectory — they just won't resolve to a
  `problem_type` when joined, which is a display/enrichment gap, not a
  reason to exclude them from the twin's history.
- **`assist_districts`** — **not reachable from any twin instance in this
  release.** No FK path connects it to `assist_classes` or
  `assist_student_classes`. It is freestanding geographic/demographic
  reference data, not a twin feature source — a documented limitation of
  this dataset release, the same category as OULAD having no room concept
  or xAPI being unjoinable to OULAD, not something to work around with an
  invented link.

---

## Resolved scope decisions

1. **Independent schema, `assist_` table prefix**, no join to OULAD or
   xAPI — same convention as xAPI's `xapi_` prefix, for the same reason
   (avoid colliding with a future generic domain name).
2. **`assist_problem_logs.problem_id` is validated but not FK-constrained**
   — the one deliberate exception to "every FK is a verified zero-orphan
   relationship" in this plan, justified in Source profile and enforced via
   the new `warn_foreign_key` helper rather than `assert_foreign_key`.
3. **392 identifier-less `pdets` rows are dropped**, not assigned a
   synthetic ID — consistent with "never invent an identifier."
4. **`assist_districts` stays unlinked** rather than joined via any
   inferred key — no such key exists in the data.
5. **Code location:** `data/preprocessing/` — one `preprocess_assist_*.py`
   per table (7 files) plus `load_assistments.py`, mirroring
   `load_oulad.py`/`load_xapi.py` exactly, reusing their `_bulk_load`
   helper rather than duplicating it.

Proceeding directly to implementation per the approved workflow — this plan
and the code are being delivered together, unlike OULAD/xAPI's separate
plan-then-implement passes.
