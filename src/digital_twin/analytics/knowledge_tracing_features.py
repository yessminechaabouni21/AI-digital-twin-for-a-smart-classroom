"""Leakage-free historical features for the H3/H4 knowledge-tracing experiment.

Every per-student feature is a function of strictly earlier attempts by that
same student (`j < i`), across all skills, in true chronological order — not
the per-skill-bucketed order `analytics/bkt_calibration.py` and
`data/repositories/assistments_problem_attempts.fetch_assistments_attempt_sequences`
use, which throws away cross-skill interleaving. `skill_train_difficulty` is
the one population-level (not per-row-causal) feature: it is fit once from
train-fit-split students only (a set disjoint from val/test students) and
frozen before any row is generated, the same convention
`analytics.bkt_calibration.fit_bkt_em` already uses for BKT's own pooled
global parameters. See the experimental-design conversation for the full
causality argument.

No SQLAlchemy import here — this module takes plain
`{student_id: [(start_time, topic_id, correct), ...]}`, however sourced;
`data/repositories/assistments_problem_attempts.fetch_assistments_chronological_attempts`
is the only place that builds it from real ASSISTments data.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel

from digital_twin.domain.interaction import Interaction, InteractionType
from digital_twin.domain.knowledge_state import KnowledgeState
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

ChronologicalAttempts = dict[int, list[tuple[datetime, str, bool]]]


class FeatureRow(BaseModel):
    """One (student, attempt) row's causal feature vector plus its label.

    `has_prior_student_attempt`/`has_prior_skill_attempt` let a model that
    can't consume NaN directly (e.g. `LogisticRegression`) distinguish "rate
    is exactly 0" from "no history yet" once the corresponding `*_before`
    field is 0-filled; `HistGradientBoostingClassifier` can use the raw NaN
    fields directly and ignore the flags.
    """

    student_id: int
    topic_id: str
    correct: bool

    student_total_attempts_before: int
    student_total_correct_rate_before: float | None
    student_skill_attempts_before: int
    student_skill_correct_rate_before: float | None
    attempts_since_last_seen_skill: int | None
    skill_train_difficulty: float
    bkt_mastery_before: float

    has_prior_student_attempt: bool
    has_prior_skill_attempt: bool


_GLOBAL_FALLBACK_DIFFICULTY = 0.5
_BASE_TIME = datetime(2000, 1, 1, tzinfo=UTC)


def compute_skill_train_difficulty(
    train_fit_attempts: ChronologicalAttempts,
) -> dict[str, float]:
    """Fixed per-skill mean-correctness lookup, fit once from train-fit students only.

    Pools every attempt (all students, all time) in `train_fit_attempts` —
    a population-level nuisance parameter, not a per-row-causal one, exactly
    like BKT's own EM-fit `P(T)/P(S)/P(G)`. Callers must build this from the
    train-fit split alone and reuse the same frozen dict for train-fit, val,
    and test row generation; it must never be recomputed with val/test data
    mixed in.
    """
    correct_sum: dict[str, int] = {}
    total: dict[str, int] = {}
    for attempts in train_fit_attempts.values():
        for _start_time, topic_id, correct in attempts:
            total[topic_id] = total.get(topic_id, 0) + 1
            if correct:
                correct_sum[topic_id] = correct_sum.get(topic_id, 0) + 1
    return {topic_id: correct_sum.get(topic_id, 0) / count for topic_id, count in total.items()}


def _bkt_mastery_before_by_skill(
    chain: Sequence[bool], strategy: BayesianKnowledgeTracingStrategy
) -> list[float]:
    """Pre-update BKT mastery estimate before each attempt in one (student, skill) chain.

    Orchestration only (loop + `Interaction` construction) — the actual
    Bayes update math is `BayesianKnowledgeTracingStrategy.update`, reused
    unmodified, per CLAUDE.md's rule that twin_engine is the only place that
    logic lives. Mirrors `bkt_calibration._one_step_predictions`'s walk, but
    returns mastery-before values for feature-building rather than
    predicted response probabilities for evaluation.
    """
    student_id = uuid4()
    previous: KnowledgeState | None = None
    mastery_before: list[float] = []
    for t, correct in enumerate(chain):
        mastery_before.append(
            previous.mastery_probability if previous is not None else strategy.prior_mastery
        )
        interaction = Interaction(
            student_id=student_id,
            occurred_at=_BASE_TIME + timedelta(seconds=t),
            interaction_type=InteractionType.PROBLEM_ATTEMPT,
            topic_id="feature-extraction",
            outcome=correct,
        )
        previous = strategy.update(previous, interaction)
    return mastery_before


def build_feature_rows(
    attempts_by_student: ChronologicalAttempts,
    *,
    skill_train_difficulty: dict[str, float],
    bkt_strategy: BayesianKnowledgeTracingStrategy,
) -> list[FeatureRow]:
    """Build one causal `FeatureRow` per attempt, in each student's chronological order.

    `skill_train_difficulty` must already be frozen (from `compute_skill_train_difficulty`
    on train-fit students only) before this is called for any split, including
    train-fit itself. `bkt_strategy` should likewise already be fit/frozen
    (the experiment's val-selected M2 parameters) — this function only walks
    it, it does not fit it.
    """
    rows: list[FeatureRow] = []
    for student_id, attempts in attempts_by_student.items():
        ordered = sorted(attempts, key=lambda a: a[0])

        chains: dict[str, list[bool]] = {}
        for _start_time, topic_id, correct in ordered:
            chains.setdefault(topic_id, []).append(correct)
        mastery_before_by_skill = {
            topic_id: _bkt_mastery_before_by_skill(chain, bkt_strategy)
            for topic_id, chain in chains.items()
        }
        skill_cursor: dict[str, int] = dict.fromkeys(chains, 0)

        total_attempts = 0
        total_correct = 0
        skill_attempts: dict[str, int] = {}
        skill_correct: dict[str, int] = {}
        last_seen_index: dict[str, int] = {}

        for i, (_start_time, topic_id, correct) in enumerate(ordered):
            prior_skill_attempts = skill_attempts.get(topic_id, 0)
            prior_skill_correct = skill_correct.get(topic_id, 0)
            has_prior_student_attempt = total_attempts > 0
            has_prior_skill_attempt = prior_skill_attempts > 0

            cursor = skill_cursor[topic_id]
            mastery_before = mastery_before_by_skill[topic_id][cursor]
            skill_cursor[topic_id] = cursor + 1

            rows.append(
                FeatureRow(
                    student_id=student_id,
                    topic_id=topic_id,
                    correct=correct,
                    student_total_attempts_before=total_attempts,
                    student_total_correct_rate_before=(
                        total_correct / total_attempts if has_prior_student_attempt else None
                    ),
                    student_skill_attempts_before=prior_skill_attempts,
                    student_skill_correct_rate_before=(
                        prior_skill_correct / prior_skill_attempts
                        if has_prior_skill_attempt
                        else None
                    ),
                    attempts_since_last_seen_skill=(
                        i - last_seen_index[topic_id] if topic_id in last_seen_index else None
                    ),
                    skill_train_difficulty=skill_train_difficulty.get(
                        topic_id, _GLOBAL_FALLBACK_DIFFICULTY
                    ),
                    bkt_mastery_before=mastery_before,
                    has_prior_student_attempt=has_prior_student_attempt,
                    has_prior_skill_attempt=has_prior_skill_attempt,
                )
            )

            total_attempts += 1
            total_correct += 1 if correct else 0
            skill_attempts[topic_id] = prior_skill_attempts + 1
            skill_correct[topic_id] = prior_skill_correct + (1 if correct else 0)
            last_seen_index[topic_id] = i

    return rows


NUMERIC_FEATURE_COLUMNS = [
    "student_total_attempts_before",
    "student_total_correct_rate_before",
    "student_skill_attempts_before",
    "student_skill_correct_rate_before",
    "attempts_since_last_seen_skill",
    "skill_train_difficulty",
    "bkt_mastery_before",
]
INDICATOR_FEATURE_COLUMNS = ["has_prior_student_attempt", "has_prior_skill_attempt"]


def to_dense_matrix(
    rows: Sequence[FeatureRow], *, for_model: str
) -> tuple[list[list[float]], list[int]]:
    """Turn `FeatureRow`s into a plain feature matrix + label vector for sklearn.

    `for_model="gbm"` leaves missing numeric fields as `float("nan")`
    (`HistGradientBoostingClassifier` handles NaN natively). `for_model="lr"`
    0-fills them instead, relying on the indicator columns (already part of
    every row) to keep "no history" distinguishable from "history, rate 0" —
    `LogisticRegression` cannot consume NaN directly.
    """
    if for_model not in ("gbm", "lr"):
        raise ValueError(f"for_model must be 'gbm' or 'lr', got {for_model!r}")

    matrix: list[list[float]] = []
    labels: list[int] = []
    for row in rows:
        values: list[float] = []
        for name in NUMERIC_FEATURE_COLUMNS:
            value = getattr(row, name)
            if value is None:
                values.append(float("nan") if for_model == "gbm" else 0.0)
            else:
                values.append(float(value))
        for name in INDICATOR_FEATURE_COLUMNS:
            values.append(1.0 if getattr(row, name) else 0.0)
        matrix.append(values)
        labels.append(1 if row.correct else 0)
    return matrix, labels


__all__ = [
    "INDICATOR_FEATURE_COLUMNS",
    "NUMERIC_FEATURE_COLUMNS",
    "ChronologicalAttempts",
    "FeatureRow",
    "build_feature_rows",
    "compute_skill_train_difficulty",
    "to_dense_matrix",
]
