from __future__ import annotations

import asyncio

from services.band_client import BandRoom, encode_payguard_payload


class FakeResponse:
    def __init__(self, body: dict, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class FakeHTTP:
    async def get(self, path: str, params: dict | None = None) -> FakeResponse:
        if path.endswith("/context"):
            return FakeResponse({
                "data": {
                    "messages": [
                        {
                            "id": "seed",
                            "content": encode_payguard_payload({
                                "type": "payment_check_request",
                                "txn_id": "txn-1",
                            }),
                            "inserted_at": "2026-06-17T15:00:00Z",
                        }
                    ]
                }
            })
        if path.endswith("/events"):
            return FakeResponse({
                "data": [
                    {
                        "id": "agent-1",
                        "event": {
                            "content": encode_payguard_payload({
                                "agent": "destination_intelligence",
                                "sequence": 1,
                                "timestamp": "2026-06-17T15:00:01Z",
                            }),
                            "inserted_at": "2026-06-17T15:00:01Z",
                        },
                    },
                    {
                        "id": "agent-4",
                        "event": {
                            "content": encode_payguard_payload({
                                "agent": "verdict_synthesis",
                                "sequence": 4,
                                "verdict": "DANGER",
                                "risk_score": 75,
                                "timestamp": "2026-06-17T15:00:04Z",
                            }),
                            "inserted_at": "2026-06-17T15:00:04Z",
                        },
                    },
                ]
            })
        if path.endswith("/messages"):
            return FakeResponse({"data": [], "metadata": {"has_more": False}})
        raise AssertionError(f"Unexpected path: {path}")


class FakeClient:
    def __init__(self) -> None:
        self._http = FakeHTTP()


def test_get_messages_merges_band_events_with_context_messages(monkeypatch) -> None:
    monkeypatch.setenv("BAND_FETCH_EVENTS", "true")
    room = BandRoom(room_id="room-1", name="txn-1", client=FakeClient())

    messages = asyncio.run(room.get_messages())

    assert any(msg.get("type") == "payment_check_request" for msg in messages)
    assert any(msg.get("agent") == "destination_intelligence" for msg in messages)
    assert any(
        msg.get("agent") == "verdict_synthesis" and msg.get("verdict") == "DANGER"
        for msg in messages
    )
