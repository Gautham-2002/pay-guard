"""
Band Client — Band Room Coordination Layer
==========================================
Wraps the Band API (https://app.band.ai/api/v1) for async publish/subscribe
operations used by all PayGuard AI agents.

Band rooms serve as the ONLY shared communication layer between agents.
No agent-to-agent direct communication occurs — every message passes through
the Band room so that each agent's reasoning is grounded in the same shared
context, including any human_response messages from HITL interactions.

Architecture
------------
- BandClient  : Manages the HTTP session and top-level room operations
                (create_room, get_room).
- BandRoom    : Represents a single Band chat room and exposes all message
                publish/read/wait primitives used by agents.

Message Storage Strategy
-------------------------
Band messages carry a ``content`` field (plain text / @mention string).
PayGuard wraps every agent payload as JSON and embeds it in the content
field alongside the required @mention so that the Band API accepts the
message.  On read, the JSON is extracted back out from the content string.

Format written to Band content field:
    @{agent_handle} <PAYGUARD_JSON>{...json payload...}</PAYGUARD_JSON>

Implemented in: Phase 1
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Band API Constants ────────────────────────────────────────────────────────

BAND_BASE_URL = "https://app.band.ai/api/v1"
_JSON_TAG_OPEN = "<PAYGUARD_JSON>"
_JSON_TAG_CLOSE = "</PAYGUARD_JSON>"

# ─── Custom Exceptions ────────────────────────────────────────────────────────


class BandConnectionError(Exception):
    """Raised when the Band API is unreachable or returns an unexpected HTTP error."""


class BandTimeoutError(Exception):
    """Raised when a wait_for_* poll operation exceeds its timeout."""


# ─── BandClient ───────────────────────────────────────────────────────────────


class BandClient:
    """
    Async HTTP client for the Band room API.

    All methods are coroutines and must be awaited.
    Instantiate once per request/session; re-use across agents for the same
    transaction.

    Parameters
    ----------
    api_key:
        Band agent API key.  Defaults to ``os.getenv("BAND_API_KEY")``.

    Usage
    -----
    ::

        client = BandClient()
        room = await client.create_room("txn-abc123")
        await room.publish({"agent": "domain_intel", "sequence": 1, "result": {...}})
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key: str = api_key or os.getenv("BAND_API_KEY", "")
        if not self.api_key:
            logger.warning(
                "BandClient: BAND_API_KEY is not set. All API calls will fail."
            )
        self._http: httpx.AsyncClient = httpx.AsyncClient(
            base_url=BAND_BASE_URL,
            headers={
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        # Cache for the agent's own profile (lazy-loaded on first use)
        self._agent_profile: Optional[dict] = None

    # ── Agent identity ────────────────────────────────────────────────────────

    async def get_agent_profile(self) -> dict:
        """
        Return the authenticated agent's profile (id, name, handle).
        Result is cached after the first call.
        """
        if self._agent_profile is not None:
            return self._agent_profile
        try:
            resp = await self._http.get("/agent/me")
            resp.raise_for_status()
            self._agent_profile = resp.json()["data"]
            logger.debug("Band agent profile: %s", self._agent_profile)
            return self._agent_profile
        except httpx.HTTPStatusError as exc:
            logger.error("Band get_agent_profile HTTP error: %s", exc)
            raise BandConnectionError(
                f"Failed to fetch agent profile: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Band get_agent_profile connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    # ── Room operations ───────────────────────────────────────────────────────

    async def create_room(self, name: str) -> "BandRoom":
        """
        Create a new Band chat room and return a ``BandRoom`` object.

        Parameters
        ----------
        name:
            Human-readable room title.  Convention: ``"txn-{txn_id}"``.

        Returns
        -------
        BandRoom
            A room object bound to this client.
        """
        try:
            resp = await self._http.post(
                "/agent/chats",
                json={"chat": {"title": name}},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            logger.info("Created Band room '%s' → id=%s", name, data["id"])
            return BandRoom(room_id=data["id"], name=name, client=self)
        except httpx.HTTPStatusError as exc:
            logger.error("Band create_room HTTP error: %s | body: %s", exc, exc.response.text)
            raise BandConnectionError(
                f"Failed to create Band room '{name}': HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Band create_room connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def get_room(self, room_id: str) -> "BandRoom":
        """
        Retrieve an existing Band room by its UUID.

        Parameters
        ----------
        room_id:
            Band-assigned room UUID.

        Returns
        -------
        BandRoom
        """
        try:
            resp = await self._http.get(f"/agent/chats/{room_id}")
            resp.raise_for_status()
            data = resp.json()["data"]
            name = data.get("title") or room_id
            logger.info("Retrieved Band room id=%s title='%s'", room_id, name)
            return BandRoom(room_id=room_id, name=name, client=self)
        except httpx.HTTPStatusError as exc:
            logger.error("Band get_room HTTP error: %s", exc)
            raise BandConnectionError(
                f"Failed to get Band room '{room_id}': HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Band get_room connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Call when the client is no longer needed."""
        await self._http.aclose()

    # ── Context manager support ───────────────────────────────────────────────

    async def __aenter__(self) -> "BandClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()


# ─── BandRoom ─────────────────────────────────────────────────────────────────


class BandRoom:
    """
    Represents a single Band chat room.

    All message operations (publish, read, wait) happen through this object.
    Instantiated by ``BandClient.create_room`` or ``BandClient.get_room``.

    Parameters
    ----------
    room_id:
        Band-assigned UUID for this room.
    name:
        Human-readable title (``txn-{uuid}``).
    client:
        The parent ``BandClient`` instance (shares HTTP connection and auth).
    """

    def __init__(self, room_id: str, name: str, client: BandClient) -> None:
        self._room_id = room_id
        self._name = name
        self._client = client

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        """The Band-assigned UUID for this room."""
        return self._room_id

    @property
    def name(self) -> str:
        """Human-readable room title."""
        return self._name

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _encode_message(self, payload: dict, agent_handle: str) -> str:
        """
        Encode a dict payload into a Band-compatible content string.

        Band requires every message to contain at least one @mention.
        We embed the JSON payload inside a custom XML-like tag so it
        can be reliably parsed back out on read.

        Format:
            @{agent_handle} <PAYGUARD_JSON>{...}</PAYGUARD_JSON>
        """
        json_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"@{agent_handle} {_JSON_TAG_OPEN}{json_str}{_JSON_TAG_CLOSE}"

    def _decode_message(self, raw_message: dict) -> Optional[dict]:
        """
        Parse a raw Band message dict into a PayGuard payload dict.

        Returns None if the message does not contain an embedded PayGuard
        JSON block (i.e., it is a plain Band system message).
        """
        content: str = raw_message.get("content", "")
        start = content.find(_JSON_TAG_OPEN)
        end = content.find(_JSON_TAG_CLOSE)
        if start == -1 or end == -1:
            return None
        json_str = content[start + len(_JSON_TAG_OPEN): end]
        try:
            payload = json.loads(json_str)
            # Attach Band-level metadata for traceability
            payload.setdefault("_band_message_id", raw_message.get("id"))
            payload.setdefault("_band_inserted_at", raw_message.get("inserted_at"))
            payload.setdefault("_band_sender_type", raw_message.get("sender_type"))
            return payload
        except json.JSONDecodeError as exc:
            logger.warning("BandRoom: failed to decode PayGuard JSON from message: %s", exc)
            return None

    async def _get_agent_handle(self) -> str:
        """Return the agent's handle (e.g. ``john_doe/my-agent``) from its profile."""
        profile = await self._client.get_agent_profile()
        return profile.get("handle", "payguard-agent")

    def _validate_payload(self, payload: dict) -> None:
        """
        Warn (but do not raise) if a required field is missing from an agent message.

        Required for agent messages:   agent (str), sequence (int), timestamp (str)
        Required for HITL messages:    type = "needs_clarification" | "human_response"
        """
        msg_type = payload.get("type")
        if msg_type in ("needs_clarification", "human_response"):
            # HITL message — valid as-is
            return
        # Agent message
        missing = [f for f in ("agent", "sequence") if f not in payload]
        if missing:
            logger.warning(
                "BandRoom.publish: message is missing recommended fields %s. "
                "Schema: {agent, sequence, timestamp, ...}",
                missing,
            )

    # ── Core message operations ───────────────────────────────────────────────

    async def publish(self, message: dict) -> None:
        """
        Publish a JSON-serialisable dict to this Band room.

        Automatically adds ``published_at`` (ISO-8601 UTC) if not present.
        Logs a schema warning if ``agent`` or ``sequence`` fields are absent
        and this is not a HITL message.

        Parameters
        ----------
        message:
            Payload dict.  Must be JSON-serialisable.

        Raises
        ------
        BandConnectionError
            If the Band API call fails.
        """
        # Add timestamp if missing
        if "published_at" not in message:
            message = {
                **message,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }

        self._validate_payload(message)

        agent_handle = await self._get_agent_handle()
        agent_id = (await self._client.get_agent_profile()).get("id", "")
        content = self._encode_message(message, agent_handle)

        body = {
            "message": {
                "content": content,
                "mentions": [
                    {
                        "id": agent_id,
                        "handle": agent_handle,
                        "name": agent_handle.split("/")[-1] if "/" in agent_handle else agent_handle,
                    }
                ],
            }
        }

        try:
            resp = await self._client._http.post(
                f"/agent/chats/{self._room_id}/messages",
                json=body,
            )
            resp.raise_for_status()
            logger.debug(
                "BandRoom '%s': published message (agent=%s)",
                self._name,
                message.get("agent", message.get("type", "unknown")),
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "BandRoom.publish HTTP error %s: %s",
                exc.response.status_code,
                exc.response.text[:300],
            )
            raise BandConnectionError(
                f"Failed to publish to Band room '{self._name}': "
                f"HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("BandRoom.publish connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def get_messages(self) -> list[dict]:
        """
        Return all PayGuard messages in this room in chronological order.

        Fetches all pages from Band (uses ``status=all`` to include already-
        processed messages) and decodes each one from its embedded JSON.
        Plain Band system messages without a PayGuard JSON block are omitted.

        Returns
        -------
        list[dict]
            Decoded payload dicts in insertion order.

        Raises
        ------
        BandConnectionError
        """
        all_raw: list[dict] = []
        page = 1
        page_size = 100  # Maximum per page to reduce round-trips

        try:
            while True:
                resp = await self._client._http.get(
                    f"/agent/chats/{self._room_id}/messages",
                    params={"status": "all", "page": page, "page_size": page_size},
                )
                resp.raise_for_status()
                body = resp.json()
                messages = body.get("data", [])
                all_raw.extend(messages)

                meta = body.get("metadata", {})
                has_more = meta.get("has_more", False)
                if not has_more or not messages:
                    break
                page += 1
        except httpx.HTTPStatusError as exc:
            logger.error("BandRoom.get_messages HTTP error: %s", exc)
            raise BandConnectionError(
                f"Failed to fetch messages from Band room '{self._name}': "
                f"HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            logger.error("BandRoom.get_messages connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

        # Decode and filter — skip messages without PayGuard JSON
        decoded = [self._decode_message(m) for m in all_raw]
        return [m for m in decoded if m is not None]

    async def get_messages_by_agent(self, agent_name: str) -> list[dict]:
        """
        Return all messages published by a specific agent.

        Parameters
        ----------
        agent_name:
            Value of the ``agent`` field in the message payload.

        Returns
        -------
        list[dict]
        """
        all_messages = await self.get_messages()
        return [m for m in all_messages if m.get("agent") == agent_name]

    # ── Polling / wait operations ─────────────────────────────────────────────

    async def wait_for_agent(
        self, agent_name: str, timeout_seconds: int = 30
    ) -> Optional[dict]:
        """
        Poll every 500 ms until a message from ``agent_name`` appears in the
        room, or until ``timeout_seconds`` elapses.

        Parameters
        ----------
        agent_name:
            The ``agent`` field value to wait for.
        timeout_seconds:
            Maximum wait time.  Returns ``None`` on timeout.

        Returns
        -------
        dict | None
            The first matching message, or ``None`` on timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            try:
                messages = await self.get_messages_by_agent(agent_name)
                if messages:
                    logger.info(
                        "BandRoom '%s': received message from agent '%s'",
                        self._name, agent_name,
                    )
                    return messages[-1]  # Return the most recent
            except BandConnectionError as exc:
                logger.warning("BandRoom.wait_for_agent poll error (will retry): %s", exc)
            await asyncio.sleep(0.5)
        logger.warning(
            "BandRoom '%s': timeout waiting for agent '%s' after %ds",
            self._name, agent_name, timeout_seconds,
        )
        return None

    async def wait_for_agents(
        self, agent_names: list[str], timeout_seconds: int = 60
    ) -> dict[str, Optional[dict]]:
        """
        Wait for all listed agents to publish a message.

        Polls every 500 ms and accumulates results.  Returns as soon as all
        agents have posted, or when ``timeout_seconds`` is reached.

        Parameters
        ----------
        agent_names:
            List of ``agent`` field values to wait for.
        timeout_seconds:
            Maximum total wait time.

        Returns
        -------
        dict[str, dict | None]
            Mapping from agent_name to the received message (or ``None``).
        """
        results: dict[str, Optional[dict]] = {name: None for name in agent_names}
        pending = set(agent_names)
        deadline = asyncio.get_event_loop().time() + timeout_seconds

        while pending and asyncio.get_event_loop().time() < deadline:
            try:
                messages = await self.get_messages()
                for msg in messages:
                    agent = msg.get("agent")
                    if agent in pending:
                        results[agent] = msg
                        pending.discard(agent)
            except BandConnectionError as exc:
                logger.warning("BandRoom.wait_for_agents poll error (will retry): %s", exc)
            if pending:
                await asyncio.sleep(0.5)

        if pending:
            logger.warning(
                "BandRoom '%s': timeout — still waiting for agents: %s",
                self._name, pending,
            )
        return results

    async def wait_for_human_response(
        self, timeout_seconds: int = 300
    ) -> Optional[dict]:
        """
        Poll every 500 ms until a message with ``type="human_response"`` appears,
        or until ``timeout_seconds`` elapses (default 5 minutes for HITL).

        Returns
        -------
        dict | None
            The human_response message, or ``None`` on timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            try:
                messages = await self.get_messages()
                for msg in messages:
                    if msg.get("type") == "human_response":
                        logger.info(
                            "BandRoom '%s': received human_response", self._name
                        )
                        return msg
            except BandConnectionError as exc:
                logger.warning(
                    "BandRoom.wait_for_human_response poll error (will retry): %s", exc
                )
            await asyncio.sleep(0.5)
        logger.warning(
            "BandRoom '%s': timeout waiting for human_response after %ds",
            self._name, timeout_seconds,
        )
        return None

    # ── Context / LLM helpers ─────────────────────────────────────────────────

    async def get_full_context(self) -> str:
        """
        Return all room messages formatted as a string suitable for LLM context injection.

        Format
        ------
        ::

            === Band Room: txn-abc123 ===

            [Agent: domain_intel]
            {"agent": "domain_intel", "sequence": 1, ...}

            [Agent: qr_scanner]
            {"agent": "qr_scanner", "sequence": 2, ...}

            [Human Response]
            {"type": "human_response", "human_answer": "Yes"}

        Returns
        -------
        str
            Formatted multi-line string ready for LLM prompt injection.
        """
        messages = await self.get_messages()

        lines: list[str] = [f"=== Band Room: {self._name} ===\n"]
        for msg in messages:
            msg_type = msg.get("type")
            if msg_type == "human_response":
                label = "[Human Response]"
            elif msg_type == "needs_clarification":
                label = "[Needs Clarification]"
            else:
                agent = msg.get("agent", "unknown")
                label = f"[Agent: {agent}]"

            # Pretty-print the payload (strip internal Band metadata keys)
            display = {k: v for k, v in msg.items() if not k.startswith("_band_")}
            lines.append(label)
            lines.append(json.dumps(display, indent=2, ensure_ascii=False))
            lines.append("")  # blank line separator

        return "\n".join(lines)
