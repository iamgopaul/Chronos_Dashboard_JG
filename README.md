# Chronos dashboard (Chronos-only)

Web UI to upload a CSV and run **Amazon Chronos-Bolt** zero-shot forecasts with probabilistic outputs (P10 / P50 / P90) and metrics (MASE, sMAPE, WQL). **No ARIMA** — use a separate workflow for econometrics.

## Requirements

- **Python 3.10+** (3.11 recommended; matches the Docker image)
- First run downloads `amazon/chronos-bolt-base` from Hugging Face (~hundreds of MB)

## Local run

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

## Railway

1. Create a new project and deploy from this directory (Dockerfile is detected automatically).
2. Railway sets `PORT`; the container listens on `$PORT`.
3. Allocate enough **RAM** (Chronos-Bolt + PyTorch: plan for **≥ 4 GB**; CPU inference is slower but fine for moderate CSV sizes).
4. Optional: set `HF_TOKEN` in Railway variables if you use a private or gated Hugging Face model.

## CSV format

- **Time column**: parseable dates (e.g. `datadate`, `ds`).
- **Target column**: numeric series (e.g. ROA).
- **Optional `item_id` column**: for panels, one forecast block per ID.

Use **Rolling** mode for expanding-window one-step backtests (as in the Chronos protocol doc), or **Direct** for a single multi-step forecast over the last `h` observations.
