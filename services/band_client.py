"""
Band Client — Band Room Coordination Layer
==========================================
Wraps the Band API for async publish/subscribe operations used by all agents.

Band rooms serve as the ONLY shared communication layer between agents.
No agent-to-agent direct communication occurs — every message passes through
the Band room so that each agent's reasoning is grounded in the same shared
context, including any human_response messages from HITL interactions.

Responsibilities
----------------
- create_room(txn_id)           : Create a new Band room for a transaction.
- publish(room_id, payload)      : Publish a JSON payload to the room.
- get_room_messages(room_id)     : Fetch all messages from the room (for agents
                                   to read prior context before running).
- subscribe_sse(room_id)         : Server-Sent Events stream for the frontend
                                   to receive real-time agent progress updates.
- publish_hitl_question(...)     : Publish a needs_clarification message to pause
                                   the pipeline and surface a question in the UI.
- publish_human_response(...)    : Publish the user's answer back to the room so
                                   the next agent can read it.

Implemented in: Phase 1
"""

from __future__ import annotations

import os

# TODO (Phase 1): Implement BandClient using httpx.AsyncClient.
#                 Base URL from BAND_API_KEY env var.


class BandClient:
    """
    Async HTTP client for the Band room API.

    All methods are coroutines and must be awaited.
    Instantiate once per transaction; re-use across agents.
    """

    def __init__(self) -> None:
        self.api_key: str = os.environ.get("BAND_API_KEY", "")
        # TODO (Phase 1): Initialise httpx.AsyncClient with auth headers.

    async def create_room(self, txn_id: str) -> str:
        """
        Create a new Band room for the given transaction.

        Parameters
        ----------
        txn_id: Unique transaction identifier (format: txn-{uuid}).

        Returns
        -------
        band_room_id: The Band-assigned room identifier string.
        """
        raise NotImplementedError("BandClient.create_room implemented in Phase 1")

    async def publish(self, room_id: str, payload: dict) -> None:
        """
        Publish a JSON payload to the Band room.

        Parameters
        ----------
        room_id: Band room identifier.
        payload: JSON-serialisable dict (Agent*Output or HITLMessage).
        """
        raise NotImplementedError("BandClient.publish implemented in Phase 1")

    async def get_room_messages(self, room_id: str) -> list[dict]:
        """
        Retrieve all messages posted to a Band room in chronological order.

        Parameters
        ----------
        room_id: Band room identifier.

        Returns
        -------
        List of message dicts as published by each agent / human participant.
        """
        raise NotImplementedError("BandClient.get_room_messages implemented in Phase 1")

    async def subscribe_sse(self, room_id: str):
        """
        Async generator yielding Server-Sent Events from the Band room.
        Consumed by the /check/status SSE endpoint in the FastAPI backend.

        Parameters
        ----------
        room_id: Band room identifier.

        Yields
        ------
        Parsed SSE event dicts as they arrive.
        """
        raise NotImplementedError("BandClient.subscribe_sse implemented in Phase 5")
