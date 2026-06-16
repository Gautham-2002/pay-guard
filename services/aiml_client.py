"""
AIML API Client
===============
OpenAI-compatible async client for the AIML API inference endpoint.

Used by:
  Agent 2 — QR Decode & Validator  (gpt-4o vision mode)
  Agent 3 — Web Intelligence       (gpt-4o reasoning + vision for screenshots)
  Agent 4 — Verdict Synthesis      (gpt-4o or claude-3-5-sonnet)

Configuration
-------------
  Base URL : https://api.aimlapi.com/v2
  Models   : gpt-4o  |  claude-3-5-sonnet
  API key  : AIML_API_KEY env var

The client wraps the `openai` SDK with a custom `base_url` and `api_key`
pointing to AIML API's OpenAI-compatible endpoint.

Implemented in: Phase 2
"""

from __future__ import annotations

import os

# TODO (Phase 2): Initialise openai.AsyncOpenAI with AIML API base URL.

AIML_BASE_URL = "https://api.aimlapi.com/v2"
AIML_MODEL_TEXT = "gpt-4o"
AIML_MODEL_VISION = "gpt-4o"
AIML_MODEL_VERDICT = "claude-3-5-sonnet"


async def chat_completion(
    messages: list[dict],
    model: str = AIML_MODEL_TEXT,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """
    Send a chat completion request to AIML API.

    Parameters
    ----------
    messages:    OpenAI-format message list. For vision calls, include
                 image_url content parts as per OpenAI multimodal format.
    model:       Model identifier. Use AIML_MODEL_VISION for image inputs.
    temperature: Sampling temperature.
    max_tokens:  Maximum tokens in the model response.

    Returns
    -------
    The assistant's reply as a plain string.
    """
    raise NotImplementedError("AIML chat_completion implemented in Phase 2")


async def vision_completion(
    prompt: str,
    image_bytes: bytes,
    model: str = AIML_MODEL_VISION,
) -> str:
    """
    Send a vision completion request with a base64-encoded image.

    Used by Agent 2 (QR visual analysis) and Agent 3 (screenshot fraud detection).

    Parameters
    ----------
    prompt:      Text instruction for the vision model.
    image_bytes: Raw image bytes (PNG/JPEG) to analyse.
    model:       Vision-capable model identifier.

    Returns
    -------
    The model's analysis as a plain string.
    """
    raise NotImplementedError("AIML vision_completion implemented in Phase 2")
