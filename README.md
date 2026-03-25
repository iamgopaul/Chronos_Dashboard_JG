# Chronos dashboard (Chronos-only)

Web UI to upload a CSV and run **Amazon Chronos-Bolt** zero-shot forecasts (P10 / P50 / P90) with **Plotly charts**, **filters** (date range, series IDs, categories), and **backtest vs full-context forecast** modes. **No ARIMA** and no fine-tuning—Chronos uses pretrained weights only.

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
