"""SQLAlchemy ORM models for the OULAD, xAPI, ASSISTments, and CO2 schemas.

Four independent dataset-scoped schemas in one file, none joined to
another (no shared identifier exists across any pair of them):

- OULAD (unprefixed table names) — see docs/datasets/oulad.md.
- xAPI (`xapi_` prefix) — see docs/datasets/xapi-preprocessing-plan.md.
- ASSISTments 2019-2020 (`assist_` prefix) — see
  docs/datasets/assist-preprocessing-plan.md.
- Spanish Classroom CO2 sensors (`co2_` prefix) — see
  docs/datasets/spanish-co2-preprocessing-plan.md. Not the UCI Occupancy
  Detection dataset.
- UCI Occupancy Detection (`occupancy_readings`) — see
  docs/datasets/occupancy-preprocessing-plan.md. Not the Spanish Classroom
  CO2 dataset; no shared identifier, never joined.
- NYC DOE Daily Attendance (`nyc_daily_attendance`) — standalone, no shared
  identifier with any schema above.
- UCI/Zenodo "Predict students' dropout and academic success"
  (`dropout_records`) — standalone, no shared identifier with any schema
  above.
- `student_knowledge_states` — the one exception to "raw source data only"
  above: a persisted *derived* Student Digital Twin state (current per-topic
  BKT mastery), keyed by the twin's own `student_id` (a UUID minted or
  deterministically derived per `domain/student.py::derive_student_id`),
  never a raw dataset's native id. See its own docstring below for why it's
  kept separate from every raw-observation table in this file.

These are persistence-only models; domain/ (pydantic) is a separate, later
concern per CLAUDE.md's module boundaries.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models in this project."""


class Course(Base):
    """One course presentation (a specific run of a module).

    Root reference table — every other table's foreign key chain
    terminates here via (code_module, code_presentation). Loaded first;
    nothing else can validate its foreign keys until this table exists.
    """

    __tablename__ = "courses"

    code_module: Mapped[str] = mapped_column(String(10), primary_key=True)
    code_presentation: Mapped[str] = mapped_column(String(10), primary_key=True)
    module_presentation_length: Mapped[int] = mapped_column(Integer, nullable=False)

    vle_sites: Mapped[list[VleSite]] = relationship(back_populates="course")
    assessments: Mapped[list[Assessment]] = relationship(back_populates="course")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="course")


class VleSite(Base):
    """One VLE resource/site offered in a course presentation.

    week_from/week_to from the source file are dropped upstream (82% null
    on both — see docs/datasets/oulad-preprocessing-plan.md Stage 2), so
    they have no columns here.
    """

    __tablename__ = "vle_sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["code_module", "code_presentation"],
            ["courses.code_module", "courses.code_presentation"],
        ),
    )

    id_site: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_module: Mapped[str] = mapped_column(String(10), nullable=False)
    code_presentation: Mapped[str] = mapped_column(String(10), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)

    course: Mapped[Course] = relationship(back_populates="vle_sites")
    interactions: Mapped[list[VleInteraction]] = relationship(back_populates="site")


class Assessment(Base):
    """One assessment definition (type, due date, weight) within a course presentation."""

    __tablename__ = "assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["code_module", "code_presentation"],
            ["courses.code_module", "courses.code_presentation"],
        ),
    )

    id_assessment: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_module: Mapped[str] = mapped_column(String(10), nullable=False)
    code_presentation: Mapped[str] = mapped_column(String(10), nullable=False)
    assessment_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Null for the 11 Exam rows where OULAD withholds/varies the final exam
    # date — documented dataset behavior, not missing data. Never impute.
    date: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)

    course: Mapped[Course] = relationship(back_populates="assessments")
    submissions: Mapped[list[AssessmentSubmission]] = relationship(back_populates="assessment")


class Enrollment(Base):
    """One student's presence in one course presentation: profile + timing + outcome.

    Merge of studentInfo.csv + studentRegistration.csv — the two source
    files share the exact same grain and key set (verified zero orphans
    either direction in oulad.md), so this is a lossless 1:1 merge, not a
    denormalization risk. This table is the hinge of the schema: every
    other student-scoped table reaches it through the full composite key,
    never id_student alone, because id_student is reused across a
    student's multiple enrollments (3,538 students in the source data).
    """

    __tablename__ = "enrollments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["code_module", "code_presentation"],
            ["courses.code_module", "courses.code_presentation"],
        ),
    )

    code_module: Mapped[str] = mapped_column(String(10), primary_key=True)
    code_presentation: Mapped[str] = mapped_column(String(10), primary_key=True)
    id_student: Mapped[int] = mapped_column(Integer, primary_key=True)

    gender: Mapped[str] = mapped_column(String(1), nullable=False)
    highest_education: Mapped[str] = mapped_column(String(50), nullable=False)
    # ~3.4% null — a socioeconomic proxy; left NULL rather than imputed so
    # no bias is encoded into a field that may correlate with the outcome.
    imd_band: Mapped[str | None] = mapped_column(String(10), nullable=True)
    age_band: Mapped[str] = mapped_column(String(10), nullable=False)
    num_of_prev_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    studied_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    disability: Mapped[str] = mapped_column(String(1), nullable=False)
    # Null for ~0.14% of rows — unknown registration date, not day zero.
    date_registration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL means "did not withdraw" (~69% of rows) — the single most
    # important null-handling rule in this schema. Never impute, never 0.
    date_unregistration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_result: Mapped[str] = mapped_column(String(20), nullable=False)

    course: Mapped[Course] = relationship(back_populates="enrollments")
    vle_interactions: Mapped[list[VleInteraction]] = relationship(back_populates="enrollment")

    # No `submissions` relationship here: AssessmentSubmission does not
    # store (code_module, code_presentation), so there is no physical FK
    # from this table to it — id_student alone would be an ambiguous join
    # key, since it is reused across a student's other enrollments. The
    # link is validated in software (two-hop, via assessments) at
    # preprocessing time; see AssessmentSubmission's docstring.


class AssessmentSubmission(Base):
    """One student's attempt at one assessment: score achieved and submission date.

    Deliberately does NOT store code_module/code_presentation — course
    context is reached via id_assessment -> assessments, not duplicated
    here (see docs/datasets/oulad.md's finalized schema). This also means
    there is no physical foreign key to `enrollments` on this table: the
    (code_module, code_presentation, id_student) -> enrollments check is a
    two-hop, software-level validation performed in
    data/preprocessing/preprocess_student_assessment.py, not a DB
    constraint (see docs/datasets/oulad-preprocessing-plan.md Stage 5).
    """

    __tablename__ = "assessment_submissions"

    id_assessment: Mapped[int] = mapped_column(
        ForeignKey("assessments.id_assessment"), primary_key=True
    )
    id_student: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_submitted: Mapped[int] = mapped_column(Integer, nullable=False)
    # ~0.1% null — genuinely ungraded/missing, not zero (zero would read as
    # "failed"). The submission's existence + date is still valid signal.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Persisted for provenance but deliberately excluded from the Student
    # Digital Twin's feature read path — a banked score reflects a
    # *previous* presentation's effort, not this one.
    is_banked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assessment: Mapped[Assessment] = relationship(back_populates="submissions")


class VleInteraction(Base):
    """One student's aggregated click count on one VLE site on one day.

    sum_click here is SUM-aggregated at preprocessing time, not the raw
    source value — the raw studentVle.csv is not pre-aggregated despite
    sum_click's name (20.6% of raw rows share this table's key with a
    differing sum_click; see
    data/preprocessing/preprocess_student_vle.py and
    docs/datasets/oulad-preprocessing-plan.md Stage 6).
    """

    __tablename__ = "vle_interactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["code_module", "code_presentation", "id_student"],
            [
                "enrollments.code_module",
                "enrollments.code_presentation",
                "enrollments.id_student",
            ],
        ),
    )

    code_module: Mapped[str] = mapped_column(String(10), primary_key=True)
    code_presentation: Mapped[str] = mapped_column(String(10), primary_key=True)
    id_student: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_site: Mapped[int] = mapped_column(ForeignKey("vle_sites.id_site"), primary_key=True)
    date: Mapped[int] = mapped_column(Integer, primary_key=True)
    sum_click: Mapped[int] = mapped_column(Integer, nullable=False)

    enrollment: Mapped[Enrollment] = relationship(back_populates="vle_interactions")
    site: Mapped[VleSite] = relationship(back_populates="interactions")


class XapiClassSection(Base):
    """One (stage, grade, section, topic, semester) class context from xAPI-Edu-Data.

    Independent of the OULAD schema above — no shared identifier, never
    joined to it. Root reference table for the xAPI dataset, same role
    `Course` plays for OULAD: every `XapiStudentRecord` FKs into this table.
    See docs/datasets/xapi-preprocessing-plan.md for the full rationale.
    """

    __tablename__ = "xapi_class_sections"

    stage_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    grade_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    section_id: Mapped[str] = mapped_column(String(5), primary_key=True)
    topic: Mapped[str] = mapped_column(String(30), primary_key=True)
    semester: Mapped[str] = mapped_column(String(1), primary_key=True)

    records: Mapped[list[XapiStudentRecord]] = relationship(back_populates="class_section")


class XapiStudentRecord(Base):
    """One student's single behavioral/demographic snapshot from xAPI-Edu-Data.

    No natural key exists for this grain — 4 source rows are fully
    duplicate across all 17 columns, proving no column subset can be
    unique. `record_id` is a DB-generated surrogate key, never derived from
    row content (a content hash would collide on those 4 rows and silently
    merge students the data gives no evidence to treat as the same). See
    "Primary key strategy" in docs/datasets/xapi-preprocessing-plan.md.
    """

    __tablename__ = "xapi_student_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["stage_id", "grade_id", "section_id", "topic", "semester"],
            [
                "xapi_class_sections.stage_id",
                "xapi_class_sections.grade_id",
                "xapi_class_sections.section_id",
                "xapi_class_sections.topic",
                "xapi_class_sections.semester",
            ],
        ),
    )

    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage_id: Mapped[str] = mapped_column(String(20), nullable=False)
    grade_id: Mapped[str] = mapped_column(String(10), nullable=False)
    section_id: Mapped[str] = mapped_column(String(5), nullable=False)
    topic: Mapped[str] = mapped_column(String(30), nullable=False)
    semester: Mapped[str] = mapped_column(String(1), nullable=False)

    gender: Mapped[str] = mapped_column(String(1), nullable=False)
    nationality: Mapped[str] = mapped_column(String(30), nullable=False)
    place_of_birth: Mapped[str] = mapped_column(String(30), nullable=False)
    relation: Mapped[str] = mapped_column(String(10), nullable=False)
    raised_hands: Mapped[int] = mapped_column(Integer, nullable=False)
    visited_resources: Mapped[int] = mapped_column(Integer, nullable=False)
    announcements_view: Mapped[int] = mapped_column(Integer, nullable=False)
    discussion: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_answering_survey: Mapped[str] = mapped_column(String(3), nullable=False)
    parent_school_satisfaction: Mapped[str] = mapped_column(String(4), nullable=False)
    student_absence_days: Mapped[str] = mapped_column(String(10), nullable=False)
    # "class" is Python-reserved-adjacent — never used as attribute/column name.
    class_label: Mapped[str] = mapped_column(String(1), nullable=False)

    class_section: Mapped[XapiClassSection] = relationship(back_populates="records")


class AssistDistrict(Base):
    """One school district row from ddets.csv (ASSISTments 2019-2020).

    Standalone — no other ASSISTments table carries a district_id or any
    other district-linking column in this release (verified, not assumed;
    see docs/datasets/assist-preprocessing-plan.md). Never referenced by,
    or referencing, any other table.
    """

    __tablename__ = "assist_districts"

    district_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location: Mapped[str] = mapped_column(String(50), nullable=False)
    opportunity_zone: Mapped[str] = mapped_column(String(15), nullable=False)
    # ~97.5% null — populated only for classified US districts (Census-style
    # rural/city/suburb/town bucket); informative when present, not sparse
    # noise, so kept rather than dropped.
    locale_description: Mapped[str | None] = mapped_column(String(20), nullable=True)


class AssistClass(Base):
    """One class row from cdets.csv. Root table for everything class-scoped."""

    __tablename__ = "assist_classes"

    class_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # No teacher table exists in this release — plain attribute, not an FK.
    teacher_id: Mapped[int] = mapped_column(Integer, nullable=False)
    class_creation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    student_count: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_sets_assigned: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_builders_assigned: Mapped[int] = mapped_column(Integer, nullable=False)

    student_classes: Mapped[list[AssistStudentClass]] = relationship(back_populates="class_")
    assignments: Mapped[list[AssistAssignment]] = relationship(back_populates="class_")


class AssistProblem(Base):
    """One problem row from pdets.csv.

    392 source rows with a null problem_id are dropped at preprocessing
    time — no identifier may be invented for them (see
    docs/datasets/assist-preprocessing-plan.md Stage 3).
    """

    __tablename__ = "assist_problems"

    problem_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Raw Python-list-repr strings, e.g. "['8.F.B.5']" — not parsed into a
    # skills table; encoding/decomposition is an analytics-layer concern.
    content_source: Mapped[str] = mapped_column(String(100), nullable=False)
    skills: Mapped[str | None] = mapped_column(String(150), nullable=True)
    problem_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tutoring_types: Mapped[str | None] = mapped_column(String(100), nullable=True)
    student_answer_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_correct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_time_on_task: Mapped[float | None] = mapped_column(Float, nullable=True)


class AssistStudentClass(Base):
    """One student's activity summary within one class, from sdets.csv.

    student_id alone is not unique — 8,560 students appear under more than
    one class_id (verified) — so the composite (student_id, class_id) is
    this table's real identity, the same reuse pattern OULAD's id_student
    has across enrollments.
    """

    __tablename__ = "assist_student_classes"

    student_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("assist_classes.class_id"), primary_key=True)
    account_creation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_problem_sets_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_problem_sets_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_skill_builders_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mastered_skill_builders_count: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_problems_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_problem_correctness: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_problem_time_on_task: Mapped[float | None] = mapped_column(Float, nullable=True)

    class_: Mapped[AssistClass] = relationship(back_populates="student_classes")


class AssistAssignment(Base):
    """One assignment row from adets.csv."""

    __tablename__ = "assist_assignments"

    assignment_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("assist_classes.class_id"), nullable=False)
    release_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assignment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    started_student_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_or_mastered_student_count: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_correct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_time_on_task: Mapped[float | None] = mapped_column(Float, nullable=True)

    class_: Mapped[AssistClass] = relationship(back_populates="assignments")
    logs: Mapped[list[AssistAssignmentLog]] = relationship(back_populates="assignment")


class AssistAssignmentLog(Base):
    """One assignment-attempt session row from alogs.csv.

    `student_id` is deliberately a plain column, not a SQLAlchemy
    ForeignKey: assist_student_classes' primary key is the composite
    (student_id, class_id), and student_id alone is not unique there, so
    Postgres cannot express a single-column FK to it (no matching unique
    constraint to reference) — the same situation AssessmentSubmission's
    id_student is in for OULAD. Validated in software at preprocessing
    time (assert_foreign_key against assist_student_classes' distinct
    student_id values), not as a database constraint.
    """

    __tablename__ = "assist_assignment_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assist_assignments.assignment_id"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mean_correct: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_on_task: Mapped[float | None] = mapped_column(Float, nullable=True)
    assignment_completed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    assignment: Mapped[AssistAssignment] = relationship(back_populates="logs")
    problem_logs: Mapped[list[AssistProblemLog]] = relationship(back_populates="assignment_log")


class AssistProblemLog(Base):
    """One problem-attempt row from plogs.csv.

    No natural key exists at this grain: log_id alone repeats by design
    (one session, many problems attempted), and (log_id, problem_id) is
    proven non-unique by 508 genuine same-problem-retry rows. `id` is a
    DB-generated surrogate, never derived from row content, for the same
    reason as XapiStudentRecord.record_id.

    `student_id`/`assignment_id` from the source are dropped — verified to
    always match the parent assist_assignment_logs row (0 mismatches on
    all 20,752,836 rows), reachable via log_id, the same normalization
    OULAD applies to AssessmentSubmission dropping code_module/
    code_presentation.

    `problem_id` is deliberately a plain column, not a ForeignKey: 392
    distinct problem_ids referenced here (172,865 rows) have no matching
    row in assist_problems, because those problems' pdets row itself had
    no problem_id and was dropped (see AssistProblem). A hard FK would
    reject real, verified attempt events over a metadata gap in a
    different table. Validated with a warning (warn_foreign_key), not an
    assertion — see docs/datasets/assist-preprocessing-plan.md Stage 7.
    """

    __tablename__ = "assist_problem_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[int] = mapped_column(ForeignKey("assist_assignment_logs.log_id"), nullable=False)
    problem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_on_task: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_before_tutoring: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fraction_of_hints_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_given: Mapped[bool] = mapped_column(Boolean, nullable=False)
    problem_completed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    assignment_log: Mapped[AssistAssignmentLog] = relationship(back_populates="problem_logs")


class Co2SensorReading(Base):
    """One CO2/temperature/humidity/battery reading from one classroom sensor.

    Standalone table, no relationship to any other schema in this file and
    no relationship to the (separately sourced, not yet modeled) UCI
    Occupancy Detection dataset — see docs/datasets/spanish-co2-preprocessing-plan.md.

    (sensor_id, recorded_at) is a natural composite key, not a surrogate:
    413 fully-duplicate source rows (sensor retransmissions) are dropped at
    preprocessing time, after which this pair is unique with zero
    collisions — verified, not assumed.
    """

    __tablename__ = "co2_sensor_readings"

    sensor_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False)
    co2_ppm: Mapped[int] = mapped_column(Integer, nullable=False)
    # 0 observed for 40 source rows — a dead/dying battery, real sensor-health
    # signal, not an invalid reading. Never filtered out.
    battery_pct: Mapped[float] = mapped_column(Float, nullable=False)


class OccupancyReading(Base):
    """One timestamped room reading from the UCI Occupancy Detection dataset.

    Standalone table, no relationship to any other schema in this file and
    no relationship to co2_sensor_readings — see
    docs/datasets/occupancy-preprocessing-plan.md.

    (source_file, recorded_at) is a natural composite key: the three source
    files (training/test/test2) are verified time-disjoint segments of one
    sensor deployment, so recorded_at is collision-free within and across
    files. source_row_id is the original per-file row id, kept for
    traceability only — it is not globally unique (each file restarts its
    own numbering) so it is not part of the key.
    """

    __tablename__ = "occupancy_readings"

    source_file: Mapped[str] = mapped_column(String(8), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    source_row_id: Mapped[int] = mapped_column(Integer, nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False)
    # 0 observed for a large share of rows — lights off / room dark, expected
    # to correlate with occupancy == 0, not a sensor fault.
    light_lux: Mapped[float] = mapped_column(Float, nullable=False)
    co2_ppm: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    # Target variable, restricted to {0, 1} — enforced at preprocessing time.
    occupancy: Mapped[int] = mapped_column(Integer, nullable=False)


class NycDailyAttendance(Base):
    """One school's daily enrollment/attendance count from NYC DOE data.

    Standalone table, no relationship to any other schema in this file.

    Surrogate integer PK, not a natural `(school_id, attendance_date)` key:
    that pair is unique for 1,680 of 1,681 schools, but school "15K592" has
    177 dates with two genuinely different rows each (354 rows total, not
    duplicate transmissions — distinct enrolled/present/absent/released
    values, consistent with two co-located programs sharing one school
    code). A surrogate key avoids rejecting real source data over that.
    """

    __tablename__ = "nyc_daily_attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[str] = mapped_column(String(6), nullable=False)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Source encoding of the school-year span, e.g. "20122013" for 2012-2013.
    school_year: Mapped[str] = mapped_column(String(8), nullable=False)
    enrolled: Mapped[int] = mapped_column(Integer, nullable=False)
    present: Mapped[int] = mapped_column(Integer, nullable=False)
    absent: Mapped[int] = mapped_column(Integer, nullable=False)
    released: Mapped[int] = mapped_column(Integer, nullable=False)


class DropoutRecord(Base):
    """One student's enrollment profile + semester outcomes + final status.

    Standalone table, no relationship to any other schema in this file. The
    source has no student identifier at all, so a surrogate integer PK is
    the only option (unlike nyc_daily_attendance, there isn't even a
    partially-working natural key to fall back to).

    All int-typed columns below are source-coded categoricals (e.g.
    `marital_status` 1-6, `course` a numeric course code, occupation/
    qualification codes), not free-form counts — stored as given, no
    lookup/decoding table added since the source provides no code->label
    mapping to populate one from.
    """

    __tablename__ = "dropout_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    marital_status: Mapped[int] = mapped_column(Integer, nullable=False)
    application_mode: Mapped[int] = mapped_column(Integer, nullable=False)
    application_order: Mapped[int] = mapped_column(Integer, nullable=False)
    course: Mapped[int] = mapped_column(Integer, nullable=False)
    daytime_evening_attendance: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_qualification: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_qualification_grade: Mapped[float] = mapped_column(Float, nullable=False)
    nationality: Mapped[int] = mapped_column(Integer, nullable=False)
    mothers_qualification: Mapped[int] = mapped_column(Integer, nullable=False)
    fathers_qualification: Mapped[int] = mapped_column(Integer, nullable=False)
    mothers_occupation: Mapped[int] = mapped_column(Integer, nullable=False)
    fathers_occupation: Mapped[int] = mapped_column(Integer, nullable=False)
    admission_grade: Mapped[float] = mapped_column(Float, nullable=False)
    displaced: Mapped[int] = mapped_column(Integer, nullable=False)
    educational_special_needs: Mapped[int] = mapped_column(Integer, nullable=False)
    debtor: Mapped[int] = mapped_column(Integer, nullable=False)
    tuition_fees_up_to_date: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[int] = mapped_column(Integer, nullable=False)
    scholarship_holder: Mapped[int] = mapped_column(Integer, nullable=False)
    age_at_enrollment: Mapped[int] = mapped_column(Integer, nullable=False)
    international: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_1st_sem_credited: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_1st_sem_enrolled: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_1st_sem_evaluations: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_1st_sem_approved: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_1st_sem_grade: Mapped[float] = mapped_column(Float, nullable=False)
    curricular_units_1st_sem_without_evaluations: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    curricular_units_2nd_sem_credited: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_2nd_sem_enrolled: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_2nd_sem_evaluations: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_2nd_sem_approved: Mapped[int] = mapped_column(Integer, nullable=False)
    curricular_units_2nd_sem_grade: Mapped[float] = mapped_column(Float, nullable=False)
    curricular_units_2nd_sem_without_evaluations: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    unemployment_rate: Mapped[float] = mapped_column(Float, nullable=False)
    inflation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    gdp: Mapped[float] = mapped_column(Float, nullable=False)
    # Final status, restricted to {"Graduate", "Dropout", "Enrolled"} —
    # enforced at preprocessing time.
    target: Mapped[str] = mapped_column(String(10), nullable=False)


class StudentKnowledgeState(Base):
    """One StudentTwin's current per-topic mastery estimate — derived state, not an observation.

    Deliberately separate from every raw-observation table above: the raw
    ASSISTments attempts that produced this mastery estimate already live,
    unmodified, in `assist_problem_logs`/`assist_assignment_logs`/
    `assist_problems`. This table stores only the *output* of replaying
    those observations through `twin_engine.update_strategies`'s BKT (or
    another `UpdateStrategy`) — one row per `(student_id, topic_id)`,
    upserted to the latest value, never a history of every past value. It
    is written and read exclusively by
    `data/repositories/student_twin_repository.py::PostgresStudentTwinRepository`;
    no update-strategy math is duplicated here.

    `student_id` is a twin identity (UUID), never an ASSISTments/OULAD
    native id — this table has no foreign key to, and no column from, any
    raw-observation table above. A caller that wants this row findable
    again in a later process must have derived `student_id` reproducibly
    (see `domain/student.py::derive_student_id`); this table does not
    itself record which real `(source_dataset, source_id)` produced it —
    that provenance already lives at the raw-observation layer, and
    duplicating it here would risk drifting out of sync with it.

    `topic_id` reuses ASSISTments' own skill identifiers, the same
    convention `domain/knowledge_state.py::KnowledgeState.topic_id`
    documents — BKT only ever updates from ASSISTments-shaped
    PROBLEM_ATTEMPT interactions (OULAD's RESOURCE_VIEW interactions carry
    no topic_id/outcome), so every row here is, in practice, ASSISTments-
    derived, exactly as the raw data it was computed from already implies.
    """

    __tablename__ = "student_knowledge_states"

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    topic_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    mastery_probability: Mapped[float] = mapped_column(Float, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClassroomContextMapping(Base):
    """An explicit, human-authorized link from one real classroom to a contextual data source.

    This is the ONLY place in the schema where a classroom is ever
    associated with a CO2 sensor or an xAPI-Edu-Data record. No loader or
    analytics module writes a row here — every row is created by an
    explicit, caller-driven call to
    `data/repositories/classroom_context_mapping.py::upsert_classroom_context_mapping`,
    asserting a real-world fact ("this sensor is physically installed in
    this classroom's room", "this xAPI record belongs to a student in this
    classroom") that none of this project's source datasets encode — see
    `domain/classroom.py`'s module docstring: no dataset links a CO2 sensor
    or an xAPI-Edu-Data record to any ASSISTments `class_id`. In the
    absence of such an explicit assertion, no row exists for a class_id and
    every contextual signal for it stays unavailable — never inferred.
    `sensor_id`/`xapi_record_id` are independently optional: a classroom
    may have neither, either, or both configured.

    `sensor_id` is a plain column, not a ForeignKey: `co2_sensor_readings`'
    primary key is the composite `(sensor_id, recorded_at)`, so there is no
    unique constraint on `sensor_id` alone to reference — the same
    situation `AssistProblemLog.problem_id` is in (see its own docstring).
    `xapi_record_id` IS a real ForeignKey to `xapi_student_records.record_id`,
    a genuine single-column primary key, so referential integrity is
    enforced by the database for that half of the mapping.
    """

    __tablename__ = "classroom_context_mappings"

    source_dataset: Mapped[str] = mapped_column(String(30), primary_key=True)
    class_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
    xapi_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("xapi_student_records.record_id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
