"""
Route: /report
==============
GET /report/{txn_id} — Shareable, read-only verdict report.

Returns the full Agent 4 verdict, all three agent narratives, price
intelligence, and the Band room reference for a completed transaction.

Designed to be shared with:
  - Police complaints
  - cybercrime.gov.in reports
  - Friends / family to warn about a scammer

Data sources (in priority order)
---------------------------------
1. In-memory pipeline registry — covers active + recently completed checks.
2. SQLite via api.database (CheckRecord ORM) — covers all persisted checks.

Implemented in: Phase 6
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from api.database import get_check_record
from api.models import CheckResponse
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
    - All three agent narratives
    - Price intelligence (if product description was provided)
    - Band room reference (for audit purposes)
    - Avoided fraud estimate (for DANGER verdicts)

    Parameters
    ----------
    txn_id: The transaction ID returned by POST /check.

    Returns
    -------
    CheckResponse JSON with full report data.

    Raises
    ------
    202: Analysis is still in progress.
    404: Transaction not found in memory or database.
    500: Pipeline error or database failure.
    """
    # ── 1. Check in-memory pipeline registry ──────────────────────────────────
    state = get_state(txn_id)
    if state is not None:
        status = state.get("status")

        if status == STATUS_COMPLETE:
            result = state.get("result")
            if result is not None:
                logger.info("GET /report/%s: served from in-memory registry", txn_id)
                return JSONResponse(
                    status_code=200,
                    content=result.model_dump(),
                )

        elif status in (
            "running", "agent_1_running", "agent_2_running",
            "agent_3_running", "agent_4_running", "hitl_waiting",
        ):
            return JSONResponse(
                status_code=202,
                content={
                    "txn_id":  txn_id,
                    "status":  status,
                    "message": (
                        "Analysis is still in progress. "
                        f"Open GET /api/check/{txn_id}/stream for real-time updates."
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

    # ── 2. Fall back to SQLite ORM ────────────────────────────────────────────
    try:
        record = await get_check_record(txn_id)
    except Exception as db_exc:
        logger.error("GET /report/%s: DB query failed: %s", txn_id, db_exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve transaction from database.",
        )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Report for transaction '{txn_id}' not found. "
                "The transaction may still be running — check /api/check/{txn_id}/status."
            ),
        )

    if record.status in ("running", "agent_1_running", "agent_2_running",
                          "agent_3_running", "agent_4_running", "hitl_waiting"):
        return JSONResponse(
            status_code=202,
            content={
                "txn_id":  txn_id,
                "status":  record.status,
                "message": "Analysis is still in progress.",
            },
        )

    if record.status == "error":
        raise HTTPException(
            status_code=500,
            detail=f"Transaction '{txn_id}' failed: {record.plain_english_summary or 'Unknown error'}",
        )

    # Prefer the denormalised result_json fast-path
    if record.result_json:
        try:
            result_dict = json.loads(record.result_json)
            logger.info("GET /report/%s: served from DB (result_json)", txn_id)
            return JSONResponse(status_code=200, content=result_dict)
        except json.JSONDecodeError:
            logger.warning("GET /report/%s: result_json parse failed; rebuilding", txn_id)

    # Rebuild CheckResponse from individual columns if result_json is missing / corrupt
    if record.verdict is None:
        raise HTTPException(
            status_code=404,
            detail=f"Report for '{txn_id}' is not yet available — verdict not finalised.",
        )

    result_dict = {
        "txn_id":                txn_id,
        "band_room_id":          record.band_room_id or "",
        "verdict":               record.verdict,
        "risk_score":            record.risk_score or 0,
        "plain_english_summary": record.plain_english_summary or "",
        "recommended_actions":   record.recommended_actions or [],
        "ask_merchant":          record.ask_merchant or [],
        "agent_narratives": {
            "destination_intelligence": record.agent1_narrative or "",
            "qr_upi_validator":         record.agent2_narrative or "",
            "web_intelligence":         record.agent3_narrative or "",
            "verdict_synthesis":        record.plain_english_summary or "",
        },
        "price_intelligence":       record.price_intelligence,
        "avoided_fraud_estimate":   record.avoided_fraud_estimate,
        "report_url":               f"/api/report/{txn_id}",
    }

    logger.info("GET /report/%s: rebuilt from DB columns", txn_id)
    return JSONResponse(status_code=200, content=result_dict)
