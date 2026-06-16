"""
PayGuard AI — FastAPI Application Entry Point
=============================================
Wires together all route groups, middleware, and startup hooks.

Routes
------
  POST /check                     — Submit payment destination for analysis
  GET  /check/{txn_id}/status     — SSE stream for real-time agent progress
  POST /check/{txn_id}/hitl       — Submit human response to a HITL question
  GET  /report/{txn_id}           — Shareable read-only verdict report
  GET  /history                   — User's check history

Implemented in: Phase 5
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import check, history, report

logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan hook — runs startup and shutdown logic.

    Startup:
    - Initialise SQLite database (creates table if needed).
    """
    # Startup
    try:
        from data.db import init_db
        await init_db()
        logger.info("PayGuard AI: database initialised successfully")
    except Exception as exc:
        logger.error("PayGuard AI: database init failed: %s", exc)
        # Non-fatal — in-memory state still works without persistence

    yield

    # Shutdown (no-op for now)
    logger.info("PayGuard AI: shutting down")


# ─── Application ──────────────────────────────────────────────────────────────


app = FastAPI(
    title="PayGuard AI",
    description=(
        "Pre-payment fraud intelligence for Indian UPI payments. "
        "Analyses UPI IDs, URLs, and QR codes before you pay. "
        "4-agent sequential pipeline coordinated through Band."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─── Middleware ───────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routes ───────────────────────────────────────────────────────────────────

app.include_router(check.router,   prefix="/check",   tags=["check"])
app.include_router(report.router,  prefix="/report",  tags=["report"])
app.include_router(history.router, prefix="/history", tags=["history"])


# ─── Health check ─────────────────────────────────────────────────────────────


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Liveness probe — confirms the API server is running."""
    return {"status": "ok", "service": "payguard-ai", "version": "1.0.0"}
