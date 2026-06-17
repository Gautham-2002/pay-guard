"""LangGraph tools that expose PayGuard's specialist analysis code."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class EphemeralBandRoom:
    """
    Minimal BandRoom-compatible context used by remote-agent tools.

    The existing specialist agents expect a BandRoom for context and publishing.
    Remote agents already run inside Band via the SDK, so this room captures
    tool outputs locally and lets the adapter publish/hand off through Band.
    """

    def __init__(self, context: str = "", room_id: str = "band-remote-room") -> None:
        self._context = context
        self._room_id = room_id
        self._published: list[dict[str, Any]] = []

    @property
    def id(self) -> str:
        return self._room_id

    @property
    def name(self) -> str:
        return "Band remote room"

    async def publish(self, message: dict) -> None:
        if "published_at" not in message:
            message = {
                **message,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        self._published.append(message)

    async def get_messages(self) -> list[dict]:
        return list(self._published)

    async def get_messages_by_agent(self, agent_name: str) -> list[dict]:
        return [m for m in self._published if m.get("agent") == agent_name]

    async def get_full_context(self) -> str:
        lines = []
        if self._context:
            lines.extend(["=== Existing Band Context ===", self._context, ""])
        for message in self._published:
            lines.append(json.dumps(message, ensure_ascii=False, indent=2))
        return "\n".join(lines)


def _to_json_payload(value: Any) -> str:
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def build_tools_for_agent(config_key: str) -> list[object]:
    """Return LangChain tools for one PayGuard remote agent."""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise RuntimeError(
            "Remote tools require langchain-core. Install `band-sdk[langgraph]`."
        ) from exc

    if config_key == "destination_intelligence":

        async def analyze_destination(
            payment_url: str | None = None,
            upi_id: str | None = None,
            amount: float | None = None,
            product_description: str | None = None,
            source_type: str | None = None,
            additional_context: str | None = None,
        ) -> str:
            """Analyze URL/UPI destination intelligence and return Agent 1 JSON."""
            from agents import agent1_destination

            room = EphemeralBandRoom()
            output = await agent1_destination.run(
                band_room=room,  # type: ignore[arg-type]
                url=payment_url,
                upi_id=upi_id,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            return _to_json_payload(output)

        return [
            StructuredTool.from_function(
                coroutine=analyze_destination,
                name="payguard_analyze_destination",
                description=(
                    "Analyze a payment URL or UPI ID using PayGuard destination "
                    "intelligence. Use this before handing off to QR/UPI validation."
                ),
            )
        ]

    if config_key == "qr_upi_validator":

        async def validate_qr_upi_context(
            band_context: str,
            upi_id: str | None = None,
            payment_url: str | None = None,
            amount: float | None = None,
            product_description: str | None = None,
            source_type: str | None = None,
            additional_context: str | None = None,
        ) -> str:
            """Validate UPI/QR payment context and return Agent 2 JSON."""
            from agents import agent2_qr_upi

            room = EphemeralBandRoom(context=band_context)
            output = await agent2_qr_upi.run(
                band_room=room,  # type: ignore[arg-type]
                qr_image_bytes=None,
                upi_id=upi_id,
                url=payment_url,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            return _to_json_payload(output)

        return [
            StructuredTool.from_function(
                coroutine=validate_qr_upi_context,
                name="payguard_validate_qr_upi_context",
                description=(
                    "Validate UPI and QR social-engineering context using prior Band "
                    "findings. Pass the relevant Band room context as band_context."
                ),
            )
        ]

    if config_key == "web_intelligence":

        async def run_web_intelligence(
            band_context: str,
            payment_url: str | None = None,
            upi_id: str | None = None,
            amount: float | None = None,
            product_description: str | None = None,
            source_type: str | None = None,
            additional_context: str | None = None,
        ) -> str:
            """Run web/search/price intelligence and return Agent 3 JSON."""
            from agents import agent3_web_intelligence

            room = EphemeralBandRoom(context=band_context)
            output = await agent3_web_intelligence.run(
                band_room=room,  # type: ignore[arg-type]
                url=payment_url,
                upi_id=upi_id,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            return _to_json_payload(output)

        return [
            StructuredTool.from_function(
                coroutine=run_web_intelligence,
                name="payguard_run_web_intelligence",
                description=(
                    "Run PayGuard web intelligence using URL, UPI, amount, product, "
                    "and prior Band findings."
                ),
            )
        ]

    if config_key == "verdict_synthesis":

        async def synthesize_final_verdict(
            band_context: str,
            payment_url: str | None = None,
            upi_id: str | None = None,
            amount: float | None = None,
            product_description: str | None = None,
            source_type: str | None = None,
            additional_context: str | None = None,
        ) -> str:
            """Synthesize the final PayGuard verdict and return Agent 4 JSON."""
            from agents import agent4_verdict

            room = EphemeralBandRoom(context=band_context)
            output = await agent4_verdict.run(
                band_room=room,  # type: ignore[arg-type]
                url=payment_url,
                upi_id=upi_id,
                amount=amount,
                product_description=product_description,
                source_type=source_type,
                additional_context=additional_context,
            )
            return _to_json_payload(output)

        return [
            StructuredTool.from_function(
                coroutine=synthesize_final_verdict,
                name="payguard_synthesize_final_verdict",
                description=(
                    "Synthesize final SAFE/VERIFY/DANGER verdict from the complete "
                    "Band room context."
                ),
            )
        ]

    raise RuntimeError(f"No PayGuard remote tools registered for '{config_key}'.")
