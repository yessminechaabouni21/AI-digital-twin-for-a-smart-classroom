"""Fits and evaluates BKT parameters (P(L0), P(T), P(S), P(G)) from real data.

Classical parameter estimation (Baum-Welch EM over a left-to-right 2-state
HMM — the standard BKT formulation), not a new ML framework: no dependency
beyond what this project already has (pydantic, scikit-learn's `log_loss`).
No PostgreSQL/SQLAlchemy import here — this module takes plain Python
sequences, however they were sourced; `data/repositories/assistments_problem_attempts.py`
is the only place that touches the database to build them from real
ASSISTments data.

Evaluation deliberately reuses `twin_engine.update_strategies.BayesianKnowledgeTracingStrategy`
itself rather than re-deriving its update math here, per CLAUDE.md's rule
that twin_engine is the only place update logic lives — this module must
not duplicate it, only fit its parameters and score them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field
from sklearn.metrics import log_loss
from sklearn.model_selection import train_test_split

from digital_twin.domain.interaction import Interaction, InteractionType
from digital_twin.domain.knowledge_state import KnowledgeState
from digital_twin.twin_engine.update_strategies import BayesianKnowledgeTracingStrategy

_EPS = 1e-4


class BktParameters(BaseModel):
    """The four standard BKT parameters, in `BayesianKnowledgeTracingStrategy`'s own terms."""

    prior_mastery: float = Field(ge=0.0, le=1.0)
    p_transit: float = Field(ge=0.0, le=1.0)
    p_slip: float = Field(gt=0.0, lt=1.0)
    p_guess: float = Field(gt=0.0, lt=1.0)


class BktEvaluationResult(BaseModel):
    """Held-out one-step-ahead response-prediction quality for one parameter set."""

    n_predictions: int
    n_sequences: int
    log_loss: float
    accuracy: float


def flatten_sequences(sequences_by_student: dict[int, dict[str, list[bool]]]) -> list[list[bool]]:
    """Flatten {student: {topic: [outcomes]}} into one independent HMM chain per (student, topic).

    Each (student, topic) pair is its own chain: BKT tracks mastery per
    topic independently, so a student's sequences on different topics must
    never be concatenated into one chain.
    """
    return [
        outcomes
        for by_topic in sequences_by_student.values()
        for outcomes in by_topic.values()
        if outcomes
    ]


def split_student_ids(
    student_ids: Sequence[int], *, test_size: float = 0.2, random_state: int = 42
) -> tuple[list[int], list[int]]:
    """Deterministically split student_ids into train/test, at the student level.

    Splitting by student (not by individual sequence or attempt) is what
    prevents leakage: no student's interactions may inform parameter
    fitting and also be used to evaluate it, and no future attempt may
    influence an earlier state's estimate — the chronological ordering
    within each retained sequence is untouched by this split.
    """
    train_ids, test_ids = train_test_split(
        list(student_ids), test_size=test_size, random_state=random_state
    )
    return train_ids, test_ids


def fit_bkt_em(
    sequences: Sequence[Sequence[bool]],
    *,
    n_iter: int = 20,
    initial: BktParameters | None = None,
) -> BktParameters:
    """Fit global BKT parameters via Baum-Welch EM on a left-to-right 2-state HMM.

    States: 0 = not yet mastered, 1 = mastered. Transition only 0 -> 1 is
    possible (probability `p_transit`; the standard BKT "no forgetting"
    assumption) — mastered stays mastered. Emission: P(correct | mastered)
    = 1 - p_slip, P(correct | not mastered) = p_guess. One shared parameter
    set is fit across all (student, topic) sequences pooled together (not
    per-topic) — the ASSISTments sample here doesn't have enough attempts
    per individual skill to fit per-skill parameters reliably, so a single
    pooled fit is the defensible choice, not a per-skill one.

    Uses Rabiner's scaled forward-backward algorithm (each alpha_t
    renormalized to sum to 1, with the scale factor reused in the backward
    pass) to avoid floating-point underflow on the longer sequences in this
    data (some skills have 100+ chronological attempts from one student).
    """
    params = initial or BktParameters(prior_mastery=0.3, p_transit=0.2, p_slip=0.1, p_guess=0.25)
    usable = [list(seq) for seq in sequences if len(seq) > 0]
    if not usable:
        raise ValueError("fit_bkt_em requires at least one non-empty sequence")

    for _ in range(n_iter):
        params = _em_step(usable, params)
    return params


def _emission(z: int, correct: bool, p_slip: float, p_guess: float) -> float:
    if correct:
        return p_guess if z == 0 else (1.0 - p_slip)
    return (1.0 - p_guess) if z == 0 else p_slip


def _em_step(sequences: list[list[bool]], params: BktParameters) -> BktParameters:
    l0, trans, slip, guess = (
        params.prior_mastery,
        params.p_transit,
        params.p_slip,
        params.p_guess,
    )
    pi = (1.0 - l0, l0)
    # a[from][to]; state 1 (mastered) never transitions back to 0.
    a = ((1.0 - trans, trans), (0.0, 1.0))

    sum_l0 = 0.0
    n_sequences = 0
    trans_num = 0.0
    trans_den = 0.0
    slip_num = 0.0
    slip_den = 0.0
    guess_num = 0.0
    guess_den = 0.0

    for obs in sequences:
        t_len = len(obs)
        alpha = [[0.0, 0.0] for _ in range(t_len)]
        scale = [0.0] * t_len

        alpha[0][0] = pi[0] * _emission(0, obs[0], slip, guess)
        alpha[0][1] = pi[1] * _emission(1, obs[0], slip, guess)
        total0 = alpha[0][0] + alpha[0][1]
        scale[0] = 1.0 / total0 if total0 > 0.0 else 1.0
        alpha[0][0] *= scale[0]
        alpha[0][1] *= scale[0]

        for t in range(1, t_len):
            for z in (0, 1):
                alpha[t][z] = (alpha[t - 1][0] * a[0][z] + alpha[t - 1][1] * a[1][z]) * _emission(
                    z, obs[t], slip, guess
                )
            total_t = alpha[t][0] + alpha[t][1]
            scale[t] = 1.0 / total_t if total_t > 0.0 else 1.0
            alpha[t][0] *= scale[t]
            alpha[t][1] *= scale[t]

        beta = [[0.0, 0.0] for _ in range(t_len)]
        beta[t_len - 1] = [scale[t_len - 1], scale[t_len - 1]]
        for t in range(t_len - 2, -1, -1):
            for z in (0, 1):
                beta[t][z] = scale[t] * (
                    a[z][0] * _emission(0, obs[t + 1], slip, guess) * beta[t + 1][0]
                    + a[z][1] * _emission(1, obs[t + 1], slip, guess) * beta[t + 1][1]
                )

        gammas = []
        for t in range(t_len):
            g0 = alpha[t][0] * beta[t][0]
            g1 = alpha[t][1] * beta[t][1]
            total_g = g0 + g1
            gammas.append((g0 / total_g, g1 / total_g) if total_g > 0.0 else (g0, g1))

        sum_l0 += gammas[0][1]
        n_sequences += 1

        for t in range(t_len - 1):
            xi01 = alpha[t][0] * a[0][1] * _emission(1, obs[t + 1], slip, guess) * beta[t + 1][1]
            xi00 = alpha[t][0] * a[0][0] * _emission(0, obs[t + 1], slip, guess) * beta[t + 1][0]
            xi10 = alpha[t][1] * a[1][0] * _emission(0, obs[t + 1], slip, guess) * beta[t + 1][0]
            xi11 = alpha[t][1] * a[1][1] * _emission(1, obs[t + 1], slip, guess) * beta[t + 1][1]
            xi_total = xi00 + xi01 + xi10 + xi11
            trans_num += xi01 / xi_total if xi_total > 0.0 else 0.0
            trans_den += gammas[t][0]

        for t in range(t_len):
            g0, g1 = gammas[t]
            guess_den += g0
            slip_den += g1
            if obs[t]:
                guess_num += g0
            else:
                slip_num += g1

    new_l0 = sum_l0 / n_sequences if n_sequences > 0 else l0
    new_trans = trans_num / trans_den if trans_den > 0.0 else trans
    new_slip = slip_num / slip_den if slip_den > 0.0 else slip
    new_guess = guess_num / guess_den if guess_den > 0.0 else guess

    return BktParameters(
        prior_mastery=min(1.0, max(0.0, new_l0)),
        p_transit=min(1.0, max(0.0, new_trans)),
        p_slip=min(1.0 - _EPS, max(_EPS, new_slip)),
        p_guess=min(1.0 - _EPS, max(_EPS, new_guess)),
    )


def predict_correct_probability(mastery: float, p_slip: float, p_guess: float) -> float:
    """P(correct) given a mastery estimate, before this attempt's own outcome is known."""
    return mastery * (1.0 - p_slip) + (1.0 - mastery) * p_guess


def evaluate_bkt(
    parameters: BktParameters, sequences: Sequence[Sequence[bool]]
) -> BktEvaluationResult:
    """Score one-step-ahead response prediction on held-out sequences.

    For every attempt, predicts P(correct) from the mastery estimate
    available *before* that attempt (never from its own outcome), then
    feeds the actual outcome into `BayesianKnowledgeTracingStrategy.update`
    to get the mastery estimate for the next attempt in the same sequence —
    exactly the production update path, run against held-out data only.
    """
    strategy = BayesianKnowledgeTracingStrategy(
        prior_mastery=parameters.prior_mastery,
        p_transit=parameters.p_transit,
        p_slip=parameters.p_slip,
        p_guess=parameters.p_guess,
    )

    y_true: list[int] = []
    y_pred: list[float] = []
    n_sequences = 0
    base_time = datetime(2000, 1, 1, tzinfo=UTC)

    for obs in sequences:
        if not obs:
            continue
        n_sequences += 1
        student_id = uuid4()
        previous: KnowledgeState | None = None
        for t, correct in enumerate(obs):
            mastery_before = (
                previous.mastery_probability if previous is not None else strategy.prior_mastery
            )
            y_true.append(1 if correct else 0)
            y_pred.append(
                predict_correct_probability(mastery_before, strategy.p_slip, strategy.p_guess)
            )

            interaction = Interaction(
                student_id=student_id,
                occurred_at=base_time + timedelta(seconds=t),
                interaction_type=InteractionType.PROBLEM_ATTEMPT,
                topic_id="calibration",
                outcome=correct,
            )
            previous = strategy.update(previous, interaction)

    clipped = [min(1.0 - 1e-9, max(1e-9, p)) for p in y_pred]
    predicted_labels = [1 if p >= 0.5 else 0 for p in clipped]
    accuracy = sum(1 for t, p in zip(y_true, predicted_labels, strict=True) if t == p) / len(y_true)

    return BktEvaluationResult(
        n_predictions=len(y_true),
        n_sequences=n_sequences,
        log_loss=log_loss(y_true, clipped, labels=[0, 1]),
        accuracy=accuracy,
    )


__all__ = [
    "BktEvaluationResult",
    "BktParameters",
    "evaluate_bkt",
    "fit_bkt_em",
    "flatten_sequences",
    "predict_correct_probability",
    "split_student_ids",
]
