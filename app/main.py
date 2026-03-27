"""Chronos-only dashboard API."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

import pandas as pd

from app.chronos_service import run_chronos_on_prepared
from app.column_suggest import suggest_mapping, time_column_try_order
from app.data_prep import (
    filter_raw_dataframe,
    parse_datetime_column,
    prepare_series,
    read_csv_bytes,
    time_bounds_for_column,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chronos Dashboard", version="0.2.0")

_origins = os.environ.get("CORS_ORIGINS", "*")
_allow = [o.strip() for o in _origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


def _parse_list(s: str) -> list[str]:
    s = (s or "").strip()
    if not s:
        return []
    return [x.strip() for x in s.replace("\n", ",").split(",") if x.strip()]


@app.get("/", response_class=HTMLResponse)
def index():
    p = Path("web/index.html")
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    p2 = Path("app/templates/index.html")
    return HTMLResponse(p2.read_text(encoding="utf-8"))


@app.get("/config.js")
def config_js():
    p = Path("web/config.js")
    if p.exists():
        return FileResponse(p, media_type="application/javascript")
    return HTMLResponse(
        "window.API_BASE = '';", media_type="application/javascript"
    )


@app.post("/api/preview")
async def preview(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        df = read_csv_bytes(raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}") from e
    suggested = suggest_mapping(df)
    time_bounds = None
    for tc in time_column_try_order(df, suggested.get("time_col")):
        time_bounds = time_bounds_for_column(df, tc)
        if time_bounds:
            if tc != suggested.get("time_col"):
                suggested = {**suggested, "time_col": tc}
            break

    return {
        "columns": list(df.columns),
        "rows": int(len(df)),
        "sample": df.head(8).to_dict(orient="records"),
        "suggested": {
            "time_col": suggested["time_col"],
            "target_col": suggested["target_col"],
            "id_col": suggested["id_col"],
            "freq": suggested["freq"],
        },
        "suggested_note": suggested.get("note") or "",
        "time_bounds": time_bounds,
    }


@app.post("/api/time-bounds")
async def time_bounds(
    file: UploadFile = File(...),
    time_col: str = Form(...),
):
    """
    Compute min/max dates (YYYY-MM-DD) from the uploaded CSV for the selected time column.
    Used to auto-fill the UI so the default subset is the full dataset.
    """
    raw = await file.read()
    try:
        df = read_csv_bytes(raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}") from e

    if time_col not in df.columns:
        raise HTTPException(400, f"Missing time column: {time_col}")

    t = parse_datetime_column(df[time_col])
    t = t.dropna()
    if t.empty:
        raise HTTPException(
            400,
            f"Could not parse any valid dates from column: {time_col}. "
            "Pick the calendar date column (e.g. datadate), not fiscal year alone.",
        )

    min_dt = t.min().normalize()
    max_dt = t.max().normalize()
    return {
        "time_col": time_col,
        "min_date": min_dt.strftime("%Y-%m-%d"),
        "max_date": max_dt.strftime("%Y-%m-%d"),
        "n_valid_dates": int(len(t)),
    }


@app.post("/api/column-values")
async def column_values(
    file: UploadFile = File(...),
    column: str = Form(...),
    limit: int = Form(200),
):
    raw = await file.read()
    try:
        df = read_csv_bytes(raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}") from e
    if column not in df.columns:
        raise HTTPException(400, f"Missing column: {column}")
    ser = df[column].dropna().astype(str)
    uniq = ser.unique().tolist()
    uniq.sort(key=lambda x: (len(str(x)), str(x)))
    return {"column": column, "values": uniq[: max(1, min(limit, 2000))], "total_unique": len(uniq)}


@app.post("/api/forecast")
async def forecast(
    file: UploadFile = File(...),
    time_col: str = Form(...),
    target_col: str = Form(...),
    id_col: str = Form(""),
    freq: str = Form(""),
    model_id: str = Form("amazon/chronos-bolt-base"),
    run_mode: Literal["rolling", "direct", "forecast_only"] = Form("rolling"),
    rolling_windows: int = Form(8),
    direct_horizon: int = Form(8),
    forecast_horizon: int = Form(8),
    winsorize: bool = Form(False),
    date_start: str = Form(""),
    date_end: str = Form(""),
    item_ids: str = Form(""),
    category_col: str = Form(""),
    category_values: str = Form(""),
):
    raw = await file.read()
    try:
        df = read_csv_bytes(raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}") from e

    for col in (time_col, target_col):
        if col not in df.columns:
            raise HTTPException(400, f"Missing column: {col}")
    id_col_clean = (id_col or "").strip() or None
    freq_clean = (freq or "").strip() or None
    if id_col_clean and id_col_clean not in df.columns:
        raise HTTPException(400, f"Missing id column: {id_col_clean}")

    cat_col = (category_col or "").strip() or None
    cats = _parse_list(category_values)
    if cat_col and cat_col not in df.columns:
        raise HTTPException(400, f"Missing category column: {cat_col}")

    items_allow = _parse_list(item_ids)
    ds = (date_start or "").strip() or None
    de = (date_end or "").strip() or None

    try:
        df = filter_raw_dataframe(
            df,
            time_col=time_col,
            date_start=ds,
            date_end=de,
            category_col=cat_col,
            category_values=cats or None,
            id_col=id_col_clean,
            item_ids_allowlist=items_allow or None,
        )
    except Exception as e:
        raise HTTPException(400, f"Filter failed: {e}") from e

    wz = (0.01, 0.99) if winsorize else None
    try:
        long_df = prepare_series(
            df,
            time_col=time_col,
            target_col=target_col,
            id_col=id_col_clean,
            freq=freq_clean,
            winsorize_pct=wz,
        )
    except Exception as e:
        raise HTTPException(400, f"Data preparation failed: {e}") from e

    if long_df.empty:
        raise HTTPException(400, "No rows left after cleaning.")

    n_per = long_df.groupby("item_id").size()
    if (n_per < 10).any():
        logger.warning("Some series have fewer than 10 points; Chronos may be unstable.")

    try:
        out = run_chronos_on_prepared(
            long_df,
            model_id=model_id,
            run_mode=run_mode,
            rolling_windows=max(1, rolling_windows),
            direct_horizon=max(1, direct_horizon),
            forecast_horizon=max(1, forecast_horizon),
            freq=freq_clean,
            quantile_levels=[0.1, 0.5, 0.9],
        )
    except Exception as e:
        logger.exception("Forecast failed")
        raise HTTPException(500, f"Forecast failed: {e}") from e

    return {
        "model_id": model_id,
        "run_mode": run_mode,
        "series_count": int(long_df["item_id"].nunique()),
        "observations": int(len(long_df)),
        **out,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if Path("web").exists():
    app.mount("/static", StaticFiles(directory="web"), name="webstatic")
else:
    app.mount("/static", StaticFiles(directory="app/static"), name="legacy_static")
