"""Classroom-level skill priority ranking: which topic to focus on next.

Rule-based, not ML — see docs/datasets (audit conclusion: BKT already
estimates per-topic mastery, and ASSISTments has no independently recorded
target for "the optimal resource," so a supervised model would either
duplicate BKT's own estimate or be trained on a circular/fabricated label).
Consumes an already-computed `ClassroomTwinState` only; no SQLAlchemy, no
scikit-learn, no dependency on twin_engine's update logic, per CLAUDE.md's
module boundaries.
"""

from __future__ import annotations

from pydantic import BaseModel

from digital_twin.twin_engine.classroom_twin import ClassroomTwinState

# Below this many pooled observations, a topic's average_mastery is too thin
# to act on (e.g. one student's single attempt) — excluded from the ranking
# rather than reported with a misleading low-confidence score.
DEFAULT_MIN_OBSERVATIONS = 3


class SkillPriorityRecommendation(BaseModel):
    """One topic ranked for classroom-wide priority, lowest mastery first.

    `priority_score` is `1 - average_mastery` — a monotonic restatement of
    the same ranking, kept as its own field so a caller can sort/threshold
    on "priority" without recomputing it from `average_mastery` each time.
    """

    topic_id: str
    priority_score: float
    average_mastery: float
    observation_count: int


def recommend_skill_priorities(
    state: ClassroomTwinState,
    *,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> list[SkillPriorityRecommendation]:
    """Rank this classroom's topics by lowest average mastery, most reliable first tie-break.

    Topics with fewer than `min_observations` pooled observations (summed
    across attached students, see `ClassroomTwinState.topic_observation_counts`)
    are excluded rather than ranked on thin data. Ties in `average_mastery`
    are broken by higher `observation_count` first, so a well-observed weak
    topic outranks a barely-observed one reporting the same average.
    """
    recommendations = [
        SkillPriorityRecommendation(
            topic_id=topic_id,
            priority_score=1.0 - average_mastery,
            average_mastery=average_mastery,
            observation_count=state.topic_observation_counts.get(topic_id, 0),
        )
        for topic_id, average_mastery in state.average_mastery_by_topic.items()
        if state.topic_observation_counts.get(topic_id, 0) >= min_observations
    ]
    recommendations.sort(key=lambda r: (-r.priority_score, -r.observation_count))
    return recommendations


__all__ = ["DEFAULT_MIN_OBSERVATIONS", "SkillPriorityRecommendation", "recommend_skill_priorities"]
