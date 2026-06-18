"""
tests/test_agent1.py
=====================
Integration tests for Agent 1 — Destination Intelligence.

Runs real API calls to:
  - Band (room creation + message publish/read)
  - External intelligence APIs (VirusTotal, WHOIS, GSB, SSL)
  - Featherless AI (Llama 3.3 70B)

Each test:
  1. Creates a fresh Band room.
  2. Runs agent1.run() with the test inputs.
  3. Asserts the output schema is valid.
  4. Asserts the message was published to Band.
  5. Prints the full agent output for manual review.

Run with:
    python tests/test_agent1.py

Requirements: .env file with BAND_API_KEY, FEATHERLESS_API_KEY, and
optionally VIRUSTOTAL_API_KEY, GOOGLE_SAFE_BROWSING_KEY, WHOISJSON_KEY.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# ── Project root on sys.path ───────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import agents.agent1_destination as agent1
from services.band_client import BandClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_agent1")

# ─── Test Cases ───────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "name": "Legitimate domain — Razorpay",
        "url": "https://razorpay.com",
        "upi_id": None,
        "amount": 500.0,
        "product_description": "SaaS subscription payment",
        "source_type": "website",
        "additional_context": "Paying for my Razorpay dashboard subscription",
        "expected_risk": "LOW",
    },
    {
        "name": "Suspicious lookalike domain",
        "url": "https://razorpay-secure.co",
        "upi_id": None,
        "amount": 9999.0,
        "product_description": "iPhone 15 Pro 256GB",
        "source_type": "whatsapp_unknown",
        "additional_context": "Someone sent me this link on WhatsApp and said pay here to get the phone",
        "expected_risk": "HIGH",
    },
    {
        "name": "Legitimate UPI handle — Razorpay merchant",
        "url": None,
        "upi_id": "merchant@razorpay",
        "amount": 1200.0,
        "product_description": "E-commerce order payment",
        "source_type": "website",
        "additional_context": "Checking out on an e-commerce site",
        "expected_risk": "LOW",
    },
    {
        "name": "Suspicious individual UPI — random string",
        "url": None,
        "upi_id": "xkvb7722@ybl",
        "amount": 15000.0,
        "product_description": "Second-hand laptop",
        "source_type": "olx_marketplace",
        "additional_context": "The seller on OLX said to pay via UPI first and they will ship the laptop",
        "expected_risk": "MEDIUM or HIGH",
    },
]

# ─── Assertion helpers ────────────────────────────────────────────────────────


def assert_output_valid(output, test_name: str) -> list[str]:
    """
    Validate Agent1Output fields. Returns list of failure messages (empty = pass).
    """
    failures = []

    # risk_level must be present
    if output.risk_level is None:
        failures.append("risk_level is None")

    # agent_narrative must be a meaningful string
    narrative = output.agent_narrative or ""
    if len(narrative) < 50:
        failures.append(
            f"agent_narrative too short ({len(narrative)} chars < 50 min): '{narrative[:80]}'"
        )

    # top_signals must have at least 1 item
    if not output.top_signals or len(output.top_signals) == 0:
        failures.append("top_signals is empty")

    # timestamp must be a non-empty string
    if not output.timestamp:
        failures.append("timestamp is missing")

    return failures


async def assert_band_published(room, test_name: str) -> list[str]:
    """
    Verify at least one message with agent=destination_intelligence is in the room.
    """
    failures = []
    messages = await room.get_messages()
    agent_msgs = [m for m in messages if m.get("agent") == "destination_intelligence"]
    if not agent_msgs:
        failures.append("No message from 'destination_intelligence' found in Band room")
    return failures


# ─── Individual test runner ────────────────────────────────────────────────────


async def run_test(tc: dict, band_client: BandClient, test_index: int) -> bool:
    """
    Run a single test case. Returns True on pass, False on failure.
    """
    sep = "─" * 70
    print(f"\n{sep}")
    print(f"  TEST {test_index}: {tc['name']}")
    print(f"  URL: {tc.get('url')}  |  UPI: {tc.get('upi_id')}")
    print(f"  Amount: ₹{tc.get('amount')}  |  Expected risk: {tc.get('expected_risk')}")
    print(sep)

    # Create a fresh Band room per test
    room_name = f"payguard-test-agent1-{test_index}-{int(time.time())}"
    try:
        room = await band_client.create_room(room_name)
        print(f"  ✓ Band room created: {room.name} (id={room.id})")
    except Exception as exc:
        print(f"  ✗ FAILED to create Band room: {exc}")
        return False

    # Run Agent 1
    start = time.perf_counter()
    try:
        output = await agent1.run(
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
    print("\n  ── Agent 1 Output ──────────────────────────────────────────")
    print(f"  Risk Level    : {output.risk_level.value}")
    print(f"  Confidence    : (check Band message payload)")
    print(f"  Dest Type     : {output.destination_type}")
    if output.upi_id:
        print(f"  UPI ID        : {output.upi_id}  PSP: {output.upi_psp}")
    print(f"  Top Signals   :")
    for sig in output.top_signals:
        print(f"    • {sig}")
    print(f"  Narrative     :\n    {output.agent_narrative}")
    print(f"  Needs Clarif. : {output.needs_clarification}")
    if output.clarification_question:
        print(f"  Question      : {output.clarification_question}")
    print(f"  Timestamp     : {output.timestamp}")

    # Assertions
    all_failures = []

    output_failures = assert_output_valid(output, tc["name"])
    all_failures.extend(output_failures)

    band_failures = await assert_band_published(room, tc["name"])
    all_failures.extend(band_failures)

    if all_failures:
        print(f"\n  ✗ ASSERTIONS FAILED:")
        for f in all_failures:
            print(f"      - {f}")
        return False
    else:
        print(f"\n  ✓ All assertions passed!")
        expected = tc.get("expected_risk", "")
        actual = output.risk_level.value
        if expected and actual.upper() not in expected.upper():
            print(f"  ⚠  Note: expected risk={expected}, got risk={actual} "
                  f"(informational — LLM reasoning may differ from heuristic expectation)")
        else:
            print(f"  ✓ Risk level '{actual}' matches expected '{expected}'")
        return True


# ─── Main test runner ──────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 70)
    print("  PayGuard AI — Agent 1 Integration Tests")
    print("=" * 70)

    # Check critical env vars
    missing_keys = []
    for key in ("BAND_API_KEY", "FEATHERLESS_API_KEY"):
        if not os.getenv(key):
            missing_keys.append(key)
    if missing_keys:
        print(f"\n⚠  Warning: Missing critical env vars: {missing_keys}")
        print("   Tests will likely fail. Add them to your .env file.\n")

    optional_keys = ("VIRUSTOTAL_API_KEY", "GOOGLE_SAFE_BROWSING_KEY", "WHOISJSON_KEY")
    for key in optional_keys:
        if not os.getenv(key):
            print(f"  ℹ  {key} not set — that data source will return {{error: 'not configured'}}")

    async with BandClient() as band_client:
        results = []
        for i, tc in enumerate(TEST_CASES, start=1):
            passed = await run_test(tc, band_client, i)
            results.append((tc["name"], passed))
            # Small pause between tests to avoid API rate limits
            if i < len(TEST_CASES):
                print(f"\n  ⏳ Waiting 3s before next test (rate limit buffer)...")
                await asyncio.sleep(3)

    # Summary
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        icon = "✓" if ok else "✗"
        print(f"  {icon}  {name}")
    print(f"\n  {passed}/{total} tests passed")
    print("=" * 70)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
