"""
Pipeline Orchestrator — Band-Native Room Seeder
================================================
Creates a Band room, seeds the first @mention to Agent 1, and monitors Band
context for progress/final verdict. Specialist agents run as Band remote agents.

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
from typing import Optional

from api.models import CheckResponse, VerdictLevel
from agents.band_config import load_remote_agent_configs
from services.band_client import BandClient, BandRoom
from services.hitl_manager import HITLManager

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
    Starts and observes the Band-native 4-agent workflow for one payment check.

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
        Create a Band room, invite/mention Agent 1, and monitor remote agents.

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
        logger.info("Band-native pipeline starting | txn_id=%s", txn_id)
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
                additional_context=additional_context,
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

            # ── Seed Band-native workflow ─────────────────────────────────────
            configs = load_remote_agent_configs()
            agent1_config = configs["destination_intelligence"]
            seed_payload = {
                "type": "payment_check_request",
                "txn_id": txn_id,
                "payment_url": payment_url,
                "upi_id": upi_id,
                "amount": amount,
                "product_description": product_description,
                "source_type": source_type,
                "additional_context": additional_context,
                "qr_image_uploaded": qr_image_bytes is not None,
                "instructions": (
                    "Begin PayGuard analysis. Use your PayGuard tool, publish structured "
                    "findings, then hand off to the configured next agent by @mention."
                ),
            }
            await band_room.publish_routed_message_to_handle(
                seed_payload,
                participant_handle=agent1_config.handle,
            )
            logger.info(
                "Pipeline: seeded Band room '%s' by mentioning @%s",
                band_room.name,
                agent1_config.handle,
            )

            result = await self._monitor_band_room(
                txn_id=txn_id,
                band_room=band_room,
                amount=amount,
            )

            # ── Persist to DB (SQLAlchemy ORM — api/database.py) ─────────────
            try:
                from api.database import complete_check_record
                price_intel_dict: dict | None = None
                if result.price_intelligence is not None:
                    if hasattr(result.price_intelligence, "model_dump"):
                        price_intel_dict = result.price_intelligence.model_dump()
                    elif isinstance(result.price_intelligence, dict):
                        price_intel_dict = result.price_intelligence

                await complete_check_record(
                    txn_id=txn_id,
                    verdict=result.verdict.value,
                    risk_score=result.risk_score,
                    plain_english_summary=result.plain_english_summary,
                    recommended_actions=result.recommended_actions,
                    ask_merchant=result.ask_merchant,
                    agent1_narrative=result.agent_narratives.get("destination_intelligence", ""),
                    agent2_narrative=result.agent_narratives.get("qr_upi_validator", ""),
                    agent3_narrative=result.agent_narratives.get("web_intelligence", ""),
                    price_intelligence=price_intel_dict,
                    avoided_fraud_estimate=None,
                    result_json=result.model_dump_json(),
                )
                logger.info("Pipeline: transaction persisted (ORM) | txn_id=%s", txn_id)
            except Exception as db_exc:
                # Non-fatal — the in-memory result is still available for this session
                logger.error("Pipeline: DB persist failed (non-fatal): %s", db_exc)

            _set_status(txn_id, STATUS_COMPLETE, result=result, hitl_question=None)
            logger.info("Band-native pipeline complete | txn_id=%s | verdict=%s", txn_id, result.verdict)

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

    async def _monitor_band_room(
        self,
        txn_id: str,
        band_room: BandRoom,
        amount: float,
        timeout_seconds: int = 600,
    ) -> CheckResponse:
        """Watch Band context for remote-agent progress and final verdict."""
        sequence_status = {
            1: STATUS_AGENT_1,
            2: STATUS_AGENT_2,
            3: STATUS_AGENT_3,
            4: STATUS_AGENT_4,
        }
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        latest_by_agent: dict[str, dict] = {}

        while asyncio.get_event_loop().time() < deadline:
            messages = await band_room.get_messages()
            for message in messages:
                agent_name = message.get("agent")
                if agent_name:
                    latest_by_agent[agent_name] = message
                seq = message.get("sequence")
                if isinstance(seq, int) and seq in sequence_status:
                    _set_status(txn_id, sequence_status[seq])
                if message.get("type") == "needs_clarification":
                    _set_status(txn_id, STATUS_HITL, hitl_question=message.get("question"))

            final_msg = latest_by_agent.get("verdict_synthesis")
            if final_msg:
                verdict_value = str(final_msg.get("verdict", "VERIFY")).upper()
                try:
                    verdict = VerdictLevel(verdict_value)
                except ValueError:
                    verdict = VerdictLevel.VERIFY

                try:
                    risk_score = int(final_msg.get("risk_score", 50))
                except (TypeError, ValueError):
                    risk_score = 50

                return CheckResponse(
                    txn_id=txn_id,
                    band_room_id=band_room.id,
                    verdict=verdict,
                    risk_score=max(0, min(100, risk_score)),
                    plain_english_summary=(
                        final_msg.get("plain_english_summary")
                        or final_msg.get("agent_narrative")
                        or "PayGuard completed Band-native analysis."
                    ),
                    recommended_actions=final_msg.get("recommended_actions", []),
                    ask_merchant=final_msg.get("ask_merchant", []),
                    agent_narratives={
                        "destination_intelligence": latest_by_agent.get(
                            "destination_intelligence", {}
                        ).get("agent_narrative", ""),
                        "qr_upi_validator": latest_by_agent.get(
                            "qr_upi_validator", {}
                        ).get("agent_narrative", ""),
                        "web_intelligence": latest_by_agent.get(
                            "web_intelligence", {}
                        ).get("agent_narrative", ""),
                        "verdict_synthesis": final_msg.get("plain_english_summary", ""),
                    },
                    price_intelligence=latest_by_agent.get("web_intelligence", {}).get(
                        "price_intelligence"
                    ),
                    report_url=f"/report/{txn_id}",
                )

            await asyncio.sleep(1.0)

        raise TimeoutError(
            f"Band-native pipeline timed out after {timeout_seconds}s waiting for Agent 4."
        )

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
