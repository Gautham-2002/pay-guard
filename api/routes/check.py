"""
Route: /check
=============
POST /check                  — Submit a payment destination for agent pipeline analysis.
GET  /check/{txn_id}/status  — SSE stream for real-time agent pipeline progress.
POST /check/{txn_id}/hitl    — Submit human response to a HITL clarification question.

All three endpoints are implemented in Phase 5 of the PayGuard AI pipeline.

HITL flow
---------
1. POST /check → pipeline starts, returns txn_id immediately.
2. Frontend opens GET /{txn_id}/status SSE stream.
3. If an agent needs clarification, SSE emits status="hitl_waiting" + question.
4. User answers in UI → POST /{txn_id}/hitl → pipeline resumes.
5. SSE continues through agent_4_running → complete.

Implemented in: Phase 5
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from api.models import CheckStatus, SourceType, VerdictLevel
from services.band_client import BandRoom, BandClient
from services.hitl_manager import hitl_manager
from services.pipeline import STATUS_COMPLETE, STATUS_ERROR, get_state, orchestrator

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── POST /check ─────────────────────────────────────────────────────────────


@router.post(
    "",
    summary="Submit payment destination for fraud analysis",
    response_description="Transaction ID and initial status",
    status_code=202,
)
async def submit_check(
    background_tasks: BackgroundTasks,
    # ── Payment destination (at least one required) ──
    payment_url: Optional[str] = Form(
        default=None,
        description="Full URL to analyse (e.g. https://flipkart-sale.in/pay)",
    ),
    upi_id: Optional[str] = Form(
        default=None,
        description="UPI Virtual Payment Address (e.g. merchant@paytm)",
    ),
    # ── Required fields ──────────────────────────────
    amount: float = Form(
        ...,
        gt=0,
        description="INR amount the user is about to pay",
    ),
    source_type: SourceType = Form(
        ...,
        description="How the payment destination was received",
    ),
    # ── Optional enrichment fields ───────────────────
    product_description: Optional[str] = Form(
        default=None,
        description="What the user says they are paying for",
    ),
    additional_context: Optional[str] = Form(
        default="",
        description="Free-text notes from the user",
    ),
    # ── Optional QR image upload ─────────────────────
    qr_image: Optional[UploadFile] = File(
        default=None,
        description="QR code image (PNG / JPEG) — decoded by Agent 2",
    ),
) -> JSONResponse:
    """
    Submit a payment destination for the full 4-agent fraud analysis pipeline.

    At least one of ``payment_url``, ``upi_id``, or ``qr_image`` must be provided.

    The pipeline runs asynchronously in the background.  The caller receives a
    ``txn_id`` immediately and should poll ``GET /{txn_id}/status`` (SSE) for
    real-time progress.
    """
    # ── Validate: at least one destination ────────────────────────────────────
    if not payment_url and not upi_id and not qr_image:
        raise HTTPException(
            status_code=422,
            detail=(
                "At least one of 'payment_url', 'upi_id', or 'qr_image' must be provided."
            ),
        )

    # ── Read QR image bytes ────────────────────────────────────────────────────
    qr_image_bytes: Optional[bytes] = None
    if qr_image is not None:
        try:
            qr_image_bytes = await qr_image.read()
            logger.info(
                "POST /check: received QR image (%d bytes) filename='%s'",
                len(qr_image_bytes),
                qr_image.filename,
            )
        except Exception as exc:
            logger.error("POST /check: failed to read QR image: %s", exc)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to read QR image: {exc}",
            )

    # ── Create transaction ID ──────────────────────────────────────────────────
    txn_id = orchestrator.create_txn_id()
    logger.info(
        "POST /check: new transaction | txn_id=%s | url=%s | upi_id=%s | amount=₹%.2f",
        txn_id, payment_url, upi_id, amount,
    )

    # ── Launch pipeline as background task ─────────────────────────────────────
    background_tasks.add_task(
        orchestrator.run,
        txn_id=txn_id,
        payment_url=payment_url,
        upi_id=upi_id,
        amount=amount,
        product_description=product_description,
        source_type=source_type.value,
        additional_context=additional_context or "",
        qr_image_bytes=qr_image_bytes,
    )

    return JSONResponse(
        status_code=202,
        content={
            "txn_id": txn_id,
            "status": "running",
            "status_url": f"/check/{txn_id}/status",
            "hitl_url": f"/check/{txn_id}/hitl",
            "report_url": f"/report/{txn_id}",
        },
    )


# ─── GET /check/{txn_id}/status (SSE) ─────────────────────────────────────────


@router.get(
    "/{txn_id}/status",
    summary="Stream real-time pipeline status via SSE",
    response_description="Server-Sent Events stream of CheckStatus updates",
)
async def stream_status(txn_id: str) -> EventSourceResponse:
    """
    Stream real-time pipeline status updates for a transaction.

    Emits one ``CheckStatus`` event approximately every 500 ms.
    Closes the stream when status reaches ``complete`` or ``error``.

    Event data fields
    -----------------
    - ``txn_id``       : transaction ID
    - ``status``       : current status string
    - ``current_agent``: agent name (if applicable)
    - ``hitl_question``: pending question (if status == hitl_waiting)
    - ``result``       : full CheckResponse (if status == complete)
    - ``error``        : error message (if status == error)
    """

    async def event_generator():
        # Status → human-readable agent name mapping
        agent_label_map = {
            "agent_1_running": "destination_intelligence",
            "agent_2_running": "qr_upi_validator",
            "agent_3_running": "web_intelligence",
            "agent_4_running": "verdict_synthesis",
        }

        max_wait_seconds = 600  # 10 minutes max pipeline time
        poll_interval = 0.5     # seconds between polls
        elapsed = 0.0
        last_status = None

        while elapsed < max_wait_seconds:
            state = get_state(txn_id)

            if state is None:
                # Transaction not found yet — may not have been created
                if elapsed > 10:
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "txn_id": txn_id,
                            "status": "error",
                            "error": f"Transaction '{txn_id}' not found.",
                        }),
                    }
                    return
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                continue

            status = state.get("status", "unknown")

            # Only emit an event if status has changed (or it's the first emit)
            if status != last_status:
                current_agent = agent_label_map.get(status)
                hitl_question = state.get("hitl_question") if status == "hitl_waiting" else None

                event_data: dict = {
                    "txn_id": txn_id,
                    "status": status,
                    "current_agent": current_agent,
                    "hitl_question": hitl_question,
                    "band_room_id": state.get("band_room_id"),
                }

                if status == STATUS_COMPLETE:
                    result = state.get("result")
                    if result is not None:
                        event_data["result"] = result.model_dump()

                if status == STATUS_ERROR:
                    event_data["error"] = state.get("error", "Unknown error")

                yield {
                    "event": status,
                    "data": json.dumps(event_data),
                }
                last_status = status

                # Terminal states — close the stream
                if status in (STATUS_COMPLETE, STATUS_ERROR):
                    return

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Timeout
        yield {
            "event": "error",
            "data": json.dumps({
                "txn_id": txn_id,
                "status": "error",
                "error": "Pipeline timed out after 10 minutes.",
            }),
        }

    return EventSourceResponse(event_generator())


# ─── POST /check/{txn_id}/hitl ────────────────────────────────────────────────


@router.post(
    "/{txn_id}/hitl",
    summary="Submit human response to a HITL clarification question",
    response_description="Confirmation that the response was published to Band",
)
async def submit_hitl_response(
    txn_id: str,
    answer: str = Form(..., description="The user's answer to the clarification question"),
) -> JSONResponse:
    """
    Submit a human response to an active HITL (Human-in-the-Loop) question.

    This publishes the answer to the Band room as a ``human_response`` message.
    The pipeline orchestrator, which is polling the Band room, will detect the
    response and resume the pipeline.

    Parameters
    ----------
    txn_id: Transaction ID (from POST /check response).
    answer: The user's answer to the pending clarification question.
    """
    state = get_state(txn_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Transaction '{txn_id}' not found.",
        )

    if state.get("status") != "hitl_waiting":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transaction '{txn_id}' is not waiting for HITL input. "
                f"Current status: {state.get('status')}"
            ),
        )

    band_room_id = state.get("band_room_id")
    if not band_room_id:
        raise HTTPException(
            status_code=500,
            detail="Band room ID not found in pipeline state.",
        )

    question = state.get("hitl_question") or ""

    # Publish human response to Band room
    try:
        async with BandClient() as band_client:
            band_room = await band_client.get_room(band_room_id)
            await hitl_manager.submit_human_response(
                band_room=band_room,
                question=question,
                answer=answer,
            )
    except Exception as exc:
        logger.error(
            "POST /%s/hitl: failed to publish human response to Band: %s",
            txn_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to publish response to Band room: {exc}",
        )

    logger.info(
        "POST /%s/hitl: human response published | answer='%s...'",
        txn_id, answer[:80],
    )

    return JSONResponse(
        status_code=200,
        content={
            "txn_id": txn_id,
            "status": "response_submitted",
            "message": "Your response has been submitted. The analysis will resume shortly.",
        },
    )
