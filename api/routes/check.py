"""
Route: /check
=============
POST /check        — Submit a payment destination for agent pipeline analysis.
GET  /check/{txn_id}/status — SSE stream for real-time agent progress.
POST /check/{txn_id}/hitl  — Submit human response to a HITL clarification.

Implemented in: Phase 5
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# TODO (Phase 5): Implement POST /check (multipart: JSON fields + optional QR image)
# TODO (Phase 5): Implement GET  /{txn_id}/status (SSE via sse-starlette)
# TODO (Phase 5): Implement POST /{txn_id}/hitl (publish human_response to Band)
