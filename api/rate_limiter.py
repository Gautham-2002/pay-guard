"""
Rate Limiter — PayGuard AI
==========================
Async sliding-window rate limiter implemented as a Starlette/FastAPI middleware.

Two independent limit tiers are enforced on every **POST /api/check** request
(the only endpoint that triggers expensive LLM/pipeline work):

1. **Per-IP limit**   — e.g. 10 requests per IP per 60 seconds.
2. **Global limit**   — e.g. 50 requests from *all* IPs per 60 seconds.

Both limits are checked atomically before the request is forwarded.
If either is exceeded the middleware returns HTTP 429 with Retry-After header
and a JSON body.

Configuration (via environment variables, all optional)
-------------------------------------------------------
RATE_LIMIT_PER_IP          — max requests per IP per window  (default: 10)
RATE_LIMIT_GLOBAL          — max requests across all IPs      (default: 50)
RATE_LIMIT_WINDOW_SECONDS  — sliding window in seconds        (default: 60)
RATE_LIMIT_ENABLED         — set "false" to disable entirely  (default: true)

Notes
-----
- Uses a simple deque of timestamps per key (O(n) per request, n is small).
- All state is in-process; restarting the server resets counters.
  For multi-process or multi-node deployments, replace with a Redis backend.
- The real client IP is extracted from X-Forwarded-For / X-Real-IP headers
  (set by Nginx/Caddy) with a fallback to the direct socket address.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


# ─── Configuration ────────────────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        logger.warning("rate_limiter: invalid value for %s=%r; using default %d", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


RATE_LIMIT_ENABLED: bool = _env_bool("RATE_LIMIT_ENABLED", True)
RATE_LIMIT_PER_IP: int = _env_int("RATE_LIMIT_PER_IP", 10)
RATE_LIMIT_GLOBAL: int = _env_int("RATE_LIMIT_GLOBAL", 50)
RATE_LIMIT_WINDOW: int = _env_int("RATE_LIMIT_WINDOW_SECONDS", 60)
# Hard cap on the number of distinct IPs tracked simultaneously.
# Prevents the _ip_windows dict from growing without bound under a flood of
# spoofed / rotating IPs. New IPs beyond this limit are rejected with 429.
RATE_LIMIT_MAX_IPS: int = _env_int("RATE_LIMIT_MAX_IPS", 5_000)

# Only apply rate limiting to these path prefixes (exact match or startswith).
_RATE_LIMITED_PATHS = {"/api/check"}


# ─── Sliding-window state ─────────────────────────────────────────────────────


# ip → deque of Unix timestamps (float) within the current window
_ip_windows: dict[str, Deque[float]] = {}

# Global deque of all request timestamps within the current window
_global_window: Deque[float] = deque()


def _prune(dq: Deque[float], now: float, window: int) -> None:
    """Remove timestamps older than `window` seconds from the left of the deque."""
    cutoff = now - window
    while dq and dq[0] < cutoff:
        dq.popleft()


def _get_client_ip(request: Request) -> str:
    """
    Extract the real client IP from the request.

    Priority:
    1. X-Forwarded-For (first entry, set by load-balancer / reverse proxy)
    2. X-Real-IP (set by Nginx)
    3. Direct socket address (fallback for local development)
    """
    xff = request.headers.get("x-forwarded-for", "").split(",")
    if xff and xff[0].strip():
        return xff[0].strip()

    x_real_ip = request.headers.get("x-real-ip", "").strip()
    if x_real_ip:
        return x_real_ip

    client = request.client
    return client.host if client else "unknown"


def check_rate_limit(ip: str) -> tuple[bool, str, int]:
    """
    Check both the per-IP and global sliding-window limits.

    Returns
    -------
    (allowed, reason, retry_after_seconds)
        allowed         — True if the request may proceed.
        reason          — Human-readable explanation if blocked.
        retry_after     — Seconds until the oldest entry expires (0 if allowed).
    """
    now = time.monotonic()

    # ── Global window ──────────────────────────────────────────────────────────
    _prune(_global_window, now, RATE_LIMIT_WINDOW)
    if len(_global_window) >= RATE_LIMIT_GLOBAL:
        oldest = _global_window[0]
        retry_after = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return (
            False,
            f"Global rate limit exceeded ({RATE_LIMIT_GLOBAL} requests/{RATE_LIMIT_WINDOW}s). "
            f"Please wait {retry_after}s.",
            retry_after,
        )

    # ── Per-IP window ──────────────────────────────────────────────────────────
    is_new_ip = ip not in _ip_windows

    if is_new_ip:
        # Before admitting a brand-new IP, prune every existing deque so we
        # evict IPs whose window has fully expired and get an accurate count.
        if len(_ip_windows) >= RATE_LIMIT_MAX_IPS:
            _evict_empty_ip_windows(now)

        # Still over the cap after eviction → reject rather than OOM.
        if len(_ip_windows) >= RATE_LIMIT_MAX_IPS:
            logger.warning(
                "check_rate_limit: ip table full (%d/%d) — rejecting new ip=%s",
                len(_ip_windows), RATE_LIMIT_MAX_IPS, ip,
            )
            return (
                False,
                f"Server is under high load. Please try again in {RATE_LIMIT_WINDOW}s.",
                RATE_LIMIT_WINDOW,
            )

        _ip_windows[ip] = deque()

    ip_dq = _ip_windows[ip]
    _prune(ip_dq, now, RATE_LIMIT_WINDOW)

    # Evict this IP's entry if the window became empty after pruning and it
    # was not new — it had stale data that just expired, keep memory clean.
    if not ip_dq and not is_new_ip:
        del _ip_windows[ip]
        # Re-insert as a fresh entry (same path as a new IP).
        _ip_windows[ip] = ip_dq  # ip_dq is now an empty deque — reuse it

    if len(ip_dq) >= RATE_LIMIT_PER_IP:
        oldest = ip_dq[0]
        retry_after = int(RATE_LIMIT_WINDOW - (now - oldest)) + 1
        return (
            False,
            f"Per-IP rate limit exceeded ({RATE_LIMIT_PER_IP} requests/{RATE_LIMIT_WINDOW}s). "
            f"Please wait {retry_after}s.",
            retry_after,
        )

    # ── Record this request ────────────────────────────────────────────────────
    ip_dq.append(now)
    _global_window.append(now)

    return True, "", 0


def _evict_empty_ip_windows(now: float) -> int:
    """
    Prune every tracked IP's deque and remove entries that have become empty.

    Called lazily when the ip table reaches RATE_LIMIT_MAX_IPS to reclaim
    memory before deciding whether to reject a new IP.

    Returns the number of IPs removed.
    """
    to_delete = [
        addr for addr, dq in _ip_windows.items()
        if not dq or (dq and (_prune(dq, now, RATE_LIMIT_WINDOW) or not dq))
    ]
    for addr in to_delete:
        del _ip_windows[addr]
    if to_delete:
        logger.debug("_evict_empty_ip_windows: removed %d stale IP entries", len(to_delete))
    return len(to_delete)


# ─── Middleware ───────────────────────────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that enforces per-IP and global sliding-window rate limits.

    Only paths that start with an entry in ``_RATE_LIMITED_PATHS`` **and** use
    the ``POST`` method are gated.  All other requests are passed through.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        if RATE_LIMIT_ENABLED:
            logger.info(
                "RateLimitMiddleware: enabled | per_ip=%d | global=%d | window=%ds",
                RATE_LIMIT_PER_IP,
                RATE_LIMIT_GLOBAL,
                RATE_LIMIT_WINDOW,
            )
        else:
            logger.info("RateLimitMiddleware: disabled (RATE_LIMIT_ENABLED=false)")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Fast-path: rate limiting disabled or non-gated path/method
        if not RATE_LIMIT_ENABLED:
            return await call_next(request)

        method = request.method.upper()
        path = request.url.path

        # Only gate POST requests to rate-limited paths.
        # /api/check  → submit_check (expensive pipeline trigger)
        is_gated = method == "POST" and any(
            path == p or path.startswith(p + "/") for p in _RATE_LIMITED_PATHS
        )
        if not is_gated:
            return await call_next(request)

        # ── Evaluate rate limits ───────────────────────────────────────────────
        ip = _get_client_ip(request)
        allowed, reason, retry_after = check_rate_limit(ip)

        if not allowed:
            logger.warning(
                "RateLimitMiddleware: 429 | ip=%s | path=%s | reason=%s",
                ip, path, reason,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": reason,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit-IP": str(RATE_LIMIT_PER_IP),
                    "X-RateLimit-Limit-Global": str(RATE_LIMIT_GLOBAL),
                    "X-RateLimit-Window": str(RATE_LIMIT_WINDOW),
                },
            )

        # ── Request allowed — forward and attach rate-limit headers ───────────
        response = await call_next(request)

        # Attach informational headers on successful pass-through
        response.headers["X-RateLimit-Limit-IP"] = str(RATE_LIMIT_PER_IP)
        response.headers["X-RateLimit-Limit-Global"] = str(RATE_LIMIT_GLOBAL)
        response.headers["X-RateLimit-Window"] = str(RATE_LIMIT_WINDOW)

        return response
