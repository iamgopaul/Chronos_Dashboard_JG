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

METRICS_FULL_CONTEXT: dict[str, Any] = {
    "mase": None,
    "smape": None,
    "wql": None,
    "mae": None,
    "n": 0,
    "note": "Full-context forecast only (no holdout). Chronos is zero-shot—not trained on your CSV.",
}


def load_pipeline(model_id: str = "amazon/chronos-bolt-base") -> Any:
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


def _ts_iso(x: Any) -> str:
    return pd.Timestamp(x).isoformat()


def _forecast_time_labels(last_train_ts: Any, horizon: int, freq: Optional[str]) -> list[str]:
    last = pd.Timestamp(last_train_ts)
    if not freq or not str(freq).strip():
        return [f"h{i + 1}" for i in range(horizon)]
    cand = pd.date_range(start=last, periods=horizon + 24, freq=freq)
    future = cand[cand > last][:horizon]
    if len(future) < horizon:
        future = pd.date_range(start=last + pd.Timedelta(seconds=1), periods=horizon, freq=freq)
    return [pd.Timestamp(t).isoformat() for t in future[:horizon]]


def _segment_from_forecasts(
    rows: list[dict[str, Any]], quantile_levels: list[float]
) -> list[dict[str, Any]]:
    seg = []
    for row in rows:
        entry: dict[str, Any] = {
            "t": row.get("timestamp") or row.get("t") or str(row.get("step", "")),
            "actual": row.get("actual"),
        }
        for q in quantile_levels:
            entry[f"p{int(q * 100)}"] = row.get(f"p{int(q * 100)}")
        seg.append(entry)
    return seg


def forecast_direct(
    y: np.ndarray,
    ts: np.ndarray,
    pipeline: Any,
    test_horizon: int,
    quantile_levels: list[float],
    freq: Optional[str],
) -> dict[str, Any]:
    if len(y) <= test_horizon:
        raise ValueError("Series too short for direct evaluation.")
    train = y[:-test_horizon]
    test = y[-test_horizon:]
    last_train = ts[-test_horizon - 1]
    ctx = _tensor_context(train)
    q_t, _mean_t = pipeline.predict_quantiles(
        ctx,
        prediction_length=test_horizon,
        quantile_levels=quantile_levels,
        limit_prediction_length=False,
    )
    q_np = q_t[0].cpu().numpy()
    p50_idx = quantile_levels.index(0.5)
    p50 = q_np[:, p50_idx]
    qmap = {q: q_np[:, i] for i, q in enumerate(quantile_levels)}
    metrics = summarize_backtest(
        test, p50, qmap, train_for_mase=train, q_levels=quantile_levels
    )
    ft_labels = _forecast_time_labels(last_train, test_horizon, freq)
    rows = []
    for i in range(test_horizon):
        rows.append(
            {
                "step": i + 1,
                "timestamp": ft_labels[i] if i < len(ft_labels) else str(i + 1),
                "actual": float(test[i]),
                "p50": float(p50[i]),
                **{f"p{int(q * 100)}": float(qmap[q][i]) for q in quantile_levels},
            }
        )
    chart = {
        "history": {"t": [_ts_iso(x) for x in ts], "y": [float(v) for v in y]},
        "segment": _segment_from_forecasts(rows, quantile_levels),
    }
    return {"mode": "direct", "metrics": metrics, "forecasts": rows, "chart": chart}


def forecast_rolling(
    y: np.ndarray,
    timestamps: np.ndarray,
    pipeline: Any,
    num_val_windows: int,
    quantile_levels: list[float],
) -> dict[str, Any]:
    n = len(y)
    if n <= num_val_windows + 1:
        raise ValueError(
            f"Need more than {num_val_windows + 1} observations for rolling evaluation."
        )
    start = n - num_val_windows
    train_for_mase = y[:start]
    preds: list[dict[str, Any]] = []
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
        row: dict[str, Any] = {"timestamp": _ts_iso(timestamps[t]), "actual": actual}
        for i, q in enumerate(quantile_levels):
            qv = float(q_np[i])
            q_store[q].append(qv)
            row[f"p{int(q * 100)}"] = qv
        preds.append(row)

    actuals_arr = np.array([float(r["actual"]) for r in preds])
    p50_arr = np.array(q_store[0.5])
    q_arr = {q: np.array(q_store[q]) for q in quantile_levels}
    metrics = summarize_backtest(
        actuals_arr, p50_arr, q_arr, train_for_mase=train_for_mase, q_levels=quantile_levels
    )
    chart = {
        "history": {"t": [_ts_iso(x) for x in timestamps], "y": [float(v) for v in y]},
        "segment": _segment_from_forecasts(preds, quantile_levels),
    }
    return {"mode": "rolling", "metrics": metrics, "forecasts": preds, "chart": chart}


def forecast_full_context(
    y: np.ndarray,
    ts: np.ndarray,
    pipeline: Any,
    horizon: int,
    quantile_levels: list[float],
    freq: Optional[str],
) -> dict[str, Any]:
    if len(y) < 2:
        raise ValueError("Series too short for forecasting.")
    ctx = _tensor_context(y)
    q_t, _ = pipeline.predict_quantiles(
        ctx,
        prediction_length=horizon,
        quantile_levels=quantile_levels,
        limit_prediction_length=False,
    )
    q_np = q_t[0].cpu().numpy()
    last_ts = ts[-1]
    ft_labels = _forecast_time_labels(last_ts, horizon, freq)
    rows = []
    for i in range(horizon):
        row = {
            "step": i + 1,
            "timestamp": ft_labels[i] if i < len(ft_labels) else str(i + 1),
            "actual": None,
            "p50": float(q_np[i, quantile_levels.index(0.5)]),
        }
        for j, q in enumerate(quantile_levels):
            row[f"p{int(q * 100)}"] = float(q_np[i, j])
        rows.append(row)
    chart = {
        "history": {"t": [_ts_iso(x) for x in ts], "y": [float(v) for v in y]},
        "segment": _segment_from_forecasts(rows, quantile_levels),
    }
    return {
        "mode": "forecast_only",
        "metrics": dict(METRICS_FULL_CONTEXT),
        "forecasts": rows,
        "chart": chart,
    }


def run_chronos_on_prepared(
    long_df: pd.DataFrame,
    model_id: str,
    run_mode: Literal["rolling", "direct", "forecast_only"],
    rolling_windows: int,
    direct_horizon: int,
    forecast_horizon: int,
    freq: Optional[str] = None,
    quantile_levels: Optional[list[float]] = None,
) -> dict[str, Any]:
    ql = quantile_levels or [0.1, 0.5, 0.9]
    pipeline = load_pipeline(model_id)
    items = long_df["item_id"].unique()
    results_per_item = []
    for item in items:
        sub = long_df[long_df["item_id"] == item].sort_values("timestamp")
        y = sub["target"].astype(float).values
        ts = sub["timestamp"].values
        if run_mode == "direct":
            out = forecast_direct(y, ts, pipeline, direct_horizon, ql, freq=freq)
        elif run_mode == "forecast_only":
            out = forecast_full_context(
                y, ts, pipeline, max(1, forecast_horizon), ql, freq=freq
            )
        else:
            out = forecast_rolling(y, ts, pipeline, rolling_windows, ql)
        out["item_id"] = item
        results_per_item.append(out)

    if len(results_per_item) == 1:
        return {"items": results_per_item, "aggregate": results_per_item[0]["metrics"]}

    def _metric_val(m: dict, key: str) -> Optional[float]:
        v = m.get(key)
        if v is None:
            return None
        return float(v)

    keys = ["mase", "smape", "wql", "mae"]
    agg: dict[str, Any] = {}
    for k in keys:
        vals = [_metric_val(r["metrics"], k) for r in results_per_item]
        vals_f = [v for v in vals if v is not None and not np.isnan(v)]
        agg[k] = float(np.mean(vals_f)) if vals_f else None
    agg["n"] = int(sum(r["metrics"].get("n") or 0 for r in results_per_item))
    return {"items": results_per_item, "aggregate": agg}
