"""Chronos-Bolt zero-shot forecasting (no ARIMA)."""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

import numpy as np
import pandas as pd
import torch

from app.metrics import summarize_backtest

logger = logging.getLogger(__name__)

_pipeline: Optional[Any] = None
_pipeline_id: Optional[str] = None


def get_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_pipeline(model_id: str = "amazon/chronos-bolt-base") -> Any:
    """Lazy-load Chronos-Bolt (singleton per model_id)."""
    global _pipeline, _pipeline_id
    if _pipeline is not None and _pipeline_id == model_id:
        return _pipeline
    from chronos import ChronosBoltPipeline

    logger.info("Loading Chronos-Bolt: %s", model_id)
    pipe = ChronosBoltPipeline.from_pretrained(model_id)
    _pipeline = pipe
    _pipeline_id = model_id
    return pipe


def _tensor_context(y: np.ndarray) -> torch.Tensor:
    x = torch.tensor(y, dtype=torch.float32)
    if torch.isnan(x).any():
        x = torch.tensor(
            pd.Series(x.numpy()).interpolate(limit_direction="both").ffill().bfill().values,
            dtype=torch.float32,
        )
    return x


def forecast_direct(
    y: np.ndarray,
    pipeline: Any,
    test_horizon: int,
    quantile_levels: list[float],
) -> dict[str, Any]:
    """One-shot multi-step forecast: train = y[:-h], predict h steps."""
    if len(y) <= test_horizon:
        raise ValueError("Series too short for direct evaluation.")
    train = y[:-test_horizon]
    test = y[-test_horizon:]
    ctx = _tensor_context(train)
    q_t, mean_t = pipeline.predict_quantiles(
        ctx,
        prediction_length=test_horizon,
        quantile_levels=quantile_levels,
        limit_prediction_length=False,
    )
    # (1, h, nq)
    q_np = q_t[0].cpu().numpy()
    p50_idx = quantile_levels.index(0.5)
    p50 = q_np[:, p50_idx]
    qmap = {q: q_np[:, i] for i, q in enumerate(quantile_levels)}
    metrics = summarize_backtest(
        test, p50, qmap, train_for_mase=train, q_levels=quantile_levels
    )
    rows = []
    for i in range(test_horizon):
        rows.append(
            {
                "step": i + 1,
                "actual": float(test[i]),
                "p50": float(p50[i]),
                **{f"p{int(q*100)}": float(qmap[q][i]) for q in quantile_levels},
            }
        )
    return {"mode": "direct", "metrics": metrics, "forecasts": rows}


def forecast_rolling(
    y: np.ndarray,
    timestamps: np.ndarray,
    pipeline: Any,
    num_val_windows: int,
    quantile_levels: list[float],
) -> dict[str, Any]:
    """
    Expanding window: for each of the last `num_val_windows` points, use history
    [:t] and forecast one step ahead.
    """
    n = len(y)
    if n <= num_val_windows + 1:
        raise ValueError(
            f"Need more than {num_val_windows + 1} observations for rolling evaluation."
        )
    start = n - num_val_windows
    train_for_mase = y[:start]
    preds: list[dict[str, Any]] = []
    actuals: list[float] = []
    q_store: dict[float, list[float]] = {q: [] for q in quantile_levels}

    for t in range(start, n):
        ctx = _tensor_context(y[:t])
        q_t, _ = pipeline.predict_quantiles(
            ctx,
            prediction_length=1,
            quantile_levels=quantile_levels,
        )
        q_np = q_t[0, 0].cpu().numpy()
        actual = float(y[t])
        actuals.append(actual)
        row: dict[str, Any] = {"timestamp": str(timestamps[t]), "actual": actual}
        for i, q in enumerate(quantile_levels):
            qv = float(q_np[i])
            q_store[q].append(qv)
            row[f"p{int(q * 100)}"] = qv
        preds.append(row)

    actuals_arr = np.array(actuals)
    if 0.5 not in quantile_levels:
        raise ValueError("quantile_levels must include 0.5 for point metrics.")
    p50_arr = np.array(q_store[0.5])
    q_arr = {q: np.array(q_store[q]) for q in quantile_levels}
    metrics = summarize_backtest(
        actuals_arr, p50_arr, q_arr, train_for_mase=train_for_mase, q_levels=quantile_levels
    )
    return {"mode": "rolling", "metrics": metrics, "forecasts": preds}


def run_chronos_on_prepared(
    long_df: pd.DataFrame,
    model_id: str,
    eval_mode: Literal["rolling", "direct"],
    rolling_windows: int,
    direct_horizon: int,
    quantile_levels: Optional[list[float]] = None,
) -> dict[str, Any]:
    """
    `long_df` has columns item_id, timestamp, target.
    """
    ql = quantile_levels or [0.1, 0.5, 0.9]
    pipeline = load_pipeline(model_id)
    items = long_df["item_id"].unique()
    results_per_item = []
    for item in items:
        sub = long_df[long_df["item_id"] == item].sort_values("timestamp")
        y = sub["target"].astype(float).values
        ts = sub["timestamp"].values
        if eval_mode == "direct":
            out = forecast_direct(y, pipeline, direct_horizon, ql)
        else:
            out = forecast_rolling(y, ts, pipeline, rolling_windows, ql)
        out["item_id"] = item
        results_per_item.append(out)

    # Aggregate metrics if multiple items (mean across items)
    if len(results_per_item) == 1:
        return {"items": results_per_item, "aggregate": results_per_item[0]["metrics"]}
    agg = {
        "mase": float(np.nanmean([r["metrics"]["mase"] for r in results_per_item])),
        "smape": float(np.nanmean([r["metrics"]["smape"] for r in results_per_item])),
        "wql": float(np.nanmean([r["metrics"]["wql"] for r in results_per_item])),
        "mae": float(np.nanmean([r["metrics"]["mae"] for r in results_per_item])),
        "n": int(sum(r["metrics"]["n"] for r in results_per_item)),
    }
    return {"items": results_per_item, "aggregate": agg}
