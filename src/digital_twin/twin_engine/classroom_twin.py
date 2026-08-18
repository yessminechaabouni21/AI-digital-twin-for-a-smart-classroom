"""Classroom-level twin: aggregates classroom-scoped state and student twins.

Two independent kinds of input, kept separate throughout (see
domain/classroom.py's module docstring for why the underlying datasets are
never joined):

- classroom-level input: `Classroom` (ASSISTments `assist_classes`) and
  `ClassroomEnvironmentReading` (Spanish CO2 sensor feed) — recorded here
  directly, not derived from any student.
- student-level input: already-computed `StudentTwinState` snapshots,
  produced elsewhere by `StudentTwin.current_state()` — this module never
  touches a raw Interaction/AssessmentResult or recomputes mastery, per
  CLAUDE.md's rule that twin *update* logic lives only in student_twin.py/
  update_strategies.py. `ClassroomTwin` only aggregates already-derived
  snapshots (means/sums), the same "attach, don't compute" posture
  `StudentTwin.attach_dropout_risk` etc. take for externally-computed
  predictions.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from digital_twin.domain.classroom import Classroom, ClassroomEnvironmentReading
from digital_twin.twin_engine.student_twin import StudentTwinState


class ClassroomEngagementSummary(BaseModel):
    """Roster-wide totals/averages over attached students' EngagementSummary.

    Every field is a plain sum or mean of the corresponding
    `EngagementSummary` field across attached students who have at least one
    recorded interaction — no trend/window logic is re-derived here (that
    already happened once, per student, in `StudentTwin`).
    """

    students_with_interactions: int = 0
    total_interactions: int = 0
    total_correct_attempts: int = 0
    total_incorrect_attempts: int = 0
    average_active_days: float | None = None


class ClassroomAssessmentSummary(BaseModel):
    """Roster-wide average over attached students' AssessmentPerformanceSummary.

    `average_score` is the mean of each attached student's own
    `average_score`, i.e. a mean of means (one vote per student, not one vote
    per assessment result) — deliberate, so a single highly-active student's
    result count can't dominate the classroom figure.
    """

    students_with_results: int = 0
    average_score: float | None = None


class ClassroomEnvironmentSummary(BaseModel):
    """Summary over this classroom's attached ClassroomEnvironmentReading history."""

    reading_count: int = 0
    average_temperature_c: float | None = None
    average_humidity_pct: float | None = None
    average_co2_ppm: float | None = None
    latest_battery_pct: float | None = None
    last_recorded_at: datetime | None = None


class ClassroomTwinState(BaseModel):
    """A read-only snapshot of a ClassroomTwin's current derived state.

    `topic_observation_counts` is the sum of each attached student's
    `KnowledgeState.observation_count` for that topic — a reliability check
    alongside `average_mastery_by_topic`, so a caller can tell a topic with
    one thin observation apart from one with many (see
    `analytics/skill_priority.py`, which reads both together rather than
    ranking on `average_mastery_by_topic` alone).
    """

    classroom_id: UUID
    source_student_count: int | None
    roster_size: int
    average_mastery_by_topic: dict[str, float]
    topic_observation_counts: dict[str, int]
    engagement: ClassroomEngagementSummary
    assessment_performance: ClassroomAssessmentSummary
    environment: ClassroomEnvironmentSummary
    as_of: datetime | None


class ClassroomTwin:
    """Current aggregated state for one classroom: roster + environment.

    Pure in-memory aggregation over already-computed `StudentTwinState`
    snapshots and directly-recorded `ClassroomEnvironmentReading` events — no
    PostgreSQL/SQLAlchemy dependency and no student-level update logic, per
    CLAUDE.md's module boundaries.
    """

    def __init__(self, classroom: Classroom) -> None:
        self.classroom = classroom
        self.student_states: dict[UUID, StudentTwinState] = {}
        self.environment_readings: list[ClassroomEnvironmentReading] = []

    def attach_student_state(self, state: StudentTwinState) -> None:
        """Attach or replace one student's current StudentTwinState snapshot.

        Keyed by `state.student_id`, so re-attaching a student's updated
        snapshot (after their own twin processes more events) replaces the
        stale one rather than accumulating a history — this class holds
        current roster state, not a log of past snapshots.
        """
        self.student_states[state.student_id] = state

    def attach_student_states(self, states: Iterable[StudentTwinState]) -> None:
        """Attach multiple StudentTwinState snapshots at once."""
        for state in states:
            self.attach_student_state(state)

    def apply_environment_reading(self, reading: ClassroomEnvironmentReading) -> None:
        """Record one classroom environmental sensor reading."""
        self.environment_readings.append(reading)

    def current_state(self) -> ClassroomTwinState:
        """A read-only snapshot of this classroom's current aggregated state."""
        scores_by_topic, counts_by_topic = self._knowledge_state_by_topic()
        return ClassroomTwinState(
            classroom_id=self.classroom.classroom_id,
            source_student_count=self.classroom.student_count,
            roster_size=len(self.student_states),
            average_mastery_by_topic=self._average_mastery_by_topic(scores_by_topic),
            topic_observation_counts=counts_by_topic,
            engagement=self._engagement_summary(),
            assessment_performance=self._assessment_summary(),
            environment=self._environment_summary(),
            as_of=self._as_of(),
        )

    def _knowledge_state_by_topic(self) -> tuple[dict[str, list[float]], dict[str, int]]:
        scores_by_topic: dict[str, list[float]] = {}
        counts_by_topic: dict[str, int] = {}
        for state in self.student_states.values():
            for topic_id, knowledge_state in state.knowledge_states.items():
                scores_by_topic.setdefault(topic_id, []).append(knowledge_state.mastery_probability)
                counts_by_topic[topic_id] = (
                    counts_by_topic.get(topic_id, 0) + knowledge_state.observation_count
                )
        return scores_by_topic, counts_by_topic

    def _average_mastery_by_topic(
        self, scores_by_topic: dict[str, list[float]]
    ) -> dict[str, float]:
        return {topic_id: sum(scores) / len(scores) for topic_id, scores in scores_by_topic.items()}

    def _engagement_summary(self) -> ClassroomEngagementSummary:
        engaged = [
            state.engagement
            for state in self.student_states.values()
            if state.engagement.total_interactions > 0
        ]
        if not engaged:
            return ClassroomEngagementSummary()

        return ClassroomEngagementSummary(
            students_with_interactions=len(engaged),
            total_interactions=sum(e.total_interactions for e in engaged),
            total_correct_attempts=sum(e.correct_attempts for e in engaged),
            total_incorrect_attempts=sum(e.incorrect_attempts for e in engaged),
            average_active_days=sum(e.active_days for e in engaged) / len(engaged),
        )

    def _assessment_summary(self) -> ClassroomAssessmentSummary:
        scored = [
            state.assessment_performance
            for state in self.student_states.values()
            if state.assessment_performance.average_score is not None
        ]
        if not scored:
            return ClassroomAssessmentSummary()

        averages = [a.average_score for a in scored if a.average_score is not None]
        return ClassroomAssessmentSummary(
            students_with_results=len(scored),
            average_score=sum(averages) / len(averages),
        )

    def _environment_summary(self) -> ClassroomEnvironmentSummary:
        if not self.environment_readings:
            return ClassroomEnvironmentSummary()

        ordered = sorted(self.environment_readings, key=lambda r: r.recorded_at)
        return ClassroomEnvironmentSummary(
            reading_count=len(ordered),
            average_temperature_c=sum(r.temperature_c for r in ordered) / len(ordered),
            average_humidity_pct=sum(r.humidity_pct for r in ordered) / len(ordered),
            average_co2_ppm=sum(r.co2_ppm for r in ordered) / len(ordered),
            latest_battery_pct=ordered[-1].battery_pct,
            last_recorded_at=ordered[-1].recorded_at,
        )

    def _as_of(self) -> datetime | None:
        timestamps = [
            state.as_of for state in self.student_states.values() if state.as_of is not None
        ]
        timestamps += [r.recorded_at for r in self.environment_readings]
        return max(timestamps) if timestamps else None
