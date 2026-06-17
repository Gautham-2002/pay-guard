"""
Route: /check
=============
POST   /check                    — Submit a payment destination for agent pipeline analysis.
GET    /check/{txn_id}/status    — SSE stream: real-time pipeline progress (status events).
GET    /check/{txn_id}/stream    — SSE stream: Band-room-level agent update events.
POST   /check/{txn_id}/respond   — Submit human response to a HITL clarification question.
POST   /check/{txn_id}/hitl      — Backwards-compatible alias for /respond.

HITL flow
---------
1. POST /check → pipeline starts in background, returns txn_id immediately.
2. Frontend opens GET /{txn_id}/status (or /stream) SSE.
3. If an agent needs clarification → SSE emits status="hitl_waiting" + question.
4. User answers in UI → POST /{txn_id}/respond → pipeline resumes.
5. SSE continues through agent_4_running → complete.

/status vs /stream
------------------
- /status  : Emits one CheckStatus event per status change (~500 ms poll).
             Simple polling for quick integration.
- /stream  : Emits Band-room-level events as each agent publishes.
             More granular; designed for animated UIs.

Implemented in: Phase 6
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from api.models import CheckStatus, SourceType, VerdictLevel
from services.band_client import BandRoom, BandClient
from services.hitl_manager import hitl_manager
from services.pipeline import STATUS_COMPLETE, STATUS_ERROR, get_state, orchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory idempotency for duplicate browser submits/retries. This is enough
# for the hackathon single-process demo; production should move it to Redis.
_submission_idempotency: dict[str, dict] = {}


# ─── POST /check ──────────────────────────────────────────────────────────────


@router.post(
    "",
    summary="Submit payment destination for fraud analysis",
    response_description="Transaction ID and initial status",
    status_code=202,
)
async def submit_check(
    background_tasks: BackgroundTasks,
    x_idempotency_key: Optional[str] = Header(default=None, alias="X-Idempotency-Key"),
    # ── Payment destination (at least one required) ──────────────────────
    payment_url: Optional[str] = Form(
        default=None,
        description="Full URL to analyse (e.g. https://flipkart-sale.in/pay)",
    ),
    upi_id: Optional[str] = Form(
        default=None,
        description="UPI Virtual Payment Address (e.g. merchant@paytm)",
    ),
    # ── Required fields ──────────────────────────────────────────────────
    amount: float = Form(
        ...,
        gt=0,
        description="INR amount the user is about to pay",
    ),
    source_type: SourceType = Form(
        ...,
        description="How the payment destination was received",
    ),
    # ── Optional enrichment fields ───────────────────────────────────────
    product_description: Optional[str] = Form(
        default=None,
        description="What the user says they are paying for",
    ),
    additional_context: Optional[str] = Form(
        default="",
        description="Free-text notes from the user",
    ),
    # ── Optional QR image upload ─────────────────────────────────────────
    qr_image: Optional[UploadFile] = File(
        default=None,
        description="QR code image (PNG / JPEG) — decoded by Agent 2",
    ),
) -> JSONResponse:
    """
    Submit a payment destination for the full 4-agent fraud analysis pipeline.

    At least one of ``payment_url``, ``upi_id``, or ``qr_image`` must be provided.

    The pipeline runs asynchronously in the background. The caller receives a
    ``txn_id`` immediately and should open ``GET /{txn_id}/stream`` for
    real-time progress, or poll ``GET /{txn_id}/status``.
    """
    idempotency_key = (x_idempotency_key or "").strip()
    if idempotency_key and idempotency_key in _submission_idempotency:
        logger.info("POST /check: duplicate submission key=%s; returning existing txn", idempotency_key)
        return JSONResponse(status_code=202, content=_submission_idempotency[idempotency_key])

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

    response_content = {
        "txn_id": txn_id,
        "status": "running",
        "status_url": f"/api/check/{txn_id}/status",
        "stream_url": f"/api/check/{txn_id}/stream",
        "respond_url": f"/api/check/{txn_id}/respond",
        "report_url": f"/api/report/{txn_id}",
    }
    if idempotency_key:
        _submission_idempotency[idempotency_key] = response_content

    return JSONResponse(status_code=202, content=response_content)


# ─── GET /check/{txn_id}/status (SSE — status-change stream) ──────────────────


@router.get(
    "/{txn_id}/status",
    summary="Stream real-time pipeline status via SSE (status-change events)",
    response_description="Server-Sent Events stream of CheckStatus updates",
)
async def stream_status(txn_id: str) -> EventSourceResponse:
    """
    Stream real-time pipeline status updates for a transaction.

    Emits one event per *status change* (approximately every 500 ms poll).
    Closes the stream when status reaches ``complete`` or ``error``.

    Event types
    -----------
    - ``agent_1_running`` / ``agent_2_running`` / ``agent_3_running`` / ``agent_4_running``
    - ``hitl_waiting``  — includes ``hitl_question``
    - ``complete``      — includes full ``result`` (CheckResponse)
    - ``error``         — includes ``error`` message
    """

    async def event_generator():
        agent_label_map = {
            "agent_1_running": "destination_intelligence",
            "agent_2_running": "qr_upi_validator",
            "agent_3_running": "web_intelligence",
            "agent_4_running": "verdict_synthesis",
        }

        max_wait_seconds = 600   # 10-minute pipeline cap
        poll_interval   = 0.5
        elapsed         = 0.0
        last_status     = None

        while elapsed < max_wait_seconds:
            state = get_state(txn_id)

            if state is None:
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

            if status != last_status:
                current_agent   = agent_label_map.get(status)
                hitl_question   = state.get("hitl_question") if status == "hitl_waiting" else None

                event_data: dict = {
                    "txn_id":        txn_id,
                    "status":        status,
                    "current_agent": current_agent,
                    "hitl_question": hitl_question,
                    "band_room_id":  state.get("band_room_id"),
                }

                if status == STATUS_COMPLETE:
                    result = state.get("result")
                    if result is not None:
                        event_data["result"] = result.model_dump()

                if status == STATUS_ERROR:
                    event_data["error"] = state.get("error", "Unknown error")

                yield {
                    "event": status,
                    "data":  json.dumps(event_data),
                }
                last_status = status

                if status in (STATUS_COMPLETE, STATUS_ERROR):
                    return

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        yield {
            "event": "error",
            "data": json.dumps({
                "txn_id": txn_id,
                "status": "error",
                "error":  "Pipeline timed out after 10 minutes.",
            }),
        }

    return EventSourceResponse(event_generator())


# ─── GET /check/{txn_id}/stream (SSE — Band-room agent-update stream) ─────────


@router.get(
    "/{txn_id}/stream",
    summary="Stream Band-room agent events via SSE (agent_update / complete / hitl_required)",
    response_description="Server-Sent Events stream of granular agent progress",
)
async def stream_band_events(txn_id: str) -> EventSourceResponse:
    """
    Server-Sent Events stream of Band-room agent activity.

    Polls the Band room every second. When a new agent message appears,
    emits an ``agent_update`` event. Emits ``complete`` once the verdict
    is ready, or ``hitl_required`` if a clarification is needed.

    Event formats
    -------------

    ``agent_update``::

        {
          "event": "agent_update",
          "data": {
            "agent":            "destination_intelligence",
            "status":           "complete",
            "risk_level":       "HIGH",
            "narrative_preview": "first 150 chars of narrative..."
          }
        }

    ``complete``::

        {
          "event": "complete",
          "data": {
            "txn_id":     "...",
            "verdict":    "DANGER",
            "risk_score": 88,
            "result":     { ...full CheckResponse... }
          }
        }

    ``hitl_required``::

        {
          "event": "hitl_required",
          "data": {
            "txn_id":   "...",
            "question": "Did they ask you to scan this QR to receive money?"
          }
        }

    The stream closes after ``complete`` / ``hitl_required`` / ``error``,
    or after 5 minutes of inactivity.
    """

    async def event_generator():
        # Agent sequence → readable agent name mapping
        agent_seq_map: dict[int, str] = {
            1: "destination_intelligence",
            2: "qr_upi_validator",
            3: "web_intelligence",
            4: "verdict_synthesis",
        }

        max_wait_seconds = 600   # absolute cap
        poll_interval    = 1.0   # Band poll cadence
        elapsed          = 0.0

        # Track which agents have already been emitted
        emitted_agents: set[int] = set()
        band_room_id: Optional[str] = None

        # Wait up to 30 s for the pipeline to start and register state
        for _ in range(60):
            state = get_state(txn_id)
            if state is not None:
                band_room_id = state.get("band_room_id")
                if band_room_id:
                    break
            await asyncio.sleep(0.5)
            elapsed += 0.5
        else:
            yield {
                "event": "error",
                "data": json.dumps({
                    "txn_id": txn_id,
                    "error":  f"Transaction '{txn_id}' not found or Band room not yet created.",
                }),
            }
            return

        # ── Main poll loop ─────────────────────────────────────────────────────
        try:
            async with BandClient() as band_client:
                band_room: BandRoom = await band_client.get_room(band_room_id)

                while elapsed < max_wait_seconds:
                    state = get_state(txn_id)

                    # ── Check pipeline status for terminal events ──────────────
                    if state is not None:
                        pipeline_status = state.get("status", "")

                        if pipeline_status == STATUS_COMPLETE:
                            result = state.get("result")
                            event_data: dict = {
                                "txn_id":     txn_id,
                                "verdict":    result.verdict.value if result else None,
                                "risk_score": result.risk_score if result else None,
                            }
                            if result:
                                event_data["result"] = result.model_dump()
                            yield {
                                "event": "complete",
                                "data":  json.dumps(event_data),
                            }
                            return

                        if pipeline_status == STATUS_ERROR:
                            yield {
                                "event": "error",
                                "data":  json.dumps({
                                    "txn_id": txn_id,
                                    "error":  state.get("error", "Pipeline error"),
                                }),
                            }
                            return

                        if pipeline_status == "hitl_waiting":
                            yield {
                                "event": "hitl_required",
                                "data":  json.dumps({
                                    "txn_id":   txn_id,
                                    "question": state.get("hitl_question"),
                                }),
                            }
                            return

                    # ── Poll Band room for new agent messages ──────────────────
                    try:
                        messages = await band_room.get_messages()
                        for msg in messages:
                            seq = msg.get("sequence")
                            if seq is not None and seq not in emitted_agents:
                                agent_name = agent_seq_map.get(seq, msg.get("agent", "unknown"))
                                risk_level = (
                                    msg.get("risk_level")
                                    or msg.get("web_risk_level")
                                    or msg.get("verdict")
                                )
                                narrative  = msg.get("agent_narrative", "") or ""
                                yield {
                                    "event": "agent_update",
                                    "data":  json.dumps({
                                        "agent":             agent_name,
                                        "sequence":          seq,
                                        "status":            "complete",
                                        "risk_level":        risk_level,
                                        "narrative_preview": narrative[:150],
                                    }),
                                }
                                emitted_agents.add(seq)
                    except Exception as poll_exc:
                        logger.warning("stream_band_events: Band poll error (will retry): %s", poll_exc)

                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

        except Exception as exc:
            logger.error("stream_band_events: fatal error txn_id=%s: %s", txn_id, exc)
            yield {
                "event": "error",
                "data":  json.dumps({
                    "txn_id": txn_id,
                    "error":  str(exc),
                }),
            }
            return

        yield {
            "event": "error",
            "data": json.dumps({
                "txn_id": txn_id,
                "error":  "Stream timed out after 10 minutes.",
            }),
        }

    return EventSourceResponse(event_generator())


# ─── POST /check/{txn_id}/respond — HITL Response (canonical) ────────────────


@router.post(
    "/{txn_id}/respond",
    summary="Submit human response to a HITL clarification question",
    response_description="Confirmation that the response was published to Band",
)
async def submit_hitl_respond(
    txn_id: str,
    answer: str = Body(..., embed=True, description="The user's answer to the clarification question"),
) -> JSONResponse:
    """
    Submit a human response to an active HITL (Human-in-the-Loop) question.

    This publishes the answer to the Band room as a ``human_response`` message.
    The pipeline orchestrator, which is polling the Band room, will detect the
    response and resume the pipeline from where it left off.

    Parameters
    ----------
    txn_id: Transaction ID (from POST /check response).
    answer: The user's answer to the pending clarification question.

    Raises
    ------
    404: Transaction not found.
    409: Transaction is not in ``hitl_waiting`` state.
    500: Could not publish to Band room.
    """
    return await _handle_hitl_answer(txn_id, answer)


# ─── POST /check/{txn_id}/hitl — Backwards-compatible alias ──────────────────


@router.post(
    "/{txn_id}/hitl",
    summary="[Deprecated] Submit human HITL response — use /respond instead",
    response_description="Confirmation that the response was published to Band",
    include_in_schema=True,
    deprecated=True,
)
async def submit_hitl_response(
    txn_id: str,
    answer: str = Form(..., description="The user's answer to the clarification question"),
) -> JSONResponse:
    """
    Backwards-compatible alias for ``POST /{txn_id}/respond``.

    Accepts ``answer`` as a form field (original Phase 5 interface).
    New clients should use the ``/respond`` endpoint with a JSON body.
    """
    return await _handle_hitl_answer(txn_id, answer)


# ─── Shared HITL handler ──────────────────────────────────────────────────────


async def _handle_hitl_answer(txn_id: str, answer: str) -> JSONResponse:
    """
    Core logic shared by both /respond and /hitl endpoints.

    Validates pipeline state, publishes human response to Band, and returns
    a confirmation payload.
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
            "HITL answer: failed to publish to Band room | txn_id=%s: %s",
            txn_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to publish response to Band room: {exc}",
        )

    logger.info(
        "HITL answer published | txn_id=%s | answer='%s...'",
        txn_id, answer[:80],
    )

    return JSONResponse(
        status_code=200,
        content={
            "txn_id":  txn_id,
            "status":  "response_submitted",
            "message": "Your response has been submitted. The analysis will resume shortly.",
        },
    )
