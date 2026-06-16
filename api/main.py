"""
PayGuard AI — FastAPI Application Entry Point
=============================================
Wires together all route groups and middleware.

Routes
------
  POST /check                     — Submit payment destination for analysis
  GET  /check/{txn_id}/status     — SSE stream for real-time agent progress
  POST /check/{txn_id}/hitl       — Submit human response to a HITL question
  GET  /report/{txn_id}           — Shareable read-only verdict report
  GET  /history                   — User's check history
  GET  /scam-patterns             — Browsable scam pattern library

Implemented in: Phase 5
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# TODO (Phase 5): Import and register all route modules.
# from api.routes import check, report, history

app = FastAPI(
    title="PayGuard AI",
    description=(
        "Pre-payment fraud intelligence for Indian UPI payments. "
        "Analyses UPI IDs, URLs, and QR codes before you pay."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health_check() -> dict:
    """Liveness probe — confirms the API server is running."""
    return {"status": "ok", "service": "payguard-ai"}


# TODO (Phase 5): app.include_router(check.router, prefix="/check", tags=["check"])
# TODO (Phase 5): app.include_router(report.router, prefix="/report", tags=["report"])
# TODO (Phase 5): app.include_router(history.router, prefix="/history", tags=["history"])
