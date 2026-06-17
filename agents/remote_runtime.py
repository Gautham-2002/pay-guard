"""No-hop Band runtime for PayGuard specialist agents."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from agents.band_config import (
    RemoteAgentConfig,
    load_remote_agent_config,
    load_remote_agent_configs,
    resolve_next_handle,
)
from services.band_client import (
    decode_payguard_payload_from_content,
    decode_payguard_payload_from_record,
    encode_payguard_payload,
    make_json_safe,
)
from services.qr_artifacts import load_qr_artifact


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

_PAYMENT_CONTEXT_KEYS = (
    "txn_id",
    "payment_url",
    "upi_id",
    "amount",
    "product_description",
    "source_type",
    "additional_context",
    "qr_artifact_ref",
    "qr_image_uploaded",
)


def _first_env(*names: str) -> tuple[str, str] | None:
    """Return the first non-empty environment override and its variable name."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return name, value.strip()
    return None


def _normalize_band_url(env_name: str, raw_url: str, *, default_scheme: str) -> str:
    """Normalize Band URL overrides before passing them into the SDK."""
    url = raw_url.strip()
    parsed = urlparse(url)
    if not parsed.scheme:
        url = f"{default_scheme}://{url}"
        parsed = urlparse(url)

    allowed_schemes = {"ws", "wss"} if default_scheme == "wss" else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        expected = "ws:// or wss://" if default_scheme == "wss" else "http:// or https://"
        raise RuntimeError(
            f"{env_name} must be a valid URL including {expected}; got {raw_url!r}."
        )

    return url


def _load_band_runtime_urls() -> dict[str, str]:
    """Load optional Band SDK endpoint overrides from the environment."""
    runtime_urls: dict[str, str] = {}

    ws_override = _first_env("THENVOI_WS_URL", "BAND_WS_URL")
    if ws_override:
        env_name, value = ws_override
        runtime_urls["ws_url"] = _normalize_band_url(env_name, value, default_scheme="wss")

    rest_override = _first_env("THENVOI_REST_URL", "BAND_REST_URL")
    if rest_override:
        env_name, value = rest_override
        runtime_urls["rest_url"] = _normalize_band_url(
            env_name,
            value,
            default_scheme="https",
        )

    return runtime_urls


def extract_payguard_payload(message: Any) -> dict | None:
    """Extract a PayGuard payload from a Band SDK PlatformMessage-like object."""
    metadata = getattr(message, "metadata", None)
    if isinstance(metadata, dict):
        metadata_payload = metadata.get("payguard_payload")
        if isinstance(metadata_payload, dict):
            return dict(metadata_payload)

    content = str(getattr(message, "content", "") or "")
    return decode_payguard_payload_from_content(content)


def _context_payloads_from_history(history: Any) -> list[dict]:
    """Decode PayGuard payloads from SDK bootstrap history."""
    raw_items = getattr(history, "raw", None)
    if raw_items is None:
        raw_items = history if isinstance(history, list) else []

    payloads: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        payload = decode_payguard_payload_from_record(item)
        if payload is None:
            payload = decode_payguard_payload_from_content(str(item.get("content", "")))
        if payload is not None:
            payloads.append(payload)
    return payloads


def _dedupe_payloads(payloads: list[dict]) -> list[dict]:
    """Dedupe Band payloads while preserving order."""
    seen: set[tuple[str, str, str]] = set()
    result: list[dict] = []
    for payload in payloads:
        key = (
            str(payload.get("_band_message_id") or ""),
            str(payload.get("agent") or payload.get("type") or ""),
            str(payload.get("sequence") or ""),
        )
        if key != ("", "", "") and key in seen:
            continue
        if key != ("", "", ""):
            seen.add(key)
        result.append(payload)
    return result


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _payment_context(payload: dict) -> dict:
    return {key: payload.get(key) for key in _PAYMENT_CONTEXT_KEYS if key in payload}


def _prior_context(payload: dict) -> list[dict]:
    context = payload.get("payguard_context")
    return [item for item in context if isinstance(item, dict)] if isinstance(context, list) else []


class SDKBandRoom:
    """BandRoom-compatible wrapper backed by Band SDK platform tools."""

    def __init__(
        self,
        *,
        room_id: str,
        tools: Any,
        seed_messages: list[dict] | None = None,
    ) -> None:
        self._room_id = room_id
        self._tools = tools
        self._seed_messages = seed_messages or []
        self._published: list[dict] = []

    @property
    def id(self) -> str:
        return self._room_id

    @property
    def name(self) -> str:
        return f"Band room {self._room_id}"

    async def publish(self, message: dict) -> None:
        if "published_at" not in message:
            message = {
                **message,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        self._published.append(message)
        await self._tools.send_event(
            content=encode_payguard_payload(message),
            message_type="task",
            metadata={
                "source": "payguard",
                "payguard_payload": message,
            },
        )

    async def get_messages(self) -> list[dict]:
        payloads: list[dict] = list(self._seed_messages)
        try:
            context = await self._tools.fetch_room_context(room_id=self._room_id)
        except Exception as exc:
            logger.warning("Band SDK context fetch failed for room %s: %s", self._room_id, exc)
            context = {}

        entries = context.get("data", []) if isinstance(context, dict) else []
        for entry in entries:
            if isinstance(entry, dict):
                payload = decode_payguard_payload_from_record(entry)
                if payload is not None:
                    payloads.append(payload)

        payloads.extend(self._published)
        return _dedupe_payloads(payloads)

    async def get_messages_by_agent(self, agent_name: str) -> list[dict]:
        return [m for m in await self.get_messages() if m.get("agent") == agent_name]

    async def get_full_context(self) -> str:
        import json

        messages = await self.get_messages()
        lines = [f"=== Band Room: {self.name} ==="]
        for message in messages:
            lines.append(json.dumps(make_json_safe(message), ensure_ascii=False, indent=2))
        return "\n".join(lines)


async def _run_local_agent(
    *,
    config_key: str,
    band_room: SDKBandRoom,
    payload: dict,
) -> Any:
    """Dispatch a structured Band payload to the matching PayGuard agent."""
    args = {
        "upi_id": payload.get("upi_id"),
        "amount": payload.get("amount"),
        "product_description": payload.get("product_description"),
        "source_type": payload.get("source_type"),
        "additional_context": payload.get("additional_context"),
    }

    if config_key == "destination_intelligence":
        from agents import agent1_destination

        return await agent1_destination.run(
            band_room=band_room,  # type: ignore[arg-type]
            url=payload.get("payment_url"),
            **args,
        )

    if config_key == "qr_upi_validator":
        from agents import agent2_qr_upi

        qr_image_bytes = load_qr_artifact(payload.get("qr_artifact_ref"))
        return await agent2_qr_upi.run(
            band_room=band_room,  # type: ignore[arg-type]
            qr_image_bytes=qr_image_bytes,
            url=payload.get("payment_url"),
            **args,
        )

    if config_key == "web_intelligence":
        from agents import agent3_web_intelligence

        return await agent3_web_intelligence.run(
            band_room=band_room,  # type: ignore[arg-type]
            url=payload.get("payment_url"),
            **args,
        )

    if config_key == "verdict_synthesis":
        from agents import agent4_verdict

        return await agent4_verdict.run(
            band_room=band_room,  # type: ignore[arg-type]
            url=payload.get("payment_url"),
            **args,
        )

    raise RuntimeError(f"No local PayGuard agent registered for '{config_key}'.")


class PayGuardBandAdapter:
    """
    Deterministic Band SDK adapter for PayGuard agents.

    This is intentionally not an LLM adapter.  It uses Band for transport,
    context, audit trail, and handoff; model reasoning stays inside the local
    specialist agents through Featherless and AI/ML API clients.
    """

    def __init__(
        self,
        *,
        config: RemoteAgentConfig,
        all_configs: dict[str, RemoteAgentConfig],
    ) -> None:
        try:
            from band.core.simple_adapter import SimpleAdapter
        except ImportError:
            self._adapter = self
        else:
            outer = self

            class _Adapter(SimpleAdapter):
                async def on_message(inner_self, msg, tools, history, participants_msg, contacts_msg, *, is_session_bootstrap, room_id):  # type: ignore[no-untyped-def]
                    await outer.on_message(
                        msg=msg,
                        tools=tools,
                        history=history,
                        room_id=room_id,
                    )

            self._adapter = _Adapter()
        self.config = config
        self.all_configs = all_configs
        self.log = logging.getLogger(f"payguard.{config.key}")

    async def on_message(self, *, msg: Any, tools: Any, history: Any, room_id: str) -> None:
        payload = extract_payguard_payload(msg)
        if payload is None:
            await tools.send_event(
                content="PayGuard ignored a Band message without a structured payload.",
                message_type="error",
                metadata={
                    "source": "payguard",
                    "agent": self.config.key,
                    "reason": "missing_payguard_payload",
                    "message_id": getattr(msg, "id", None),
                },
            )
            return

        self.log.info(
            "Received PayGuard payload | room=%s | txn_id=%s",
            room_id,
            payload.get("txn_id"),
        )

        seed_messages = _dedupe_payloads(
            _context_payloads_from_history(history) + _prior_context(payload)
        )
        band_room = SDKBandRoom(
            room_id=room_id,
            tools=tools,
            seed_messages=seed_messages,
        )

        try:
            output = await _run_local_agent(
                config_key=self.config.key,
                band_room=band_room,
                payload=payload,
            )
        except Exception as exc:
            self.log.exception("PayGuard agent failed | txn_id=%s", payload.get("txn_id"))
            await tools.send_event(
                content=f"PayGuard {self.config.key} failed: {exc}",
                message_type="error",
                metadata={
                    "source": "payguard",
                    "agent": self.config.key,
                    "txn_id": payload.get("txn_id"),
                    "error": str(exc),
                },
            )
            return

        try:
            await self._handoff_if_needed(
                tools=tools,
                payload=payload,
                room=band_room,
                output=_json_safe(output),
            )
        except Exception as exc:
            self.log.exception("PayGuard handoff failed | txn_id=%s", payload.get("txn_id"))
            await tools.send_event(
                content=f"PayGuard {self.config.key} handoff failed: {exc}",
                message_type="error",
                metadata={
                    "source": "payguard",
                    "agent": self.config.key,
                    "txn_id": payload.get("txn_id"),
                    "error": str(exc),
                    "stage": "handoff",
                },
            )

    async def _handoff_if_needed(
        self,
        *,
        tools: Any,
        payload: dict,
        room: SDKBandRoom,
        output: dict,
    ) -> None:
        next_handle = resolve_next_handle(self.config, self.all_configs)
        if not next_handle:
            self.log.info("Final PayGuard agent completed | txn_id=%s", payload.get("txn_id"))
            return

        messages = await room.get_messages()
        agent_outputs = [m for m in messages if m.get("agent")]
        if not any(m.get("agent") == self.config.key for m in agent_outputs):
            if isinstance(output, dict):
                agent_outputs.append(output)

        handoff_payload = {
            **_payment_context(payload),
            "type": "payguard_agent_handoff",
            "txn_id": payload.get("txn_id"),
            "from_agent": self.config.key,
            "to_agent": next_handle,
            "completed_agents": [
                m.get("agent") for m in agent_outputs if isinstance(m.get("agent"), str)
            ],
            "payguard_context": agent_outputs,
        }

        try:
            await tools.add_participant(next_handle)
        except Exception as exc:
            self.log.debug("Could not add @%s before handoff; trying mention anyway: %s", next_handle, exc)

        await tools.send_message(
            content=f"@{next_handle} {encode_payguard_payload(handoff_payload)}",
            mentions=[f"@{next_handle}"],
        )
        self.log.info(
            "Handed off PayGuard txn_id=%s from %s to @%s",
            payload.get("txn_id"),
            self.config.key,
            next_handle,
        )

    def as_sdk_adapter(self) -> Any:
        return self._adapter


async def run_remote_agent(
    *,
    config_key: str,
    display_name: str | None = None,
    provider: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int | None = None,
) -> None:
    """Load credentials, create a no-hop Band remote agent, and wait for mentions."""
    del provider, system_prompt, max_tokens
    load_dotenv()

    try:
        from band import Agent
        from band.config import load_agent_config
    except ImportError as exc:
        raise RuntimeError(
            "Band remote-agent SDK is missing. Install the remote-agents extra, "
            "then rerun this agent."
        ) from exc

    all_configs = load_remote_agent_configs()
    config = load_remote_agent_config(config_key)
    agent_id, api_key = load_agent_config(config_key)

    resolved_display_name = display_name or config.display_name
    runtime = PayGuardBandAdapter(config=config, all_configs=all_configs)

    logger.info(
        "Loaded %s credentials | agent_id=%s | handle=@%s | mode=no-hop",
        resolved_display_name,
        agent_id,
        config.handle,
    )

    agent = Agent.create(
        adapter=runtime.as_sdk_adapter(),
        agent_id=agent_id,
        api_key=api_key,
        **_load_band_runtime_urls(),
    )

    logger.info("%s is online and waiting for Band mentions", resolved_display_name)
    await agent.run()


def run_cli(**kwargs: Any) -> None:
    """Synchronous console-script bridge for async remote-agent runners."""
    asyncio.run(run_remote_agent(**kwargs))
