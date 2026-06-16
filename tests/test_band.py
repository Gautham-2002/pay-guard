"""
PayGuard AI — Band Integration Tests
======================================
Real API tests for the Band client wrapper (services/band_client.py).

Usage:
    python tests/test_band.py

Each test runs against the live Band API.  Requires BAND_API_KEY in .env.

Tests
-----
1. test_create_room          — Create a room; assert room.id is non-empty.
2. test_publish_and_read     — Publish a message; assert it appears in get_messages().
3. test_wait_for_agent       — Publish with agent="domain_intel"; assert wait_for_agent returns it.
4. test_wait_timeout         — wait_for_agent("nonexistent_agent", 3s) → returns None.
5. test_get_full_context     — Publish 2 agent messages; assert both appear in get_full_context().
6. test_human_response       — Publish human_response; assert wait_for_human_response returns it.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

# Ensure project root is on sys.path when running from any directory
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv()

from services.band_client import BandClient, BandConnectionError, BandTimeoutError  # noqa: E402

# ─── Helpers ──────────────────────────────────────────────────────────────────

_results: list[tuple[str, bool, str]] = []


def _record(name: str, passed: bool, detail: str = "") -> None:
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}  {name}" + (f"\n         {detail}" if detail else ""))
    _results.append((name, passed, detail))


def _unique_room_name() -> str:
    ts = int(time.time())
    return f"test-payguard-{ts}"


# ─── Test 1: Create Room ──────────────────────────────────────────────────────


async def test_create_room() -> None:
    """
    Create a room named ``test-payguard-{timestamp}``.
    Assert ``room.id`` is a non-empty string.
    """
    name = "test_create_room"
    try:
        async with BandClient() as client:
            room_name = _unique_room_name()
            room = await client.create_room(room_name)

            assert isinstance(room.id, str) and room.id, (
                f"room.id must be a non-empty string, got: {room.id!r}"
            )
            _record(name, True, f"room.id={room.id} | name='{room.name}'")
    except AssertionError as exc:
        _record(name, False, str(exc))
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")


# ─── Test 2: Publish & Read ───────────────────────────────────────────────────


async def test_publish_and_read() -> None:
    """
    Publish a test message, then call get_messages().
    Assert the message is present in the result.
    """
    name = "test_publish_and_read"
    try:
        async with BandClient() as client:
            room = await client.create_room(_unique_room_name())
            payload = {"agent": "test", "sequence": 1, "data": "hello"}
            await room.publish(payload)

            # Brief pause to let Band process the message
            await asyncio.sleep(1)

            messages = await room.get_messages()
            assert len(messages) >= 1, f"Expected >=1 message, got {len(messages)}"

            found = any(
                m.get("agent") == "test" and m.get("data") == "hello"
                for m in messages
            )
            assert found, (
                f"Published message not found in {len(messages)} messages. "
                f"First message: {messages[0] if messages else 'none'}"
            )
            _record(name, True, f"Published & retrieved {len(messages)} message(s)")
    except AssertionError as exc:
        _record(name, False, str(exc))
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


# ─── Test 3: Wait For Agent ───────────────────────────────────────────────────


async def test_wait_for_agent() -> None:
    """
    Publish a message with agent="domain_intel", then call
    ``wait_for_agent("domain_intel", timeout_seconds=10)``.
    Assert it returns the message.
    """
    name = "test_wait_for_agent"
    try:
        async with BandClient() as client:
            room = await client.create_room(_unique_room_name())
            payload = {
                "agent": "domain_intel",
                "sequence": 1,
                "result": {"domain": "example.com", "safe": True},
            }
            await room.publish(payload)

            result = await room.wait_for_agent("domain_intel", timeout_seconds=10)
            assert result is not None, "wait_for_agent returned None (timed out)"
            assert result.get("agent") == "domain_intel", (
                f"Expected agent='domain_intel', got {result.get('agent')!r}"
            )
            _record(name, True, f"Received message from domain_intel: {list(result.keys())}")
    except AssertionError as exc:
        _record(name, False, str(exc))
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


# ─── Test 4: Wait Timeout ────────────────────────────────────────────────────


async def test_wait_timeout() -> None:
    """
    Call ``wait_for_agent("nonexistent_agent", timeout_seconds=3)`` on an empty room.
    Assert it returns None within ~3 seconds.
    """
    name = "test_wait_timeout"
    try:
        async with BandClient() as client:
            room = await client.create_room(_unique_room_name())

            start = time.monotonic()
            result = await room.wait_for_agent("nonexistent_agent", timeout_seconds=3)
            elapsed = time.monotonic() - start

            assert result is None, f"Expected None, got: {result!r}"
            assert elapsed < 5, f"Timeout took too long: {elapsed:.1f}s (expected ~3s)"
            _record(name, True, f"Returned None after {elapsed:.1f}s ✓")
    except AssertionError as exc:
        _record(name, False, str(exc))
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


# ─── Test 5: Get Full Context ─────────────────────────────────────────────────


async def test_get_full_context() -> None:
    """
    Publish 2 messages from different agents.
    Call ``get_full_context()``.
    Assert the output is a string containing both agent names and their content.
    """
    name = "test_get_full_context"
    try:
        async with BandClient() as client:
            room = await client.create_room(_unique_room_name())

            await room.publish({
                "agent": "domain_intel",
                "sequence": 1,
                "verdict": "safe",
                "domain_age_days": 1200,
            })
            await room.publish({
                "agent": "qr_scanner",
                "sequence": 2,
                "qr_data": "upi://pay?pa=merchant@upi&am=500",
            })

            await asyncio.sleep(1)  # Let Band process both messages

            context = await room.get_full_context()

            assert isinstance(context, str) and len(context) > 0, "get_full_context() returned empty"
            assert "domain_intel" in context, "'domain_intel' missing from context"
            assert "qr_scanner" in context, "'qr_scanner' missing from context"
            assert room.name in context, f"Room name '{room.name}' missing from context header"

            # Spot-check that actual payload values appear
            assert "safe" in context, "'safe' verdict missing from context"
            assert "upi://" in context, "QR data missing from context"

            _record(
                name, True,
                f"Context is {len(context)} chars, contains both agent names ✓"
            )
            print(f"\n--- Sample get_full_context() output (first 400 chars) ---\n"
                  f"{context[:400]}\n---")
    except AssertionError as exc:
        _record(name, False, str(exc))
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


# ─── Test 6: Human Response ───────────────────────────────────────────────────


async def test_human_response() -> None:
    """
    Publish a human_response message.
    Call ``wait_for_human_response(timeout_seconds=5)``.
    Assert it returns the message.
    """
    name = "test_human_response"
    try:
        async with BandClient() as client:
            room = await client.create_room(_unique_room_name())

            payload = {
                "type": "human_response",
                "human_answer": "Yes",
                "question_id": "q1",
            }
            await room.publish(payload)

            await asyncio.sleep(1)  # Let Band process

            result = await room.wait_for_human_response(timeout_seconds=5)
            assert result is not None, "wait_for_human_response returned None (timed out)"
            assert result.get("type") == "human_response", (
                f"Expected type='human_response', got {result.get('type')!r}"
            )
            assert result.get("human_answer") == "Yes", (
                f"Expected human_answer='Yes', got {result.get('human_answer')!r}"
            )
            _record(name, True, f"Received human_response: human_answer={result.get('human_answer')!r}")
    except AssertionError as exc:
        _record(name, False, str(exc))
    except Exception as exc:
        _record(name, False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


# ─── Runner ───────────────────────────────────────────────────────────────────


async def _run_all_tests() -> None:
    await test_create_room()
    await test_publish_and_read()
    await test_wait_for_agent()
    await test_wait_timeout()
    await test_get_full_context()
    await test_human_response()


def main() -> None:
    print("\n" + "=" * 60)
    print("  PayGuard AI — Band Integration Tests")
    print("=" * 60 + "\n")

    if not os.getenv("BAND_API_KEY"):
        print("  ⚠️  WARNING: BAND_API_KEY is not set in environment / .env")
        print("       Tests will fail.  Copy .env.example → .env and add your key.\n")

    asyncio.run(_run_all_tests())

    # ── Summary ────────────────────────────────────────────────────────────
    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  |  {failed} FAILED")
        for test_name, ok, detail in _results:
            if not ok:
                print(f"    ✗  {test_name}: {detail}")
    else:
        print("  🎉  All Band integration tests passed!")
    print("=" * 60 + "\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
