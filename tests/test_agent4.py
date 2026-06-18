"""
tests/test_agent4.py
=====================
Integration tests for Agent 4 — Verdict Synthesis Agent.

Runs real API calls to:
  - Band (room creation + message publish/read)
  - AIML API (claude-3-5-sonnet — text reasoning)

Test cases
----------
1. Clear DANGER  — three agents all HIGH / refund scam / fraud complaints
   → assert verdict=DANGER, risk_score≥70, non-empty actions, empty ask_merchant

2. VERIFY with conflict — Agent 1 LOW (legit domain) vs Agent 2 HIGH (OLX buyer)
   → assert verdict=VERIFY, agent_agreement≠ALL_AGREE, non-empty conflict_resolution,
      non-empty ask_merchant

Run with:
    python tests/test_agent4.py

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

import agents.agent4_verdict as agent4
from api.models import Agent4Output, VerdictLevel
from services.band_client import BandClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_agent4")


# ─── Mock payloads ────────────────────────────────────────────────────────────

# Scenario 1: All three agents say HIGH / refund scam / fraud — clear DANGER
MOCK_AGENT1_HIGH = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "URL",
    "risk_level": "HIGH",
    "top_signals": [
        "Domain razorpay-secure.co registered 2 days ago",
        "Typosquatting: mimics Razorpay official domain",
        "SSL certificate issued by Let's Encrypt (1 day old)",
        "2 VirusTotal engines flagged as phishing",
    ],
    "agent_narrative": (
        "The domain razorpay-secure.co is a clear typosquatting attempt against "
        "Razorpay, India's leading payment gateway. Registered only 2 days ago with "
        "a freshly minted SSL certificate and two VirusTotal phishing detections, "
        "this is a highly dangerous phishing site designed to steal payment credentials."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}

MOCK_AGENT2_REFUND_SCAM = {
    "agent": "qr_upi_validator",
    "sequence": 2,
    "decoded_upi_id": "random123@ybl",
    "payee_name_from_qr": "Razorpay Refund Desk",
    "prefilled_amount": 9999.0,
    "upi_context_mismatch": True,
    "refund_scam_indicator": True,
    "visual_context": "QR code in a WhatsApp screenshot. No official branding.",
    "social_engineering_pattern": "refund_scam",
    "manipulation_signals": ["refund_framing", "urgency", "official_impersonation"],
    "agent_narrative": (
        "This is a classic refund scam. The QR code's payee name says 'Razorpay Refund Desk' "
        "but the actual UPI ID is 'random123@ybl' — a personal account with no connection to "
        "Razorpay whatsoever. You cannot receive money by scanning a QR code; you can only "
        "SEND money. The pre-filled amount of ₹9,999 is just under the ₹10,000 alert threshold. "
        "This is a high-confidence refund scam attempt."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:01:00+00:00",
}

MOCK_AGENT3_HIGH_FRAUD = {
    "agent": "web_intelligence",
    "sequence": 3,
    "website_crawled": True,
    "screenshot_analysis": (
        "Website has a fake Razorpay logo, countdown timer showing '23 minutes left', "
        "and text claiming 'Scan to receive your refund of ₹9,999'. No contact info visible. "
        "Classic urgency-based phishing page."
    ),
    "page_fraud_signals": [
        "fake_countdown_timer",
        "urgency_language",
        "no_contact_info",
        "impersonating_razorpay",
        "refund_receive_framing",
    ],
    "fraud_complaints_found": True,
    "complaint_sources": [
        "Reddit r/india: 'Got scammed ₹9,999 via razorpay-secure.co — they said it was a refund'",
        "Reddit r/LegalAdviceIndia: 'Fake Razorpay refund QR — lost money'",
        "Quora: 'Is razorpay-secure.co legit?' — top answer: 'SCAM SITE, report immediately'",
    ],
    "official_alternative_found": True,
    "official_site": "razorpay.com",
    "reddit_mentions": [
        "r/india: 'razorpay-secure.co is a scam — lost ₹9,999 last week'",
        "r/LegalAdviceIndia: 'How to report razorpay-secure.co to cybercrime?'",
    ],
    "price_intelligence": {
        "product_described": "Razorpay refund",
        "amount_requested": 9999.0,
        "market_price_range": None,
        "price_anomaly_type": "round_limit",
        "price_narrative": (
            "The amount ₹9,999 is deliberately set just under the ₹10,000 "
            "bank alert threshold — a classic fraud technique to avoid detection."
        ),
    },
    "web_risk_level": "HIGH",
    "agent_narrative": (
        "razorpay-secure.co is a confirmed fraudulent phishing site impersonating Razorpay. "
        "Multiple Reddit posts confirm users have lost money via this exact refund scam. "
        "The website features fake countdown timers, urgency language, and a refund framing "
        "designed to trick victims into scanning a QR code to 'receive' their refund — "
        "when in reality they would be sending money to a scammer."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:02:00+00:00",
}

# Scenario 2: Agent 1 LOW (legit domain), Agent 2 HIGH source (OLX), Agent 3 MEDIUM
MOCK_AGENT1_LOW = {
    "agent": "destination_intelligence",
    "sequence": 1,
    "destination_type": "UPI_ID",
    "upi_id": "seller_individual@oksbi",
    "upi_psp": "oksbi",
    "risk_level": "LOW",
    "top_signals": [
        "UPI PSP 'oksbi' is a valid State Bank of India UPI handle",
        "No WHOIS data — UPI ID, not a URL",
        "VPA structure: individual name format (not a merchant brand)",
    ],
    "agent_narrative": (
        "The UPI ID 'seller_individual@oksbi' uses State Bank of India's UPI PSP, "
        "which is legitimate and widely used. However, the username format suggests "
        "an individual account, not a registered merchant account. No URL-based "
        "signals to analyse as this is a UPI-only transaction."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:00:00+00:00",
}

MOCK_AGENT2_OLX_HIGH = {
    "agent": "qr_upi_validator",
    "sequence": 2,
    "decoded_upi_id": None,
    "payee_name_from_qr": None,
    "prefilled_amount": None,
    "upi_context_mismatch": True,
    "refund_scam_indicator": False,
    "visual_context": None,
    "social_engineering_pattern": "olx_buyer_scam",
    "manipulation_signals": ["advance_payment_request", "too_good_to_be_true_price"],
    "source_risk_level": "HIGH",
    "agent_narrative": (
        "The payment context raises significant OLX buyer scam concerns. "
        "The user is selling a laptop on OLX and the buyer is sending a UPI ID. "
        "OLX buyer scams are extremely common in India — the 'buyer' requests the "
        "seller to scan a QR or pay a small 'token amount' first, then disappears. "
        "The UPI ID is an individual account, not a verified buyer account. "
        "Agent 1's LOW risk for the UPI ID itself conflicts with the HIGH-risk "
        "social context from OLX — the context is more relevant here."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:01:00+00:00",
}

MOCK_AGENT3_MEDIUM = {
    "agent": "web_intelligence",
    "sequence": 3,
    "website_crawled": False,
    "screenshot_analysis": None,
    "page_fraud_signals": [],
    "fraud_complaints_found": False,
    "complaint_sources": [],
    "official_alternative_found": False,
    "official_site": None,
    "reddit_mentions": [
        "r/india: 'OLX buyer asked me to pay ₹1,200 token first — lost money'",
    ],
    "price_intelligence": {
        "product_described": "Used Dell laptop",
        "amount_requested": 1200.0,
        "market_price_range": "₹8,000 – ₹25,000",
        "price_anomaly_type": "too_low_bait",
        "price_narrative": (
            "₹1,200 for a used Dell laptop is far below market value (₹8,000–₹25,000). "
            "This extremely low price is a classic bait used in OLX scams to attract "
            "sellers into making an 'advance token payment'. "
            "The low amount ₹1,200 is chosen to seem like a trivial loss if the user proceeds."
        ),
    },
    "web_risk_level": "MEDIUM",
    "agent_narrative": (
        "No website to crawl (UPI-only transaction). Reddit mentions of OLX buyer scams "
        "are present but not specific to this UPI ID. Price intelligence flags the ₹1,200 "
        "payment as a classic advance-fee / OLX token payment scam pattern. "
        "The amount is suspiciously low for a used laptop, suggesting this is a token "
        "amount designed to establish trust before a larger fraud."
    ),
    "needs_clarification": False,
    "clarification_question": None,
    "timestamp": "2024-01-01T00:02:00+00:00",
}


# ─── Test cases ───────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "name": "Scenario 1 — Clear DANGER (refund scam, all agents HIGH)",
        "mock_agents": [MOCK_AGENT1_HIGH, MOCK_AGENT2_REFUND_SCAM, MOCK_AGENT3_HIGH_FRAUD],
        "url": "https://razorpay-secure.co",
        "upi_id": None,
        "amount": 9999.0,
        "product_description": "Razorpay payment gateway fee (claimed refund)",
        "source_type": "whatsapp_unknown",
        "additional_context": "They said I had a pending refund of ₹9,999 and sent me a QR to scan",
        "assertions": {
            "verdict": "DANGER",
            "risk_score_min": 70,
            "ask_merchant_empty": True,
            "recommended_actions_min": 2,
        },
    },
    {
        "name": "Scenario 2 — VERIFY with conflict (Agent 1 LOW vs Agent 2/3 HIGH/MEDIUM)",
        "mock_agents": [MOCK_AGENT1_LOW, MOCK_AGENT2_OLX_HIGH, MOCK_AGENT3_MEDIUM],
        "url": None,
        "upi_id": "seller_individual@oksbi",
        "amount": 1200.0,
        "product_description": "Used Dell laptop",
        "source_type": "olx_marketplace",
        "additional_context": "OLX buyer says pay ₹1,200 token amount first to confirm my seriousness",
        "assertions": {
            "verdict": "VERIFY",
            "agent_agreement_not": "ALL_AGREE",
            "conflict_resolution_nonempty": True,
            "ask_merchant_nonempty": True,
        },
    },
]


# ─── Assertion helpers ────────────────────────────────────────────────────────


def assert_output_schema(output: Agent4Output, test_name: str) -> list[str]:
    """Validate Agent4Output schema. Returns list of failure messages."""
    failures = []

    if output.verdict not in (VerdictLevel.SAFE, VerdictLevel.VERIFY, VerdictLevel.DANGER):
        failures.append(f"verdict is invalid: {output.verdict}")

    if not (0 <= output.risk_score <= 100):
        failures.append(f"risk_score {output.risk_score} out of range 0–100")

    if not output.plain_english_summary or len(output.plain_english_summary) < 30:
        failures.append(
            f"plain_english_summary too short ({len(output.plain_english_summary or '')} chars)"
        )

    if not isinstance(output.recommended_actions, list):
        failures.append("recommended_actions is not a list")

    if not isinstance(output.ask_merchant, list):
        failures.append("ask_merchant is not a list")

    if output.agent_agreement not in ("ALL_AGREE", "PARTIAL_CONFLICT", "FULL_CONFLICT"):
        failures.append(f"agent_agreement invalid: {output.agent_agreement}")

    if not output.timestamp:
        failures.append("timestamp is missing")

    if not output.band_room_id:
        failures.append("band_room_id is missing")

    return failures


def assert_scenario(output: Agent4Output, tc: dict) -> list[str]:
    """Run scenario-specific assertions. Returns list of failure messages."""
    failures = []
    a = tc["assertions"]

    if "verdict" in a:
        expected = a["verdict"]
        if output.verdict.value != expected:
            failures.append(
                f"Expected verdict={expected}, got {output.verdict.value}. "
                f"Summary: {output.plain_english_summary[:120]}"
            )

    if "risk_score_min" in a:
        min_score = a["risk_score_min"]
        if output.risk_score < min_score:
            failures.append(
                f"Expected risk_score ≥ {min_score}, got {output.risk_score}"
            )

    if a.get("ask_merchant_empty"):
        if output.ask_merchant:
            failures.append(
                f"Expected ask_merchant=[] for DANGER verdict, "
                f"got {output.ask_merchant}"
            )

    if "recommended_actions_min" in a:
        min_actions = a["recommended_actions_min"]
        if len(output.recommended_actions) < min_actions:
            failures.append(
                f"Expected ≥ {min_actions} recommended_actions, "
                f"got {len(output.recommended_actions)}: {output.recommended_actions}"
            )

    if "verdict" in a and a["verdict"] == "VERIFY":
        if output.ask_merchant:
            # VERIFY should have ask_merchant items
            pass  # OK
        # Note: ask_merchant_nonempty checked separately below

    if "agent_agreement_not" in a:
        not_expected = a["agent_agreement_not"]
        if output.agent_agreement == not_expected:
            failures.append(
                f"Expected agent_agreement != {not_expected}, "
                f"got {output.agent_agreement}"
            )

    if a.get("conflict_resolution_nonempty"):
        if not output.conflict_resolution or len(output.conflict_resolution.strip()) < 10:
            failures.append(
                f"Expected non-empty conflict_resolution, "
                f"got: '{output.conflict_resolution}'"
            )

    if a.get("ask_merchant_nonempty"):
        if not output.ask_merchant:
            failures.append(
                "Expected non-empty ask_merchant for VERIFY verdict, got []"
            )

    return failures


async def assert_band_published(room, test_name: str) -> list[str]:
    """Verify Agent 4 message is published to Band room."""
    failures = []
    messages = await room.get_messages()
    agent_msgs = [m for m in messages if m.get("agent") == "verdict_synthesis"]
    if not agent_msgs:
        failures.append("No message from 'verdict_synthesis' found in Band room")
    return failures


# ─── Individual test runner ────────────────────────────────────────────────────


async def run_test(tc: dict, band_client: BandClient, test_index: int) -> bool:
    sep = "─" * 70
    print(f"\n{sep}")
    print(f"  TEST {test_index}: {tc['name']}")
    print(f"  URL: {tc.get('url')}  |  UPI: {tc.get('upi_id')}  |  Amount: ₹{tc.get('amount')}")
    print(f"  Source: {tc.get('source_type')}")
    print(f"  Context: {tc.get('additional_context', '')[:80]}")
    print(sep)

    # Create fresh Band room
    room_name = f"payguard-test-agent4-{test_index}-{int(time.time())}"
    try:
        room = await band_client.create_room(room_name)
        print(f"  ✓ Band room created: {room.name} (id={room.id})")
    except Exception as exc:
        print(f"  ✗ FAILED to create Band room: {exc}")
        return False

    # Pre-populate with mock Agent 1, 2, 3 outputs
    agent_labels = ["Agent 1", "Agent 2", "Agent 3"]
    for mock_payload, label in zip(tc["mock_agents"], agent_labels):
        try:
            await room.publish(mock_payload)
            print(f"  ✓ Mock {label} output published to Band room")
        except Exception as exc:
            print(f"  ✗ FAILED to publish mock {label} output: {exc}")
            return False

    # Run Agent 4
    start = time.perf_counter()
    try:
        output = await agent4.run(
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
    print(f"  ✓ Agent 4 completed in {elapsed:.1f}s")

    # Pretty-print output
    print("\n  ── Agent 4 Output ──────────────────────────────────────────")
    print(f"  Verdict                : {output.verdict.value}")
    print(f"  Risk Score             : {output.risk_score}/100")
    print(f"  Agent Agreement        : {output.agent_agreement}")
    print(f"  Conflict Resolution    : {(output.conflict_resolution or 'N/A')[:120]}")
    print(f"  Plain English Summary  :\n    {output.plain_english_summary}")
    print(f"  Recommended Actions    :")
    for action in output.recommended_actions:
        print(f"    • {action}")
    print(f"  Ask Merchant           : {output.ask_merchant or '[]'}")
    print(f"  Avoided Fraud Estimate : {output.avoided_fraud_estimate or 'N/A'}")
    print(f"  Band Room ID           : {output.band_room_id}")
    print(f"  Timestamp              : {output.timestamp}")

    # Run assertions
    all_failures: list[str] = []
    all_failures.extend(assert_output_schema(output, tc["name"]))
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
    print("  PayGuard AI — Agent 4 Integration Tests")
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
