"""
QR Handler Service
==================
Decodes UPI QR code images and parses the embedded UPI deep-link.

A UPI QR code encodes a URL deep link in the format:
    upi://pay?pa=merchant@paytm&pn=MerchantName&am=500&cu=INR

Fields
------
  pa  — payee UPI ID  (the ONLY thing that determines who gets the money)
  pn  — payee name    (user-controlled label, CAN be faked)
  am  — pre-filled amount (can be SET by the QR creator to manipulate the user)
  cu  — currency (always INR for Indian UPI)

Security note: `pn` and `am` are entirely attacker-controlled. Only `pa`
determines the actual payment destination. Agent 2 checks for mismatches.

Implementation approach
-----------------------
1. First attempts a fast local decode via pyzbar (no API cost, no latency).
2. If local decode fails (blurry, partial, etc.), falls back to AIML API vision.

Implemented in: Phase 3
"""

from __future__ import annotations

import io
import logging
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


# ─── UPI Deep-link Parser ─────────────────────────────────────────────────────


def parse_upi_deep_link(upi_url: str) -> dict:
    """
    Parse a UPI deep-link string into its constituent fields.

    Parameters
    ----------
    upi_url: A string of the form "upi://pay?pa=...&pn=...&am=...&cu=..."

    Returns
    -------
    Dict with keys:
      pa  (str)            — payee UPI ID
      pn  (str | None)     — payee display name
      am  (float | None)   — pre-filled amount in INR
      cu  (str)            — currency code (default: "INR")
      raw (str)            — the original upi_url string

    Raises
    ------
    ValueError if `pa` (the payee address) is missing from the URL.
    """
    parsed = urlparse(upi_url)
    params = parse_qs(parsed.query)

    pa = params.get("pa", [None])[0]
    if not pa:
        raise ValueError(f"Invalid UPI deep link — missing 'pa' field: {upi_url!r}")

    am_raw = params.get("am", [None])[0]
    amount = float(am_raw) if am_raw else None

    return {
        "pa": pa,
        "pn": params.get("pn", [None])[0],
        "am": amount,
        "cu": params.get("cu", ["INR"])[0],
        "raw": upi_url,
    }


# ─── Local QR Decode ──────────────────────────────────────────────────────────


def _classify_decoded_type(raw_data: str) -> str:
    """
    Determine the type of the decoded QR content.

    Returns
    -------
    "UPI_PAYMENT" | "URL" | "TEXT" | "UNKNOWN"
    """
    lower = raw_data.lower()
    if lower.startswith("upi://"):
        return "UPI_PAYMENT"
    if lower.startswith("http://") or lower.startswith("https://"):
        return "URL"
    if raw_data.strip():
        return "TEXT"
    return "UNKNOWN"


async def decode_qr_from_image(image_bytes: bytes) -> dict | None:
    """
    Attempt to decode a QR code from image bytes using pyzbar.

    Strategy
    --------
    1. Try pyzbar on the original image.
    2. If pyzbar fails, try after converting to greyscale via Pillow.
    3. Return None (not raise) on any failure — caller handles fallback.

    Parameters
    ----------
    image_bytes: Raw PNG or JPEG bytes of the QR code image.

    Returns
    -------
    On success:
    {
        "raw_data":     "upi://pay?pa=merchant@paytm&pn=MerchantName&am=500&cu=INR",
        "decoded_type": "UPI_PAYMENT" | "URL" | "TEXT" | "UNKNOWN",
        "upi_params": {          # only present when decoded_type == "UPI_PAYMENT"
            "pa": "merchant@paytm",
            "pn": "MerchantName",
            "am": 500.0,
            "cu": "INR"
        }
    }

    None if the QR code cannot be decoded locally.
    Never raises.
    """
    try:
        from pyzbar import pyzbar  # type: ignore
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(image_bytes))

        # Attempt 1: decode directly
        codes = pyzbar.decode(img)

        # Attempt 2: greyscale conversion often helps with colour QRs
        if not codes and img.mode != "L":
            grey = img.convert("L")
            codes = pyzbar.decode(grey)

        # Attempt 3: scale up small images
        if not codes and (img.width < 300 or img.height < 300):
            scale = 3
            upscaled = img.resize((img.width * scale, img.height * scale))
            codes = pyzbar.decode(upscaled)
            if not codes:
                upscaled_grey = upscaled.convert("L")
                codes = pyzbar.decode(upscaled_grey)

        if not codes:
            logger.debug("decode_qr_from_image: pyzbar found no QR codes in image")
            return None

        # Use the first detected code
        raw_data = codes[0].data.decode("utf-8", errors="replace").strip()
        if not raw_data:
            return None

        decoded_type = _classify_decoded_type(raw_data)

        result: dict = {
            "raw_data": raw_data,
            "decoded_type": decoded_type,
        }

        if decoded_type == "UPI_PAYMENT":
            try:
                upi_parsed = parse_upi_deep_link(raw_data)
                result["upi_params"] = {
                    "pa": upi_parsed["pa"],
                    "pn": upi_parsed.get("pn"),
                    "am": upi_parsed.get("am"),
                    "cu": upi_parsed.get("cu", "INR"),
                }
            except ValueError as exc:
                logger.warning(
                    "decode_qr_from_image: UPI deep-link parse failed: %s", exc
                )
                result["upi_params"] = None
        else:
            result["upi_params"] = None

        logger.info(
            "decode_qr_from_image: decoded type=%s raw='%s...'",
            decoded_type, raw_data[:60],
        )
        return result

    except ImportError:
        logger.debug("decode_qr_from_image: pyzbar or Pillow not available — skipping local decode")
        return None
    except Exception as exc:
        logger.debug("decode_qr_from_image: local decode failed (%s) — returning None", exc)
        return None


# ─── Legacy API-level entry point ─────────────────────────────────────────────


async def decode_qr_image(image_bytes: bytes) -> str:
    """
    Attempt to decode a QR code from raw image bytes.

    Strategy:
      1. Try local decode via pyzbar (fast, no API call).
      2. If that fails, raises ValueError (caller should use AIML vision API).

    Parameters
    ----------
    image_bytes: Raw PNG or JPEG bytes from the uploaded QR image.

    Returns
    -------
    The decoded QR content string (typically a upi:// deep link).

    Raises
    ------
    ValueError if the QR code cannot be decoded locally.
    """
    result = await decode_qr_from_image(image_bytes)
    if result is None:
        raise ValueError("Could not decode QR code locally — use vision API fallback")
    return result["raw_data"]
