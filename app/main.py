"""Chronos-only dashboard API."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.data_prep import prepare_series, read_csv_bytes
from app.chronos_service import run_chronos_on_prepared

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chronos Dashboard", version="0.1.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    with open("app/templates/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.post("/api/preview")
async def preview(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        df = read_csv_bytes(raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}") from e
    return {
        "columns": list(df.columns),
        "rows": int(len(df)),
        "sample": df.head(8).to_dict(orient="records"),
    }


@app.post("/api/forecast")
async def forecast(
    file: UploadFile = File(...),
    time_col: str = Form(...),
    target_col: str = Form(...),
    id_col: str = Form(""),
    freq: str = Form(""),
    model_id: str = Form("amazon/chronos-bolt-base"),
    eval_mode: Literal["rolling", "direct"] = Form("rolling"),
    rolling_windows: int = Form(8),
    direct_horizon: int = Form(8),
    winsorize: bool = Form(False),
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
            eval_mode=eval_mode,
            rolling_windows=max(1, rolling_windows),
            direct_horizon=max(1, direct_horizon),
            quantile_levels=[0.1, 0.5, 0.9],
        )
    except Exception as e:
        logger.exception("Forecast failed")
        raise HTTPException(500, f"Forecast failed: {e}") from e

    return {
        "model_id": model_id,
        "eval_mode": eval_mode,
        "series_count": int(long_df["item_id"].nunique()),
        "observations": int(len(long_df)),
        **out,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
