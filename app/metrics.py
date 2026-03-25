"""Forecast accuracy metrics (GluonTS-style WQL / MASE / sMAPE)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def mase(y_true: np.ndarray, y_pred: np.ndarray, y_train: np.ndarray) -> float:
    """Mean Absolute Scaled Error vs naive one-step (last-value) forecast on training scale."""
    y_train = np.asarray(y_train, dtype=float)
    if len(y_train) < 2:
        return float("nan")
    naive_mae = np.mean(np.abs(np.diff(y_train)))
    if naive_mae < 1e-12:
        return float("nan")
    return float(np.mean(np.abs(y_true - y_pred)) / naive_mae)


def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Symmetric MAPE in [0, 200] scale (percentage points if *100)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = (np.abs(y_true) + np.abs(y_pred)).clip(min=1e-12)
    return float(200.0 * np.mean(np.abs(y_pred - y_true) / denom))


def pinball_loss(y: float, q_hat: float, q: float) -> float:
    e = y - q_hat
    return float(max(q * e, (q - 1.0) * e))


def weighted_quantile_loss(
    y_true: np.ndarray,
    quantile_preds: dict[float, np.ndarray],
    quantile_levels: list[float],
) -> float:
    """
    Average pinball loss across quantiles and time steps (unweighted mean over q and t).
    """
    losses = []
    for q in quantile_levels:
        qh = quantile_preds[q]
        for t in range(len(y_true)):
            losses.append(pinball_loss(float(y_true[t]), float(qh[t]), q))
    return float(np.mean(losses)) if losses else float("nan")


def summarize_backtest(
    actuals: np.ndarray,
    p50: np.ndarray,
    quantiles: dict[float, np.ndarray],
    train_for_mase: np.ndarray,
    q_levels: list[float],
) -> dict:
    return {
        "mase": mase(actuals, p50, train_for_mase),
        "smape": smape(actuals, p50),
        "wql": weighted_quantile_loss(actuals, quantiles, q_levels),
        "mae": float(np.mean(np.abs(actuals - p50))),
        "n": int(len(actuals)),
    }
