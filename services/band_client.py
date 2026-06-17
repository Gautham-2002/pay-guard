"""
Band Client — Band Room Coordination Layer
==========================================
Wraps the Band Agent API (https://app.band.ai/api/v1) for async room, event,
and context operations used by all PayGuard AI agents.

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
PayGuard pipeline records are internal audit/context updates, not routed
agent-to-agent chat messages.  Band text messages require an @mention of
another room participant and agents cannot mention themselves, so ``publish()``
stores pipeline payloads as Band ``task`` events.  Routed chat messages remain
available through ``publish_routed_message()`` for cases where PayGuard needs
to explicitly contact a human or peer agent.

Format written to Band event content:
    <PAYGUARD_JSON>{...json payload...}</PAYGUARD_JSON>

Implemented in: Phase 1
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

import httpx

logger = logging.getLogger(__name__)

# ─── Band API Constants ────────────────────────────────────────────────────────

BAND_BASE_URL = "https://app.band.ai/api/v1"
_JSON_TAG_OPEN = "<PAYGUARD_JSON>"
_JSON_TAG_CLOSE = "</PAYGUARD_JSON>"

# ─── Custom Exceptions ────────────────────────────────────────────────────────


class BandConnectionError(Exception):
    """Raised when the Band API is unreachable or returns an unexpected HTTP error."""


class BandAuthenticationError(BandConnectionError):
    """Raised when the configured Band API key is missing or rejected."""


class BandTimeoutError(Exception):
    """Raised when a wait_for_* poll operation exceeds its timeout."""


def _raise_band_http_error(action: str, exc: httpx.HTTPStatusError) -> None:
    """Raise a Band exception with an actionable message for common HTTP errors."""
    status_code = exc.response.status_code
    body = exc.response.text[:300]
    if status_code == 401:
        raise BandAuthenticationError(
            f"{action}: HTTP 401. BAND_API_KEY was rejected by Band. Use a valid "
            "Band Agent API key for the FastAPI app shell."
        ) from exc
    raise BandConnectionError(f"{action}: HTTP {status_code}. Response: {body}") from exc


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
        Band Agent API key for the app shell. Defaults to ``os.getenv("BAND_API_KEY")``.

    Usage
    -----
    ::

        client = BandClient()
        room = await client.create_room("txn-abc123")
        await room.publish({"agent": "domain_intel", "sequence": 1, "result": {...}})
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key: str = api_key or os.getenv("BAND_API_KEY", "")
        print("===============")
        print(api_key,os.getenv("BAND_API_KEY", ""))
        print("init", self.api_key)
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
        Return the authenticated Band profile (id, name, handle).
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
            _raise_band_http_error("Failed to fetch Band agent profile", exc)
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
            print("create room", self.api_key)
            
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
            _raise_band_http_error(f"Failed to create Band room '{name}'", exc)
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
            _raise_band_http_error(f"Failed to get Band room '{room_id}'", exc)
        except httpx.RequestError as exc:
            logger.error("Band get_room connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def get_peers(self, not_in_chat: Optional[str] = None) -> list[dict]:
        """Return peers this agent can recruit into Band rooms."""
        params = {"not_in_chat": not_in_chat} if not_in_chat else None
        try:
            resp = await self._http.get("/agent/peers", params=params)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return data if isinstance(data, list) else []
        except httpx.HTTPStatusError as exc:
            logger.error("Band get_peers HTTP error: %s", exc)
            _raise_band_http_error("Failed to list Band peers", exc)
        except httpx.RequestError as exc:
            logger.error("Band get_peers connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def find_peer_by_handle(
        self,
        handle: str,
        not_in_chat: Optional[str] = None,
    ) -> Optional[dict]:
        """Find a recruitable Band peer by exact handle."""
        peers = await self.get_peers(not_in_chat=not_in_chat)
        available_handles = [p.get("handle") for p in peers]
        logger.info(
            "Band peers available (not_in_chat=%s): %s — looking for '%s'",
            not_in_chat,
            available_handles,
            handle,
        )
        for peer in peers:
            if peer.get("handle") == handle:
                return peer
        return None

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

    def _encode_payload(self, payload: dict) -> str:
        """
        Encode a dict payload into a Band-compatible content string.

        The XML-like tag keeps PayGuard payloads easy to extract from Band
        context entries without depending on the display text around them.
        """
        json_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return f"{_JSON_TAG_OPEN}{json_str}{_JSON_TAG_CLOSE}"

    def _decode_payload_from_content(self, content: str) -> Optional[dict]:
        """Extract a PayGuard JSON payload from a Band content string."""
        start = content.find(_JSON_TAG_OPEN)
        end = content.find(_JSON_TAG_CLOSE)
        if start == -1 or end == -1 or end < start:
            return None
        json_str = content[start + len(_JSON_TAG_OPEN): end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("BandRoom: failed to decode PayGuard JSON from content: %s", exc)
            return None

    def _decode_message(self, raw_message: dict) -> Optional[dict]:
        """
        Parse a raw Band message dict into a PayGuard payload dict.

        Returns None if the message does not contain an embedded PayGuard
        JSON block (i.e., it is a plain Band system message).
        """
        content: str = raw_message.get("content", "")
        payload = self._decode_payload_from_content(content)
        if payload is None:
            return None
        # Attach Band-level metadata for traceability
        payload.setdefault("_band_message_id", raw_message.get("id"))
        payload.setdefault("_band_inserted_at", raw_message.get("inserted_at"))
        payload.setdefault("_band_sender_type", raw_message.get("sender_type"))
        return payload

    def _decode_context_entry(self, entry: dict) -> Optional[dict]:
        """
        Parse a Band context entry into a PayGuard payload.

        Band context payloads can include messages and events.  SDK/API versions
        differ a little in shape, so this accepts both direct ``content`` fields
        and nested ``message``/``event`` objects.
        """
        candidate = entry
        for key in ("message", "event"):
            if isinstance(entry.get(key), dict):
                candidate = entry[key]
                break

        payload: Optional[dict] = None
        metadata = candidate.get("metadata")
        if isinstance(metadata, dict):
            metadata_payload = metadata.get("payguard_payload")
            if isinstance(metadata_payload, dict):
                payload = metadata_payload

        if payload is None:
            content = str(candidate.get("content", ""))
            payload = self._decode_payload_from_content(content)

        if payload is None:
            return None

        payload.setdefault("_band_message_id", candidate.get("id") or entry.get("id"))
        payload.setdefault(
            "_band_inserted_at",
            candidate.get("inserted_at") or entry.get("inserted_at"),
        )
        payload.setdefault(
            "_band_sender_type",
            candidate.get("sender_type") or entry.get("sender_type") or "agent",
        )
        payload.setdefault(
            "_band_record_type",
            candidate.get("message_type") or entry.get("message_type") or entry.get("type"),
        )
        return payload

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

    async def add_participant_by_handle(self, handle: str) -> dict:
        """
        Recruit a peer into this Band room by handle.

        The app-shell Band key must have the peer in its reachable peer network.

        Band API v1 schema (confirmed from docs):
            POST /agent/chats/:chat_id/participants
            Body: {"participant": {"participant_id": "<uuid>", "role": "member"}}
        Only ``participant_id`` (UUID) and ``role`` are accepted; ``id``,
        ``handle``, and ``type`` are all rejected with HTTP 422.
        """
        peer = await self._client.find_peer_by_handle(handle, not_in_chat=self._room_id)
        if peer is None:
            raise BandConnectionError(
                f"Band peer '@{handle}' was not found or is already unavailable for room "
                f"'{self._name}'. Make sure the agents are siblings/contacts in Band."
            )

        participant_id = peer.get("id") or peer.get("agent_id") or peer.get("user_id")
        if not participant_id:
            raise BandConnectionError(
                f"Band peer '@{handle}' did not include a UUID (id/agent_id/user_id)."
            )

        participant_body = {
            "participant": {
                "participant_id": participant_id,
            }
        }
        try:
            resp = await self._client._http.post(
                f"/agent/chats/{self._room_id}/participants",
                json=participant_body,
            )
            resp.raise_for_status()
            data = resp.json().get("data", peer)
            # Ensure downstream callers can still resolve an id from the response.
            if not data.get("id") and not data.get("agent_id"):
                data = {**data, "id": participant_id}
            return data
        except httpx.HTTPStatusError as exc:
            logger.error(
                "BandRoom.add_participant_by_handle HTTP error %s: %s",
                exc.response.status_code,
                exc.response.text[:300],
            )
            _raise_band_http_error(
                f"Failed to add participant '@{handle}' to Band room '{self._name}'",
                exc,
            )
        except httpx.RequestError as exc:
            logger.error("BandRoom.add_participant_by_handle connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def publish(self, message: dict) -> None:
        """
        Publish a JSON-serialisable PayGuard record to this Band room.

        Records are written as Band ``task`` events.  This is the correct shape
        for the app-owned sequential pipeline because these payloads are audit
        and shared-context records, not chat messages that should wake another
        Band participant.

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

        content = self._encode_payload(message)
        body = {
            "event": {
                "content": content,
                "message_type": "task",
                "metadata": {
                    "source": "payguard",
                    "payguard_payload": message,
                },
            }
        }

        try:
            resp = await self._client._http.post(
                f"/agent/chats/{self._room_id}/events",
                json=body,
            )
            resp.raise_for_status()
            logger.debug(
                "BandRoom '%s': published event (agent=%s)",
                self._name,
                message.get("agent", message.get("type", "unknown")),
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "BandRoom.publish HTTP error %s: %s",
                exc.response.status_code,
                exc.response.text[:300],
            )
            _raise_band_http_error(
                f"Failed to publish event to Band room '{self._name}'",
                exc,
            )
        except httpx.RequestError as exc:
            logger.error("BandRoom.publish connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def publish_routed_message_to_handle(
        self,
        message: dict,
        *,
        participant_handle: str,
    ) -> None:
        """Recruit a handle if needed, then send a routed @mention message."""
        participant = await self.add_participant_by_handle(participant_handle)
        await self.publish_routed_message(
            message,
            participant_id=str(
                participant.get("id")
                or participant.get("agent_id")
                or participant.get("user_id")
                or ""
            ),
            participant_handle=participant_handle,
            participant_name=participant.get("name"),
        )

    async def publish_routed_message(
        self,
        message: dict,
        *,
        participant_id: str,
        participant_handle: str,
        participant_name: Optional[str] = None,
    ) -> None:
        """
        Send a routed Band text message to another room participant.

        Use this only when PayGuard needs Band's @mention routing.  The target
        participant must already be in the room.  Do not pass the authenticated
        agent itself; Band rejects self-mentions.
        """
        if "published_at" not in message:
            message = {
                **message,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        self._validate_payload(message)

        content = f"@{participant_handle} {self._encode_payload(message)}"
        body = {
            "message": {
                "content": content,
                "mentions": [
                    {
                        "id": participant_id,
                        "handle": participant_handle,
                        "name": participant_name or participant_handle.split("/")[-1],
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
                "BandRoom '%s': sent routed message to %s",
                self._name,
                participant_handle,
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "BandRoom.publish_routed_message HTTP error %s: %s",
                exc.response.status_code,
                exc.response.text[:300],
            )
            _raise_band_http_error(
                f"Failed to send routed message in Band room '{self._name}'",
                exc,
            )
        except httpx.RequestError as exc:
            logger.error("BandRoom.publish_routed_message connection error: %s", exc)
            raise BandConnectionError(
                f"Failed to connect to Band API: {exc}"
            ) from exc

    async def get_messages(self) -> list[dict]:
        """
        Return all PayGuard messages in this room in chronological order.

        Reads the Band ``/context`` endpoint first so task events written by
        ``publish()`` are included.  Falls back to ``/messages?status=all`` for
        older Band API deployments or diagnostics.

        Returns
        -------
        list[dict]
            Decoded payload dicts in insertion order.

        Raises
        ------
        BandConnectionError
        """
        try:
            resp = await self._client._http.get(
                f"/agent/chats/{self._room_id}/context",
            )
            resp.raise_for_status()
            body = resp.json()
            context_entries = body.get("data", body)
            if isinstance(context_entries, dict):
                for key in ("context", "messages", "events", "items"):
                    if isinstance(context_entries.get(key), list):
                        context_entries = context_entries[key]
                        break

            if isinstance(context_entries, list):
                decoded = [self._decode_context_entry(e) for e in context_entries if isinstance(e, dict)]
                messages = [m for m in decoded if m is not None]
                if messages:
                    return messages
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "BandRoom.get_messages context endpoint HTTP error %s; falling back to messages",
                exc.response.status_code,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "BandRoom.get_messages context endpoint connection error; falling back to messages: %s",
                exc,
            )

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
            _raise_band_http_error(
                f"Failed to fetch messages from Band room '{self._name}'",
                exc,
            )
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
