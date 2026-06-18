# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:22-bookworm-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python runtime (API + Band remote agents) ──────────────────────
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libzbar0 \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml .python-version README.md main.py ./
COPY agents/ agents/
COPY api/ api/
COPY data/ data/
COPY services/ services/
COPY deploy/ deploy/

RUN chmod +x deploy/docker-entrypoint.sh deploy/run-api.sh \
    && uv sync --extra remote-agents --no-dev \
    && uv run playwright install --with-deps chromium

COPY --from=frontend /build/dist frontend/dist

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/payguard.db \
    PAYGUARD_QR_ARTIFACT_DIR=/app/data/artifacts/qr

EXPOSE 8000

ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/app/deploy/supervisord.conf"]
