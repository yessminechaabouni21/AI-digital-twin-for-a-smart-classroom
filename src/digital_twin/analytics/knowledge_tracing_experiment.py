"""Orchestrates the H1-H4 knowledge-tracing experiment.

Produces the *new*, scientifically controlled comparisons this experiment
adds on top of the frozen baseline: M2 (a train-fitted BKT whose EM
iteration count is selected on a validation split, never on test), M3 (BKT
+ leakage-free historical features -> logistic regression), and M4
(the same features -> gradient-boosted trees). Every model here is fit on
train-fit, model-selected on val, refit on train-fit+val, and scored
exactly once on the frozen test split.

Deliberately does not import from or modify `analytics/bkt_calibration.py`'s
evaluation functions or `scripts/calibrate_bkt.py` — the literature-default,
current-production, and baseline numbers already reported stay exactly as
they are; this module is additive. The one thing it reuses from that module
is `split_student_ids` (the outer train/test student partition) and
`flatten_sequences`, so the outer split is identical to the one that
produced the frozen numbers, not a fresh/incompatible one.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from pydantic import BaseModel
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import train_test_split

from digital_twin.analytics.bkt_calibration import (
    BktParameters,
    evaluate_bkt_identified,
    fit_bkt_em,
    flatten_sequences,
)
from digital_twin.analytics.knowledge_tracing_features import (
    ChronologicalAttempts,
    FeatureRow,
    to_dense_matrix,
)


class TrainFitValTestSplit(BaseModel):
    """Student-id partition: train-fit (fitting) / val (model selection) / test (frozen)."""

    train_fit_ids: list[int]
    val_ids: list[int]
    test_ids: list[int]


def split_train_fit_val_test(
    student_ids: Sequence[int],
    *,
    test_size: float = 0.2,
    val_size: float = 0.2,
    outer_random_state: int = 42,
    inner_random_state: int = 43,
) -> TrainFitValTestSplit:
    """Reuse the frozen test split (`outer_random_state=42`, same as `split_student_ids`),
    then further split its train side into train-fit/val with a distinct seed.

    Splitting on the already-frozen train side (never re-deriving the
    test/train partition) keeps this experiment's test set identical to the
    one the immutable baseline numbers were computed on.
    """
    train_ids, test_ids = train_test_split(
        list(student_ids), test_size=test_size, random_state=outer_random_state
    )
    train_fit_ids, val_ids = train_test_split(
        train_ids, test_size=val_size, random_state=inner_random_state
    )
    return TrainFitValTestSplit(train_fit_ids=train_fit_ids, val_ids=val_ids, test_ids=test_ids)


def subset_attempts(attempts: ChronologicalAttempts, ids: Sequence[int]) -> ChronologicalAttempts:
    """Restrict `attempts` to the given student ids — the split-boundary primitive every
    train-fit/val/test/combined slice in this module is built from."""
    id_set = set(ids)
    return {sid: seq for sid, seq in attempts.items() if sid in id_set}


def _to_sequences_by_student(
    attempts: ChronologicalAttempts,
) -> dict[int, dict[str, list[bool]]]:
    """Rebuild `bkt_calibration`'s `{student: {topic: [outcome,...]}}` shape from chronological
    rows.

    Sorting by timestamp before bucketing preserves each (student, topic)
    chain's own chronological order, only discarding cross-skill
    interleaving — exactly what `fit_bkt_em`/`evaluate_bkt_identified`
    already expect as input.
    """
    result: dict[int, dict[str, list[bool]]] = {}
    for student_id, rows in attempts.items():
        for _start_time, topic_id, correct in sorted(rows, key=lambda r: r[0]):
            result.setdefault(student_id, {}).setdefault(topic_id, []).append(correct)
    return result


DEFAULT_EM_ITERATION_CANDIDATES = (5, 10, 15, 20, 25, 30, 40)


class M2SelectionResult(BaseModel):
    parameters: BktParameters
    selected_n_iter: int
    val_log_loss_by_n_iter: dict[int, float]


def select_and_fit_bkt(
    train_fit_attempts: ChronologicalAttempts,
    val_attempts: ChronologicalAttempts,
    *,
    candidate_iterations: Sequence[int] = DEFAULT_EM_ITERATION_CANDIDATES,
) -> M2SelectionResult:
    """Select EM iteration count on val (by one-step-ahead log loss), then refit on train-fit+val.

    Model selection never touches test: every candidate is fit on train-fit
    only and scored on val only. Once the winning `n_iter` is chosen, the
    final M2 parameters are refit with that `n_iter` on train-fit+val
    combined (more data for the final estimate), then frozen.
    """
    train_fit_sequences = flatten_sequences(_to_sequences_by_student(train_fit_attempts))
    val_by_student = _to_sequences_by_student(val_attempts)

    val_log_loss_by_n_iter: dict[int, float] = {}
    for n_iter in candidate_iterations:
        fitted = fit_bkt_em(train_fit_sequences, n_iter=n_iter)
        result = evaluate_bkt_identified(fitted, val_by_student)
        val_log_loss_by_n_iter[n_iter] = result.log_loss

    selected_n_iter = min(val_log_loss_by_n_iter, key=lambda k: val_log_loss_by_n_iter[k])

    combined_attempts: ChronologicalAttempts = {**train_fit_attempts, **val_attempts}
    combined_sequences = flatten_sequences(_to_sequences_by_student(combined_attempts))
    final_parameters = fit_bkt_em(combined_sequences, n_iter=selected_n_iter)

    return M2SelectionResult(
        parameters=final_parameters,
        selected_n_iter=selected_n_iter,
        val_log_loss_by_n_iter=val_log_loss_by_n_iter,
    )


class ExperimentEvaluationResult(BaseModel):
    """Held-out evaluation summary for one model (row-level, not sequence-level, granularity)."""

    n_predictions: int
    n_students: int
    n_skills: int
    log_loss: float
    accuracy: float
    rmse: float
    brier_score: float
    auc: float | None = None


def score_predictions(
    y_true: Sequence[int], y_pred: Sequence[float], rows: Sequence[FeatureRow]
) -> ExperimentEvaluationResult:
    """Compute log-loss/RMSE/Brier/accuracy/AUC for any row-aligned (y_true, y_pred) pair.

    Public so callers (e.g. the M2-vs-M3-vs-M4 script) can score row-aligned
    predictions from any of the three models — including M2's own, computed
    directly from each row's `bkt_mastery_before` via
    `bkt_calibration.predict_correct_probability` — on identical footing.
    """
    clipped = [min(1.0 - 1e-9, max(1e-9, p)) for p in y_pred]
    predicted_labels = [1 if p >= 0.5 else 0 for p in y_pred]
    accuracy = sum(1 for t, p in zip(y_true, predicted_labels, strict=True) if t == p) / len(y_true)
    squared_errors = [(t - p) ** 2 for t, p in zip(y_true, y_pred, strict=True)]
    brier = sum(squared_errors) / len(squared_errors)
    auc = float(roc_auc_score(y_true, y_pred)) if len(set(y_true)) > 1 else None

    return ExperimentEvaluationResult(
        n_predictions=len(y_true),
        n_students=len({row.student_id for row in rows}),
        n_skills=len({row.topic_id for row in rows}),
        log_loss=log_loss(y_true, clipped, labels=[0, 1]),
        accuracy=accuracy,
        rmse=brier**0.5,
        brier_score=brier,
        auc=auc,
    )


def evaluate_m2_bkt_rowwise(
    parameters: BktParameters, test_attempts: ChronologicalAttempts
) -> ExperimentEvaluationResult:
    """Score M2 (val-selected, train-fit+val-fitted BKT) on test, at the same row granularity
    used for M3/M4 so all three are directly comparable in one results table.

    Delegates the actual one-step-ahead walk to `bkt_calibration.evaluate_bkt_identified`
    (imported, not reimplemented) and repackages its result as an
    `ExperimentEvaluationResult` — the numbers are identical, only the
    return type changes for consistency with M3/M4's reporting.
    """
    result = evaluate_bkt_identified(parameters, _to_sequences_by_student(test_attempts))
    return ExperimentEvaluationResult(
        n_predictions=result.n_predictions,
        n_students=result.n_students or 0,
        n_skills=result.n_skills or 0,
        log_loss=result.log_loss,
        accuracy=result.accuracy,
        rmse=result.rmse,
        brier_score=result.brier_score,
        auc=result.auc,
    )


LR_C_CANDIDATES = (0.01, 0.1, 1.0, 10.0)


def select_and_fit_logistic_regression(
    train_fit_rows: Sequence[FeatureRow],
    val_rows: Sequence[FeatureRow],
    combined_rows: Sequence[FeatureRow],
    *,
    c_candidates: Sequence[float] = LR_C_CANDIDATES,
) -> tuple[LogisticRegression, float]:
    """Select L2 strength `C` on val log loss, refit on train-fit+val with the winner."""
    x_train, y_train = to_dense_matrix(train_fit_rows, for_model="lr")
    x_val, y_val = to_dense_matrix(val_rows, for_model="lr")

    val_log_loss_by_c: dict[float, float] = {}
    for c in c_candidates:
        model = LogisticRegression(C=c, max_iter=2000)
        model.fit(x_train, y_train)
        proba = model.predict_proba(x_val)[:, 1]
        val_log_loss_by_c[c] = log_loss(y_val, proba, labels=[0, 1])

    selected_c = min(val_log_loss_by_c, key=lambda k: val_log_loss_by_c[k])

    x_combined, y_combined = to_dense_matrix(combined_rows, for_model="lr")
    final_model = LogisticRegression(C=selected_c, max_iter=2000)
    final_model.fit(x_combined, y_combined)
    return final_model, selected_c


GBM_CANDIDATES: tuple[dict[str, float], ...] = (
    {"max_depth": 3, "learning_rate": 0.1, "max_iter": 100},
    {"max_depth": 3, "learning_rate": 0.05, "max_iter": 200},
    {"max_depth": 5, "learning_rate": 0.05, "max_iter": 200},
    {"max_depth": 5, "learning_rate": 0.1, "max_iter": 100},
)


def select_and_fit_gbm(
    train_fit_rows: Sequence[FeatureRow],
    val_rows: Sequence[FeatureRow],
    combined_rows: Sequence[FeatureRow],
    *,
    candidates: Sequence[dict[str, float]] = GBM_CANDIDATES,
    random_state: int = 42,
) -> tuple[HistGradientBoostingClassifier, dict[str, float]]:
    """Select depth/learning-rate/iterations on val log loss, refit on train-fit+val with
    the winner.

    `HistGradientBoostingClassifier` (scikit-learn), not XGBoost/LightGBM:
    neither is a `pyproject.toml` dependency, and sklearn's own histogram
    GBM already answers "does a non-linear, interaction-capturing model
    beat classical BKT/logistic regression" without adding one — the same
    reasoning `analytics/predictive.py`'s ADR entry used for random forest
    over XGBoost. It also handles missing (NaN) features natively, matching
    `to_dense_matrix(..., for_model="gbm")`'s output.
    """
    x_train, y_train = to_dense_matrix(train_fit_rows, for_model="gbm")
    x_val, y_val = to_dense_matrix(val_rows, for_model="gbm")

    best_config: dict[str, float] | None = None
    best_log_loss = float("inf")
    for config in candidates:
        model = HistGradientBoostingClassifier(
            max_depth=int(config["max_depth"]),
            learning_rate=config["learning_rate"],
            max_iter=int(config["max_iter"]),
            random_state=random_state,
        )
        model.fit(x_train, y_train)
        proba = model.predict_proba(x_val)[:, 1]
        val_ll = log_loss(y_val, proba, labels=[0, 1])
        if val_ll < best_log_loss:
            best_log_loss = val_ll
            best_config = config

    assert best_config is not None

    x_combined, y_combined = to_dense_matrix(combined_rows, for_model="gbm")
    final_model = HistGradientBoostingClassifier(
        max_depth=int(best_config["max_depth"]),
        learning_rate=best_config["learning_rate"],
        max_iter=int(best_config["max_iter"]),
        random_state=random_state,
    )
    final_model.fit(x_combined, y_combined)
    return final_model, best_config


def evaluate_sklearn_model(
    model: LogisticRegression | HistGradientBoostingClassifier,
    rows: Sequence[FeatureRow],
    *,
    for_model: str,
) -> ExperimentEvaluationResult:
    x, y = to_dense_matrix(rows, for_model=for_model)
    y_pred = model.predict_proba(x)[:, 1].tolist()
    return score_predictions(y, y_pred, rows)


def bootstrap_log_loss_difference(
    reference_rows: Sequence[FeatureRow],
    reference_pred: Sequence[float],
    challenger_rows: Sequence[FeatureRow],
    challenger_pred: Sequence[float],
    *,
    n_bootstrap: int = 2000,
    random_state: int = 42,
) -> tuple[float, float, float]:
    """Student-level bootstrap CI for (challenger log loss - reference log loss) on the same rows.

    `reference_rows`/`challenger_rows` must be row-aligned (same attempts,
    same order) — only the predictions differ per model. Resampling is done
    by student (with replacement), not by row, since rows from the same
    student are correlated (shared history) and row-level resampling would
    understate the true sampling variance. Returns
    (point_estimate, ci_low, ci_high) for a 95% percentile interval;
    negative values mean the challenger has lower (better) log loss.
    """
    if len(reference_rows) != len(challenger_rows):
        raise ValueError("reference_rows and challenger_rows must be row-aligned")

    students = sorted({row.student_id for row in reference_rows})
    rows_by_student: dict[int, list[int]] = {sid: [] for sid in students}
    for idx, row in enumerate(reference_rows):
        rows_by_student[row.student_id].append(idx)

    y_true = [1 if row.correct else 0 for row in reference_rows]
    ref_pred = [min(1.0 - 1e-9, max(1e-9, p)) for p in reference_pred]
    chal_pred = [min(1.0 - 1e-9, max(1e-9, p)) for p in challenger_pred]

    def _log_loss_for(indices: list[int], pred: list[float]) -> float:
        total = 0.0
        for idx in indices:
            y, p = y_true[idx], pred[idx]
            total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        return total / len(indices)

    all_indices = list(range(len(reference_rows)))
    point_estimate = _log_loss_for(all_indices, chal_pred) - _log_loss_for(all_indices, ref_pred)

    rng = random.Random(random_state)
    diffs: list[float] = []
    for _ in range(n_bootstrap):
        sampled_students = rng.choices(students, k=len(students))
        indices = [idx for sid in sampled_students for idx in rows_by_student[sid]]
        diffs.append(_log_loss_for(indices, chal_pred) - _log_loss_for(indices, ref_pred))

    diffs.sort()
    ci_low = diffs[int(0.025 * n_bootstrap)]
    ci_high = diffs[min(n_bootstrap - 1, int(0.975 * n_bootstrap))]
    return point_estimate, ci_low, ci_high


__all__ = [
    "DEFAULT_EM_ITERATION_CANDIDATES",
    "GBM_CANDIDATES",
    "LR_C_CANDIDATES",
    "ExperimentEvaluationResult",
    "M2SelectionResult",
    "TrainFitValTestSplit",
    "bootstrap_log_loss_difference",
    "evaluate_m2_bkt_rowwise",
    "evaluate_sklearn_model",
    "select_and_fit_bkt",
    "select_and_fit_gbm",
    "select_and_fit_logistic_regression",
    "score_predictions",
    "split_train_fit_val_test",
    "subset_attempts",
]
