FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── Dependencies ───────────────────────────────────────────────────────────────
FROM base AS deps

COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install ".[dev]"

# ── Production image ───────────────────────────────────────────────────────────
FROM base AS prod

COPY pyproject.toml .
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# ── Reaper entrypoint (used by K8s CronJob) ────────────────────────────────────
FROM prod AS reaper

CMD ["python", "-m", "app.reaper_job"]
