"""
tests/test_agent3.py
=====================
Integration tests for Agent 3 — Web Intelligence Agent.

Runs real API calls to:
  - Band (room creation + message publish/read)
  - AIML API (gpt-4o — vision + text reasoning)
  - Playwright (headless Chromium crawl)
  - DuckDuckGo search (no API key)
  - PRAW Reddit (optional — falls back gracefully)
  - Quora HTTP scrape

Test cases
----------
1. Known suspicious domain (razorpay-secure.co) — expect web_risk_level=HIGH
2. Legitimate domain (razorpay.com)             — expect web_risk_level=LOW
3. UPI only + low price for iPhone              — expect price_anomaly_type=too_low_bait
4. UPI only + reasonable price for course       — expect price_assessment=reasonable

Run with:
    python tests/test_agent3.py

Requirements: .env file with BAND_API_KEY and AIML_API_KEY.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import agents.agent3_web_intelligence as agent3
from api.models import Agent3Output, RiskLevel
from services.band_client import BandClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_agent3")


# ─── Mock Agent 1 + 2 Payloads ────────────────────────────────────────────────

MOCK_AGENT1_SUSPICIOUS = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "URL",
    "risk_level": "HIGH",
    "top_signals": [
        "Domain razorpay-secure.co registered very recently (< 30 days)",
        "Typosquatting: mimics razorpay.com with deceptive subdomain",
        "No WHOIS privacy — random registrant data",
        "SSL certificate issued only 2 days ago",
    ],
    "agent_narrative": (
        "The domain razorpay-secure.co is a clear typosquatting attempt against the legitimate "
        "payment gateway Razorpay. It was registered recently and uses a deceptive name "
        "designed to fool users into trusting it as an official Razorpay page. "
        "This is a high-risk phishing destination."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}

MOCK_AGENT1_LEGITIMATE = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "URL",
    "risk_level": "LOW",
    "top_signals": [
        "razorpay.com is the official Razorpay payment gateway",
        "Domain age > 10 years, reputable registrant",
        "Valid EV SSL certificate",
        "No threat signals in VirusTotal or Google Safe Browsing",
    ],
    "agent_narrative": (
        "razorpay.com is the verified official website of Razorpay, India's leading payment "
        "gateway. It has a long domain history, valid EV SSL, and zero threat signals. "
        "This is a trusted and legitimate payment destination."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}

MOCK_AGENT1_UPI_ONLY = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "UPI_ID",
    "risk_level": "MEDIUM",
    "top_signals": [
        "UPI ID uses individual PSP (ybl)",
        "No associated business registration found",
        "Source: WhatsApp from unknown contact",
    ],
    "agent_narrative": (
        "The destination is a personal UPI ID on the YBL PSP. "
        "This could be a legitimate individual seller or a scammer. "
        "The source being WhatsApp from an unknown contact warrants caution."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}

MOCK_AGENT2_GENERIC = {
    "agent": "qr_upi_validator",
    "sequence": 2,
    "decoded_upi_id": None,
    "upi_context_mismatch": False,
    "refund_scam_indicator": False,
    "social_engineering_pattern": "none",
    "manipulation_signals": [],
    "agent_narrative": "No QR code provided. UPI context appears standard based on stated purchase.",
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}


# ─── Test Cases ───────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "name": "Suspicious domain — razorpay-secure.co",
        "mock_agent1": MOCK_AGENT1_SUSPICIOUS,
        "mock_agent2": MOCK_AGENT2_GENERIC,
        "url": "https://razorpay-secure.co",
        "upi_id": None,
        "amount": 4999.0,
        "product_description": "iPhone case",
        "source_type": "website",
        "additional_context": "Found this site from a WhatsApp forward claiming Razorpay cashback",
        "assertions": ["web_risk_level is HIGH"],
    },
    {
        "name": "Legitimate domain — razorpay.com",
        "mock_agent1": MOCK_AGENT1_LEGITIMATE,
        "mock_agent2": MOCK_AGENT2_GENERIC,
        "url": "https://razorpay.com",
        "upi_id": None,
        "amount": 2999.0,
        "product_description": "SaaS subscription",
        "source_type": "website",
        "additional_context": "Paying for a business software subscription",
        "assertions": ["web_risk_level is LOW or MEDIUM"],
    },
    {
        "name": "UPI only — iPhone ₹5000 (too low bait)",
        "mock_agent1": MOCK_AGENT1_UPI_ONLY,
        "mock_agent2": MOCK_AGENT2_GENERIC,
        "url": None,
        "upi_id": "seller123@ybl",
        "amount": 5000.0,
        "product_description": "iPhone 15 Pro 256GB",
        "source_type": "olx_marketplace",
        "additional_context": "Seller on OLX offering brand new iPhone 15 Pro for ₹5000, says it's urgent",
        "assertions": ["price_anomaly_type is too_low_bait"],
    },
    {
        "name": "UPI only — Course subscription ₹999 (reasonable)",
        "mock_agent1": MOCK_AGENT1_UPI_ONLY,
        "mock_agent2": MOCK_AGENT2_GENERIC,
        "url": None,
        "upi_id": "courses@razorpay",
        "amount": 999.0,
        "product_description": "Online Python programming course subscription",
        "source_type": "website",
        "additional_context": "Paying for annual access to an online learning platform",
        "assertions": ["price_assessment is reasonable"],
    },
]


# ─── Assertion helpers ────────────────────────────────────────────────────────


def assert_output_valid(output: Agent3Output, test_name: str) -> list[str]:
    """Validate Agent3Output schema. Returns list of failure messages."""
    failures = []

    narrative = output.agent_narrative or ""
    if len(narrative) < 40:
        failures.append(
            f"agent_narrative too short ({len(narrative)} chars < 40 min): '{narrative[:80]}'"
        )

    if not output.timestamp:
        failures.append("timestamp is missing")

    if output.web_risk_level not in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH):
        failures.append(f"web_risk_level invalid: {output.web_risk_level}")

    if not isinstance(output.page_fraud_signals, list):
        failures.append("page_fraud_signals is not a list")

    if not isinstance(output.complaint_sources, list):
        failures.append("complaint_sources is not a list")

    return failures


async def assert_band_published(room, test_name: str) -> list[str]:
    """Verify at least one Agent3 message is in the room."""
    failures = []
    messages = await room.get_messages()
    agent_msgs = [m for m in messages if m.get("agent") == "web_intelligence"]
    if not agent_msgs:
        failures.append("No message from 'web_intelligence' found in Band room")
    return failures


def assert_scenario(output: Agent3Output, tc: dict) -> list[str]:
    """Run scenario-specific assertions. Returns list of failure messages."""
    failures = []

    for assertion in tc.get("assertions", []):
        a = assertion.lower()

        if "web_risk_level is high" in a:
            if output.web_risk_level != RiskLevel.HIGH:
                failures.append(
                    f"Expected web_risk_level=HIGH, got: {output.web_risk_level}. "
                    f"Narrative: {output.agent_narrative[:120]}"
                )

        elif "web_risk_level is low or medium" in a:
            if output.web_risk_level == RiskLevel.HIGH:
                failures.append(
                    f"Expected web_risk_level=LOW or MEDIUM for legitimate site, "
                    f"got HIGH. Narrative: {output.agent_narrative[:120]}"
                )

        elif "price_anomaly_type is too_low_bait" in a:
            pi = output.price_intelligence
            if pi is None:
                failures.append("Expected price_intelligence object, got None")
            elif pi.price_anomaly_type != "too_low_bait":
                failures.append(
                    f"Expected price_anomaly_type=too_low_bait, "
                    f"got: {pi.price_anomaly_type}. "
                    f"Narrative: {pi.price_narrative[:120]}"
                )

        elif "price_assessment is reasonable" in a:
            pi = output.price_intelligence
            if pi is None:
                failures.append("Expected price_intelligence object, got None")
            else:
                # LLM might say "reasonable" in different forms
                narrative_lower = (pi.price_narrative or "").lower()
                assessment_lower = (pi.price_assessment or "").lower()
                if "reasonable" not in assessment_lower and "reasonable" not in narrative_lower:
                    failures.append(
                        f"Expected price_assessment=reasonable or narrative mentioning reasonable, "
                        f"got assessment='{pi.price_assessment}'. "
                        f"Narrative: {pi.price_narrative[:120]}"
                    )

    return failures


# ─── Individual test runner ────────────────────────────────────────────────────


async def run_test(tc: dict, band_client: BandClient, test_index: int) -> bool:
    sep = "─" * 70
    print(f"\n{sep}")
    print(f"  TEST {test_index}: {tc['name']}")
    print(f"  URL: {tc.get('url')}  |  UPI: {tc.get('upi_id')}  |  Amount: ₹{tc.get('amount')}")
    print(f"  Product: {tc.get('product_description')}")
    print(f"  Context: {tc.get('additional_context', '')[:80]}")
    print(sep)

    # Create fresh Band room
    room_name = f"payguard-test-agent3-{test_index}-{int(time.time())}"
    try:
        room = await band_client.create_room(room_name)
        print(f"  ✓ Band room created: {room.name} (id={room.id})")
    except Exception as exc:
        print(f"  ✗ FAILED to create Band room: {exc}")
        return False

    # Pre-populate with mock Agent 1 + 2 outputs
    for mock_payload, label in [
        (tc.get("mock_agent1", MOCK_AGENT1_UPI_ONLY), "Agent 1"),
        (tc.get("mock_agent2", MOCK_AGENT2_GENERIC), "Agent 2"),
    ]:
        try:
            await room.publish(mock_payload)
            print(f"  ✓ Mock {label} output published to Band room")
        except Exception as exc:
            print(f"  ✗ FAILED to publish mock {label} output: {exc}")
            return False

    # Run Agent 3
    start = time.perf_counter()
    try:
        output = await agent3.run(
            band_room=room,
            url=tc.get("url"),
            upi_id=tc.get("upi_id"),
            amount=tc.get("amount"),
            product_description=tc.get("product_description"),
            source_type=tc.get("source_type"),
            additional_context=tc.get("additional_context"),
        )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        print(f"  ✗ AGENT RUN FAILED after {elapsed:.1f}s: {exc}")
        import traceback
        traceback.print_exc()
        return False

    elapsed = time.perf_counter() - start
    print(f"  ✓ Agent completed in {elapsed:.1f}s")

    # Pretty-print output
    print("\n  ── Agent 3 Output ──────────────────────────────────────────")
    print(f"  Web Risk Level        : {output.web_risk_level}")
    print(f"  Website Crawled       : {output.website_crawled}")
    print(f"  Screenshot Analysis   : {(output.screenshot_analysis or '')[:100]}")
    print(f"  Page Fraud Signals    :")
    for sig in output.page_fraud_signals:
        print(f"    • {sig}")
    print(f"  Fraud Complaints Found: {output.fraud_complaints_found}")
    print(f"  Complaint Sources     : {output.complaint_sources}")
    print(f"  Official Site Found   : {output.official_alternative_found}")
    print(f"  Official Site URL     : {output.official_site}")
    print(f"  Reddit Mentions       : {len(output.reddit_mentions)} posts")
    for rm in output.reddit_mentions:
        print(f"    • {rm[:80]}")
    if output.price_intelligence:
        pi = output.price_intelligence
        print(f"  Price Intelligence    :")
        print(f"    Market Range        : {pi.market_price_range}")
        print(f"    Assessment          : {pi.price_assessment}")
        print(f"    Anomaly Type        : {pi.price_anomaly_type}")
        print(f"    Narrative           : {pi.price_narrative[:120]}")
    print(f"  Agent Narrative       :\n    {output.agent_narrative}")
    print(f"  Needs Clarification   : {output.needs_clarification}")
    if output.clarification_question:
        print(f"  Clarif. Question      : {output.clarification_question}")
    print(f"  Timestamp             : {output.timestamp}")

    # Run assertions
    all_failures: list[str] = []
    all_failures.extend(assert_output_valid(output, tc["name"]))
    all_failures.extend(await assert_band_published(room, tc["name"]))
    all_failures.extend(assert_scenario(output, tc))

    if all_failures:
        print(f"\n  ✗ ASSERTIONS FAILED:")
        for f in all_failures:
            print(f"      - {f}")
        return False
    else:
        print(f"\n  ✓ All assertions passed!")
        return True


# ─── Main test runner ─────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 70)
    print("  PayGuard AI — Agent 3 Integration Tests")
    print("=" * 70)

    missing_keys = [k for k in ("BAND_API_KEY", "AIML_API_KEY") if not os.getenv(k)]
    if missing_keys:
        print(f"\n⚠  Warning: Missing critical env vars: {missing_keys}")
        print("   Tests will likely fail. Add them to your .env file.\n")

    async with BandClient() as band_client:
        results = []
        for i, tc in enumerate(TEST_CASES, start=1):
            passed = await run_test(tc, band_client, i)
            results.append((tc["name"], passed))
            if i < len(TEST_CASES):
                print(f"\n  ⏳ Waiting 5s before next test (rate limit buffer)...")
                await asyncio.sleep(5)

    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    total = len(results)
    passed_count = sum(1 for _, ok in results if ok)
    for name, ok in results:
        icon = "✓" if ok else "✗"
        print(f"  {icon}  {name}")
    print(f"\n  {passed_count}/{total} tests passed")
    print("=" * 70)

    if passed_count < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
