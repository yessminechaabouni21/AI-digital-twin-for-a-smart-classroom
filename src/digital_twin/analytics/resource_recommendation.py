"""Problem-level recommendation for the classroom's highest-priority skill.

Rule-based, not ML — ranks *existing* ASSISTments problems already tagged
with a target skill by how close their recorded `mean_correct` is to a
target success-probability band ("desirable difficulty": neither trivially
easy nor discouragingly hard), using only statistics ASSISTments itself
recorded over its own historical population of attempts
(`AssistProblem.mean_correct`/`student_answer_count`, see
data/db/models.py). This does not claim any problem is causally "optimal"
or produces better learning outcomes than another: ASSISTments has no
randomized/counterfactual assignment data to support that claim (see the
classroom-recommendation feasibility audit) — only each problem's own
recorded historical difficulty, which is what's ranked on.

Composes `analytics/skill_priority.py`'s already-ranked topics with
`data/repositories/assistments_problem_attempts.fetch_assistments_problems_for_skill`'s
catalog lookup. No SQLAlchemy/scikit-learn import here, per CLAUDE.md's
module boundaries; no twin_engine import either — this stays outside the
twin, consuming only plain data its caller already fetched, the same
"attach, don't compute" posture the rest of analytics/ takes relative to
StudentTwin/ClassroomTwin.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from digital_twin.analytics.skill_priority import SkillPriorityRecommendation

DEFAULT_TARGET_SUCCESS_PROBABILITY = 0.65
DEFAULT_MIN_STUDENT_ANSWER_COUNT = 20
DEFAULT_PROBLEM_LIMIT = 3


class AssistmentsProblemCandidate(BaseModel):
    """One real ASSISTments problem tagged with a given skill, with its recorded stats.

    `mean_correct`/`student_answer_count` are ASSISTments' own precomputed
    aggregates over its full historical population of attempts at this
    problem (`AssistProblem` in data/db/models.py) — not derived from, or
    specific to, this project's Student/Classroom Twins.
    """

    problem_id: int
    mean_correct: float = Field(ge=0.0, le=1.0)
    mean_time_on_task: float | None = None
    student_answer_count: int = Field(ge=0)


class ProblemRecommendation(BaseModel):
    """One recommended problem for a skill, ranked by closeness to a target difficulty.

    `distance_from_target` is `|mean_correct - target_success_probability|`
    — kept as its own field so a caller can see/sort on the ranking basis
    without recomputing it.
    """

    problem_id: int
    mean_correct: float
    student_answer_count: int
    distance_from_target: float


class ClassroomResourceRecommendation(BaseModel):
    """The classroom's single highest-priority skill, plus problems to assign for it.

    Composes `skill_priority.recommend_skill_priorities`'s top-ranked topic
    with a catalog lookup for that topic — no independent computation
    beyond that composition and the difficulty-band ranking in
    `recommend_problems_for_skill`.
    """

    topic_id: str
    priority_score: float
    average_mastery: float
    observation_count: int
    recommended_problems: list[ProblemRecommendation]


def recommend_problems_for_skill(
    candidates: list[AssistmentsProblemCandidate],
    *,
    target_success_probability: float = DEFAULT_TARGET_SUCCESS_PROBABILITY,
    min_student_answer_count: int = DEFAULT_MIN_STUDENT_ANSWER_COUNT,
    limit: int = DEFAULT_PROBLEM_LIMIT,
) -> list[ProblemRecommendation]:
    """Rank `candidates` by closeness of recorded `mean_correct` to `target_success_probability`.

    Not "the optimal problem" for any student — a desirable-difficulty
    heuristic over the historical population's own recorded success rate.
    Candidates with fewer than `min_student_answer_count` recorded answers
    are excluded as too thin to trust their `mean_correct` on, the same
    reliability posture `skill_priority.py`'s `min_observations` takes for
    topic-level mastery.
    """
    reliable = [c for c in candidates if c.student_answer_count >= min_student_answer_count]
    ranked = sorted(reliable, key=lambda c: abs(c.mean_correct - target_success_probability))
    return [
        ProblemRecommendation(
            problem_id=c.problem_id,
            mean_correct=c.mean_correct,
            student_answer_count=c.student_answer_count,
            distance_from_target=abs(c.mean_correct - target_success_probability),
        )
        for c in ranked[:limit]
    ]


def recommend_classroom_resource(
    skill_priorities: list[SkillPriorityRecommendation],
    problem_candidates_by_topic: dict[str, list[AssistmentsProblemCandidate]],
    *,
    target_success_probability: float = DEFAULT_TARGET_SUCCESS_PROBABILITY,
    min_student_answer_count: int = DEFAULT_MIN_STUDENT_ANSWER_COUNT,
    problem_limit: int = DEFAULT_PROBLEM_LIMIT,
) -> ClassroomResourceRecommendation | None:
    """Combine the top-ranked skill from `skill_priorities` with problem candidates for it.

    `skill_priorities` is expected already ranked (as
    `recommend_skill_priorities` returns it) — this takes its first entry,
    it does not re-rank. Returns `None` if `skill_priorities` is empty (no
    topic met `skill_priority.py`'s own reliability threshold): never
    fabricates a recommendation for a topic the classroom has no reliable
    mastery signal on. If the top topic has no catalog candidates (or none
    reliable enough), `recommended_problems` is an empty list rather than a
    guessed one.
    """
    if not skill_priorities:
        return None

    top = skill_priorities[0]
    candidates = problem_candidates_by_topic.get(top.topic_id, [])
    recommended_problems = recommend_problems_for_skill(
        candidates,
        target_success_probability=target_success_probability,
        min_student_answer_count=min_student_answer_count,
        limit=problem_limit,
    )
    return ClassroomResourceRecommendation(
        topic_id=top.topic_id,
        priority_score=top.priority_score,
        average_mastery=top.average_mastery,
        observation_count=top.observation_count,
        recommended_problems=recommended_problems,
    )


__all__ = [
    "AssistmentsProblemCandidate",
    "ClassroomResourceRecommendation",
    "ProblemRecommendation",
    "recommend_classroom_resource",
    "recommend_problems_for_skill",
]
