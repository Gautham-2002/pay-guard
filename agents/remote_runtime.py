"""Runtime helper for PayGuard Band remote agents."""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from agents.band_config import load_remote_agent_config, load_remote_agent_configs
from agents.llm_adapter import make_llm_adapter
from agents.remote_prompts import render_remote_prompt
from agents.remote_tools import build_tools_for_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
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


async def run_remote_agent(
    *,
    config_key: str,
    display_name: str | None = None,
    provider: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int | None = None,
) -> None:
    """Load credentials, create a Band remote agent, and wait for mentions."""
    load_dotenv()

    logger = logging.getLogger(f"payguard.{config_key}")
    try:
        from band import Agent
        from band.config import load_agent_config
    except ImportError as exc:
        raise RuntimeError(
            "Band remote-agent SDK is missing. Install `band-sdk[langgraph]`, "
            "then rerun this agent."
        ) from exc

    all_configs = load_remote_agent_configs()
    config = load_remote_agent_config(config_key)

    # Keep the SDK helper in the path so credentials match Band's documented
    # agent_config.yaml behavior. Our config loader runs first so a missing file
    # points users at this repo's example filename.
    agent_id, api_key = load_agent_config(config_key)
    rendered_prompt = system_prompt or render_remote_prompt(config, all_configs)
    tools = build_tools_for_agent(config_key)

    resolved_display_name = display_name or config.display_name
    resolved_provider = provider or config.provider
    resolved_max_tokens = max_tokens or config.max_tokens

    logger.info(
        "Loaded %s credentials | agent_id=%s | handle=@%s",
        resolved_display_name,
        agent_id,
        config.handle,
    )

    adapter = make_llm_adapter(
        provider=resolved_provider,
        system_prompt=rendered_prompt,
        model=config.model,
        max_tokens=resolved_max_tokens,
        tools=tools,
    )

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        **_load_band_runtime_urls(),
    )

    logger.info("%s is online and waiting for Band mentions", resolved_display_name)
    await agent.run()


def run_cli(**kwargs) -> None:
    """Synchronous console-script bridge for async remote-agent runners."""
    asyncio.run(run_remote_agent(**kwargs))
