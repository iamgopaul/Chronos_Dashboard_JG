# Chronos-Bolt dashboard — CPU inference (add GPU base image if you self-host with CUDA)
FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt .
ENV PIP_NO_CACHE_DIR=1
RUN pip install --no-cache-dir -r requirements.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple

COPY app ./app
COPY web ./web

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
