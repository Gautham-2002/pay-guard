"""
Featherless AI Client
=====================
OpenAI-compatible async client for the Featherless AI inference API.

Used by Agent 1 — Destination Intelligence.

Configuration
-------------
  Base URL : https://api.featherless.ai/v1
  Primary  : meta-llama/Llama-3.3-70B-Instruct
  Fallback : Qwen/Qwen2.5-72B-Instruct
  API key  : FEATHERLESS_API_KEY env var

The client wraps the `openai` SDK with a custom `base_url` pointing to
Featherless's OpenAI-compatible endpoint.

Retry strategy
--------------
1. Call PRIMARY_MODEL with response_format=json_object.
2. On any exception → retry once with FALLBACK_MODEL.
3. If the response is not valid JSON → append schema reminder and retry once.
"""

from __future__ import annotations

import json
import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ─── Client Setup ─────────────────────────────────────────────────────────────

FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
PRIMARY_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
FALLBACK_MODEL = "Qwen/Qwen2.5-72B-Instruct"

# Lazy-initialised client — created on first use so that missing env vars
# only surface when an actual API call is made, not at module import time.
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Return (or lazily create) the Featherless AI async client."""
    global _client
    if _client is None:
        api_key = os.getenv("FEATHERLESS_API_KEY", "")
        if not api_key:
            logger.warning(
                "FEATHERLESS_API_KEY is not set. "
                "Agent 1 calls will fail until the key is configured."
            )
        _client = AsyncOpenAI(
            api_key=api_key or "placeholder",
            base_url=FEATHERLESS_BASE_URL,
        )
    return _client


# ─── Core chat function ───────────────────────────────────────────────────────


async def chat(
    messages: list[dict],
    response_format: dict = None,
    model: str = PRIMARY_MODEL,
    temperature: float = 0.15,
    max_tokens: int = 1024,
) -> str:
    """
    Make a chat completion call to Featherless AI.

    Strategy
    --------
    - Always requests JSON output via response_format={"type": "json_object"}.
    - On failure with PRIMARY_MODEL, retries once with FALLBACK_MODEL.
    - If response is not parseable JSON, appends a schema reminder and retries once.

    Parameters
    ----------
    messages:
        OpenAI-format message list [{\"role\": ..., \"content\": ...}].
    response_format:
        Override the response format dict. Defaults to {\"type\": \"json_object\"}.
    model:
        Starting model. Defaults to PRIMARY_MODEL.

    Returns
    -------
    Raw string content of the response (always valid JSON string on success).

    Raises
    ------
    RuntimeError if both PRIMARY and FALLBACK fail.
    """
    if response_format is None:
        response_format = {"type": "json_object"}

    async def _call(m: str, msgs: list[dict]) -> str:
        response = await _get_client().chat.completions.create(
            model=m,
            messages=msgs,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    # ── Attempt 1: PRIMARY_MODEL ───────────────────────────────────────────────
    raw_content: str = ""
    try:
        raw_content = await _call(model, messages)
        logger.debug("Featherless (%s) responded (%d chars)", model, len(raw_content))
    except Exception as exc:
        logger.warning("Featherless primary model (%s) failed: %s — retrying with fallback", model, exc)
        try:
            raw_content = await _call(FALLBACK_MODEL, messages)
            logger.info("Featherless fallback model (%s) succeeded", FALLBACK_MODEL)
        except Exception as exc2:
            raise RuntimeError(
                f"Both Featherless models failed. Primary: {exc}. Fallback: {exc2}"
            ) from exc2

    # ── JSON validation + schema-reminder retry ────────────────────────────────
    try:
        json.loads(raw_content)
        return raw_content  # Valid JSON — done
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Featherless response is not valid JSON. Appending schema reminder and retrying."
        )
        schema_reminder = {
            "role": "user",
            "content": (
                "Your previous response was not valid JSON. "
                "You MUST respond with ONLY a valid JSON object — no markdown, no code fences, "
                "no extra text. Start your response with '{' and end with '}'."
            ),
        }
        retry_messages = messages + [
            {"role": "assistant", "content": raw_content},
            schema_reminder,
        ]
        try:
            raw_content = await _call(FALLBACK_MODEL, retry_messages)
            json.loads(raw_content)  # Verify the retry is valid
            logger.info("Featherless schema-reminder retry succeeded.")
            return raw_content
        except Exception as exc:
            logger.error("Featherless schema-reminder retry failed: %s", exc)
            raise RuntimeError(
                f"Featherless returned non-JSON response and schema-reminder retry also failed: {exc}"
            ) from exc


async def chat_completion(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """
    Backward-compatible alias for older callers.
    Delegates to chat() passing through temperature and max_tokens.
    """
    return await chat(messages, temperature=temperature, max_tokens=max_tokens)
