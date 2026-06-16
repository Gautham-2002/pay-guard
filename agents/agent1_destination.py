"""
Agent 1 — Destination Intelligence Agent
=========================================
Power:   Featherless AI — meta-llama/Llama-3.3-70B-Instruct
Trigger: Always runs first in the pipeline.

Responsibilities
----------------
Collects raw signals about the payment destination (URL or UPI ID) using
external intelligence APIs, then passes the evidence to the Featherless LLM
for holistic reasoning.

Critical design rule: NO hardcoded thresholds, scoring, or if/else risk logic.
The LLM receives all raw evidence and reasons holistically about what it means.

LLM reasoning focus
--------------------
- Are any signals individually minor but collectively alarming?
- Does the UPI handle pattern suggest an individual vs merchant account?
- What would a sophisticated fraudster do to appear legitimate here?
- Are there inconsistencies between what appears legitimate and the data?

Band output schema
------------------
See api/models.py :: Agent1Output
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from api.models import Agent1Output, RiskLevel
from services.band_client import BandRoom
from services.domain_intel import collect_all_signals
from services import featherless_client

logger = logging.getLogger(__name__)


# ─── Prompt Builder ───────────────────────────────────────────────────────────


def _build_prompt(
    url: str | None,
    upi_id: str | None,
    amount: float | None,
    product_description: str | None,
    source_type: str | None,
    additional_context: str | None,
    raw_evidence: dict,
) -> list[dict]:
    """
    Build the Featherless LLM prompt messages with all raw evidence embedded.
    Returns OpenAI-format message list.
    """
    if url and upi_id:
        destination = f"URL: {url}  |  UPI ID: {upi_id}"
        dest_type = "BOTH"
    elif url:
        destination = f"URL: {url}"
        dest_type = "URL"
    else:
        destination = f"UPI ID: {upi_id}"
        dest_type = "UPI_ID"

    system_prompt = (
        "You are Agent 1 in PayGuard AI, a pre-payment fraud detection system used in India. "
        "Your role is to analyse the payment destination using the raw evidence collected by automated tools "
        "and produce a structured risk assessment. "
        "You do NOT apply rule-based thresholds. You reason holistically about what the combination of signals means."
    )

    user_prompt = f"""PAYMENT DESTINATION: {destination}
TYPE: {dest_type}
AMOUNT BEING PAID: ₹{amount if amount is not None else "Not specified"}
PRODUCT/SERVICE: {product_description or "Not specified"}
SOURCE: {source_type or "Not specified"}
USER CONTEXT: {additional_context or "None provided"}

=== RAW EVIDENCE COLLECTED ===
{json.dumps(raw_evidence, indent=2, ensure_ascii=False)}

=== YOUR ANALYSIS TASK ===
Reason holistically about whether this payment destination is likely fraudulent.

Consider:
1. What does the combination of signals tell you — even if individually weak?
2. For URLs: does the domain age, SSL certificate details, and threat detection data paint a consistent picture?
3. For UPI IDs: does the VPA structure suggest a legitimate merchant or an individual/random account?
4. What would a sophisticated fraudster do to appear legitimate — and are those patterns visible here?
5. Are there signals that contradict each other (e.g., old domain but suspicious VirusTotal votes)?

India-specific context to apply:
- Legitimate UPI merchant accounts typically use PSPs like paytm, razorpay, okaxis, oksbi, okhdfcbank
- Random-looking usernames in UPI IDs (e.g., "xkvb7722@ybl") are almost always individual accounts, not merchants
- Domains registered less than 30 days ago in a payment context carry very high fraud risk
- Even 1-2 VirusTotal malicious votes on a payment URL is significant and should not be dismissed
- Self-signed SSL certificates on payment sites are a strong warning signal
- The combination of a new domain + no GSB threats can indicate an unknown phishing site not yet catalogued

Do NOT apply numeric thresholds. Reason from the evidence as a skilled fraud analyst would.

Output JSON with EXACTLY these keys (no extra keys, no markdown):
{{
  "risk_level": "LOW" or "MEDIUM" or "HIGH",
  "top_signals": ["2 to 4 specific findings as short strings, naming actual values"],
  "agent_narrative": "3-4 sentences of plain English reasoning. Be specific. Name exact values (e.g., 'domain is 3 days old', '2 VirusTotal engines flagged this URL as malicious'). India-appropriate language.",
  "confidence": 0.0 to 1.0,
  "needs_clarification": false,
  "clarification_question": null
}}"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ─── Agent Entry Point ────────────────────────────────────────────────────────


async def run(
    band_room: BandRoom,
    url: str = None,
    upi_id: str = None,
    amount: float = None,
    product_description: str = None,
    source_type: str = None,
    additional_context: str = None,
) -> Agent1Output:
    """
    Agent 1 — Destination Intelligence.

    Flow
    ----
    1. Collect raw signals via services/domain_intel.py (concurrent I/O).
    2. Build a detailed LLM prompt with all raw evidence as context.
    3. Call Featherless AI (Llama 3.3 70B) with the prompt.
    4. Parse the LLM JSON response into Agent1Output.
    5. Publish Agent1Output dict to Band room.
    6. Return Agent1Output.

    Parameters
    ----------
    band_room:           Active BandRoom to publish results into.
    url:                 Payment URL to analyse (optional if upi_id given).
    upi_id:              UPI VPA to analyse (optional if url given).
    amount:              INR amount the user is about to pay.
    product_description: What the user says they are paying for.
    source_type:         How the payment detail was received.
    additional_context:  Free-text notes from the user.

    Returns
    -------
    Agent1Output — Pydantic model published to the Band room.
    """
    logger.info(
        "Agent 1 starting | url=%s | upi_id=%s | amount=₹%s",
        url, upi_id, amount,
    )

    # ── Step 1: Collect raw signals ────────────────────────────────────────────
    logger.info("Agent 1: collecting domain intelligence signals...")
    raw_evidence = await collect_all_signals(url=url, upi_id=upi_id)
    logger.debug("Agent 1: raw evidence collected: %s", json.dumps(raw_evidence, indent=2)[:500])

    # ── Step 2: Build LLM prompt ───────────────────────────────────────────────
    messages = _build_prompt(
        url=url,
        upi_id=upi_id,
        amount=amount,
        product_description=product_description,
        source_type=source_type,
        additional_context=additional_context,
        raw_evidence=raw_evidence,
    )

    # ── Step 3: Call Featherless AI ────────────────────────────────────────────
    logger.info("Agent 1: calling Featherless AI (Llama 3.3 70B)...")
    llm_response_str = await featherless_client.chat(
        messages=messages,
        response_format={"type": "json_object"},
    )

    # ── Step 4: Parse LLM response ─────────────────────────────────────────────
    try:
        llm_data = json.loads(llm_response_str)
    except json.JSONDecodeError as exc:
        logger.error("Agent 1: could not parse LLM response as JSON: %s", exc)
        # Fallback — produce a safe degraded output
        llm_data = {
            "risk_level": "MEDIUM",
            "top_signals": ["LLM response parse failure — manual review required"],
            "agent_narrative": "The AI analysis encountered a technical issue and could not produce a structured result. Treat this as a medium risk until manually reviewed.",
            "confidence": 0.3,
            "needs_clarification": False,
            "clarification_question": None,
        }

    # Determine destination type
    if url and upi_id:
        dest_type = "BOTH"
    elif url:
        dest_type = "URL"
    else:
        dest_type = "UPI_ID"

    # Extract UPI PSP from raw evidence if available
    upi_psp = None
    if upi_id and "upi_analysis" in raw_evidence:
        upi_psp = raw_evidence["upi_analysis"].get("psp")

    # Normalise risk_level — default to MEDIUM if LLM returns unexpected value
    raw_risk = str(llm_data.get("risk_level", "MEDIUM")).upper().strip()
    risk_level = RiskLevel(raw_risk) if raw_risk in ("LOW", "MEDIUM", "HIGH") else RiskLevel.MEDIUM

    output = Agent1Output(
        destination_type=dest_type,
        upi_id=upi_id,
        upi_psp=upi_psp,
        risk_level=risk_level,
        top_signals=llm_data.get("top_signals", []),
        agent_narrative=llm_data.get("agent_narrative", ""),
        raw_evidence=raw_evidence,
        needs_clarification=llm_data.get("needs_clarification", False),
        clarification_question=llm_data.get("clarification_question"),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(
        "Agent 1 complete | risk=%s | confidence=%.2f | signals=%s",
        output.risk_level,
        llm_data.get("confidence", 0.0),
        output.top_signals,
    )

    # ── Step 5: Publish to Band room ───────────────────────────────────────────
    # Exclude raw_evidence from the Band payload — it can be very large (multi-KB
    # of WHOIS/VT data) and downstream agents only need the summarised signals.
    # The full evidence stays in the returned Agent1Output for the local orchestrator.
    payload = output.model_dump(exclude={"raw_evidence"})
    payload["confidence"] = llm_data.get("confidence", 0.0)
    await band_room.publish(payload)
    logger.info("Agent 1: published result to Band room '%s'", band_room.name)

    return output
