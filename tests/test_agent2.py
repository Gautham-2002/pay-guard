"""
tests/test_agent2.py
=====================
Integration tests for Agent 2 — QR Decode & UPI Context Validator.

Runs real API calls to:
  - Band (room creation + message publish/read)
  - AIML API (gpt-4o — text reasoning)

Each test:
  1. Creates a fresh Band room.
  2. Pre-populates the room with a mock Agent 1 output.
  3. Runs agent2.run() with the test inputs.
  4. Asserts the output schema is valid.
  5. Asserts the message was published to Band.
  6. Asserts scenario-specific conditions (e.g. refund_scam_indicator, social_engineering_pattern).
  7. Prints the full agent output for manual review.

Run with:
    python tests/test_agent2.py

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

# ── Project root on sys.path ───────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import agents.agent2_qr_upi as agent2
from api.models import Agent2Output
from services.band_client import BandClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_agent2")

# ─── Mock Agent 1 Payloads ────────────────────────────────────────────────────
# Pre-populated Band room messages simulating Agent 1 output.
# These are generic enough to work across all test scenarios.

MOCK_AGENT1_GENERIC = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "UPI_ID",
    "risk_level": "MEDIUM",
    "top_signals": [
        "UPI ID uses individual account PSP (ybl / oksbi)",
        "No domain registration data (UPI-only check)",
        "Transaction context sourced from peer-to-peer marketplace",
    ],
    "agent_narrative": (
        "The destination is a UPI ID belonging to what appears to be an individual account. "
        "The PSP (oksbi) is typically associated with personal accounts rather than merchant handles. "
        "Combined with the marketplace sourcing, this warrants careful review."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}

MOCK_AGENT1_LOW_RISK = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "UPI_ID",
    "risk_level": "LOW",
    "top_signals": [
        "UPI ID uses merchant PSP (razorpay)",
        "Consistent with software/SaaS payment context",
        "No suspicious domain or threat signals",
    ],
    "agent_narrative": (
        "The destination UPI ID uses the Razorpay PSP, which is a registered payment gateway "
        "commonly used by legitimate Indian businesses for software subscriptions and e-commerce. "
        "The PSP and stated purchase context are consistent. No threat signals detected."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}

MOCK_AGENT1_HIGH_RISK = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "UPI_ID",
    "risk_level": "HIGH",
    "top_signals": [
        "UPI ID 'refund@paytm' is suspicious — legitimate refunds are never initiated by QR",
        "Source: WhatsApp from unknown contact",
        "Context mentions 'Amazon refund' — classic impersonation scam",
    ],
    "agent_narrative": (
        "The UPI ID 'refund@paytm' is a direct red flag — no legitimate refund process "
        "requires the customer to scan a QR code and send money. "
        "This is a classic Amazon refund impersonation scam where the victim is tricked "
        "into paying the fraudster believing they are receiving a refund."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}


# ─── Test Cases ───────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "name": "OLX buyer scam context",
        "mock_agent1": MOCK_AGENT1_GENERIC,
        "upi_id": "buyer123@oksbi",
        "amount": 1200.0,
        "source_type": "olx_marketplace",
        "product_description": "Second-hand laptop",
        "additional_context": (
            "A buyer on OLX sent me this UPI ID to pay for my old laptop. "
            "He said to pay first and he will ship it later."
        ),
        "expected_pattern": "olx_buyer_scam",
        "assertions": ["social_engineering_pattern contains olx"],
    },
    {
        "name": "Refund scam context",
        "mock_agent1": MOCK_AGENT1_HIGH_RISK,
        "upi_id": "refund@paytm",
        "amount": 9999.0,
        "source_type": "whatsapp_unknown",
        "product_description": None,
        "additional_context": (
            "They said I need to scan QR to get my Amazon refund of ₹9999. "
            "Someone called me from Amazon customer care."
        ),
        "expected_pattern": "refund_scam",
        "assertions": ["refund_scam_indicator is True"],
    },
    {
        "name": "Legitimate vendor payment",
        "mock_agent1": MOCK_AGENT1_LOW_RISK,
        "upi_id": "vendor@razorpay",
        "amount": 5000.0,
        "source_type": "website",
        "product_description": "Software subscription on company website",
        "additional_context": (
            "Paying for my annual software subscription on the vendor's official website. "
            "The UPI ID was shown on the checkout page."
        ),
        "expected_risk": "LOW",
        "assertions": ["source_risk_level is LOW"],
    },
]


# ─── Assertion helpers ────────────────────────────────────────────────────────


def assert_output_valid(output: Agent2Output, test_name: str) -> list[str]:
    """
    Validate Agent2Output fields. Returns list of failure messages (empty = pass).
    """
    failures = []

    # agent_narrative must be a meaningful string
    narrative = output.agent_narrative or ""
    if len(narrative) < 40:
        failures.append(
            f"agent_narrative too short ({len(narrative)} chars < 40 min): '{narrative[:80]}'"
        )

    # timestamp must be present
    if not output.timestamp:
        failures.append("timestamp is missing")

    # social_engineering_pattern must be set (can be "none")
    if output.social_engineering_pattern is None:
        failures.append("social_engineering_pattern is None — expected at least 'none' or a pattern")

    # manipulation_signals must be a list
    if not isinstance(output.manipulation_signals, list):
        failures.append("manipulation_signals is not a list")

    return failures


async def assert_band_published(room, test_name: str) -> list[str]:
    """
    Verify at least one message with agent=qr_upi_validator is in the room.
    """
    failures = []
    messages = await room.get_messages()
    agent_msgs = [m for m in messages if m.get("agent") == "qr_upi_validator"]
    if not agent_msgs:
        failures.append("No message from 'qr_upi_validator' found in Band room")
    return failures


def assert_scenario(output: Agent2Output, tc: dict) -> list[str]:
    """
    Run scenario-specific assertions based on tc["assertions"].
    Returns list of failure messages (empty = pass).
    """
    failures = []

    for assertion in tc.get("assertions", []):
        assertion_lower = assertion.lower()

        if "olx" in assertion_lower:
            pattern = (output.social_engineering_pattern or "").lower()
            if "olx" not in pattern and "buyer" not in pattern:
                failures.append(
                    f"Expected OLX scam pattern, got: '{output.social_engineering_pattern}'"
                )

        elif "refund_scam_indicator is true" in assertion_lower:
            if not output.refund_scam_indicator:
                failures.append(
                    f"Expected refund_scam_indicator=True, got: {output.refund_scam_indicator}. "
                    f"Pattern: {output.social_engineering_pattern}"
                )

        elif "source_risk_level is low" in assertion_lower:
            narrative_lower = (output.agent_narrative or "").lower()
            pattern = (output.social_engineering_pattern or "none").lower()
            # Either pattern=none or narrative does not indicate high risk
            if output.refund_scam_indicator or "high" in pattern:
                failures.append(
                    f"Expected LOW risk for legitimate payment, but got refund_scam={output.refund_scam_indicator} "
                    f"pattern={output.social_engineering_pattern}"
                )

    return failures


# ─── Individual test runner ────────────────────────────────────────────────────


async def run_test(tc: dict, band_client: BandClient, test_index: int) -> bool:
    """
    Run a single test case. Returns True on pass, False on failure.
    """
    sep = "─" * 70
    print(f"\n{sep}")
    print(f"  TEST {test_index}: {tc['name']}")
    print(f"  UPI: {tc.get('upi_id')}  |  Amount: ₹{tc.get('amount')}")
    print(f"  Source: {tc.get('source_type')}")
    print(f"  Context: {tc.get('additional_context', '')[:80]}...")
    print(sep)

    # Create a fresh Band room per test
    room_name = f"payguard-test-agent2-{test_index}-{int(time.time())}"
    try:
        room = await band_client.create_room(room_name)
        print(f"  ✓ Band room created: {room.name} (id={room.id})")
    except Exception as exc:
        print(f"  ✗ FAILED to create Band room: {exc}")
        return False

    # Pre-populate the room with a mock Agent 1 output
    mock_agent1 = tc.get("mock_agent1", MOCK_AGENT1_GENERIC)
    try:
        await room.publish(mock_agent1)
        print(f"  ✓ Mock Agent 1 output published to Band room (risk={mock_agent1['risk_level']})")
    except Exception as exc:
        print(f"  ✗ FAILED to publish mock Agent 1 output: {exc}")
        return False

    # Run Agent 2
    start = time.perf_counter()
    try:
        output = await agent2.run(
            band_room=room,
            qr_image_bytes=None,   # No QR image in these text-only scenarios
            upi_id=tc.get("upi_id"),
            url=tc.get("url"),
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
    print("\n  ── Agent 2 Output ──────────────────────────────────────────")
    print(f"  Decoded UPI ID     : {output.decoded_upi_id}")
    print(f"  Payee Name (QR)    : {output.payee_name_from_qr}")
    print(f"  Pre-filled Amount  : {output.prefilled_amount}")
    print(f"  UPI Context Mismatch: {output.upi_context_mismatch}")
    print(f"  Refund Scam        : {output.refund_scam_indicator}")
    print(f"  SE Pattern         : {output.social_engineering_pattern}")
    print(f"  Manipulation Sigs  :")
    for sig in output.manipulation_signals:
        print(f"    • {sig}")
    print(f"  Narrative          :\n    {output.agent_narrative}")
    print(f"  Needs Clarif.      : {output.needs_clarification}")
    if output.clarification_question:
        print(f"  Question           : {output.clarification_question}")
    print(f"  Timestamp          : {output.timestamp}")

    # Assertions
    all_failures = []

    output_failures = assert_output_valid(output, tc["name"])
    all_failures.extend(output_failures)

    band_failures = await assert_band_published(room, tc["name"])
    all_failures.extend(band_failures)

    scenario_failures = assert_scenario(output, tc)
    all_failures.extend(scenario_failures)

    if all_failures:
        print(f"\n  ✗ ASSERTIONS FAILED:")
        for f in all_failures:
            print(f"      - {f}")
        return False
    else:
        print(f"\n  ✓ All assertions passed!")
        expected_pattern = tc.get("expected_pattern", "")
        actual_pattern = output.social_engineering_pattern or "none"
        if expected_pattern:
            if expected_pattern.lower() in actual_pattern.lower():
                print(f"  ✓ Pattern '{actual_pattern}' matches expected '{expected_pattern}'")
            else:
                print(
                    f"  ⚠  Note: expected pattern='{expected_pattern}', "
                    f"got pattern='{actual_pattern}' "
                    f"(informational — LLM reasoning may differ from heuristic expectation)"
                )
        return True


# ─── Main test runner ──────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 70)
    print("  PayGuard AI — Agent 2 Integration Tests")
    print("=" * 70)

    # Check critical env vars
    missing_keys = []
    for key in ("BAND_API_KEY", "AIML_API_KEY"):
        if not os.getenv(key):
            missing_keys.append(key)
    if missing_keys:
        print(f"\n⚠  Warning: Missing critical env vars: {missing_keys}")
        print("   Tests will likely fail. Add them to your .env file.\n")

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
