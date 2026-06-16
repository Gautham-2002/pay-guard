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
Phase 2 uses AIML API gpt-4o vision to decode the QR from the raw image bytes
because:
  1. The vision model can simultaneously decode and visually analyse context
     (WhatsApp screenshot, shop sticker, official PDF envelope, etc.).
  2. It avoids dependency on a native QR library that may struggle with
     low-resolution or partially obscured codes.

As a fallback, a local decode attempt via `pillow` + `pyzbar` (if available)
may be attempted before sending to the vision API.

Implemented in: Phase 2
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


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


async def decode_qr_image(image_bytes: bytes) -> str:
    """
    Attempt to decode a QR code from raw image bytes.

    Strategy:
      1. Try local decode via pillow (fast, no API call).
      2. If that fails, delegate to AIML API vision model (Phase 2).

    Parameters
    ----------
    image_bytes: Raw PNG or JPEG bytes from the uploaded QR image.

    Returns
    -------
    The decoded QR content string (typically a upi:// deep link).

    Raises
    ------
    ValueError if the QR code cannot be decoded by any available method.
    """
    raise NotImplementedError("decode_qr_image implemented in Phase 2")
