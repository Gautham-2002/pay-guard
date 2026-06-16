"""
HITL Manager — Human-in-the-Loop Backbone
==========================================
Manages the pause/resume pattern when an agent needs user input mid-pipeline.

Flow
----
1. An agent publishes a ``needs_clarification`` message to the Band room.
2. The pipeline orchestrator calls ``check_hitl_needed()`` — if truthy, it
   signals the backend to return ``hitl_waiting`` status to the frontend.
3. The frontend shows the question card to the user.
4. The user answers → frontend POSTs to ``/check/{txn_id}/hitl``.
5. The route calls ``submit_human_response()`` → published to Band room.
6. The pipeline orchestrator polls ``is_hitl_resolved()`` and resumes.
7. The next agent reads the human response from Band exactly as it reads any
   other agent message — Band is the single shared context layer.

Design principles
-----------------
- No direct agent-to-agent communication; Band room is the only shared layer.
- Human responses are first-class Band room messages.
- Timeout behaviour: ``wait_for_human_response`` returns None after 300 s;
  the orchestrator may then proceed with a default/safe answer.

Implemented in: Phase 5
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from services.band_client import BandRoom

logger = logging.getLogger(__name__)

# Default timeout for waiting on a human response (seconds)
_DEFAULT_HITL_TIMEOUT: int = 300


class HITLManager:
    """
    Manages the Human-in-the-Loop flow via Band room.

    When an agent sets needs_clarification=True:
    1. The agent publishes a ``needs_clarification`` message to the Band room.
    2. HITLManager detects this and signals the backend to pause.
    3. Backend returns a ``hitl_waiting`` status to the frontend.
    4. Frontend shows the question to the user.
    5. User answers → frontend POSTs to /check/{txn_id}/hitl.
    6. Backend calls submit_human_response() → publishes human_response to Band.
    7. HITLManager signals the pipeline to resume.
    8. The next agent reads the human response from Band and continues.
    """

    # ── Query helpers ─────────────────────────────────────────────────────────

    async def check_hitl_needed(self, band_room: BandRoom) -> Optional[dict]:
        """
        Check if any message in the room has type='needs_clarification' and
        has not yet been answered by a human_response message.

        Parameters
        ----------
        band_room: The active BandRoom to inspect.

        Returns
        -------
        The ``needs_clarification`` message dict if found and not yet answered;
        None otherwise.
        """
        messages = await band_room.get_messages()

        clarification_msg: Optional[dict] = None
        has_human_response = False

        for msg in messages:
            msg_type = msg.get("type")
            if msg_type == "needs_clarification":
                clarification_msg = msg  # keep the most recent one
            elif msg_type == "human_response":
                has_human_response = True

        if clarification_msg and not has_human_response:
            logger.info(
                "HITLManager: unresolved clarification found in Band room '%s' | "
                "from_agent=%s | question='%s...'",
                band_room.name,
                clarification_msg.get("from_agent", "unknown"),
                str(clarification_msg.get("question", ""))[:80],
            )
            return clarification_msg

        return None

    async def is_hitl_resolved(self, band_room: BandRoom) -> bool:
        """
        Check if a human_response message exists in the Band room.

        This is used by the orchestrator polling loop to determine when the
        pipeline can resume after a HITL pause.

        Parameters
        ----------
        band_room: The active BandRoom to inspect.

        Returns
        -------
        True if a human_response message exists; False otherwise.
        """
        messages = await band_room.get_messages()
        resolved = any(m.get("type") == "human_response" for m in messages)
        if resolved:
            logger.debug(
                "HITLManager: HITL resolved in Band room '%s'", band_room.name
            )
        return resolved

    async def get_pending_question(self, band_room: BandRoom) -> Optional[str]:
        """
        Return the pending clarification question text, or None if no HITL
        is pending.

        Parameters
        ----------
        band_room: The active BandRoom to inspect.

        Returns
        -------
        Question string or None.
        """
        hitl_msg = await self.check_hitl_needed(band_room)
        if hitl_msg:
            return hitl_msg.get("question")
        return None

    # ── Response submission ───────────────────────────────────────────────────

    async def submit_human_response(
        self,
        band_room: BandRoom,
        question: str,
        answer: str,
    ) -> None:
        """
        Publish the user's answer to the Band room as a human_response message.

        The next agent reads this message exactly as it reads any other agent's
        output — Band room is the single shared context layer.

        Message format:
        ::

            {
                "type": "human_response",
                "question_from_agent": "<original question>",
                "human_answer": "<user's answer>",
                "timestamp": "<ISO-8601 UTC>"
            }

        Parameters
        ----------
        band_room: The active BandRoom to publish into.
        question:  The original clarification question from the agent.
        answer:    The human's answer text.
        """
        message = {
            "type": "human_response",
            "question_from_agent": question,
            "human_answer": answer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await band_room.publish(message)
        logger.info(
            "HITLManager: human response published to Band room '%s' | "
            "answer='%s...'",
            band_room.name,
            answer[:80],
        )

    async def wait_for_human_response(
        self,
        band_room: BandRoom,
        timeout: int = _DEFAULT_HITL_TIMEOUT,
    ) -> Optional[str]:
        """
        Poll the Band room for a human_response message.

        Delegates to BandRoom.wait_for_human_response() and extracts the
        ``human_answer`` string.

        Parameters
        ----------
        band_room: The active BandRoom to poll.
        timeout:   Maximum seconds to wait (default 300 — 5 minutes).

        Returns
        -------
        The ``human_answer`` string if received; None on timeout.
        """
        logger.info(
            "HITLManager: waiting up to %ds for human response in Band room '%s'",
            timeout, band_room.name,
        )
        msg = await band_room.wait_for_human_response(timeout_seconds=timeout)
        if msg is None:
            logger.warning(
                "HITLManager: timeout waiting for human response in Band room '%s'",
                band_room.name,
            )
            return None

        answer = msg.get("human_answer", "")
        logger.info(
            "HITLManager: received human response: '%s...'",
            answer[:80],
        )
        return answer


# ─── Module-level singleton ───────────────────────────────────────────────────

# Shared instance for use across the application.
hitl_manager = HITLManager()
