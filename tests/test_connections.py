"""
PayGuard AI — External API Connection Tests
============================================
Run this file directly to verify all external integrations before starting
agent implementation.

Usage:
    python tests/test_connections.py

Each test is independent. Results are printed with PASS / FAIL.
A summary is printed at the end.

Requires a populated .env file — copy .env.example and fill in your keys.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback

from dotenv import load_dotenv

load_dotenv()

# ─── Helpers ──────────────────────────────────────────────────────────────────

_results: list[tuple[str, bool, str]] = []  # (name, passed, detail)


def _record(name: str, passed: bool, detail: str = "") -> None:
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {name}" + (f"\n         {detail}" if detail else ""))
    _results.append((name, passed, detail))


# ─── Test 1: Featherless AI ───────────────────────────────────────────────────


async def test_featherless_connection() -> None:
    """
    Make a simple chat completion to Featherless AI (Llama 3.3 70B).
    Asserts the response contains "ok".
    """
    name = "Featherless AI (Llama 3.3 70B)"
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=os.environ["FEATHERLESS_API_KEY"],
            base_url="https://api.featherless.ai/v1",
        )
        resp = await client.chat.completions.create(
            model="meta-llama/Llama-3.3-70B-Instruct",
            messages=[
                {
                    "role": "user",
                    "content": 'Reply with JSON only, no markdown: {"status": "ok"}',
                }
            ],
            max_tokens=32,
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        assert "ok" in content.lower(), f"Unexpected response: {content!r}"
        _record(name, True, f"Response: {content.strip()[:80]}")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 2: AIML API ────────────────────────────────────────────────────────


async def test_aiml_connection() -> None:
    """
    Make a simple chat completion to AIML API (gpt-4o).
    Asserts the response contains "ok".
    """
    name = "AIML API (gpt-4o)"
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=os.environ["AIML_API_KEY"],
            base_url="https://api.aimlapi.com/v2",
        )
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": 'Reply with JSON only, no markdown: {"status": "ok"}',
                }
            ],
            max_tokens=32,
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        assert "ok" in content.lower(), f"Unexpected response: {content!r}"
        _record(name, True, f"Response: {content.strip()[:80]}")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 3: VirusTotal ───────────────────────────────────────────────────────


async def test_virustotal_connection() -> None:
    """
    Call VirusTotal API v3 to look up google.com. Asserts HTTP 200.
    """
    name = "VirusTotal API"
    try:
        import httpx
        import base64

        url_id = base64.urlsafe_b64encode(b"https://google.com").decode().rstrip("=")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://www.virustotal.com/api/v3/urls/{url_id}",
                headers={"x-apikey": os.environ["VIRUSTOTAL_API_KEY"]},
            )
        assert resp.status_code == 200, f"HTTP {resp.status_code}"
        data = resp.json()
        malicious = data["data"]["attributes"]["last_analysis_stats"].get("malicious", 0)
        _record(name, True, f"HTTP 200 — malicious votes for google.com: {malicious}")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 4: Google Safe Browsing ────────────────────────────────────────────


async def test_safe_browsing_connection() -> None:
    """
    Call Google Safe Browsing API v4 for google.com. Asserts HTTP 200.
    """
    name = "Google Safe Browsing API"
    try:
        import httpx

        key = os.environ["GOOGLE_SAFE_BROWSING_KEY"]
        payload = {
            "client": {"clientId": "payguard-ai", "clientVersion": "0.1.0"},
            "threatInfo": {
                "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING"],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": "https://google.com"}],
            },
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}",
                json=payload,
            )
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        _record(name, True, f"HTTP 200 — google.com is clean (no threats found)")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 5: WhoisJSON ────────────────────────────────────────────────────────


async def test_whoisjson_connection() -> None:
    """
    Call WhoisJSON API for google.com. Asserts HTTP 200 and a `created` field.
    """
    name = "WhoisJSON API"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://whoisjson.com/api/v1/whois",
                params={"domain": "google.com"},
                headers={"Authorization": f"Token {os.environ['WHOISJSON_KEY']}"},
            )
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        created = data.get("created") or data.get("creation_date") or data.get("created_date")
        assert created, f"No 'created' field in response keys: {list(data.keys())}"
        _record(name, True, f"HTTP 200 — google.com created: {created}")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 6: DuckDuckGo Search ────────────────────────────────────────────────


def test_duckduckgo_search() -> None:
    """
    Run a DDG text search for 'site:google.com'. Asserts at least 1 result.
    Synchronous — duckduckgo-search does not require an API key.
    """
    name = "DuckDuckGo Search (ddgs)"
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text("site:google.com", max_results=3))
        assert len(results) >= 1, f"Got 0 results"
        _record(name, True, f"{len(results)} result(s) — first: {results[0].get('title', '')[:60]}")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 7: Reddit (PRAW) ────────────────────────────────────────────────────


def test_reddit_connection() -> None:
    """
    Connect PRAW and search r/india for 'payment'. Asserts at least 1 result.
    """
    name = "Reddit PRAW"
    try:
        import praw

        reddit = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ.get("REDDIT_USER_AGENT", "PayGuardAI/1.0"),
        )
        results = list(reddit.subreddit("india").search("payment", limit=3))
        assert len(results) >= 1, "Got 0 results"
        _record(name, True, f"{len(results)} result(s) — first: {results[0].title[:60]}")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 8: Playwright (headless Chromium) ───────────────────────────────────


async def test_playwright_browser() -> None:
    """
    Launch headless Chromium, navigate to example.com, take a screenshot.
    Asserts screenshot byte length > 0.
    """
    name = "Playwright (headless Chromium)"
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://example.com", timeout=20_000)
            screenshot = await page.screenshot(full_page=True)
            await browser.close()

        assert len(screenshot) > 0, "Screenshot bytes is empty"
        _record(name, True, f"Screenshot captured — {len(screenshot):,} bytes")
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Runner ───────────────────────────────────────────────────────────────────


async def _run_async_tests() -> None:
    await test_featherless_connection()
    await test_aiml_connection()
    await test_virustotal_connection()
    await test_safe_browsing_connection()
    await test_whoisjson_connection()
    await test_playwright_browser()


def main() -> None:
    print("\n" + "=" * 60)
    print("  PayGuard AI — External API Connection Tests")
    print("=" * 60 + "\n")

    # Sync tests
    test_duckduckgo_search()
    test_reddit_connection()

    # Async tests
    asyncio.run(_run_async_tests())

    # Summary
    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  |  {failed} FAILED ← check your .env keys")
    else:
        print("  🎉  All connections verified!")
    print("=" * 60 + "\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
