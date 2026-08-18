# Schema Validation: can the OULAD schema support the rest of the project's datasets?

Validates the [OULAD relational schema](oulad.md#proposed-final-relational-schema)
(`courses`, `enrollments`, `assessments`, `assessment_submissions`, `vle_sites`,
`vle_interactions`) against the five remaining datasets in `data/raw/`. No
preprocessing performed — this is a design-time check, verified by inspecting
real file headers/rows/sheets, not by assuming ADR-008's original descriptions
still match what's actually on disk.

## Three findings from the original pass — status update

**1. RESOLVED. `data/raw/engagement_analysis/DATA (1).csv` has been replaced
with `data/raw/xAPI-Edu-Data/xAPI-Edu-Data.csv`.** The real xAPI-Edu-Data
(Kalboard 360) file is now in place — verified 480 rows, header matches the
known schema exactly (`raisedhands`, `VisITedResources`, `AnnouncementsView`,
`Discussion`, `StudentAbsenceDays`, `Class`, etc.), 0 nulls, 2 trivial
duplicate rows. Section A below has been rewritten against this file; it now
correctly supports the Engagement Detection role ADR-008 selected it for.
See [data-quality-audit.md](data-quality-audit.md) for the full profiling.

**2. `data/raw/2019-2020_school_year/` is ASSISTments, but not the release ADR-008 named.**
ADR-008 specified the small, flat "2009–2010 Skill-Builder" file. What's on
disk is a much larger, fully relational 2019–2020 school-year release (7
files, one down to district level, ~2GB total, 20.7M problem-level log rows).
Same platform, same role, better data — this is a version upgrade, not a
wrong dataset. Worth a note back in ADR-008/DATASETS.md, but not a blocker.
(Unchanged from the original pass.)

**3. RESOLVED. A real NYC attendance export (`data/raw/NYC_attendance.csv`)
has been added.** 857,620 rows, verified internally consistent
(`Enrolled = Present + Absent + Released` holds exactly for all rows once a
comma-formatting quirk is handled), covering school years 2012–2015 rather
than 2018–2019 as originally named — a vintage difference, not a wrong
dataset, similar to finding 2. The old `2018_-_2019_Daily_Attendance_by_School_R_DD.xlsx`
is now redundant (it never had data rows — confirmed in
data-quality-audit.md) and should be moved to `docs/` as reference
documentation rather than kept in `data/raw/`. Section E below has been
rewritten against the real export.

---

## A. xAPI-Edu-Data (verified — real file now in place)

- **Role in the project:** the real xAPI-Edu-Data (Kalboard 360) dataset — 480 rows, one row per student per course topic, with explicit LMS behavioral engagement counters (`raisedhands`, `VisITedResources`, `AnnouncementsView`, `Discussion`) alongside demographics and a `StudentAbsenceDays` flag and final `Class` outcome (Low/Middle/High). This is exactly the Engagement Detection dataset ADR-008 intended, now correctly in place.
- **Maps to existing tables:** conceptually closest to `enrollments` (one row = one student's standing in one course/topic, with an outcome), but **does not physically map** for the same structural reasons as before: no shared key space with OULAD's `id_student`/`code_module` (this is a different institution's students entirely), and the column sets don't align (`raisedhands`/`VisITedResources`/etc. have no OULAD counterpart at this granularity — OULAD's closest analog, `studentVle.sum_click`, is a raw click count with no behavior-type breakdown). Nothing in `assessments`/`assessment_submissions`/`vle_sites`/`vle_interactions` applies — there's no per-assessment or per-timestamped-interaction data here, only per-student aggregate counts.
- **New tables required:** **Yes.** A new independent table (e.g. `xapi_student_records`) — one row per student record, holding demographics (`gender`, `nationality`, `place_of_birth`, `stage_id`, `grade_id`, `section_id`, `topic`, `semester`, `relation`), the four behavioral counters, `student_absence_days`, and the `class` target.
- **Schema modifications needed:** none to the existing OULAD tables — purely additive.
- **New finding (identifier gap):** unlike every other dataset reviewed so far, **this file has no student ID column at all** — no `STUDENT ID`, no row identifier of any kind. A surrogate/synthetic primary key (e.g. an auto-incrementing row number) will need to be generated when this table is built; there is no natural key to preserve from the source.

---

## B. ASSISTments (2019–2020 school year release)

- **Role in the project:** the richest interaction/knowledge-tracing dataset in the collection — district → class → student → assignment → assignment-attempt → problem-attempt, down to per-problem correctness, hint usage, and time-on-task. Strongest fit for Personalized Learning / Recommendation System (mastery tracking) and a strong secondary fit for Engagement Analysis and Performance Prediction, as ADR-008 anticipated — this release just supports it with far more depth than the originally-named file.
- **Maps to existing tables:** conceptually, each ASSISTments file parallels an OULAD table at a similar *grain*, but none share a physical key space with it:

  | ASSISTments file | Grain | Conceptually parallels |
  |---|---|---|
  | `ddets.csv` (district) | 1 row/district | *(no OULAD equivalent — OULAD has no institutional hierarchy above course)* |
  | `cdets.csv` (class) | 1 row/class | `courses` (a cohort container) — but grain differs: OULAD's `courses` = one module presentation; ASSISTments' `cdets` = one teacher's actual class roster, which is arguably a *better* literal match for "Classroom" than OULAD ever had |
  | `sdets.csv` (student×class) | 1 row/(student, class) — confirmed 0 duplicate keys | `enrollments` (one student's presence in one cohort) |
  | `adets.csv` (assignment) | 1 row/assignment | `assessments` (a task definition tied to a class, with a due date) |
  | `alogs.csv` (assignment attempt) | 1 row/(student, assignment) | `assessment_submissions` (one student's attempt at one task) |
  | `pdets.csv` (problem) | 1 row/problem | `vle_sites` (a content-item dimension) |
  | `plogs.csv` (problem attempt) | 1 row/(student, assignment, problem); confirmed `plogs.log_id` is a foreign key back to `alogs.log_id`, not its own ID space | `vle_interactions` (the fine-grained event table — and at 20.7M rows, even larger than OULAD's) |

  Despite the conceptual parallels, **no physical merge is possible or advisable**: `student_id`/`class_id`/`assignment_id`/`problem_id` come from an entirely different real-world population than OULAD's `id_student`/`code_module`, and the column sets barely overlap even where the grain matches (e.g. `adets` has `release_date`/`assignment_type`/`problem_count`; OULAD's `assessments` has `assessment_type`/`weight` — related concept, different fields).
- **New tables required:** **Yes — a full parallel schema of 7 new tables**, mirroring the structure above (`assistments_districts`, `assistments_classes`, `assistments_class_enrollments`, `assistments_assignments`, `assistments_assignment_logs`, `assistments_problems`, `assistments_problem_logs`).
- **Schema modifications needed:** none to OULAD's tables. **One gap to flag:** `cdets.csv` has no `district_id` column — confirmed by inspecting its actual header (`class_id, teacher_id, class_creation_date, student_count, problem_sets_assigned, skill_builders_assigned`). As distributed, **there is no visible join path from class to district**; if district-level context (e.g. `opportunity_zone`, `locale_description`) is wanted for the Classroom Digital Twin, this needs to be resolved (possibly via `teacher_id`, if a teacher-to-district mapping exists elsewhere, or this file's `ddets.csv` may simply be unusable without an undocumented key).

---

## C. UCI Occupancy Detection Dataset

- **Role in the project:** the clean, labeled benchmark for building the occupancy-classification *methodology* (per ADR-008) before applying it to the real classroom CO2 data. Feeds the Classroom Digital Twin's environmental layer and Anomaly Detection.
- **Maps to existing tables:** **none.** OULAD has no environmental/sensor concept whatsoever — this is a structurally orthogonal domain (physical room conditions vs. LMS records). There's also no student, course, or assessment identifier in this dataset at all — it's a single implicit room with no linkage to any of OULAD's entities.
- **New tables required:** **Yes** — a new table, e.g. `environmental_readings`, with columns approximating `(source_dataset, room_id, timestamp, temperature, humidity, light, co2, humidity_ratio, occupancy_label)`. Since this dataset has no room identifier at all (single implicit room across all rows), a constant/placeholder `room_id` would need to be assigned if unioned with a multi-room source (see D below).
- **Schema modifications needed:** none to OULAD's tables — this dataset is entirely additive and unrelated to the OULAD schema; it attaches to the Classroom Digital Twin only, never to the Student Digital Twin (no per-student signal exists here).

---

## D. Spanish Classroom CO2 Dataset (`environmental_sensors.csv`)

- **Role in the project:** real classroom-sourced environmental data (12 classrooms across 2 schools per ADR-008) — confirmed via the file's own `sensor_id` column, which has **at least 6 distinct values** (`CO2_01` through `CO2_06`, sampled from the first 2,000 rows) — so unlike the UCI Occupancy dataset, this one genuinely represents *multiple* rooms. Used to validate the occupancy/environmental methodology against authentic classroom conditions, and for Anomaly Detection.
- **Maps to existing tables:** **none**, same reasoning as C — no student/course/assessment concept present.
- **New tables required:** **Yes** — and it should be the **same** `environmental_readings` table proposed in C, not a second bespoke table, since both datasets are conceptually the same kind of record (timestamped room sensor reading) at a compatible grain. A shared table needs to tolerate the two sources' non-overlapping columns: `occupancy_label` is only ever populated from the UCI dataset (this dataset has no ground-truth occupancy, only CO2 as a proxy), while `sensor_id`/room granularity and `battery_level` are only meaningfully populated from this dataset. A `source_dataset` column distinguishes provenance.
- **Schema modifications needed:** none to OULAD's tables; same additive relationship to the Classroom Digital Twin as C. **One real limitation to document, not solve now:** neither this dataset nor UCI Occupancy Detection has any identifier that links back to OULAD's `code_module`/`code_presentation` — they're from unrelated institutions. There is currently no way to say "this sensor reading belongs to *this* OULAD course presentation's classroom." This mirrors the tradeoff already accepted in ADR-008 (real-but-imperfect classroom proxies); it means the Classroom Digital Twin will, for now, treat academic-performance data (OULAD/ASSISTments) and environmental data (Occupancy/Spanish CO2) as two parallel, not-yet-joinable views of "a classroom," rather than one fully unified record per physical room.
- **Formatting note (not a schema issue, but worth flagging for whoever preprocesses this later):** the file as downloaded has every row wrapped in an extra layer of quoting (the entire line is quoted as if it were a single CSV field containing an inner CSV) — a parsing quirk to handle at ingestion, unrelated to the schema design itself.

---

## E. NYC Daily Attendance (verified — real export now in place)

- **Role in the project:** the real, government-sourced Attendance Prediction signal (school-day-level, not individual-student), now confirmed as genuine data: 857,620 rows covering school years 2012–2015, internally consistent (`Enrolled = Present + Absent + Released` holds for every row).
- **Maps to existing tables:** **no overlap** with the OULAD schema, as anticipated — `NYC_attendance.csv` (`School`, `Date`, `SchoolYear`, `Enrolled`, `Present`, `Absent`, `Released`) is aggregated at the school-day level, with no student, course, or assessment identifier, so it cannot join to `enrollments` or anything else in the OULAD schema.
- **New tables required:** **Yes** — a new `school_daily_attendance` table (`school, date, school_year, enrolled, present, absent, released`).
- **Schema modifications needed:** none to OULAD's tables — additive, attaches to the Classroom Digital Twin (as a school/cohort-level signal) rather than the Student Digital Twin, given its aggregated grain.
- **New finding (identifier gap):** `(School, Date)` looks like the natural composite primary key, but **177 pairs are duplicated** — a handful of school DBN codes have two rows filed for the same day (a small `Enrolled=1` entry alongside the school's real count, consistent with a co-located program sharing a DBN). `(School, Date)` is therefore not a fully reliable key as distributed; either a surrogate key is needed or the duplicate rows need a documented resolution rule (e.g. sum them, or keep only the larger-`Enrolled` row) before this table is built.
- **Formatting note:** `Enrolled`/`Present` use comma thousands-separators in the source (`"1,670"`) — trivial to strip at ingestion, not a schema concern.
- **Housekeeping:** the old `2018_-_2019_Daily_Attendance_by_School_R_DD.xlsx` (documentation-only, no data rows) should be moved to `docs/datasets/` and removed from `data/raw/` now that this real export supersedes it.

---

## Summary

| Dataset | New tables needed? | Modifies OULAD tables? | Attaches to |
|---|---|---|---|
| A. xAPI-Edu-Data (verified) | Yes — 1 new table (`xapi_student_records`) | No — OULAD schema is sufficient/unmodified | Student-level (weak; static snapshot, no student ID in source) |
| B. ASSISTments (2019–2020) | Yes — 7 new tables (parallel schema) | No — OULAD schema is sufficient/unmodified | Both Student and Classroom Digital Twin |
| C. UCI Occupancy Detection | Yes — 1 new table (`environmental_readings`) | No — OULAD schema is sufficient/unmodified | Classroom Digital Twin only |
| D. Spanish Classroom CO2 | Shares C's new table | No — OULAD schema is sufficient/unmodified | Classroom Digital Twin only |
| E. NYC Attendance (verified) | Yes — 1 new table (`school_daily_attendance`) | No — OULAD schema is sufficient/unmodified | Classroom Digital Twin only |

**For every one of the five datasets, the OULAD schema itself needs zero
modification** — it stays exactly as finalized in `oulad.md`. What each
dataset needs instead is its **own** new, independent table(s); none of them
share a physical key space or column set with OULAD's tables, even where the
grain is conceptually similar (B is the clearest example of this: real
one-to-one grain parallels with OULAD, but a fully disjoint identifier space).

**This is the expected outcome, not a design gap.** It matches what
[DECISIONS.md ADR-002](../../DECISIONS.md) already committed to: the
unification point for a multi-source Digital Twin is the **domain layer**
(`domain/student.py`, `domain/classroom.py`, `domain/interaction.py`,
`domain/assessment.py`, `domain/knowledge_state.py`) and the adapter pattern
(`data/adapters/`), not a single shared physical schema. Each dataset gets its
own normalized source tables (OULAD's 6, ASSISTments' 7, one shared
`environmental_readings`, one `school_daily_attendance`, one small
`xapi_student_records`); an adapter per source maps its rows into the common
domain types; `twin_engine/` only ever reads the domain layer, never a
source-specific table directly. The Student Digital Twin is fed by OULAD and
ASSISTments (both have genuine per-student signal); the Classroom Digital
Twin is fed by all five, since even the student-level sources aggregate up to
a cohort view.

### Remaining items before preprocessing

1. **ASSISTments version:** update ADR-008/DATASETS.md to reflect that the
   2019–2020 relational release is what's actually being used, and note the
   unresolved `cdets` → `ddets` join gap.
2. **NYC Attendance / xAPI:** both resolved — real data verified in place for
   both (see data-quality-audit.md). Remaining housekeeping only: move the
   now-redundant `2018_-_2019_Daily_Attendance_by_School_R_DD.xlsx` out of
   `data/raw/` into `docs/datasets/`.
3. **Two new identifier gaps found during this verification pass** (not
   present in the original schema-validation): `xapi_student_records` has no
   natural primary key in the source (needs a surrogate key), and
   `school_daily_attendance`'s natural key `(School, Date)` has 177 duplicate
   pairs (needs a documented resolution rule before the table is built).
4. **`environmental_sensors.csv`** is still confirmed to hold only ~half of
   the intended Spanish classroom CO2 dataset (school 1 only) — unchanged
   from the previous audit, not addressed in this pass.
