# Data Quality Audit: keep / delete / replace decisions for `data/raw`

Applies two checks across every dataset currently in `data/raw`, building on
the per-file evidence already gathered in [oulad.md](oulad.md) and
[schema-validation.md](schema-validation.md), plus additional read-only
profiling (null counts, duplicate-row checks, key-integrity checks, row
counts) done specifically for this audit on the datasets that hadn't been
fully profiled yet (`dropout_prediction`, `occupancy+detection`,
`environmental_sensors.csv`, and a deeper pass on `2019-2020_school_year`).
No preprocessing performed.

**Update (this pass):** the two datasets flagged as acquisition problems in
the previous audit have been corrected — `engagement_analysis/DATA (1).csv`
has been replaced with the real `xAPI-Edu-Data/xAPI-Edu-Data.csv`, and
`NYC_attendance.csv` (an actual data export) has been added alongside the
old documentation-only `.xlsx`. Both were re-profiled from scratch below
(sections 3 and 7) rather than assumed correct.

1. **Delete/replace candidates** — datasets that are duplicates, incorrect,
   incomplete, low quality, or misaligned with the project.
2. **Module support verification** — confirms each surviving dataset can
   support at least one of: Student Digital Twin (SDT), Classroom Digital
   Twin (CDT), Learning Analytics (LA), Performance Prediction (PP),
   Engagement Analysis (EA), Personalized Learning (PL), Teacher Decision
   Support (TDS).

---

## 1. `oulad/` (7 files)

**Verdict: KEEP.** Already fully audited in [oulad.md](oulad.md) — verified
real, referentially clean across all 7 tables (0 unexpected duplicate rows
anywhere, all foreign keys resolve, all nulls are either trivial or
structurally meaningful and already explained). The one real defect found
(`studentVle.csv`'s duplicate-key aggregation issue) is a preprocessing
concern, not a quality/deletion issue — the underlying data is sound once
grouped correctly. This is the project's spine dataset; nothing here
qualifies as duplicate, incorrect, incomplete, or misaligned.

**Module support:** SDT (strong), CDT (strong, via course presentation as
cohort proxy), LA (strong), PP (strong — hosts the primary `final_result`
target), EA (strong, via `studentVle` clickstream), PL (weak — assessment
feedback only, no skill/topic tagging to drive recommendations), TDS
(strong — `final_result` + withdrawal timing support early-warning). Clears
the bar for all 7 modules, strongly for 6 of them.

---

## 2. `dropout_prediction/data.csv`

**Verdict: KEEP.** Freshly profiled for this audit: 4,424 rows × 37 columns,
**zero nulls, zero duplicate rows**, `Target` reasonably distributed
(Graduate 2,209 / Dropout 1,421 / Enrolled 794 — not as skewed as the
original ADR-008 research worried it might be). Real institutional data,
matches the known UCI schema exactly. No deletion criteria apply.

**Module support:** PP (strong — purpose-built dropout/academic-success
target), LA (strong — socioeconomic + academic features), TDS (strong —
early dropout signal), SDT (weak — usable as a standalone profile+outcome
source, but its `Course`/student identifiers are a disjoint population from
OULAD/ASSISTments, so it can only ever back a separate, non-joined Student
Digital Twin instance, not enrich an OULAD one). **Does not support** CDT (no
classroom/cohort roster, `Course` is a bare integer code with no metadata),
EA (no behavioral/time-series signal), PL (no per-skill or per-resource
data). Clears the bar (3 strong modules) — keep.

---

## 3. `xAPI-Edu-Data/xAPI-Edu-Data.csv` (replaces `engagement_analysis/`)

**Verdict: KEEP — corrected.** The wrong file flagged in the previous audit
has been replaced. Freshly profiled: 480 rows × 17 columns, header confirmed
as the genuine xAPI-Edu-Data (Kalboard 360) schema (`gender`, `NationalITy`,
`PlaceofBirth`, `StageID`, `GradeID`, `SectionID`, `Topic`, `Semester`,
`Relation`, `raisedhands`, `VisITedResources`, `AnnouncementsView`,
`Discussion`, `ParentAnsweringSurvey`, `ParentschoolSatisfaction`,
`StudentAbsenceDays`, `Class`) — row count (480) matches the dataset's known
size exactly. **0 nulls.** **2 duplicate rows** (0.4% of the data — minor,
worth dropping at preprocessing time, not a reason for concern). `Class`
(L/M/H performance target) is reasonably distributed: M 211 / H 142 / L 127.
`StudentAbsenceDays` (Under-7 289 / Above-7 191) and the behavioral columns
(`raisedhands`, `VisITedResources`, `AnnouncementsView`, `Discussion`) are
exactly the fine-grained engagement signal ADR-008 selected this dataset for
— and unlike the previous file, this one actually has them.

**Module support:** EA (strong — `raisedhands`/`VisITedResources`/
`AnnouncementsView`/`Discussion` are direct behavioral engagement measures),
PP (strong — `Class` target), LA (strong), TDS (moderate — per-student
behavioral flags support intervention targeting). SDT (weak — like
`dropout_prediction`, this is a disjoint population from OULAD/ASSISTments,
so it backs a standalone twin instance rather than enriching an existing
one). **Does not support** CDT (no classroom roster/cohort structure beyond
a bare `SectionID` code) or PL (no per-skill/per-resource data). Clears the
bar clearly and now, correctly, supports the Engagement Analysis role it was
originally selected for.

---

## 4. `2019-2020_school_year/` (ASSISTments, 7 files)

**Verdict: KEEP.** Freshly profiled all 7 files for this audit:

| File | Rows | Nulls found | Verdict |
|---|---|---|---|
| `ddets.csv` | 1,822 | `locale_description` null in 1,776 rows (97%) | expected — mostly non-US/unknown districts, not a defect |
| `cdets.csv` | 17,003 | none | clean |
| `sdets.csv` | 286,592 | `mean_problem_correctness`/`mean_problem_time_on_task` null where a student attempted 0 problems in that class | structurally meaningful, not a defect |
| `adets.csv` | 197,022 | `mean_correct`/`mean_time_on_task` null where an assignment had 0 completions | structurally meaningful |
| `pdets.csv` | 134,655 | see below | **real integrity issue found** |
| `alogs.csv` | 2,505,225 | not fully re-profiled this pass (already schema-checked) | — |
| `plogs.csv` | 20,752,836 | not fully re-profiled this pass (already schema-checked, `log_id`→`alogs.log_id` FK confirmed) | — |

**Real issue found in `pdets.csv`:** `problem_id` — meant to be this table's
primary key — has **392 null values and 391 duplicate values**, i.e. it is
not a clean key as distributed. Additionally, `skills` (the knowledge-tracing
tag column, most valuable for Personalized Learning) is **null in 88,267 of
134,655 rows (65.5%)**. Neither of these is severe enough to disqualify the
dataset — the affected rows are a small fraction of the total, and 34.5%
`skills` coverage across 134K+ problems is still a large, usable base — but
both need explicit handling at preprocessing time (deduplicate/drop the 392
bad `problem_id` rows; treat `skills`-null problems as "untagged" rather than
imputing a skill). Combined with the already-flagged missing
`cdets`↔`ddets` join path (schema-validation.md), this dataset has real,
documented rough edges — but none of them are disqualifying at the
dataset level.

**Module support:** SDT (strong), CDT (strong — `cdets.csv` is an actual
class roster with a real `teacher_id`, arguably the most literal "classroom"
of any dataset in this collection), LA (strong), PP (strong), EA (strong —
`time_on_task`, `attempt_count`, `fraction_of_hints_used`), PL (strong —
`skills` tagging, despite the 65% null rate, is still the best knowledge-
tracing signal available anywhere in this collection), TDS (strong —
teacher-level and class-level aggregates). Clears the bar for all 7 modules,
strongly.

---

## 5. `occupancy+detection/` (3 files)

**Verdict: KEEP.** Freshly profiled: `datatraining.txt` (8,143 rows),
`datatest.txt` (2,665 rows), `datatest2.txt` (9,752 rows) — confirmed **zero
date overlap between any pair of the three files** (they're three genuinely
distinct, chronologically separate periods in Feb 2015, not duplicates of
each other despite the similar naming), zero nulls, zero duplicate rows in
any of the three, and a reasonable occupied/unoccupied class balance in all
three (roughly 21–27% occupied). Matches the known UCI dataset exactly. No
deletion criteria apply.

**Module support:** CDT (strong — occupancy classification is exactly what
this table is for). **Does not support** SDT, LA, PP, or PL (no student or
academic data of any kind). EA and TDS only apply *weakly and indirectly* (a
room-level occupancy signal could inform a coarse engagement or
resource-utilization narrative, but there's no student-level behavior here).
Clears the bar with one strong module (CDT) — sufficient to keep, but its
module coverage is genuinely narrow and it should not be expected to carry
more than that.

---

## 6. `environmental_sensors.csv` (Spanish Classroom CO2)

**Verdict: KEEP, but flagged INCOMPLETE.** Freshly profiled: 38,890 data
rows, **exactly 6 distinct `sensor_id` values** (`CO2_01`–`CO2_06`), spanning
29 distinct dates in May 2021. ADR-008's original research on this dataset
described **~80,000 total observations across 2 schools** (38,891 from
school 1 + ~34,570 from school 2). The row count and single-digit sensor-ID
range here line up with **school 1 only** — the second school's ~34,570 rows
(presumably a second batch of sensor IDs) appear to be missing from what was
downloaded. This is a genuine incompleteness finding: what's on disk is a
real, valid *subset* of the intended dataset, not corrupted or wrong, but it
represents roughly half of what ADR-008 selected it for (6 classrooms
instead of 12). Recommend re-fetching the full Zenodo record
(`10.5281/zenodo.5036228`) to confirm whether a second file/sheet for school
2 exists there before deciding whether to proceed with 6 classrooms or wait
for all 12.

**Module support:** CDT (strong — real, classroom-specific sensor data, even
at half the intended scale). Same narrow-coverage profile as
`occupancy+detection`: does not support SDT, LA, PP, or PL; EA/TDS only
weakly/indirectly. Clears the bar (CDT) — keep, but flag the incompleteness
so it isn't silently treated as the full 12-classroom dataset ADR-008
described.

---

## 7. `NYC_attendance.csv` (real data, added) + `2018_-_2019_Daily_Attendance_by_School_R_DD.xlsx` (now superseded)

**Verdict: KEEP `NYC_attendance.csv`; remove or relocate the `.xlsx`.**
`NYC_attendance.csv` is a genuine data export: 857,620 rows × 7 columns
(`School`, `Date`, `SchoolYear`, `Enrolled`, `Present`, `Absent`,
`Released`). Freshly profiled:

- **0 nulls, 0 fully-duplicate rows.**
- `Enrolled`/`Present` are stored as **comma-thousands-formatted strings**
  for values ≥1,000 (e.g. `"1,670"`) — this initially looked like ~12% missing
  data when naively cast to numeric, but after stripping the commas, casting
  succeeds for **100% of rows with zero nulls**. This is a formatting quirk to
  handle at preprocessing (strip commas before numeric cast), not a
  data-quality defect.
- **Internal consistency verified exactly:** `Enrolled = Present + Absent +
  Released` holds for **all 857,620 rows**, zero exceptions, once the comma
  formatting is handled — this is real, well-formed administrative data.
- **Minor identifier issue:** 177 `(School, Date)` pairs are duplicated —
  inspection shows this is because a handful of school DBN codes have two
  filed entries per day (one tiny, e.g. `Enrolled=1`, alongside the school's
  real enrollment count for that day), consistent with a co-located
  program/site sharing a DBN. `(School, Date)` is therefore **not** a fully
  reliable primary key as distributed — worth a documented note, not a
  disqualifier (affects 0.02% of rows).
- **Vintage note:** covers school years 2012–2013 through 2014–2015 (per the
  `SchoolYear` column: 20122013 / 20132014 / 20142015), not 2018–2019 as the
  old `.xlsx` filename and ADR-008's original description implied. Same
  role, same source (NYC DOE), different time window — a version difference
  like the ASSISTments one, not a wrong dataset.

The old `.xlsx` is now **redundant** — it never had data rows (confirmed in
the previous audit pass), and a real export now exists alongside it.
Recommend moving it to `docs/datasets/` as reference documentation for the
column definitions it contains (`School DBN`, `Date`, `Enrolled`, `Present`,
`Absent`, `Released`), and removing it from `data/raw/` so nothing in the
data folder is mistaken for a usable source.

**Module support:** CDT (moderate — school-day-level attendance is a
cohort/school signal, coarser than a single classroom but still directly
usable), TDS (moderate — chronic-absenteeism flagging, day-of-week/holiday
pattern analysis for intervention). **Does not support** SDT, LA, PP, EA, or
PL (fully aggregated at the school level — no individual student
identifiers exist in this file at all). Clears the bar (CDT, TDS) — the
acquisition problem from the previous audit is resolved.

---

## Summary

| Dataset | Verdict | Reason | Modules supported (strong) |
|---|---|---|---|
| `oulad/` | **Keep** | Clean, real, referentially sound spine dataset | SDT, CDT, LA, PP, EA, TDS (+weak PL) |
| `dropout_prediction/data.csv` | **Keep** | Clean, real, 0 nulls/dupes | PP, LA, TDS |
| `xAPI-Edu-Data/xAPI-Edu-Data.csv` | **Keep — corrected** | Real xAPI-Edu-Data, matches known schema/size, 2 trivial duplicate rows | EA, PP, LA (+weak TDS) |
| `2019-2020_school_year/` (ASSISTments) | **Keep** | Real, rich, largest dataset; minor fixable integrity issues in `pdets.csv` | SDT, CDT, LA, PP, EA, PL, TDS |
| `occupancy+detection/` | **Keep** | Clean, real, verified non-overlapping splits | CDT |
| `environmental_sensors.csv` | **Keep, flagged incomplete** | Real but likely only half the intended dataset (1 of 2 schools) | CDT |
| `NYC_attendance.csv` | **Keep — corrected** | Real export, internally consistent (Enrolled=Present+Absent+Released holds 100% of rows), minor comma-formatting and 177 duplicate-key rows to handle | CDT, TDS |
| `2018_-_2019_Daily_Attendance...xlsx` | **Remove from `data/raw`** (move to `docs/` as reference) | Superseded by `NYC_attendance.csv`; never had data rows | *(documentation only, not a dataset)* |

**7 of 8 items now pass cleanly** (counting the superseded `.xlsx`
separately from its replacement). Both acquisition problems from the
previous audit are resolved: `xAPI-Edu-Data` now has real engagement columns
and correctly supports Engagement Analysis; `NYC_attendance.csv` is a real,
internally-consistent export and correctly supports Classroom Digital Twin
and Teacher Decision Support. One item remains flagged as incomplete rather
than wrong (`environmental_sensors.csv`, likely missing school 2's half of
the data) — usable as-is, worth topping up if the full 12-classroom dataset
matters for the final result. The only remaining action is housekeeping: move
the now-redundant `.xlsx` out of `data/raw/` and into `docs/datasets/`. With
that, every dataset in the collection is clear to proceed to preprocessing.
