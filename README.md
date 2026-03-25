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

## Split deploy: Vercel (UI) + API host

PyTorch + Chronos are **too large** for typical Vercel serverless functions. Deploy:

1. **API**: use the [Dockerfile](Dockerfile) on **Render**, **Fly.io**, **Google Cloud Run**, **Railway** (API-only), etc. Set `CORS_ORIGINS` to your Vercel URL (comma-separated if multiple). Example: `CORS_ORIGINS=https://your-app.vercel.app`

2. **UI**: in the Vercel dashboard, set the project **root directory** to `web` (or deploy the `web` folder as a static site). Before build, set `web/config.js` to point at your API, e.g.:

   ```js
   window.API_BASE = "https://your-api.onrender.com";
   ```

   (No trailing slash.) You can automate this with a Vercel build step that writes `config.js` from an environment variable.

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
