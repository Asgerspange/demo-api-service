# syntax=docker/dockerfile:1
# Root wrapper around api/Dockerfile so platforms that expect a Dockerfile at the repo root
# (e.g. Coolify's default build pack) can build this image with zero extra config. Build
# context is the repo root; everything below mirrors api/Dockerfile with paths prefixed `api/`.
#
#   API    →  target `runtime`         → uvicorn app.main:app (default CMD)
#   Worker →  target `runtime-worker`  → arq app.worker.WorkerSettings
#
# Coolify's Dockerfile build pack always runs the built image's own CMD — it has no notion
# of a per-app "start command" override for this build pack (that field only applies to the
# nixpacks build pack). So the worker gets its own build TARGET instead, selected via each
# Coolify app's "Docker Build Stage Target" (dockerfile_target_build) rather than a runtime flag.
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

# --- build stage: resolve + install deps into a venv (cached on lockfile) ---
FROM base AS build
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY api/app ./app
RUN uv sync --frozen --no-dev

# --- runtime stage: slim, just the venv + code ---
FROM base AS runtime
ENV PATH="/app/.venv/bin:$PATH"
# libarchive-tools provides `bsdtar` — extracts RAR4/5 + 7z multi-demo archives from HLTV
# (BSD-licensed, replacing the non-free unrar). Stage 18 §18.1.
RUN apt-get update && apt-get install -y --no-install-recommends libarchive-tools \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/.venv /app/.venv
COPY api/app ./app
COPY api/scripts ./scripts
COPY api/migrations ./migrations
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --- worker: identical image, arq instead of uvicorn as the running process ---
FROM runtime AS runtime-worker
CMD ["arq", "app.worker.WorkerSettings"]
