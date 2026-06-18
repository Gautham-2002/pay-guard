"""
PayGuard AI — FastAPI Application Entry Point
=============================================
Wires together all route groups, middleware, database lifecycle, and startup hooks.

Route map (all under /api prefix)
----------------------------------
  POST   /api/check                        — Submit payment destination for analysis
  GET    /api/check/{txn_id}/status        — SSE: pipeline status-change stream
  GET    /api/check/{txn_id}/stream        — SSE: Band-room agent-update stream
  POST   /api/check/{txn_id}/respond       — Submit HITL human response (canonical)
  POST   /api/check/{txn_id}/hitl          — Submit HITL human response (deprecated alias)
  GET    /api/report/{txn_id}              — Shareable read-only verdict report
  GET    /api/history                      — User's check history + aggregate stats

System routes (no prefix)
--------------------------
  GET    /health                           — Liveness probe
  GET    /docs                             — Swagger UI
  GET    /redoc                            — ReDoc UI

Implemented in: Phase 6
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.rate_limiter import RateLimitMiddleware
from api.routes import check, history, report

logger = logging.getLogger(__name__)


# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Startup
    -------
    - Initialise SQLite via SQLAlchemy async engine (creates ``checks`` table).

    Shutdown
    --------
    - Dispose the async engine (closes all DB connections gracefully).
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    try:
        from api.database import init_db
        await init_db()
        logger.info("PayGuard AI: database initialised")
    except Exception as exc:
        logger.error("PayGuard AI: database init failed — %s", exc)
        # Non-fatal: server will still start; individual requests will fail

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    try:
        from api.database import close_db
        await close_db()
        logger.info("PayGuard AI: database engine disposed")
    except Exception as exc:
        logger.warning("PayGuard AI: database shutdown warning — %s", exc)

    logger.info("PayGuard AI: shutdown complete")


# ─── Application ──────────────────────────────────────────────────────────────


app = FastAPI(
    title="PayGuard AI",
    description=(
        "Pre-payment fraud intelligence for Indian UPI payments.\n\n"
        "Analyses UPI IDs, URLs, and QR codes before you pay using a "
        "4-agent sequential pipeline coordinated through Band rooms.\n\n"
        "**Agents:**\n"
        "1. Destination Intelligence (Featherless AI / Llama 3.3 70B)\n"
        "2. QR Decode & UPI Validator (AIML API / GPT-4o vision)\n"
        "3. Web Intelligence (Playwright + DDG + Reddit + AIML API)\n"
        "4. Verdict Synthesis (AIML API / Claude 3.5 Sonnet)\n\n"
        "**Verdict:** 🟢 SAFE | 🟡 VERIFY | 🔴 DANGER"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ─── Middleware ───────────────────────────────────────────────────────────────
# Middleware is applied in reverse-registration order (last added = outermost).
# We register CORS last so it wraps RateLimitMiddleware, ensuring 429 responses
# still carry the correct Access-Control-Allow-Origin header for browser clients.


# 1. Rate limiting (innermost — checked first on every POST /api/check)
app.add_middleware(RateLimitMiddleware)

# 2. CORS (outermost — adds headers to every response including 429s)
_cors_origins = [
    "http://localhost:5173",    # Vite dev server (default)
    "http://localhost:3000",    # Create React App / Next.js
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
_cors_origins.extend(
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Routes ───────────────────────────────────────────────────────────────────


app.include_router(check.router,   prefix="/api/check",   tags=["check"])
app.include_router(report.router,  prefix="/api/report",  tags=["report"])
app.include_router(history.router, prefix="/api/history", tags=["history"])


# ─── System endpoints ─────────────────────────────────────────────────────────


@app.get("/health", tags=["system"], summary="Liveness probe")
async def health_check() -> dict:
    """Liveness probe — confirms the API server is running."""
    return {
        "status":  "ok",
        "service": "payguard-ai",
        "version": "1.0.0",
    }


# ─── Frontend (production) ────────────────────────────────────────────────────
# When frontend/dist exists (Docker / Render all-in-one), serve the React SPA.
# Registered last so /api, /health, and /docs keep precedence.


def _mount_frontend(application: FastAPI) -> None:
    static_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if not static_dir.is_dir():
        logger.info("Frontend dist not found at %s — API-only mode", static_dir)
        return

    application.mount(
        "/",
        StaticFiles(directory=static_dir, html=True),
        name="frontend",
    )
    logger.info("Serving frontend from %s", static_dir)


_mount_frontend(app)
