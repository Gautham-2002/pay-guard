# Phase 1 — Band Integration Layer

## Context
You are building **PayGuard AI**. Phase 0 is complete — the project structure exists at `/home/gautham/Documents/personal-projects/band-hackathon/payguard/` and all dependencies are installed.

The full PRD is at: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

**Band** is the coordination backbone of this entire system. Every agent communicates exclusively through Band rooms. No agent calls another agent directly — they only read from and write to the Band room. This is the architectural rule.

This phase builds the complete Band client wrapper that all 4 agents and the backend will use.

---

## What Band Does in PayGuard AI

1. When a user submits a payment check, the backend creates a **Band room** named `txn-{uuid}`.
2. Each agent joins this room, reads prior messages, and publishes its own structured JSON output.
3. The Band room persists as a **tamper-evident audit log** for the transaction.
4. **HITL (Human-in-the-Loop)**: when an agent needs user clarification, it publishes a `needs_clarification` message to Band. The frontend detects this and shows a question card. The user's answer is posted back to Band as a `human_response` message.

---

## Task: Build services/band_client.py

Read the Band SDK docs at `docs.band.ai` before implementing. The client must be a thin, reliable wrapper. Build it in `services/band_client.py`.

### Required interface:

```python
class BandClient:
    def __init__(self, api_key: str): ...
    
    async def create_room(self, name: str) -> BandRoom: ...
    # Creates a new Band room. Returns a BandRoom object.
    # Room name format: "txn-{txn_id}"
    
    async def get_room(self, room_id: str) -> BandRoom: ...
    # Retrieves an existing Band room by ID.

class BandRoom:
    def __init__(self, room_id: str, name: str, client: BandClient): ...
    
    @property
    def id(self) -> str: ...
    
    async def publish(self, message: dict) -> None: ...
    # Publishes a JSON-serializable dict to the room.
    # Adds "published_at" timestamp automatically if not present.
    
    async def get_messages(self) -> list[dict]: ...
    # Returns all messages in the room in chronological order.
    
    async def get_messages_by_agent(self, agent_name: str) -> list[dict]: ...
    # Filters messages by the "agent" field.
    
    async def wait_for_agent(self, agent_name: str, timeout_seconds: int = 30) -> dict | None: ...
    # Polls every 500ms until a message from agent_name appears, or timeout.
    # Returns the message dict or None on timeout.
    
    async def wait_for_agents(self, agent_names: list[str], timeout_seconds: int = 60) -> dict[str, dict | None]: ...
    # Waits for all listed agents to publish. Returns dict: {agent_name: message_or_none}
    
    async def wait_for_human_response(self, timeout_seconds: int = 300) -> dict | None: ...
    # Polls until a message with type="human_response" appears, or timeout (5 min default).
    
    async def get_full_context(self) -> str: ...
    # Returns all room messages as a formatted string suitable for LLM context injection.
    # Format: "=== Band Room: {name} ===\n[Agent: {agent}]\n{json_content}\n..."
```

### Implementation notes:
- Use `httpx.AsyncClient` for all Band API calls
- All methods must be `async`
- Wrap every Band API call in try/except — if Band is down, log the error and raise `BandConnectionError`
- The `wait_for_agent` and `wait_for_agents` methods poll using `asyncio.sleep(0.5)` between checks
- `get_full_context()` is critical — it produces the string injected into each LLM prompt so agents can "read" the room

### Create a custom exception:
```python
class BandConnectionError(Exception):
    pass

class BandTimeoutError(Exception):
    pass
```

---

## Task: Write tests/test_band.py

Test the Band client with real API calls:

1. `test_create_room()` — create a room named `"test-payguard-{timestamp}"`. Assert `room.id` is a non-empty string.

2. `test_publish_and_read()` — publish a test message `{"agent": "test", "data": "hello"}` to a room. Call `get_messages()`. Assert the message is present in the result.

3. `test_wait_for_agent()` — publish a message with `agent="domain_intel"` to a room. Call `wait_for_agent("domain_intel", timeout_seconds=5)`. Assert it returns the message.

4. `test_wait_timeout()` — call `wait_for_agent("nonexistent_agent", timeout_seconds=3)` on an empty room. Assert it returns `None` within ~3 seconds.

5. `test_get_full_context()` — publish 2 messages from different agents. Call `get_full_context()`. Assert the output is a string containing both agent names and their content.

6. `test_human_response()` — publish a `{"type": "human_response", "human_answer": "Yes"}` message. Call `wait_for_human_response(timeout_seconds=3)`. Assert it returns the message.

---

## Band Message Schema (Enforce This)

Every message published to Band must conform to one of these shapes. Enforce this in `publish()` using a Pydantic validator or simple dict check — log a warning if `agent` or `sequence` is missing.

```
Agent messages must have: agent (str), sequence (int), timestamp (str)
HITL messages must have: type="needs_clarification" OR type="human_response"
```

---

## Completion Criteria

- [ ] `services/band_client.py` is complete with all methods implemented
- [ ] `python tests/test_band.py` passes all 6 tests with real Band API
- [ ] `get_full_context()` output is readable as LLM context (test this manually)
- [ ] Custom exceptions `BandConnectionError` and `BandTimeoutError` are defined and raised correctly
- [ ] No hardcoded API keys — all read from `os.getenv("BAND_API_KEY")`
