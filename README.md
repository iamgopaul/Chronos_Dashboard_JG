# Chronos dashboard (Chronos-only)

Web UI to upload a CSV and run **Amazon Chronos-Bolt** zero-shot forecasts (P10 / P50 / P90) with **Plotly charts**, **filters** (date range, series IDs, categories), and **backtest vs full-context forecast** modes. **No ARIMA** and no fine-tuning—Chronos uses pretrained weights only.

## Alignment with the WRDS / research protocol (your docx sequence)

This app implements the **Chronos “Forecasting Tournament”** slice described across *Data Download*, *Data Preparation*, *ARIMA Analysis*, *Chronos Analysis*, and *Arima-Chronos Proposal*:

| Protocol element | In this dashboard |
|------------------|-------------------|
| WRDS `fundq`-style panel | CSV with **`datadate`**, **`gvkey`**, ROA/ROE (or other numeric target); Preview suggests `datadate` + `gvkey` + **ROA** + **`QE`** |
| Zero-shot Chronos-Bolt Base | Default model id **`amazon/chronos-bolt-base`**; no fine-tuning |
| Probabilistic outputs | Quantiles **P10, P50, P90**; charts show the fan |
| Error metrics | **MASE**, **sMAPE**, **WQL** (see API / metrics block) |
| Rolling one-step vs holdout | Mode **Backtest: rolling one-step**; use **N = 8** for eight quarterly one-step errors at the end of each series (proposal-style when your panel ends in 2024) |
| Winsorization | Optional **1% / 99%** on the target after filters (SPSS may winsorize cross-sectionally first; both are consistent with the write-up) |
| Quarterly regularity | Set **Pandas frequency** to **`QE`** so timestamps align to calendar quarters |

**Not in this repo (run in R/Python/SPSS per your other docs):** Filter-Then-Test NLI (BDS on ARIMA residuals), Bai–Perron / `ruptures`, Auto-ARIMA benchmark, Tsay test, SPSS gap logic, merged ARIMA vs Chronos regression. Export a cleaned long CSV from that pipeline and use this UI for Chronos metrics and figures.

**Date filters:** Narrowing Configuration to 2023–2024 **only** drops pre-2023 history and breaks the expanding-window logic in the proposal. For Chronos, keep the **full** time span (or leave dates empty after Preview), then use rolling **N** = 8 so the last eight one-step forecasts line up with recent quarters. Use **Research protocol → Proposal preset** in the UI to clear date bounds and set rolling N = 8.

## Requirements

- **Python 3.10+** (3.11 recommended)
- First API run downloads `amazon/chronos-bolt-base` from Hugging Face

## Local run (UI + API together)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. The UI is served from `web/`; `window.API_BASE` in `web/config.js` defaults to `""` (same origin).

## Deploy on Railway

Use Railway for the full app (FastAPI + UI together via this repo).

1. Create a Railway service from this repository (Dockerfile is included).
2. Set memory to **at least 4 GB RAM** for PyTorch + Chronos-Bolt on CPU (more for large panel datasets).
3. Railway provides `PORT` automatically; the container already binds to `${PORT}`.
4. Optional: set `HF_TOKEN` if you use gated/private Hugging Face models.

### Optional split deployment (still possible)

If you later want to host the static UI elsewhere, keep `web/config.js` and set:

```js
window.API_BASE = "https://your-railway-api-url";
```

(No trailing slash.)

## Configuration options (UI)

- **Date range**, **series ID allowlist**, **category column + values** (subset rows before building series).
- **Run mode**: rolling one-step backtest, direct multi-step backtest, or **full-context forecast** (no holdout; accuracy metrics are not applicable—see API response `note`).
- **Frequency** (e.g. `QE`): recommended so forecast dates on charts are calendar-aligned.

## CSV format

- **Time** and **target** columns required; optional **series ID** for panels.

## Endpoints

- `POST /api/preview` — columns + sample rows  
- `POST /api/column-values` — distinct values for a column (for category filters)  
- `POST /api/forecast` — multipart form, same fields as the UI  
- `GET /health`
