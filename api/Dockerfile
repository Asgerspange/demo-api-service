# syntax=docker/dockerfile:1
# One image serves both runtimes:
#   API    →  uvicorn app.main:app   (default CMD)
#   Worker →  arq app.worker.WorkerSettings   (command override in compose/k8s)
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

# --- build stage: resolve + install deps into a venv (cached on lockfile) ---
FROM base AS build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN uv sync --frozen --no-dev

# --- runtime stage: slim, just the venv + code ---
FROM base AS runtime
ENV PATH="/app/.venv/bin:$PATH"
# libarchive-tools provides `bsdtar` — extracts RAR4/5 + 7z multi-demo archives from HLTV
# (BSD-licensed, replacing the non-free unrar). Stage 18 §18.1.
RUN apt-get update && apt-get install -y --no-install-recommends libarchive-tools \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/.venv /app/.venv
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
