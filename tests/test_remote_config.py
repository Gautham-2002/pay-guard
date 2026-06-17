from __future__ import annotations

import pytest

from agents.band_config import load_remote_agent_configs
from agents.remote_runtime import _load_band_runtime_urls
from agents.remote_prompts import render_remote_prompt


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


def test_remote_prompt_includes_current_and_next_band_handles(tmp_path):
    config_path = tmp_path / "agent_config.yaml"
    config_path.write_text(
        """
destination_intelligence:
  agent_id: "agent-1"
  api_key: "band-api-1"
  handle: "team/destination"
  provider: "featherless"
  max_tokens: 4096
  next_agent_key: "qr_upi_validator"

qr_upi_validator:
  agent_id: "agent-2"
  api_key: "band-api-2"
  handle: "team/qr"
  provider: "aiml"
  max_tokens: 4096
  next_agent_key: null
""",
        encoding="utf-8",
    )
    configs = load_remote_agent_configs(config_path)

    prompt = render_remote_prompt(configs["destination_intelligence"], configs)

    assert "@team/destination" in prompt
    assert "@team/qr" in prompt
    assert "explicitly mentions @team/qr" in prompt


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
