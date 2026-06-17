from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from agents.band_config import RemoteAgentConfig, load_remote_agent_configs
from agents.remote_runtime import (
    PayGuardBandAdapter,
    _load_band_runtime_urls,
    extract_payguard_payload,
)
from services.band_client import encode_payguard_payload
from services.qr_artifacts import load_qr_artifact, save_qr_artifact


def _config(key: str, handle: str, next_agent_key: str | None = None) -> RemoteAgentConfig:
    return RemoteAgentConfig(
        key=key,
        agent_id=f"{key}-id",
        api_key=f"{key}-api-key",
        handle=handle,
        display_name=key.replace("_", " ").title(),
        provider="aiml",
        model=None,
        max_tokens=4096,
        next_agent_key=next_agent_key,
    )


@dataclass
class FakeMessage:
    content: str
    metadata: dict | None = None
    id: str = "msg-1"


class FakeTools:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.messages: list[dict] = []
        self.participants_added: list[str] = []
        self.context: list[dict] = []

    async def send_event(self, content: str, message_type: str, metadata: dict | None = None):
        self.events.append(
            {"content": content, "message_type": message_type, "metadata": metadata or {}}
        )

    async def send_message(self, content: str, mentions: list[str] | None = None):
        self.messages.append({"content": content, "mentions": mentions or []})

    async def add_participant(self, identifier: str, role: str = "member"):
        self.participants_added.append(identifier)

    async def fetch_room_context(self, *, room_id: str, page: int = 1, page_size: int = 50):
        return {"data": self.context, "meta": {"page": page, "page_size": page_size}}


def test_remote_agent_config_loads_handles_and_handoffs(tmp_path):
    config_path = tmp_path / "agent_config.yaml"
    config_path.write_text(
        """
destination_intelligence:
  agent_id: "agent-1"
  api_key: "band-api-1"
  handle: "team/destination"
  display_name: "Destination"
  provider: "featherless"
  model: "meta-llama/Llama-3.3-70B-Instruct"
  max_tokens: 4096
  next_agent_key: "qr_upi_validator"

qr_upi_validator:
  agent_id: "agent-2"
  api_key: "band-api-2"
  handle: "team/qr"
  display_name: "QR"
  provider: "aiml"
  model: "gpt-4o"
  max_tokens: 4096
  next_agent_key: null
""",
        encoding="utf-8",
    )

    configs = load_remote_agent_configs(config_path)

    assert configs["destination_intelligence"].handle == "team/destination"
    assert configs["destination_intelligence"].next_agent_key == "qr_upi_validator"
    assert configs["qr_upi_validator"].handle == "team/qr"


def test_extract_payguard_payload_prefers_metadata():
    msg = FakeMessage(
        content=encode_payguard_payload({"txn_id": "from-content"}),
        metadata={"payguard_payload": {"txn_id": "from-metadata"}},
    )

    assert extract_payguard_payload(msg) == {"txn_id": "from-metadata"}


def test_band_runtime_urls_normalize_bare_hosts(monkeypatch):
    monkeypatch.delenv("BAND_WS_URL", raising=False)
    monkeypatch.delenv("BAND_REST_URL", raising=False)
    monkeypatch.setenv("THENVOI_WS_URL", "app.band.ai/api/v1/socket/websocket")
    monkeypatch.setenv("THENVOI_REST_URL", "app.band.ai")

    assert _load_band_runtime_urls() == {
        "ws_url": "wss://app.band.ai/api/v1/socket/websocket",
        "rest_url": "https://app.band.ai",
    }


def test_band_runtime_urls_reject_invalid_schemes(monkeypatch):
    monkeypatch.delenv("THENVOI_WS_URL", raising=False)
    monkeypatch.delenv("BAND_WS_URL", raising=False)
    monkeypatch.delenv("BAND_REST_URL", raising=False)
    monkeypatch.setenv("THENVOI_REST_URL", "ftp://app.band.ai")

    with pytest.raises(RuntimeError, match="THENVOI_REST_URL must be a valid URL"):
        _load_band_runtime_urls()


def test_direct_adapter_runs_agent_and_hands_off(monkeypatch):
    from agents import remote_runtime

    async def fake_run_local_agent(*, config_key, band_room, payload):
        assert config_key == "destination_intelligence"
        assert payload["payment_url"] == "https://example.test/pay"
        await band_room.publish(
            {
                "agent": "destination_intelligence",
                "sequence": 1,
                "risk_level": "LOW",
                "agent_narrative": "Destination looks consistent.",
                "timestamp": "2026-06-17T00:00:00Z",
            }
        )
        return {"agent": "destination_intelligence", "sequence": 1}

    monkeypatch.setattr(remote_runtime, "_run_local_agent", fake_run_local_agent)

    configs = {
        "destination_intelligence": _config(
            "destination_intelligence",
            "team/destination",
            next_agent_key="qr_upi_validator",
        ),
        "qr_upi_validator": _config("qr_upi_validator", "team/qr"),
    }
    runtime = PayGuardBandAdapter(
        config=configs["destination_intelligence"],
        all_configs=configs,
    )
    tools = FakeTools()
    msg = FakeMessage(
        content=encode_payguard_payload(
            {
                "type": "payment_check_request",
                "txn_id": "txn-1",
                "payment_url": "https://example.test/pay",
                "amount": 199.0,
            }
        )
    )

    asyncio.run(runtime.on_message(msg=msg, tools=tools, history=[], room_id="room-1"))

    assert tools.events[0]["message_type"] == "task"
    assert tools.participants_added == ["team/qr"]
    assert tools.messages
    assert tools.messages[0]["mentions"] == ["@team/qr"]
    assert "payguard_agent_handoff" in tools.messages[0]["content"]


def test_final_adapter_does_not_handoff(monkeypatch):
    from agents import remote_runtime

    async def fake_run_local_agent(*, config_key, band_room, payload):
        assert config_key == "verdict_synthesis"
        await band_room.publish(
            {
                "agent": "verdict_synthesis",
                "sequence": 4,
                "verdict": "SAFE",
                "risk_score": 10,
                "plain_english_summary": "Looks safe.",
                "recommended_actions": [],
                "ask_merchant": [],
                "agent_agreement": "ALL_AGREE",
                "band_room_id": band_room.id,
                "timestamp": "2026-06-17T00:00:00Z",
            }
        )
        return {"agent": "verdict_synthesis", "sequence": 4}

    monkeypatch.setattr(remote_runtime, "_run_local_agent", fake_run_local_agent)

    config = _config("verdict_synthesis", "team/verdict")
    runtime = PayGuardBandAdapter(config=config, all_configs={"verdict_synthesis": config})
    tools = FakeTools()
    msg = FakeMessage(content=encode_payguard_payload({"txn_id": "txn-1"}))

    asyncio.run(runtime.on_message(msg=msg, tools=tools, history=[], room_id="room-1"))

    assert tools.events[0]["message_type"] == "task"
    assert tools.messages == []
    assert tools.participants_added == []


def test_adapter_publishes_error_for_missing_payload():
    config = _config("destination_intelligence", "team/destination")
    runtime = PayGuardBandAdapter(config=config, all_configs={"destination_intelligence": config})
    tools = FakeTools()

    asyncio.run(
        runtime.on_message(
            msg=FakeMessage(content="@team/destination hello"),
            tools=tools,
            history=[],
            room_id="room-1",
        )
    )

    assert tools.events[0]["message_type"] == "error"
    assert tools.events[0]["metadata"]["reason"] == "missing_payguard_payload"


def test_qr_artifact_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("PAYGUARD_QR_ARTIFACT_DIR", str(tmp_path))

    artifact_ref = save_qr_artifact("txn/unsafe", b"qr-bytes")

    assert artifact_ref == "qr:txn_unsafe"
    assert load_qr_artifact(artifact_ref) == b"qr-bytes"
