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
  Base URL : https://api.aimlapi.com/v1
  Models   : gpt-4o  |  claude-3-5-sonnet
  API key  : AIML_API_KEY env var

The client wraps the `openai` SDK with a custom `base_url` and `api_key`
pointing to AIML API's OpenAI-compatible endpoint.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ─── Client Setup ─────────────────────────────────────────────────────────────

AIML_BASE_URL = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
VISION_MODEL = os.getenv("AIML_VISION_MODEL", "gpt-4o")
REASONING_MODEL = os.getenv("AIML_REASONING_MODEL", "gpt-4o")
AIML_MODEL_TEXT = os.getenv("AIML_MODEL", "gpt-4o")
AIML_MODEL_VISION = os.getenv("AIML_VISION_MODEL", "gpt-4o")
AIML_MODEL_VERDICT = os.getenv("AIML_VERDICT_MODEL", "claude-3-5-sonnet")

# Lazy-initialised client — created on first use to avoid import-time failures
_aiml_client: AsyncOpenAI | None = None


def _get_aiml_client() -> AsyncOpenAI:
    """Return (or lazily create) the AIML API async client."""
    global _aiml_client
    if _aiml_client is None:
        api_key = os.getenv("AIML_API_KEY", "")
        if not api_key:
            logger.warning(
                "AIML_API_KEY is not set. "
                "Agent 2/3/4 calls will fail until the key is configured."
            )
        _aiml_client = AsyncOpenAI(
            api_key=api_key or "placeholder",
            base_url=AIML_BASE_URL,
        )
    return _aiml_client


# ─── Image Compression ────────────────────────────────────────────────────────


def compress_image(image_bytes: bytes, max_size_kb: int = 1024) -> bytes:
    """
    Compress image bytes using Pillow if the image exceeds max_size_kb.

    Progressively reduces JPEG quality until the image fits within the size
    limit, then returns the (possibly resized) bytes.

    Parameters
    ----------
    image_bytes:  Raw image bytes (PNG / JPEG / WEBP).
    max_size_kb:  Maximum allowed size in kilobytes. Default 1024 (1 MB).

    Returns
    -------
    Compressed image bytes (JPEG format if compression was needed).
    """
    max_bytes = max_size_kb * 1024
    if len(image_bytes) <= max_bytes:
        return image_bytes

    try:
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if necessary (PNG with alpha, WEBP, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Try progressive quality reduction first
        for quality in (85, 70, 55, 40, 25):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            result = buf.getvalue()
            if len(result) <= max_bytes:
                logger.debug(
                    "compress_image: reduced to %d KB at quality=%d",
                    len(result) // 1024, quality,
                )
                return result

        # If still too large, scale down dimensions
        while len(image_bytes) > max_bytes:
            new_width = int(img.width * 0.75)
            new_height = int(img.height * 0.75)
            if new_width < 100 or new_height < 100:
                break
            img = img.resize((new_width, new_height), Image.LANCZOS)  # type: ignore[attr-defined]
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60, optimize=True)
            image_bytes = buf.getvalue()

        logger.warning(
            "compress_image: final size %d KB (target was %d KB)",
            len(image_bytes) // 1024, max_size_kb,
        )
        return image_bytes

    except ImportError:
        logger.warning("compress_image: Pillow not available — returning original bytes")
        return image_bytes
    except Exception as exc:
        logger.warning("compress_image error (returning original): %s", exc)
        return image_bytes


# ─── Core text completion ──────────────────────────────────────────────────────


async def chat_text(
    messages: list[dict],
    response_format: dict = None,
    model: str = REASONING_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """
    Text-only chat completion via AIML API.

    Parameters
    ----------
    messages:        OpenAI-format message list.
    response_format: Optional response format override (e.g. {"type": "json_object"}).
    model:           Model to use (defaults to REASONING_MODEL = gpt-4o).
    temperature:     Sampling temperature.
    max_tokens:      Max tokens in the response.

    Returns
    -------
    Response content as a plain string (always valid JSON string when
    response_format={"type": "json_object"} is requested).

    Raises
    ------
    RuntimeError if the API call fails or returns non-JSON when JSON is requested.
    """
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    try:
        response = await _get_aiml_client().chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        logger.debug("AIML chat_text (%s): %d chars returned", model, len(content))
        return content
    except Exception as exc:
        logger.error("AIML chat_text error (%s): %s", model, exc)
        raise RuntimeError(f"AIML API chat_text failed: {exc}") from exc


# ─── Vision completion ────────────────────────────────────────────────────────


async def chat_vision(image_bytes: bytes, text_prompt: str, model: str = VISION_MODEL) -> str:
    """
    Vision chat completion via AIML API.

    Encodes the image as a base64 data URL and sends it alongside the text
    prompt in a single user message with two content parts:
      - {type: text, text: prompt}
      - {type: image_url, image_url: {url: "data:image/jpeg;base64,..."}}

    The image is automatically compressed to ≤ 1 MB before encoding.

    Parameters
    ----------
    image_bytes: Raw image bytes (PNG / JPEG / WEBP).
    text_prompt: The instruction prompt accompanying the image.
    model:       Vision-capable model (defaults to VISION_MODEL = gpt-4o).

    Returns
    -------
    The assistant's reply as a plain string.

    Raises
    ------
    RuntimeError if the API call fails.
    """
    # Compress before encoding
    compressed = compress_image(image_bytes, max_size_kb=1024)

    # Detect MIME type from magic bytes
    if compressed[:4] == b"\x89PNG":
        mime = "image/png"
    elif compressed[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif compressed[:4] == b"RIFF" and compressed[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"  # default

    b64_data = base64.b64encode(compressed).decode("utf-8")
    data_url = f"data:{mime};base64,{b64_data}"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]

    try:
        response = await _get_aiml_client().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=2048,
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        logger.debug("AIML chat_vision (%s): %d chars returned", model, len(content))
        return content
    except Exception as exc:
        logger.error("AIML chat_vision error (%s): %s", model, exc)
        raise RuntimeError(f"AIML API chat_vision failed: {exc}") from exc


# ─── Backward-compatible aliases ──────────────────────────────────────────────


async def chat_completion(
    messages: list[dict],
    model: str = AIML_MODEL_TEXT,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """
    Backward-compatible alias for older callers.
    Delegates to chat_text().
    """
    return await chat_text(messages, model=model, temperature=temperature, max_tokens=max_tokens)


async def vision_completion(
    prompt: str,
    image_bytes: bytes,
    model: str = AIML_MODEL_VISION,
) -> str:
    """
    Backward-compatible alias for older callers.
    Delegates to chat_vision().
    """
    return await chat_vision(image_bytes, prompt, model=model)


# ─── JSON chat helper ─────────────────────────────────────────────────────────


async def chat_json(
    messages: list[dict],
    model: str = REASONING_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> dict:
    """
    Chat completion that guarantees a parsed dict result.

    Requests JSON mode and retries with a schema reminder if the response
    is not valid JSON.

    Parameters
    ----------
    messages:    OpenAI-format message list.
    model:       Model to use.
    temperature: Sampling temperature.
    max_tokens:  Max tokens.

    Returns
    -------
    Parsed dict from the LLM JSON response.

    Raises
    ------
    RuntimeError if JSON cannot be obtained after retries.
    """
    content = await chat_text(
        messages,
        response_format={"type": "json_object"},
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AIML chat_json: response is not valid JSON — retrying with schema reminder")

    # Retry with a schema reminder
    schema_reminder = {
        "role": "user",
        "content": (
            "Your previous response was not valid JSON. "
            "You MUST respond with ONLY a valid JSON object — no markdown, no code fences, "
            "no extra text. Start your response with '{' and end with '}'."
        ),
    }
    retry_messages = messages + [
        {"role": "assistant", "content": content},
        schema_reminder,
    ]
    retry_content = await chat_text(
        retry_messages,
        response_format={"type": "json_object"},
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    try:
        return json.loads(retry_content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(
            f"AIML chat_json: could not get valid JSON after retry. Last response: {retry_content[:200]}"
        ) from exc
