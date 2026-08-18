# Dropout-Risk Prediction: Feature/Target Design (Student ML MVP)

First real student-level ML experiment, built on top of the already-loaded
PostgreSQL schemas (see [oulad.md](oulad.md), CLAUDE.md's module boundaries,
DECISIONS.md ADR-005/ADR-008). Design-first, matching the actual `enrollments`/
`assessment_submissions`/`vle_interactions` schema in `data/db/models.py`, not
a re-derivation from the raw CSVs.

## Which dataset trains the model, and why

**OULAD is the training dataset.** Two real alternatives exist in this
project's Postgres schema, and neither is used for training:

- **ASSISTments** (`assist_*` tables) has no dropout/withdrawal-shaped target
  at all — it's a math-tutoring interaction log (correct/incorrect per
  problem). There is nothing to predict here; it is out of scope for this
  experiment entirely, not "supporting data."
- **`dropout_records`** (UCI/Zenodo dropout dataset) is a **fully anonymized,
  static, single-snapshot population with no student identifier and no time
  dimension** — one row per (unknown) student, `Graduate`/`Dropout`/`Enrolled`
  known only as a final state. It cannot supply *early*, time-bounded
  features (there's no "day 30" concept in it), so it cannot train an
  early-warning model. It is **not joined to OULAD in any way** — its
  population is a different, unrelated set of students at a different
  institution, and its row-level identifiers don't correspond to OULAD's
  `id_student` (verified: neither dataset carries any column that could
  plausibly key the same real person). It is left **entirely unused** for
  this experiment, not blended or validated against — using it as a "test"
  for an OULAD-trained model would silently assume population equivalence
  that doesn't exist. A future, separate experiment could train an
  independent second model on `dropout_records` alone and compare
  methodology, but that is out of scope here.

**OULAD** (`enrollments`, `assessment_submissions`, `vle_interactions`) is
used because it is the only dataset in this project with (a) a genuine
per-student dropout label (`enrollments.final_result = 'Withdrawn'`), (b) a
real *timing* signal for that label (`date_unregistration`, in days from
course start), and (c) day-level behavioral history
(`vle_interactions.date`, `assessment_submissions.date_submitted`) that lets
features be computed strictly *before* a chosen cutoff — the one thing
`dropout_records` structurally cannot offer. This also matches OULAD's role
as the project's spine dataset (ADR-008).

## Target definition

`is_dropout = 1` if `enrollments.final_result = 'Withdrawn'`, else `0`
(`Pass`/`Fail`/`Distinction` → `0`). Withdrawal specifically, not academic
failure — "dropout" here means *disengagement from the course*, not a poor
grade while still completing it; conflating the two would answer a
different, less useful question for an early-warning use case.

**Population**: only enrollments still active past the cutoff day
(`date_unregistration IS NULL OR date_unregistration > cutoff_day`).
Enrollments that had already withdrawn *by* the cutoff are excluded — their
outcome is already visible at the snapshot point, so "predicting" it isn't a
real prediction task, and including them would let the model trivially learn
"near-zero post-cutoff activity ⇒ withdrawn" from data it shouldn't have had
a decision to make about yet.

With `cutoff_day = 30` (out of a 234–269 day course, ~12% through — verified
against `courses.module_presentation_length`, min 234/max 269/avg 255.5):
**27,466 of 32,593 enrollments** are eligible. Within that population:
**5,037 dropouts (18.3%) vs. 22,429 non-dropouts (81.7%)** — a real, moderate
class imbalance, handled via `class_weight="balanced"`, not resampling.

*Known edge case*: 93 `Withdrawn` enrollments have a null
`date_unregistration` (withdrew, but the source data doesn't record when).
These are conservatively kept in the eligible population (null is treated as
"not proven to be before the cutoff") — a documented, defensible choice, not
an oversight.

## Features (one row per enrollment, computed only from data ≤ cutoff_day)

| Feature | Source table.column | Type | Notes |
|---|---|---|---|
| `gender` | `enrollments.gender` | categorical | known at enrollment |
| `highest_education` | `enrollments.highest_education` | categorical | known at enrollment |
| `imd_band` | `enrollments.imd_band` | categorical | ~3.4% null (socioeconomic proxy, structurally missing — see oulad.md) |
| `age_band` | `enrollments.age_band` | categorical | known at enrollment |
| `disability` | `enrollments.disability` | categorical | known at enrollment |
| `num_of_prev_attempts` | `enrollments.num_of_prev_attempts` | numeric | known at enrollment |
| `studied_credits` | `enrollments.studied_credits` | numeric | known at enrollment |
| `date_registration` | `enrollments.date_registration` | numeric | days relative to course start; ~0.14% null |
| `assessments_submitted_count` | `COUNT(*)` over `assessment_submissions` (via `assessments` for course context) | numeric | only rows with `date_submitted <= cutoff_day` and `is_banked = false` |
| `assessments_mean_score` | `AVG(score)` over the same filtered rows | numeric | null if zero submissions by cutoff (~26% of the eligible population — only 17 of 206 assessments are even due by day 30) |
| `vle_total_clicks` | `SUM(sum_click)` over `vle_interactions` | numeric | only rows with `date <= cutoff_day` |
| `vle_active_days` | `COUNT(DISTINCT date)` over the same filtered rows | numeric | |
| `vle_distinct_sites` | `COUNT(DISTINCT id_site)` over the same filtered rows | numeric | |

**Not used as features**: `id_student`, `code_module`, `code_presentation`
(identifiers — `id_student` is dataset-scoped and reused across a student's
own enrollments, never a predictive signal, and never fed to the model
per-instruction), `final_result`/`date_unregistration` (target and
target-adjacent — see leakage section), `region` (already excluded from the
persisted `enrollments` schema, per oulad.md's own recommendation),
`is_banked` submissions (excluded at the SQL level — a banked score reflects
a *previous* presentation's effort, not this one).

`code_module`/`code_presentation` are legitimate, non-leaking features
(known at enrollment, real course-difficulty signal) but are deliberately
left out of this first baseline to keep it to demographic + early-behavioral
signal only, rather than letting the model lean on per-course base rates as
a shortcut. Worth adding in a follow-up iteration.

## Missing-value handling

- Categorical (`imd_band` is the only one with real nulls: 1,027 of 27,466):
  imputed to an explicit `"Unknown"` category, not most-frequent — a missing
  socioeconomic proxy should never be silently folded into the majority
  class.
- Numeric (`date_registration`: 7 nulls; `assessments_mean_score`: 7,108
  nulls — no submissions by cutoff, not a data error): median imputation.
- `assessments_submitted_count`/`vle_*`: not imputed — `COALESCE`d to `0` at
  the SQL level, since "no activity by cutoff" is a real 0, not a missing
  value.
- All imputation is fit only on the training split (`sklearn.Pipeline`
  inside a `ColumnTransformer`), never on validation/test/full data.

## Train / validation / test split

Stratified 60/20/20 by `is_dropout` (`sklearn.train_test_split`, twice,
`random_state=42`), preserving the ~18.3% dropout rate in every split.
Enrollment rows are treated as i.i.d. for this first baseline (no
course-level grouping) — a reasonable simplification for an MVP, worth
revisiting if a later model needs to generalize to an unseen course
presentation rather than an unseen student within a seen course.

## Leakage risks and how each is addressed

1. **`final_result` as a feature** — never included; it *is* the target.
2. **`date_unregistration` as a feature** — never included; using it would
   trivially reveal the target (non-null ⇒ withdrew). It is used only to
   define population eligibility, via a *fixed*, target-independent cutoff
   day, never the student's own withdrawal day.
3. **Post-cutoff events** — every aggregate (`assessments_*`, `vle_*`) is
   filtered to `date <= cutoff_day` / `date_submitted <= cutoff_day` at the
   SQL level, so nothing after the snapshot point can enter a feature.
4. **Banked assessment scores** — excluded (`is_banked = false`): a banked
   score is carried over from a *previous* presentation, not evidence of
   this presentation's engagement, and its presence itself is a soft
   proxy for prior withdrawal history.
5. **`id_student` as a feature** — never included; it's dataset-scoped, not
   a real person identifier (see `domain/student.py`), and reused across a
   student's own multiple enrollments — including it would let the model
   memorize per-student identity rather than generalizing from behavior.
6. **Class imbalance handling** (`class_weight="balanced"`) is applied only
   inside the fitted `Pipeline`, computed from the training split's label
   distribution — it does not use validation/test labels.
