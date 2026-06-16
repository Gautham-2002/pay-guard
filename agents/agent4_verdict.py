"""
Agent 4 — Verdict Synthesis & Recommendation Agent
====================================================
Power:   AIML API — gpt-4o or claude-3-5-sonnet
Trigger: After Agent 3 publishes (and after any HITL human responses are in Band).
Reads:   Full Band room — all 3 agent outputs + any human_response messages.

Responsibilities
----------------
The LLM reads ALL three agent narratives holistically. It does NOT apply
weighted averages or rule-based scoring. Reasoning process:

1. Identify agreements, conflicts, and interaction effects across agents.
   Example: "Agent 1: MEDIUM. Agent 2: HIGH (refund scam). Agent 3: HIGH
   (Reddit complaints). Three independent agents converge → DANGER."

2. Generate a plain-English summary in India-context language — no jargon,
   name the specific fraud type, explain WHY it is suspicious.

3. Generate specific, contextual recommended actions — not generic advice.

4. Generate "Ask the merchant" checklist if verdict is VERIFY.

5. Estimate "avoided fraud amount" if verdict is DANGER.

Verdict levels
--------------
  SAFE   (risk_score 0–30)  : Proceed normally.
  VERIFY (risk_score 31–65) : User must choose "Verify First" or "Proceed Anyway".
  DANGER (risk_score 66–100): User must type "I UNDERSTAND THE RISK" to override.

Agent agreement values
----------------------
  ALL_AGREE | PARTIAL_CONFLICT | FULL_CONFLICT

Band output schema
------------------
See api/models.py :: Agent4Output

Implemented in: Phase 4
"""

from __future__ import annotations

# TODO (Phase 4): Implement run() — read full Band room history (all agents +
#                 HITL responses), call AIML API for holistic verdict synthesis,
#                 publish Agent4Output to Band room.


async def run(
    txn_id: str,
    band_room_id: str,
    agent1_output: dict,
    agent2_output: dict,
    agent3_output: dict,
    hitl_responses: list[dict],
) -> dict:
    """
    Entry point for Agent 4.

    Parameters
    ----------
    txn_id:          Unique transaction ID for this check session.
    band_room_id:    Band room identifier to publish the final verdict into.
    agent1_output:   Full Agent1Output dict read from the Band room.
    agent2_output:   Full Agent2Output dict read from the Band room.
    agent3_output:   Full Agent3Output dict read from the Band room.
    hitl_responses:  List of HITLMessage dicts posted by the human participant
                     (empty list if no HITL was triggered).

    Returns
    -------
    Agent4Output-compatible dict published to the Band room as the final verdict.
    """
    raise NotImplementedError("Agent 4 is implemented in Phase 4")
