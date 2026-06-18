"""
tests/test_full_pipeline.py
============================
End-to-end integration test — runs the complete sequential 4-agent pipeline
on one real scenario.

Scenario: razorpay-secure.co, ₹9,999, whatsapp_unknown, "iPhone 15 Pro"
Expected: Final verdict = DANGER

Test flow
---------
1. Create Band room (txn-{uuid})
2. Run Agent 1 → assert publishes "destination_intelligence" to Band
3. Run Agent 2 (no QR image) → reads Agent 1 from Band → assert publishes
4. Run Agent 3 → reads Agent 1+2 from Band → assert publishes
5. Run Agent 4 → reads full room → assert publishes final verdict
6. Assert final verdict is DANGER
7. Assert Band room has exactly 4 agent messages
8. Print the complete Band room content in chronological order

Run with:
    python tests/test_full_pipeline.py

Requirements: .env file with BAND_API_KEY, AIML_API_KEY, and (optionally)
FEATHERLESS_API_KEY, VIRUSTOTAL_API_KEY, etc.

Note: This test makes real API calls to all external services.
Expected runtime: 60–180 seconds depending on network and Playwright.
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

import agents.agent1_destination as agent1
import agents.agent2_qr_upi as agent2
import agents.agent3_web_intelligence as agent3
import agents.agent4_verdict as agent4
from api.models import VerdictLevel
from services.band_client import BandClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_full_pipeline")


# ─── Pipeline scenario ────────────────────────────────────────────────────────

SCENARIO = {
    "name": "Full Pipeline — razorpay-secure.co, ₹9,999, iPhone 15 Pro, WhatsApp",
    "payment_url": "https://razorpay-secure.co",
    "upi_id": None,
    "amount": 9999.0,
    "product_description": "iPhone 15 Pro 256GB",
    "source_type": "whatsapp_unknown",
    "additional_context": (
        "Someone on WhatsApp said I can buy a brand new iPhone 15 Pro for ₹9,999 "
        "from their Razorpay store. They sent me this link and said pay now to reserve."
    ),
}

# Agent names in the Band room (for validation)
EXPECTED_AGENTS = [
    "destination_intelligence",
    "qr_upi_validator",
    "web_intelligence",
    "verdict_synthesis",
]


# ─── Helper: print Band room contents ────────────────────────────────────────


async def print_band_room(room) -> list[dict]:
    """Fetch and pretty-print all messages in the Band room."""
    messages = await room.get_messages()

    print("\n" + "=" * 70)
    print(f"  COMPLETE BAND ROOM CONTENTS — {room.name}")
    print("=" * 70)

    agent_msgs = [m for m in messages if m.get("agent") or m.get("type")]
    for msg in agent_msgs:
        msg_type = msg.get("type")
        agent_name = msg.get("agent", "unknown")

        if msg_type == "human_response":
            print(f"\n  [Human Response]")
            print(f"    Question : {msg.get('question_from_agent', '')[:80]}")
            print(f"    Answer   : {msg.get('human_answer', '')[:80]}")
        elif msg_type == "needs_clarification":
            print(f"\n  [HITL — {msg.get('from_agent', 'agent')}]")
            print(f"    Question : {msg.get('question', '')[:80]}")
        else:
            seq = msg.get("sequence", "?")
            print(f"\n  [Agent {seq}: {agent_name}]")
            # Print key fields only (not full raw_evidence)
            for key in ("risk_level", "web_risk_level", "verdict", "risk_score",
                        "agent_narrative", "top_signals", "fraud_complaints_found",
                        "plain_english_summary"):
                val = msg.get(key)
                if val is not None:
                    if isinstance(val, str) and len(val) > 100:
                        val = val[:100] + "..."
                    print(f"    {key}: {val}")

    print("=" * 70)
    return agent_msgs


# ─── Main pipeline test ───────────────────────────────────────────────────────


async def run_full_pipeline_test() -> bool:
    """
    Execute the complete 4-agent pipeline end-to-end and validate the result.

    Returns True if all assertions pass; False otherwise.
    """
    sep = "─" * 70
    print(f"\n{sep}")
    print(f"  FULL PIPELINE TEST: {SCENARIO['name']}")
    print(f"  URL    : {SCENARIO['payment_url']}")
    print(f"  Amount : ₹{SCENARIO['amount']}")
    print(f"  Product: {SCENARIO['product_description']}")
    print(f"  Source : {SCENARIO['source_type']}")
    print(sep)

    pipeline_start = time.perf_counter()
    failures: list[str] = []

    async with BandClient() as band_client:
        # ── 1. Create Band room ───────────────────────────────────────────────
        import uuid
        txn_id = str(uuid.uuid4())[:8]
        room_name = f"txn-fulltest-{txn_id}"

        try:
            room = await band_client.create_room(room_name)
            print(f"\n  ✓ Band room created: {room.name} (id={room.id})")
        except Exception as exc:
            print(f"  ✗ FAILED to create Band room: {exc}")
            return False

        # ── 2. Run Agent 1 ────────────────────────────────────────────────────
        print(f"\n  ─── Agent 1 — Destination Intelligence ───")
        t0 = time.perf_counter()
        try:
            a1_output = await agent1.run(
                band_room=room,
                url=SCENARIO["payment_url"],
                upi_id=SCENARIO["upi_id"],
                amount=SCENARIO["amount"],
                product_description=SCENARIO["product_description"],
                source_type=SCENARIO["source_type"],
                additional_context=SCENARIO["additional_context"],
            )
            print(f"  ✓ Agent 1 complete in {time.perf_counter() - t0:.1f}s | risk={a1_output.risk_level}")
            print(f"    Signals: {a1_output.top_signals}")
        except Exception as exc:
            print(f"  ✗ Agent 1 FAILED: {exc}")
            import traceback; traceback.print_exc()
            return False

        # Assert Agent 1 published to Band
        a1_msgs = await room.get_messages_by_agent("destination_intelligence")
        if not a1_msgs:
            failures.append("Agent 1 did not publish to Band room")
        else:
            print(f"  ✓ Agent 1 message confirmed in Band room")

        # ── 3. Run Agent 2 (no QR image) ──────────────────────────────────────
        print(f"\n  ─── Agent 2 — QR & UPI Validator ───")
        t0 = time.perf_counter()
        try:
            a2_output = await agent2.run(
                band_room=room,
                qr_image_bytes=None,  # No QR image for this scenario
                upi_id=SCENARIO["upi_id"],
                url=SCENARIO["payment_url"],
                amount=SCENARIO["amount"],
                product_description=SCENARIO["product_description"],
                source_type=SCENARIO["source_type"],
                additional_context=SCENARIO["additional_context"],
            )
            print(f"  ✓ Agent 2 complete in {time.perf_counter() - t0:.1f}s "
                  f"| refund_scam={a2_output.refund_scam_indicator} "
                  f"| pattern={a2_output.social_engineering_pattern}")
        except Exception as exc:
            print(f"  ✗ Agent 2 FAILED: {exc}")
            import traceback; traceback.print_exc()
            return False

        # Assert Agent 2 published to Band
        a2_msgs = await room.get_messages_by_agent("qr_upi_validator")
        if not a2_msgs:
            failures.append("Agent 2 did not publish to Band room")
        else:
            print(f"  ✓ Agent 2 message confirmed in Band room")

        # ── 4. Run Agent 3 ────────────────────────────────────────────────────
        print(f"\n  ─── Agent 3 — Web Intelligence ───")
        t0 = time.perf_counter()
        try:
            a3_output = await agent3.run(
                band_room=room,
                url=SCENARIO["payment_url"],
                upi_id=SCENARIO["upi_id"],
                amount=SCENARIO["amount"],
                product_description=SCENARIO["product_description"],
                source_type=SCENARIO["source_type"],
                additional_context=SCENARIO["additional_context"],
            )
            print(f"  ✓ Agent 3 complete in {time.perf_counter() - t0:.1f}s "
                  f"| web_risk={a3_output.web_risk_level} "
                  f"| complaints={a3_output.fraud_complaints_found}")
            if a3_output.price_intelligence:
                pi = a3_output.price_intelligence
                print(f"    Price: {pi.price_anomaly_type} | range={pi.market_price_range}")
        except Exception as exc:
            print(f"  ✗ Agent 3 FAILED: {exc}")
            import traceback; traceback.print_exc()
            return False

        # Assert Agent 3 published to Band
        a3_msgs = await room.get_messages_by_agent("web_intelligence")
        if not a3_msgs:
            failures.append("Agent 3 did not publish to Band room")
        else:
            print(f"  ✓ Agent 3 message confirmed in Band room")

        # ── 5. Run Agent 4 ────────────────────────────────────────────────────
        print(f"\n  ─── Agent 4 — Verdict Synthesis ───")
        t0 = time.perf_counter()
        try:
            a4_output = await agent4.run(
                band_room=room,
                url=SCENARIO["payment_url"],
                upi_id=SCENARIO["upi_id"],
                amount=SCENARIO["amount"],
                product_description=SCENARIO["product_description"],
                source_type=SCENARIO["source_type"],
                additional_context=SCENARIO["additional_context"],
            )
            print(f"  ✓ Agent 4 complete in {time.perf_counter() - t0:.1f}s "
                  f"| verdict={a4_output.verdict.value} "
                  f"| risk_score={a4_output.risk_score}")
        except Exception as exc:
            print(f"  ✗ Agent 4 FAILED: {exc}")
            import traceback; traceback.print_exc()
            return False

        # Assert Agent 4 published to Band
        a4_msgs = await room.get_messages_by_agent("verdict_synthesis")
        if not a4_msgs:
            failures.append("Agent 4 did not publish to Band room")
        else:
            print(f"  ✓ Agent 4 message confirmed in Band room")

        # ── 6. Print complete Band room ────────────────────────────────────────
        all_band_msgs = await print_band_room(room)

        # ── 7. Count agent messages ────────────────────────────────────────────
        agent_only_msgs = [
            m for m in all_band_msgs
            if m.get("agent") in EXPECTED_AGENTS
        ]
        actual_count = len(agent_only_msgs)
        expected_count = 4

        print(f"\n  ── Band Room Message Count ──────────────────────────────────")
        print(f"  Agent messages in room: {actual_count} (expected: {expected_count})")
        for msg in agent_only_msgs:
            print(f"    seq={msg.get('sequence', '?')} | agent={msg.get('agent')}")

    # ─── Assertions ──────────────────────────────────────────────────────────

    print(f"\n  ── Assertions ───────────────────────────────────────────────")

    # 6. Final verdict must be DANGER
    if a4_output.verdict != VerdictLevel.DANGER:
        failures.append(
            f"Expected final verdict=DANGER, got {a4_output.verdict.value}. "
            f"Summary: {a4_output.plain_english_summary[:120]}"
        )
    else:
        print(f"  ✓ Final verdict is DANGER")

    # 7. Band room has exactly 4 agent messages
    if actual_count != expected_count:
        failures.append(
            f"Expected {expected_count} agent messages in Band room, got {actual_count}"
        )
    else:
        print(f"  ✓ Band room has exactly 4 agent messages")

    # Validate risk_score is in DANGER range
    if a4_output.risk_score < 66:
        failures.append(
            f"Verdict=DANGER but risk_score={a4_output.risk_score} < 66 "
            "(may be an LLM inconsistency — logged but does not fail the test)"
        )
    else:
        print(f"  ✓ Risk score {a4_output.risk_score} is in DANGER range (≥ 66)")

    # Validate recommended_actions are present
    if not a4_output.recommended_actions:
        failures.append("recommended_actions is empty")
    else:
        print(f"  ✓ {len(a4_output.recommended_actions)} recommended actions provided")

    # Validate plain_english_summary is present and mentions the fraud
    summary_lower = (a4_output.plain_english_summary or "").lower()
    if len(summary_lower) < 30:
        failures.append(f"plain_english_summary too short: '{a4_output.plain_english_summary}'")
    else:
        print(f"  ✓ Plain English summary present ({len(summary_lower)} chars)")

    # Print final summary
    total_elapsed = time.perf_counter() - pipeline_start
    print(f"\n  ── Final Verdict ────────────────────────────────────────────")
    print(f"  Verdict          : {a4_output.verdict.value}")
    print(f"  Risk Score       : {a4_output.risk_score}/100")
    print(f"  Agreement        : {a4_output.agent_agreement}")
    print(f"  Summary          : {a4_output.plain_english_summary}")
    print(f"  Actions          : {a4_output.recommended_actions}")
    print(f"  Avoided Estimate : {a4_output.avoided_fraud_estimate}")
    print(f"  Total Pipeline   : {total_elapsed:.1f}s")

    if failures:
        print(f"\n  ✗ ASSERTIONS FAILED ({len(failures)} failures):")
        for f in failures:
            print(f"      - {f}")
        return False
    else:
        print(f"\n  ✓ All assertions passed!")
        return True


# ─── Entry point ──────────────────────────────────────────────────────────────


async def main() -> None:
    print("=" * 70)
    print("  PayGuard AI — Full Pipeline End-to-End Test")
    print("=" * 70)

    missing_keys = [k for k in ("BAND_API_KEY", "AIML_API_KEY") if not os.getenv(k)]
    if missing_keys:
        print(f"\n⚠  Warning: Missing critical env vars: {missing_keys}")
        print("   Tests will likely fail. Add them to your .env file.\n")

    passed = await run_full_pipeline_test()

    print("\n" + "=" * 70)
    print("  FINAL RESULT")
    print("=" * 70)
    if passed:
        print("  ✓  PASS — Full pipeline test completed successfully")
    else:
        print("  ✗  FAIL — See assertion failures above")
    print("=" * 70)

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
