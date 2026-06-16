"""
Pipeline Orchestrator — Sequential 4-Agent Runner
==================================================
Manages the full PayGuard AI agent pipeline for a single transaction.

Execution flow
--------------
  Band room created (txn-{txn_id})
      ↓
  Agent 1 — Destination Intelligence  (Featherless AI)
      ↓ publishes to Band; checks for HITL
  Agent 2 — QR Decode & UPI Validator (AIML API vision + reasoning)
      ↓ reads Agent 1; checks for HITL
  Agent 3 — Web Intelligence          (Playwright + DDG + Reddit + AIML)
      ↓ reads Agent 1 + 2; checks for HITL
  [HITL Gate] — pipeline pauses if any agent flagged ambiguity
      ↓ user responds via /check/{txn_id}/respond → Band room
  Agent 4 — Verdict Synthesis         (AIML API claude-3-5-sonnet)
      ↓ reads full room + human responses; publishes final verdict
  Verdict persisted to SQLite via api.database (SQLAlchemy async)

State management
----------------
Pipeline state is kept in two places:
  1. In-memory registry (``_registry`` dict) — for SSE streaming.
     Keys: status, band_room_id, hitl_question, result, error.
  2. SQLite via api.database (CheckRecord ORM) — for history/report.

The in-memory registry is sufficient for a hackathon demo. Production
would use Redis for the registry and PostgreSQL for persistence.

Implemented in: Phase 5 (updated in Phase 6)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from api.models import (
    Agent4Output,
    CheckResponse,
    PriceIntelligence,
    VerdictLevel,
)
from services.band_client import BandClient, BandRoom
from services.hitl_manager import HITLManager

import agents.agent1_destination as agent1
import agents.agent2_qr_upi as agent2
import agents.agent3_web_intelligence as agent3
import agents.agent4_verdict as agent4

logger = logging.getLogger(__name__)

# ─── In-memory pipeline state registry ───────────────────────────────────────

# Maps txn_id → state dict
_registry: dict[str, dict] = {}

# ─── Status constants ─────────────────────────────────────────────────────────

STATUS_AGENT_1 = "agent_1_running"
STATUS_AGENT_2 = "agent_2_running"
STATUS_AGENT_3 = "agent_3_running"
STATUS_HITL    = "hitl_waiting"
STATUS_AGENT_4 = "agent_4_running"
STATUS_COMPLETE = "complete"
STATUS_ERROR    = "error"


# ─── State helpers ────────────────────────────────────────────────────────────


def get_state(txn_id: str) -> Optional[dict]:
    """Return the pipeline state for a transaction, or None if not found."""
    return _registry.get(txn_id)


def _set_state(txn_id: str, **kwargs: object) -> None:
    """Update (merge) the pipeline state for a transaction."""
    if txn_id not in _registry:
        _registry[txn_id] = {}
    _registry[txn_id].update(kwargs)
    logger.debug("Pipeline state[%s] → %s", txn_id, _registry[txn_id].get("status"))


def _set_status(txn_id: str, status: str, **kwargs: object) -> None:
    """Convenience wrapper — set status and any extra fields."""
    _set_state(txn_id, status=status, **kwargs)


# ─── Pipeline Orchestrator ────────────────────────────────────────────────────


class PipelineOrchestrator:
    """
    Runs the full 4-agent sequential pipeline for a single payment check.

    Usage
    -----
    ::

        orchestrator = PipelineOrchestrator()
        txn_id = orchestrator.create_txn_id()
        asyncio.create_task(orchestrator.run(txn_id, payload, qr_image_bytes))
        # Frontend polls GET /check/{txn_id}/status (SSE)
    """

    def __init__(self) -> None:
        self._hitl = HITLManager()

    @staticmethod
    def create_txn_id() -> str:
        """Generate a unique transaction ID."""
        return str(uuid.uuid4())

    async def run(
        self,
        txn_id: str,
        payment_url: Optional[str],
        upi_id: Optional[str],
        amount: float,
        product_description: Optional[str],
        source_type: str,
        additional_context: Optional[str],
        qr_image_bytes: Optional[bytes] = None,
    ) -> None:
        """
        Execute the full pipeline asynchronously.

        This coroutine is designed to be launched as a background asyncio.Task.
        It updates both the in-memory state registry (for SSE streaming) and
        the SQLite database (for persistence) at each phase transition.

        Parameters
        ----------
        txn_id:              Unique transaction identifier.
        payment_url:         URL to analyse (may be None).
        upi_id:              UPI VPA (may be None).
        amount:              INR amount about to be paid.
        product_description: What the user is paying for (optional).
        source_type:         How the payment destination was received.
        additional_context:  Free-text notes from the user (optional).
        qr_image_bytes:      Raw QR image bytes (optional).
        """
        logger.info("Pipeline starting | txn_id=%s", txn_id)
        _set_status(txn_id, STATUS_AGENT_1)

        # ── Create initial DB record ───────────────────────────────────────────
        try:
            from api.database import create_check_record
            await create_check_record(
                txn_id=txn_id,
                amount=amount,
                source_type=source_type,
                payment_url=payment_url,
                upi_id=upi_id,
                product_description=product_description,
                status="running",
            )
        except Exception as db_exc:
            logger.warning("Pipeline: could not create initial DB record (non-fatal): %s", db_exc)

        band_client = BandClient()
        band_room: Optional[BandRoom] = None

        try:
            # ── Create Band room ───────────────────────────────────────────────
            room_name = f"txn-{txn_id}"
            band_room = await band_client.create_room(room_name)
            _set_state(txn_id, band_room_id=band_room.id)
            logger.info("Pipeline: Band room created '%s' (id=%s)", room_name, band_room.id)

            # ── Update DB with Band room ID ────────────────────────────────────
            try:
                from api.database import update_check_status
                await update_check_status(
                    txn_id=txn_id,
                    status="agent_1_running",
                    band_room_id=band_room.id,
                )
            except Exception as db_exc:
                logger.warning("Pipeline: DB status update non-fatal: %s", db_exc)

            # ── Agent 1 ────────────────────────────────────────────────────────
            _set_status(txn_id, STATUS_AGENT_1)
            logger.info("Pipeline: running Agent 1...")
            agent1_output = await agent1.run(
                band_room=band_room,
                url=payment_url,
                upi_id=upi_id,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            logger.info("Pipeline: Agent 1 complete | risk=%s", agent1_output.risk_level)

            # ── HITL check after Agent 1 ───────────────────────────────────────
            if agent1_output.needs_clarification:
                await self._handle_hitl_pause(txn_id, band_room)

            # ── Agent 2 ────────────────────────────────────────────────────────
            _set_status(txn_id, STATUS_AGENT_2)
            logger.info("Pipeline: running Agent 2...")
            agent2_output = await agent2.run(
                band_room=band_room,
                qr_image_bytes=qr_image_bytes,
                upi_id=upi_id,
                url=payment_url,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            logger.info(
                "Pipeline: Agent 2 complete | refund_scam=%s | mismatch=%s",
                agent2_output.refund_scam_indicator,
                agent2_output.upi_context_mismatch,
            )

            # ── HITL check after Agent 2 ───────────────────────────────────────
            if agent2_output.needs_clarification:
                await self._handle_hitl_pause(txn_id, band_room)

            # ── Agent 3 ────────────────────────────────────────────────────────
            _set_status(txn_id, STATUS_AGENT_3)
            logger.info("Pipeline: running Agent 3...")
            agent3_output = await agent3.run(
                band_room=band_room,
                url=payment_url,
                upi_id=upi_id or agent1_output.upi_id,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            logger.info(
                "Pipeline: Agent 3 complete | web_risk=%s | complaints=%s",
                agent3_output.web_risk_level,
                agent3_output.fraud_complaints_found,
            )

            # ── HITL check after Agent 3 ───────────────────────────────────────
            if agent3_output.needs_clarification:
                await self._handle_hitl_pause(txn_id, band_room)

            # ── Agent 4 ────────────────────────────────────────────────────────
            _set_status(txn_id, STATUS_AGENT_4)
            logger.info("Pipeline: running Agent 4...")
            agent4_output = await agent4.run(
                band_room=band_room,
                url=payment_url,
                upi_id=upi_id,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            logger.info(
                "Pipeline: Agent 4 complete | verdict=%s | risk_score=%d",
                agent4_output.verdict,
                agent4_output.risk_score,
            )

            # ── Build CheckResponse ────────────────────────────────────────────
            report_url = f"/report/{txn_id}"
            result = CheckResponse(
                txn_id=txn_id,
                band_room_id=band_room.id,
                verdict=agent4_output.verdict,
                risk_score=agent4_output.risk_score,
                plain_english_summary=agent4_output.plain_english_summary,
                recommended_actions=agent4_output.recommended_actions,
                ask_merchant=agent4_output.ask_merchant,
                agent_narratives={
                    "destination_intelligence": agent1_output.agent_narrative,
                    "qr_upi_validator": agent2_output.agent_narrative,
                    "web_intelligence": agent3_output.agent_narrative,
                    "verdict_synthesis": agent4_output.plain_english_summary,
                },
                price_intelligence=agent3_output.price_intelligence,
                report_url=report_url,
            )

            # ── Persist to DB (SQLAlchemy ORM — api/database.py) ─────────────
            try:
                from api.database import complete_check_record
                price_intel_dict: dict | None = None
                if agent3_output.price_intelligence is not None:
                    price_intel_dict = agent3_output.price_intelligence.model_dump()

                await complete_check_record(
                    txn_id=txn_id,
                    verdict=agent4_output.verdict.value,
                    risk_score=agent4_output.risk_score,
                    plain_english_summary=agent4_output.plain_english_summary,
                    recommended_actions=agent4_output.recommended_actions,
                    ask_merchant=agent4_output.ask_merchant,
                    agent1_narrative=agent1_output.agent_narrative,
                    agent2_narrative=agent2_output.agent_narrative,
                    agent3_narrative=agent3_output.agent_narrative,
                    price_intelligence=price_intel_dict,
                    avoided_fraud_estimate=agent4_output.avoided_fraud_estimate,
                    result_json=result.model_dump_json(),
                )
                logger.info("Pipeline: transaction persisted (ORM) | txn_id=%s", txn_id)
            except Exception as db_exc:
                # Non-fatal — the in-memory result is still available for this session
                logger.error("Pipeline: DB persist failed (non-fatal): %s", db_exc)

            _set_status(txn_id, STATUS_COMPLETE, result=result, hitl_question=None)
            logger.info("Pipeline complete | txn_id=%s | verdict=%s", txn_id, agent4_output.verdict)

        except Exception as exc:
            logger.exception("Pipeline error | txn_id=%s: %s", txn_id, exc)
            _set_status(txn_id, STATUS_ERROR, error=str(exc))
            try:
                from api.database import mark_check_error
                await mark_check_error(txn_id, str(exc))
            except Exception as db_exc:
                logger.warning("Pipeline: could not mark DB error (non-fatal): %s", db_exc)
        finally:
            await band_client.aclose()

    async def _handle_hitl_pause(self, txn_id: str, band_room: BandRoom) -> None:
        """
        Pause the pipeline at a HITL gate.

        Sets status to ``hitl_waiting`` and blocks until the human response
        arrives in the Band room (via ``/check/{txn_id}/hitl`` route) or
        the timeout is reached.

        Parameters
        ----------
        txn_id:    Transaction ID (for state updates).
        band_room: Active Band room to poll for human_response.
        """
        question = await self._hitl.get_pending_question(band_room)
        _set_status(txn_id, STATUS_HITL, hitl_question=question)
        logger.info(
            "Pipeline: HITL pause | txn_id=%s | question='%s...'",
            txn_id,
            (question or "")[:80],
        )

        # Wait for the human response (5-minute timeout)
        answer = await self._hitl.wait_for_human_response(
            band_room=band_room, timeout=300
        )

        if answer is None:
            logger.warning(
                "Pipeline: HITL timeout — no human response received for txn_id=%s. "
                "Continuing with incomplete context.",
                txn_id,
            )
        else:
            logger.info(
                "Pipeline: HITL resolved | txn_id=%s | answer='%s...'",
                txn_id,
                answer[:80],
            )

    def resume_from_hitl(self, txn_id: str) -> bool:
        """
        Check if the pipeline for ``txn_id`` is currently paused at a HITL gate.

        Returns True if the pipeline is in hitl_waiting state (i.e., the
        human response submit should unblock it via the Band room).

        Parameters
        ----------
        txn_id: Transaction ID to check.

        Returns
        -------
        True if currently paused at HITL; False otherwise.
        """
        state = get_state(txn_id)
        return state is not None and state.get("status") == STATUS_HITL


# ─── Module-level singleton ───────────────────────────────────────────────────

orchestrator = PipelineOrchestrator()
