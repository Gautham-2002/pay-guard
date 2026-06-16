"""
Route: /report
==============
GET /report/{txn_id} — Shareable, read-only verdict report.

Returns the full Agent 4 verdict, all three agent narratives, and the Band
room reference for a completed transaction.

This URL is designed to be shared with:
  - Police complaints
  - cybercrime.gov.in reports
  - Friends / family to warn about a scammer

Implemented in: Phase 5
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.models import CheckResponse
from data.db import get_transaction_result
from services.pipeline import STATUS_COMPLETE, get_state

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/{txn_id}",
    response_model=CheckResponse,
    summary="Get shareable verdict report for a transaction",
    response_description="Full agent narratives and final verdict",
)
async def get_report(txn_id: str) -> JSONResponse:
    """
    Retrieve the complete fraud analysis report for a completed transaction.

    The report includes:
    - Final verdict (SAFE / VERIFY / DANGER) and risk score
    - Plain-English summary and recommended actions
    - All four agent narratives
    - Price intelligence (if product description was provided)
    - Band room reference (for audit purposes)

    This endpoint first checks the in-memory pipeline state (for recently
    completed transactions) and falls back to SQLite for older transactions.

    Parameters
    ----------
    txn_id: The transaction ID returned by POST /check.

    Returns
    -------
    CheckResponse JSON with full report data.

    Raises
    ------
    404: If the transaction is not found or not yet complete.
    202: If the transaction is still running (not yet complete).
    """
    # ── Check in-memory state first (covers active + recently completed) ───────
    state = get_state(txn_id)
    if state is not None:
        status = state.get("status")
        if status == STATUS_COMPLETE:
            result = state.get("result")
            if result is not None:
                return JSONResponse(
                    status_code=200,
                    content=result.model_dump(),
                )
        elif status in ("agent_1_running", "agent_2_running", "agent_3_running",
                        "agent_4_running", "hitl_waiting"):
            return JSONResponse(
                status_code=202,
                content={
                    "txn_id": txn_id,
                    "status": status,
                    "message": (
                        "Analysis is still in progress. "
                        f"Poll GET /check/{txn_id}/status for real-time updates."
                    ),
                },
            )
        elif status == "error":
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Transaction '{txn_id}' encountered an error: "
                    f"{state.get('error', 'Unknown error')}"
                ),
            )

    # ── Fall back to SQLite (completed transactions from previous sessions) ─────
    try:
        result_dict = await get_transaction_result(txn_id)
    except Exception as db_exc:
        logger.error("GET /report/%s: DB query failed: %s", txn_id, db_exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve transaction from database.",
        )

    if result_dict is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Report for transaction '{txn_id}' not found. "
                "The transaction may still be running — check /check/{txn_id}/status."
            ),
        )

    logger.info("GET /report/%s: served from DB", txn_id)
    return JSONResponse(status_code=200, content=result_dict)
