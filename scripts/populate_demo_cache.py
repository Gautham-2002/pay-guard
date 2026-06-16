"""
Populate Demo Cache
====================
Calls real external APIs (VirusTotal, WHOIS, Google Safe Browsing, SSL) for
all 5 demo scenarios and saves the results to data/demo_cache.json.

Run ONCE before recording the demo video:
    uv run python scripts/populate_demo_cache.py

Then set USE_DEMO_CACHE=true in .env to replay cached results without live
API calls (avoids rate limits, ensures reliable demo).

Demo scenarios:
    1. razorpay.com         — SAFE
    2. razorpay-secure.co   — DANGER (lookalike domain)
    3. flipkart.com         — DANGER (processing fee scam)
    4. scammer123@ybl       — UPI-only (QR scenario)
    5. merchant@ybl         — VERIFY (OLX buyer)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# ── Ensure project root is on sys.path ────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import httpx
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.domain_intel import (
    fetch_virustotal_url,
    fetch_virustotal_domain,
    fetch_whois,
    fetch_safe_browsing,
    fetch_ssl_info,
    _extract_domain,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

CACHE_PATH = ROOT / "data" / "demo_cache.json"

# ── Domains / URLs to cache ────────────────────────────────────────────────────
DEMO_DOMAINS = [
    "razorpay.com",
    "razorpay-secure.co",
    "flipkart.com",
]

DEMO_UPIS = [
    "scammer123@ybl",
    "merchant@ybl",
]


async def populate_domain(domain: str, client: httpx.AsyncClient) -> dict:
    """Fetch all signals for a single domain and return a cache entry."""
    logger.info("Fetching signals for domain: %s", domain)
    url = f"https://{domain}"

    vt_url, vt_domain, whois, gsb = await asyncio.gather(
        fetch_virustotal_url(url, client),
        fetch_virustotal_domain(domain, client),
        fetch_whois(domain, client),
        fetch_safe_browsing(url, client),
        return_exceptions=True,
    )

    def safe(r, label):
        if isinstance(r, BaseException):
            logger.warning("  [%s] %s raised: %s", domain, label, r)
            return {"error": str(r)}
        return r

    ssl_info = await fetch_ssl_info(domain)

    entry = {
        "virustotal_url":    safe(vt_url, "virustotal_url"),
        "virustotal_domain": safe(vt_domain, "virustotal_domain"),
        "whois":             safe(whois, "whois"),
        "safe_browsing":     safe(gsb, "safe_browsing"),
        "ssl":               ssl_info,
    }
    logger.info("  ✓ %s — done", domain)
    return entry


async def main() -> None:
    logger.info("=== PayGuard Demo Cache Populator ===")
    logger.info("Target: %s", CACHE_PATH)

    # Load existing cache so we can merge / update individual entries
    cache: dict = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text())
            logger.info("Loaded existing cache with %d entries", len(cache))
        except json.JSONDecodeError:
            logger.warning("Existing cache is malformed — starting fresh")

    # ── Domain signals ─────────────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for domain in DEMO_DOMAINS:
            try:
                entry = await populate_domain(domain, client)
                cache[domain] = entry
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", domain, exc)
                cache[domain] = {"error": str(exc)}

            # VirusTotal free tier: 4 requests/minute — be conservative
            logger.info("  Sleeping 20s to respect VT rate limit...")
            await asyncio.sleep(20)

    # ── UPI entries (structural analysis only — no external APIs needed) ───────
    from services.domain_intel import analyze_upi_vpa
    for upi in DEMO_UPIS:
        logger.info("Analyzing UPI: %s", upi)
        upi_data = await analyze_upi_vpa(upi)
        cache[upi] = {"upi_analysis": upi_data}
        logger.info("  ✓ %s — done", upi)

    # ── Write cache ────────────────────────────────────────────────────────────
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, default=str))
    logger.info("✅ Cache written to %s (%d entries)", CACHE_PATH, len(cache))
    logger.info("")
    logger.info("Set USE_DEMO_CACHE=true in .env to use this cache during demo.")


if __name__ == "__main__":
    asyncio.run(main())
