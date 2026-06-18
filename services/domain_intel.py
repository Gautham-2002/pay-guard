"""
Domain Intelligence Service
============================
Collects raw technical signals about a URL or domain for Agent 1.

All functions in this module are designed to NEVER raise exceptions.
On any failure they return an error dict so the LLM still receives partial context.

Data sources
------------
VirusTotal (API v3)
  - Endpoint : POST /urls  then GET /analyses/{id}
  - Key      : VIRUSTOTAL_API_KEY
  - Returns  : malicious/suspicious/harmless vote counts from 70+ AV engines.

Google Safe Browsing (API v4)
  - Temporarily disabled unless ENABLE_SAFE_BROWSING=true.
  - Endpoint : POST https://safebrowsing.googleapis.com/v4/threatMatches:find
  - Key      : GOOGLE_SAFE_BROWSING_KEY
  - Returns  : threat type list (MALWARE, SOCIAL_ENGINEERING, etc.).

WhoisJSON
  - Endpoint : GET https://whoisjson.com/api/v1/whois?domain={domain}
  - Key      : WHOISJSON_KEY (header: Authorization: Token <key>)
  - Parses   : created_date, registrar, registrant_country.

SSL Certificate (via Python ssl module)
  - Direct TLS handshake to inspect: not_before, not_after, issuer CN.
  - Computed: certificate age in days, is_expired flag.

UPI VPA Parser (no external API)
  - Splits `username@psp` into (username, psp_suffix).
  - Classifies PSP: paytm | gpay | phonepe | ybl | oksbi | okhdfcbank | etc.
  - Flags patterns consistent with individual vs merchant accounts.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import ssl
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

import httpx

logger = logging.getLogger(__name__)

# ─── API Keys ─────────────────────────────────────────────────────────────────

VT_KEY = os.getenv("VIRUSTOTAL_API_KEY", "")
GSB_KEY = os.getenv("GOOGLE_SAFE_BROWSING_KEY", "")
ENABLE_SAFE_BROWSING = os.getenv("ENABLE_SAFE_BROWSING", "false").lower() == "true"
WJ_KEY = os.getenv("WHOISJSON_KEY", "")

# ─── Demo Cache ───────────────────────────────────────────────────────────────

_CACHE_PATH = Path(__file__).parent.parent / "data" / "demo_cache.json"
_demo_cache: dict | None = None


def _use_demo_cache() -> bool:
    return os.getenv("USE_DEMO_CACHE", "false").lower() == "true"


def _load_cache() -> dict:
    """Load the demo cache from disk (lazy, cached in module-level variable)."""
    global _demo_cache
    if _demo_cache is None:
        try:
            _demo_cache = json.loads(_CACHE_PATH.read_text()) if _CACHE_PATH.exists() else {}
        except Exception as exc:
            logger.warning("Demo cache load error: %s", exc)
            _demo_cache = {}
    return _demo_cache


def _get_cache(domain: str, key: str) -> dict | None:
    """Return cached result for domain+key, or None if not found."""
    if not _use_demo_cache():
        return None
    cache = _load_cache()
    entry = cache.get(domain) or {}
    return entry.get(key)

# ─── Known PSP Classification ─────────────────────────────────────────────────

_BANK_PSPS = {
    "okaxis", "oksbi", "okhdfcbank", "okicici", "axl", "sbi", "cnrb",
    "barodampay", "jupiteraxis", "fbl", "rbl", "timecosmos", "myyes",
    "yesbank", "aubank", "kotak", "hsbc", "citibank", "dbs", "postbank",
    "ibl", "upi",
}

_WALLET_PSPS = {
    "paytm", "ybl", "apl", "ikwik", "pingpay", "razorpay",
}

_ALL_KNOWN_PSPS = _BANK_PSPS | _WALLET_PSPS


def _extract_domain(url: str) -> str:
    """Extract bare domain from a URL or return the input if already a domain."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.hostname or url
    except Exception:
        return url


# ─── VirusTotal ───────────────────────────────────────────────────────────────


async def fetch_virustotal_url(url: str, client: httpx.AsyncClient) -> dict:
    """
    Submit URL to VirusTotal for scanning and return analysis summary.

    Returns: {malicious, suspicious, harmless, undetected, analysis_id, permalink}
    On error: {error: str}
    """
    domain = _extract_domain(url)
    cached = _get_cache(domain, "virustotal_url")
    if cached is not None:
        logger.info("[DEMO CACHE] virustotal_url for %s", domain)
        return cached

    if not VT_KEY:
        return {"error": "VIRUSTOTAL_API_KEY not configured"}

    headers = {"x-apikey": VT_KEY, "Content-Type": "application/x-www-form-urlencoded"}

    try:
        # Step 1: Submit URL for scanning (httpx handles form-encoding for data=)
        submit_resp = await client.post(
            "https://www.virustotal.com/api/v3/urls",
            headers=headers,
            data={"url": url},
        )
        submit_resp.raise_for_status()
        analysis_id = submit_resp.json()["data"]["id"]

        # Step 2: Poll for result (up to 3 retries with 2s backoff)
        for attempt in range(3):
            await asyncio.sleep(2)
            result_resp = await client.get(
                f"https://www.virustotal.com/api/v3/analyses/{analysis_id}",
                headers={"x-apikey": VT_KEY},
            )
            result_resp.raise_for_status()
            result_data = result_resp.json()
            status = result_data["data"]["attributes"].get("status", "")
            if status == "completed":
                stats = result_data["data"]["attributes"]["stats"]
                return {
                    "malicious": stats.get("malicious", 0),
                    "suspicious": stats.get("suspicious", 0),
                    "harmless": stats.get("harmless", 0),
                    "undetected": stats.get("undetected", 0),
                    "analysis_id": analysis_id,
                    "permalink": f"https://www.virustotal.com/gui/url/{analysis_id}/detection",
                }

        # If not completed after 3 retries, return partial
        return {
            "error": "VirusTotal analysis did not complete in time",
            "analysis_id": analysis_id,
        }

    except httpx.HTTPStatusError as exc:
        logger.warning("VirusTotal URL scan HTTP error %s: %s", exc.response.status_code, exc.response.text[:200])
        return {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:150]}"}
    except Exception as exc:
        logger.warning("VirusTotal URL scan error: %s", exc)
        return {"error": str(exc)}


async def fetch_virustotal_domain(domain: str, client: httpx.AsyncClient) -> dict:
    """
    Get domain report from VirusTotal.

    Returns: {reputation, categories, last_analysis_stats}
    On error: {error: str}
    """
    cached = _get_cache(domain, "virustotal_domain")
    if cached is not None:
        logger.info("[DEMO CACHE] virustotal_domain for %s", domain)
        return cached

    if not VT_KEY:
        return {"error": "VIRUSTOTAL_API_KEY not configured"}

    try:
        resp = await client.get(
            f"https://www.virustotal.com/api/v3/domains/{domain}",
            headers={"x-apikey": VT_KEY},
        )
        resp.raise_for_status()
        attrs = resp.json()["data"]["attributes"]
        return {
            "reputation": attrs.get("reputation", 0),
            "categories": attrs.get("categories", {}),
            "last_analysis_stats": attrs.get("last_analysis_stats", {}),
            "creation_date": attrs.get("creation_date"),
            "whois": attrs.get("whois", "")[:500],  # truncate heavy WHOIS text
        }
    except httpx.HTTPStatusError as exc:
        logger.warning("VirusTotal domain report HTTP error %s", exc.response.status_code)
        return {"error": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        logger.warning("VirusTotal domain report error: %s", exc)
        return {"error": str(exc)}


# ─── WhoisJSON ────────────────────────────────────────────────────────────────


async def fetch_whois(domain: str, client: httpx.AsyncClient) -> dict:
    """
    Fetch WHOIS data for domain via WhoisJSON API.

    Returns: {age_days, registrar, country, created, expires}
    If date is unknown, age_days is -1.
    On error: {error: str}
    """
    cached = _get_cache(domain, "whois")
    if cached is not None:
        logger.info("[DEMO CACHE] whois for %s", domain)
        return cached

    if not WJ_KEY:
        return {"error": "WHOISJSON_KEY not configured"}

    try:
        resp = await client.get(
            "https://whoisjson.com/api/v1/whois",
            params={"domain": domain},
            headers={"Authorization": f"TOKEN={WJ_KEY}"},
        )
        resp.raise_for_status()
        data = resp.json()

        # Parse creation date — handle None gracefully
        created_raw = data.get("created") or data.get("create_date") or data.get("creation_date")
        age_days = -1
        created_iso = None
        if created_raw:
            try:
                created_dt = None
                # WhoisJSON often returns ISO strings or epoch ints
                if isinstance(created_raw, (int, float)):
                    created_dt = datetime.fromtimestamp(created_raw, tz=timezone.utc)
                else:
                    raw_str = str(created_raw).strip()
                    # Try each full format string against the raw value
                    _DATE_FORMATS = [
                        "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S.%fZ",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d",
                    ]
                    for fmt in _DATE_FORMATS:
                        try:
                            created_dt = datetime.strptime(raw_str, fmt).replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    if created_dt is None:
                        # Last resort: extract YYYY-MM-DD with regex
                        match = re.search(r"(\d{4}-\d{2}-\d{2})", raw_str)
                        if match:
                            created_dt = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if created_dt:
                    age_days = (datetime.now(timezone.utc) - created_dt).days
                    created_iso = created_dt.isoformat()
            except Exception as exc:
                logger.debug("WHOIS date parse error: %s", exc)

        expires_raw = data.get("expires") or data.get("expiration_date") or data.get("registrar_registration_expiration_date")

        return {
            "age_days": age_days,
            "registrar": data.get("registrar") or data.get("registrar_name", "unknown"),
            "country": data.get("registrant_country") or data.get("country", "unknown"),
            "created": created_iso or str(created_raw) if created_raw else "unknown",
            "expires": str(expires_raw) if expires_raw else "unknown",
            "domain_status": data.get("status", []),
        }
    except httpx.HTTPStatusError as exc:
        logger.warning("WhoisJSON HTTP error %s", exc.response.status_code)
        return {"error": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        logger.warning("WhoisJSON error: %s", exc)
        return {"error": str(exc)}


# ─── Google Safe Browsing ─────────────────────────────────────────────────────


async def fetch_safe_browsing(url: str, client: httpx.AsyncClient) -> dict:
    """
    Check URL against Google Safe Browsing v4 API.

    Returns: {is_dangerous: bool, threat_types: list[str]}
    On error: {error: str}
    """
    domain = _extract_domain(url)
    cached = _get_cache(domain, "safe_browsing")
    if cached is not None:
        logger.info("[DEMO CACHE] safe_browsing for %s", domain)
        return cached

    if not ENABLE_SAFE_BROWSING:
        return {"disabled": True, "reason": "Safe Browsing temporarily disabled"}

    if not GSB_KEY:
        return {"error": "GOOGLE_SAFE_BROWSING_KEY not configured"}

    body = {
        "client": {"clientId": "payguard-ai", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": [
                "MALWARE", "SOCIAL_ENGINEERING",
                "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION",
            ],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }

    try:
        resp = await client.post(
            f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={GSB_KEY}",
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        matches = data.get("matches", [])
        threat_types = list({m["threatType"] for m in matches})
        return {
            "is_dangerous": bool(matches),
            "threat_types": threat_types,
        }
    except httpx.HTTPStatusError as exc:
        logger.warning("GSB HTTP error %s", exc.response.status_code)
        return {"error": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        logger.warning("GSB error: %s", exc)
        return {"error": str(exc)}


# ─── SSL Certificate ──────────────────────────────────────────────────────────


async def fetch_ssl_info(domain: str) -> dict:
    """
    Inspect SSL certificate for a domain using Python's ssl module (no external API).

    Returns: {valid, issuer, expires, age_days, is_self_signed}
    On failure: {valid: false, error: str}
    """
    cached = _get_cache(domain, "ssl")
    if cached is not None:
        logger.info("[DEMO CACHE] ssl for %s", domain)
        return cached

    loop = asyncio.get_event_loop()

    def _get_cert():
        ctx = ssl.create_default_context()
        try:
            with ctx.wrap_socket(
                socket.create_connection((domain, 443), timeout=10),
                server_hostname=domain,
            ) as sock:
                cert = sock.getpeercert()
                return cert, None
        except ssl.SSLCertVerificationError as e:
            # Try without verification to get the cert details anyway
            ctx_noverify = ssl.create_default_context()
            ctx_noverify.check_hostname = False
            ctx_noverify.verify_mode = ssl.CERT_NONE
            try:
                with ctx_noverify.wrap_socket(
                    socket.create_connection((domain, 443), timeout=10),
                    server_hostname=domain,
                ) as sock:
                    cert = sock.getpeercert()
                    return cert, str(e)
            except Exception as e2:
                return None, str(e2)
        except Exception as e:
            return None, str(e)

    try:
        cert, ssl_error = await loop.run_in_executor(None, _get_cert)
    except Exception as exc:
        return {"valid": False, "error": str(exc)}

    if cert is None:
        return {"valid": False, "error": ssl_error or "Could not retrieve certificate"}

    # Parse expiry date: format is "%b %d %H:%M:%S %Y %Z"
    not_after_str = cert.get("notAfter", "")
    not_before_str = cert.get("notBefore", "")
    expires_iso = None
    age_days = -1
    try:
        not_after_dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        expires_iso = not_after_dt.isoformat()
    except Exception:
        pass

    try:
        not_before_dt = datetime.strptime(not_before_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - not_before_dt).days
    except Exception:
        pass

    # Extract issuer CN
    issuer_dict = dict(x[0] for x in cert.get("issuer", []))
    subject_dict = dict(x[0] for x in cert.get("subject", []))
    issuer_cn = issuer_dict.get("commonName", "unknown")
    subject_cn = subject_dict.get("commonName", "unknown")

    # Self-signed = issuer CN matches subject CN
    is_self_signed = issuer_cn == subject_cn

    return {
        "valid": ssl_error is None,
        "issuer": issuer_cn,
        "subject": subject_cn,
        "expires": expires_iso or not_after_str,
        "age_days": age_days,
        "is_self_signed": is_self_signed,
        "ssl_error": ssl_error,
    }


# ─── UPI VPA Parser ───────────────────────────────────────────────────────────

_PERSONAL_NAME_PATTERN = re.compile(
    r"^[a-z]+\.[a-z]+$|^[a-z]+[0-9]{0,4}$",
    re.IGNORECASE,
)
_RANDOM_STRING_PATTERN = re.compile(
    r"[a-z]{0,3}[0-9]{4,}[a-z]{0,3}",
    re.IGNORECASE,
)
_MERCHANT_HINT_PATTERN = re.compile(
    r"merchant|store|shop|pay|biz|business|enterprise|pvt|ltd|llp|inc|sales|medical|clinic|hotel|cafe|restaurant",
    re.IGNORECASE,
)


async def analyze_upi_vpa(upi_id: str) -> dict:
    """
    Parse UPI Virtual Payment Address. No external API — pure structural analysis.

    VPA format: username@psp
    Returns rich dict with PSP classification and username pattern detection.
    """
    upi_id = upi_id.strip().lower()

    if "@" not in upi_id:
        return {
            "raw_vpa": upi_id,
            "error": "Invalid UPI ID format — missing '@'",
        }

    username, psp = upi_id.rsplit("@", 1)

    psp_is_known = psp in _ALL_KNOWN_PSPS
    if psp in _BANK_PSPS:
        psp_type = "bank_psp"
    elif psp in _WALLET_PSPS:
        psp_type = "wallet_psp"
    else:
        psp_type = "unknown"

    # Username pattern heuristics
    if _MERCHANT_HINT_PATTERN.search(username):
        username_pattern = "looks_merchant"
    elif _RANDOM_STRING_PATTERN.search(username):
        username_pattern = "random_string"
    elif _PERSONAL_NAME_PATTERN.match(username):
        username_pattern = "looks_personal"
    else:
        username_pattern = "unknown"

    return {
        "username": username,
        "psp": psp,
        "psp_is_known": psp_is_known,
        "psp_type": psp_type,
        "username_pattern": username_pattern,
        "raw_vpa": upi_id,
    }


# ─── Main Orchestrator ────────────────────────────────────────────────────────


async def collect_all_signals(url: str = None, upi_id: str = None) -> dict:
    """
    Main entry point — collects ALL available signals concurrently.

    If URL: fetch WHOIS, VT URL scan, VT domain report, optional GSB, SSL.
    If UPI ID: analyze VPA structure only.
    If both: fetch all.

    Returns a unified dict with all raw evidence.
    Never raises — returns error fields for failed sub-calls.
    """
    results: dict = {}

    if upi_id:
        results["upi_analysis"] = await analyze_upi_vpa(upi_id)

    if url:
        domain = _extract_domain(url)
        results["domain"] = domain

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            # Fire all I/O-bound calls concurrently.
            # return_exceptions=True ensures a rare uncaught exception becomes an
            # error dict rather than aborting the entire gather.
            gather_results = await asyncio.gather(
                fetch_whois(domain, client),
                fetch_virustotal_url(url, client),
                fetch_virustotal_domain(domain, client),
                return_exceptions=True,
            )

        def _safe_result(r, label: str) -> dict:
            if isinstance(r, BaseException):
                logger.warning("%s raised unexpectedly: %s", label, r)
                return {"error": str(r)}
            return r

        whois_result = _safe_result(gather_results[0], "fetch_whois")
        vt_url_result = _safe_result(gather_results[1], "fetch_virustotal_url")
        vt_domain_result = _safe_result(gather_results[2], "fetch_virustotal_domain")

        results["whois"] = whois_result
        results["virustotal_url"] = vt_url_result
        results["virustotal_domain"] = vt_domain_result
        results["google_safe_browsing"] = await fetch_safe_browsing(url, client)

        # SSL check runs via executor (blocking) — run after gather is done
        results["ssl"] = await fetch_ssl_info(domain)

    return results
