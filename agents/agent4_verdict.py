"""
Agent 4 — Verdict Synthesis & Recommendation Agent
====================================================
Power:   AIML API — claude-3-5-sonnet
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

Implemented in: Phase 5
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from api.models import Agent4Output, VerdictLevel
from services.band_client import BandRoom
from services import aiml_client

logger = logging.getLogger(__name__)

# ─── Model Selection ──────────────────────────────────────────────────────────

# Prefer the configured verdict model, but keep a working fallback because
# AIML model aliases can change and return 404 at runtime.
_VERDICT_MODEL = aiml_client.AIML_MODEL_VERDICT
_FALLBACK_VERDICT_MODEL = aiml_client.REASONING_MODEL


# ─── Prompt Builder ───────────────────────────────────────────────────────────


def _build_verdict_prompt(
    band_context: str,
    url: Optional[str],
    upi_id: Optional[str],
    amount: Optional[float],
    product_description: Optional[str],
    source_type: Optional[str],
    additional_context: Optional[str],
) -> list[dict]:
    """
    Build the Agent 4 verdict synthesis prompt.

    This is the most critical prompt in the system. It instructs the LLM to
    read all three agent narratives holistically and produce a final verdict
    without applying any hardcoded rules or numeric thresholds.

    Returns OpenAI-format message list (system + user).
    """
    if url and upi_id:
        destination = f"URL: {url}  |  UPI ID: {upi_id}"
    elif url:
        destination = f"URL: {url}"
    elif upi_id:
        destination = f"UPI ID: {upi_id}"
    else:
        destination = "QR code decoded by Agent 2"

    system_prompt = (
        "You are Agent 4 — the final decision-maker in PayGuard AI, a pre-payment fraud "
        "detection system for Indian users. Three specialist agents have analyzed a payment "
        "and published their findings to a shared Band room. You must read all findings "
        "holistically and synthesize a final verdict. "
        "You do NOT apply weighted averages or rule-based scoring. "
        "You MUST output ONLY valid JSON — no markdown, no prose, no code fences."
    )

    user_prompt = f"""=== COMPLETE BAND ROOM — ALL AGENT FINDINGS ===
{band_context}

=== PAYMENT DETAILS ===
Payment destination: {destination}
Amount: ₹{amount if amount is not None else "Not specified"}
What user is paying for: {product_description or "Not specified"}
How they received this: {source_type or "Not specified"}
User's context: "{additional_context or "None provided"}"

=== YOUR SYNTHESIS TASK ===

1. AGREEMENT ASSESSMENT: Do all three agents agree, partially agree, or conflict?
   - If agents conflict: explain which agent's findings are more reliable and why.
   - Example conflict: Agent 1 says LOW (domain is old), Agent 2 says HIGH (refund scam framing)
     → Agent 2's social context is more relevant for this type of fraud.

2. INTERACTION EFFECTS: How do findings from different agents reinforce each other?
   - Example: Agent 1 MEDIUM (new domain) + Agent 2 HIGH (refund scam) + Agent 3 HIGH
     (Reddit complaints) = the convergence makes this clearly DANGER, not just MEDIUM.

3. FINAL VERDICT: SAFE | VERIFY | DANGER
   Guidance (do NOT apply these as rules — use judgment):
   - SAFE: User can likely proceed. All or most signals point to legitimacy.
   - VERIFY: Something is off but not conclusively fraudulent. User should double-check before paying.
   - DANGER: Strong fraud indicators. User should not proceed without fully understanding the risk.

4. RISK SCORE: 0–100
   This is a reasoned estimate, NOT a weighted average of agent scores.
   Consider: how confident are you? How serious are the detected patterns?

5. PLAIN ENGLISH SUMMARY: 2-3 sentences for a non-technical Indian user.
   Rules:
   - Use simple language (8th grade reading level)
   - Name the specific fraud type if identified (e.g., "This is a refund scam")
   - Be direct — do not hedge with "might be" if you're confident
   - Include the most important single thing the user should know
   - India-appropriate: mention UPI-specific facts where relevant
     (e.g., "You can only send money by scanning a QR — never receive it")

6. RECOMMENDED ACTIONS: 2-4 specific actions (not generic)
   Examples of GOOD (specific):
   - "Call Flipkart's official customer care at 1800-XXX-XXXX to verify this refund"
   - "Report this WhatsApp number to cybercrime.gov.in and call 1930"
   - "Ask the OLX buyer to do a video call to show the product before you pay"
   Examples of BAD (generic — do not do this):
   - "Be careful"
   - "Verify the merchant"

7. ASK THE MERCHANT (only for VERIFY verdicts):
   2-3 specific verification questions the user can ask to confirm legitimacy.
   Examples: "Share your GST registration number", "Send an email from your company domain"
   For DANGER: leave this empty — don't suggest verifying an obvious scam.
   For SAFE: leave this empty.

8. AVOIDED FRAUD ESTIMATE (only for DANGER):
   State the amount the user would have lost: "₹X,XXX"
   For SAFE or VERIFY: set to null.

Return JSON with EXACTLY these keys (no extra keys, no markdown, no code fences):
{{
  "verdict": "SAFE" or "VERIFY" or "DANGER",
  "risk_score": integer 0-100,
  "plain_english_summary": "string",
  "recommended_actions": ["string", "string"],
  "ask_merchant": ["string"] or [],
  "agent_agreement": "ALL_AGREE" or "PARTIAL_CONFLICT" or "FULL_CONFLICT",
  "conflict_resolution": "string explaining how conflict was resolved" or null,
  "avoided_fraud_estimate": "₹X,XXX" or null
}}"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ─── JSON extraction helper ───────────────────────────────────────────────────


def _extract_json(raw: str) -> dict:
    """
    Extract a JSON object from a raw LLM response string.
    Handles markdown code fences and leading/trailing prose.
    """
    # Try direct parse first
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    stripped = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
    stripped = stripped.rstrip("`").strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to find a JSON object via brace matching
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start: i + 1])
                    except (json.JSONDecodeError, TypeError):
                        break

    raise ValueError(f"Could not extract JSON from LLM response: {raw[:400]}")


# ─── Response Validator ───────────────────────────────────────────────────────


def _validate_and_normalise(data: dict, amount: Optional[float]) -> dict:
    """
    Validate the LLM JSON response and normalise fields that are out of range
    or missing.  Returns the normalised dict (mutates in place and returns).

    Rules
    -----
    - verdict: must be SAFE | VERIFY | DANGER — default to VERIFY
    - risk_score: integer 0–100 — clamp if out of range, default to 50
    - recommended_actions: must be non-empty list — add generic fallback
    - ask_merchant: list — clear if verdict != VERIFY
    - avoided_fraud_estimate: set from amount if verdict == DANGER and null
    - agent_agreement: must be ALL_AGREE | PARTIAL_CONFLICT | FULL_CONFLICT
    """
    # Normalise verdict
    raw_verdict = str(data.get("verdict", "VERIFY")).upper().strip()
    if raw_verdict not in ("SAFE", "VERIFY", "DANGER"):
        logger.warning("Agent 4: unexpected verdict '%s' — defaulting to VERIFY", raw_verdict)
        raw_verdict = "VERIFY"
    data["verdict"] = raw_verdict

    # Normalise risk_score
    try:
        score = int(data.get("risk_score", 50))
        data["risk_score"] = max(0, min(100, score))
    except (TypeError, ValueError):
        logger.warning("Agent 4: non-integer risk_score — defaulting to 50")
        data["risk_score"] = 50

    # Ensure verdict↔score consistency (warn but do not override LLM decision)
    score = data["risk_score"]
    verdict = data["verdict"]
    if verdict == "SAFE" and score > 30:
        logger.warning(
            "Agent 4: verdict=SAFE but risk_score=%d > 30 — LLM inconsistency (not overriding)",
            score,
        )
    elif verdict == "VERIFY" and (score < 31 or score > 65):
        logger.warning(
            "Agent 4: verdict=VERIFY but risk_score=%d outside 31–65 — LLM inconsistency (not overriding)",
            score,
        )
    elif verdict == "DANGER" and score < 66:
        logger.warning(
            "Agent 4: verdict=DANGER but risk_score=%d < 66 — LLM inconsistency (not overriding)",
            score,
        )

    # Ensure required string fields
    if not data.get("plain_english_summary"):
        data["plain_english_summary"] = (
            "This payment destination has been analyzed. "
            "Please review the agent findings carefully before proceeding."
        )

    # Normalise recommended_actions
    actions = data.get("recommended_actions")
    if not isinstance(actions, list) or not actions:
        data["recommended_actions"] = [
            "Do not make this payment until you have independently verified the recipient.",
            "Contact the company's official customer support using numbers from their official website.",
        ]

    # Enforce ask_merchant rules
    if verdict != "VERIFY":
        data["ask_merchant"] = []
    elif not isinstance(data.get("ask_merchant"), list):
        data["ask_merchant"] = []

    # Enforce avoided_fraud_estimate rules
    if verdict == "DANGER":
        if not data.get("avoided_fraud_estimate") and amount is not None:
            data["avoided_fraud_estimate"] = f"₹{amount:,.0f}"
    else:
        data["avoided_fraud_estimate"] = None

    # Normalise agent_agreement
    raw_agreement = str(data.get("agent_agreement", "PARTIAL_CONFLICT")).upper().strip()
    if raw_agreement not in ("ALL_AGREE", "PARTIAL_CONFLICT", "FULL_CONFLICT"):
        logger.warning(
            "Agent 4: unexpected agent_agreement '%s' — defaulting to PARTIAL_CONFLICT",
            raw_agreement,
        )
        raw_agreement = "PARTIAL_CONFLICT"
    data["agent_agreement"] = raw_agreement

    return data


# ─── Agent Entry Point ────────────────────────────────────────────────────────


async def run(
    band_room: BandRoom,
    url: Optional[str] = None,
    upi_id: Optional[str] = None,
    amount: Optional[float] = None,
    product_description: Optional[str] = None,
    source_type: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> Agent4Output:
    """
    Agent 4 — Verdict Synthesis.

    Flow
    ----
    1. Read the full Band room context (all agents + any human responses).
    2. Verify that any pending HITL request has been answered — log a warning
       if not (the orchestrator is responsible for the actual pause; Agent 4
       proceeds with whatever is in the room).
    3. Build the verdict synthesis prompt and call AIML API.
    4. Parse, validate, and normalise the LLM JSON response.
    5. Publish Agent4Output to Band room.
    6. Return Agent4Output.

    Parameters
    ----------
    band_room:           Active BandRoom containing all prior agent outputs
                         plus any human_response messages.
    url:                 Payment URL (may be None if UPI-only).
    upi_id:              UPI VPA (may be None if URL-only).
    amount:              INR amount the user is about to pay.
    product_description: What the user says they are paying for.
    source_type:         How the payment destination was received.
    additional_context:  Free-text notes from the user.

    Returns
    -------
    Agent4Output — Pydantic model published to the Band room as the final verdict.
    """
    logger.info(
        "Agent 4 starting | url=%s | upi_id=%s | amount=₹%s",
        url, upi_id, amount,
    )

    # ── Step 1: Read full Band room context ────────────────────────────────────
    logger.info("Agent 4: reading full Band room context...")
    band_context = await band_room.get_full_context()

    # ── Step 2: Check for unresolved HITL ─────────────────────────────────────
    all_messages = await band_room.get_messages()
    has_clarification_request = any(
        m.get("type") == "needs_clarification" for m in all_messages
    )
    has_human_response = any(
        m.get("type") == "human_response" for m in all_messages
    )
    if has_clarification_request and not has_human_response:
        logger.warning(
            "Agent 4: Band room has an unresolved HITL question. "
            "The orchestrator should have waited for human response. "
            "Proceeding with available context."
        )

    logger.info(
        "Agent 4: band room has %d messages | hitl_pending=%s | hitl_resolved=%s",
        len(all_messages),
        has_clarification_request,
        has_human_response,
    )

    # ── Step 3: Build and call AIML API ───────────────────────────────────────
    messages = _build_verdict_prompt(
        band_context=band_context,
        url=url,
        upi_id=upi_id,
        amount=amount,
        product_description=product_description,
        source_type=source_type,
        additional_context=additional_context,
    )

    try:
        verdict_models = [_VERDICT_MODEL]
        if _FALLBACK_VERDICT_MODEL not in verdict_models:
            verdict_models.append(_FALLBACK_VERDICT_MODEL)

        raw_response: str | None = None
        last_exc: Exception | None = None
        for model in verdict_models:
            try:
                logger.info("Agent 4: calling AIML API (%s) for verdict synthesis...", model)
                raw_response = await aiml_client.chat_text(
                    messages=messages,
                    response_format={"type": "json_object"},
                    model=model,
                    temperature=0.15,
                    max_tokens=3000,
                )
                if model != _VERDICT_MODEL:
                    logger.info("Agent 4: fallback verdict model succeeded (%s)", model)
                break
            except Exception as model_exc:
                last_exc = model_exc
                logger.warning("Agent 4: AIML model %s failed: %s", model, model_exc)

        if raw_response is None:
            raise RuntimeError("All verdict models failed") from last_exc

        llm_data = _extract_json(raw_response)
    except Exception as exc:
        logger.error("Agent 4: AIML API call failed: %s", exc)
        # Degraded fallback — conservative DANGER to protect user
        llm_data = {
            "verdict": "DANGER",
            "risk_score": 75,
            "plain_english_summary": (
                "PayGuard AI encountered a technical issue during final analysis. "
                "As a precaution, do not proceed with this payment until you have "
                "manually verified the recipient through official channels."
            ),
            "recommended_actions": [
                "Do not make this payment until you have independently verified the recipient.",
                "Contact the company's official customer support using numbers from their website.",
                "If in doubt, call the National Cyber Crime Helpline at 1930.",
            ],
            "ask_merchant": [],
            "agent_agreement": "PARTIAL_CONFLICT",
            "conflict_resolution": "Verdict synthesis failed due to a technical error; conservative DANGER issued.",
            "avoided_fraud_estimate": f"₹{amount:,.0f}" if amount else None,
        }
        logger.warning("Agent 4: using conservative fallback verdict due to API failure")

    # ── Step 4: Validate and normalise ────────────────────────────────────────
    llm_data = _validate_and_normalise(llm_data, amount)

    logger.info(
        "Agent 4: verdict=%s | risk_score=%d | agreement=%s",
        llm_data["verdict"],
        llm_data["risk_score"],
        llm_data["agent_agreement"],
    )

    # ── Step 5: Build Agent4Output ─────────────────────────────────────────────
    output = Agent4Output(
        verdict=VerdictLevel(llm_data["verdict"]),
        risk_score=llm_data["risk_score"],
        plain_english_summary=llm_data["plain_english_summary"],
        recommended_actions=llm_data["recommended_actions"],
        ask_merchant=llm_data.get("ask_merchant", []),
        agent_agreement=llm_data["agent_agreement"],
        conflict_resolution=llm_data.get("conflict_resolution"),
        avoided_fraud_estimate=llm_data.get("avoided_fraud_estimate"),
        band_room_id=band_room.id,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # ── Step 6: Publish to Band room ───────────────────────────────────────────
    payload = output.model_dump()
    await band_room.publish(payload)
    logger.info(
        "Agent 4: published verdict to Band room '%s' | verdict=%s | risk_score=%d",
        band_room.name, output.verdict, output.risk_score,
    )

    return output
