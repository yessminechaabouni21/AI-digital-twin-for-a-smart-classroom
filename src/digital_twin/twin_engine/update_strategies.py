"""Pluggable strategies for updating knowledge state (e.g., Bayesian knowledge tracing, IRT)."""

from __future__ import annotations

from typing import Protocol

from digital_twin.domain.interaction import Interaction
from digital_twin.domain.knowledge_state import KnowledgeState


class UpdateStrategy(Protocol):
    """Turns one Interaction (+ prior state for that topic, if any) into a new KnowledgeState.

    The only contract callers (StudentTwin) rely on — swapping
    SimpleIncrementalUpdateStrategy for Bayesian Knowledge Tracing, IRT, or
    a learned model later means implementing this method, nothing else.
    """

    def update(self, previous: KnowledgeState | None, interaction: Interaction) -> KnowledgeState:
        """Return the new KnowledgeState for `interaction`'s (student, topic).

        `previous` is the student's last known KnowledgeState for that
        topic, or None if this is the first observation. Raises ValueError
        if `interaction` can't be scored (no topic_id, no outcome) or if
        `previous` belongs to a different student/topic — callers are
        expected to filter/route before calling, not rely on this to do it
        silently.
        """
        ...


class SimpleIncrementalUpdateStrategy:
    """First-version update rule: nudge mastery toward the observed outcome.

    new_mastery = old_mastery + learning_rate * (target - old_mastery),
    where target is 1.0 for a correct attempt and 0.0 for an incorrect one,
    clamped to [0, 1] (KnowledgeState's own field constraint enforces this
    too). A topic with no prior state starts from `initial_mastery`.

    This is a plain exponential moving average, not Bayesian Knowledge
    Tracing or IRT — deliberately simple and explainable for a first
    version. It exists only to satisfy the `UpdateStrategy` protocol so it
    can be swapped for a more sophisticated strategy later without
    changing any caller.
    """

    def __init__(self, learning_rate: float = 0.3, initial_mastery: float = 0.5) -> None:
        if not 0.0 < learning_rate <= 1.0:
            raise ValueError(f"learning_rate must be in (0, 1], got {learning_rate}")
        if not 0.0 <= initial_mastery <= 1.0:
            raise ValueError(f"initial_mastery must be in [0, 1], got {initial_mastery}")
        self.learning_rate = learning_rate
        self.initial_mastery = initial_mastery

    def update(self, previous: KnowledgeState | None, interaction: Interaction) -> KnowledgeState:
        if interaction.topic_id is None:
            raise ValueError("Interaction.topic_id is required to update KnowledgeState")
        if interaction.outcome is None:
            raise ValueError("Interaction.outcome is required to update KnowledgeState")
        if previous is not None and (
            previous.student_id != interaction.student_id
            or previous.topic_id != interaction.topic_id
        ):
            raise ValueError("previous KnowledgeState does not match interaction's student/topic")

        current_mastery = (
            previous.mastery_probability if previous is not None else self.initial_mastery
        )
        target = 1.0 if interaction.outcome else 0.0
        new_mastery = current_mastery + self.learning_rate * (target - current_mastery)
        new_mastery = min(1.0, max(0.0, new_mastery))

        return KnowledgeState(
            student_id=interaction.student_id,
            topic_id=interaction.topic_id,
            mastery_probability=new_mastery,
            observation_count=(previous.observation_count if previous is not None else 0) + 1,
            updated_at=interaction.occurred_at,
        )


class BayesianKnowledgeTracingStrategy:
    """Classic Bayesian Knowledge Tracing (Corbett & Anderson, 1994).

    Tracks P(mastered) per topic as a hidden binary state, updated from
    each PROBLEM_ATTEMPT via two standard BKT steps:

    1. Bayes' rule, conditioning the prior mastery on the observed
       correctness, given a fixed probability of slipping (answering
       incorrectly despite having mastered the skill) and guessing
       (answering correctly despite not having mastered it):

       P(L | correct)   = P(L)(1-slip) / [P(L)(1-slip) + (1-P(L))guess]
       P(L | incorrect) = P(L)slip     / [P(L)slip     + (1-P(L))(1-guess)]

    2. A learning-opportunity step, since even a not-yet-mastered skill may
       be learned from this attempt:

       P(L_new) = P(L | evidence) + (1 - P(L | evidence)) * p_transit

    `slip`/`guess` are fixed, global parameters (one shared set across all
    topics, not fit per-skill — see `analytics/bkt_calibration.py`'s
    docstring for why per-skill fitting wasn't reliable on this data),
    deliberately simple and explainable, the same posture as
    `SimpleIncrementalUpdateStrategy`. A topic with no prior state starts
    from `prior_mastery`, BKT's P(L0).

    The default parameters below are fit from real ASSISTments
    problem-attempt sequences via `analytics.bkt_calibration.fit_bkt_em`
    (Baum-Welch EM on a left-to-right 2-state HMM), not literature/textbook
    defaults — see `scripts/calibrate_bkt.py` for the fitting/evaluation
    run this came from. On a held-out test split (400 of 2,000 sampled
    students, disjoint from the 1,600 training students), these fitted
    parameters scored log-loss 0.597 / accuracy 68.6% one-step-ahead
    response prediction, versus 0.634 / 65.3% for the original literature
    defaults (prior_mastery=0.3, p_transit=0.2, p_slip=0.1, p_guess=0.25) —
    a real, measured improvement, kept because it won on held-out data, not
    assumed.
    """

    def __init__(
        self,
        prior_mastery: float = 0.5639,
        p_transit: float = 0.0274,
        p_slip: float = 0.1870,
        p_guess: float = 0.3521,
    ) -> None:
        if not 0.0 <= prior_mastery <= 1.0:
            raise ValueError(f"prior_mastery must be in [0, 1], got {prior_mastery}")
        if not 0.0 <= p_transit <= 1.0:
            raise ValueError(f"p_transit must be in [0, 1], got {p_transit}")
        if not 0.0 < p_slip < 1.0:
            raise ValueError(f"p_slip must be in (0, 1), got {p_slip}")
        if not 0.0 < p_guess < 1.0:
            raise ValueError(f"p_guess must be in (0, 1), got {p_guess}")
        self.prior_mastery = prior_mastery
        self.p_transit = p_transit
        self.p_slip = p_slip
        self.p_guess = p_guess

    def update(self, previous: KnowledgeState | None, interaction: Interaction) -> KnowledgeState:
        if interaction.topic_id is None:
            raise ValueError("Interaction.topic_id is required to update KnowledgeState")
        if interaction.outcome is None:
            raise ValueError("Interaction.outcome is required to update KnowledgeState")
        if previous is not None and (
            previous.student_id != interaction.student_id
            or previous.topic_id != interaction.topic_id
        ):
            raise ValueError("previous KnowledgeState does not match interaction's student/topic")

        prior = previous.mastery_probability if previous is not None else self.prior_mastery

        if interaction.outcome:
            numerator = prior * (1.0 - self.p_slip)
            denominator = numerator + (1.0 - prior) * self.p_guess
        else:
            numerator = prior * self.p_slip
            denominator = numerator + (1.0 - prior) * (1.0 - self.p_guess)
        posterior = numerator / denominator if denominator > 0.0 else prior

        new_mastery = posterior + (1.0 - posterior) * self.p_transit
        new_mastery = min(1.0, max(0.0, new_mastery))

        return KnowledgeState(
            student_id=interaction.student_id,
            topic_id=interaction.topic_id,
            mastery_probability=new_mastery,
            observation_count=(previous.observation_count if previous is not None else 0) + 1,
            updated_at=interaction.occurred_at,
        )
