"""
Agent 2 — QR Decode & UPI Context Validator
=============================================
Power:   AIML API — gpt-4o (vision + reasoning)
Trigger: Runs after Agent 1 publishes its destination intelligence to Band.

Responsibilities
----------------
1. QR Code Decode & Visual Analysis
   - Attempts a fast local QR decode via pyzbar (services/qr_handler.py).
   - Regardless of local decode result, sends the image to the AIML API
     gpt-4o vision model for visual context analysis (tampering, branding,
     refund/receive framing, etc.).
2. UPI–Purchase Context Validation
   - Reads Agent 1's output from the Band room via get_full_context().
   - Calls the AIML API reasoning model with a rich prompt containing:
     the Band room context, the user's payment context, and QR analysis
     results (if a QR was provided).
   - Detects social engineering patterns (OLX scam, refund scam, etc.),
     UPI coherence mismatches, and refund framing — without hardcoded rules.

HITL
----
If the reasoning model determines that critical information is missing, Agent 2
publishes a `needs_clarification` message to the Band room and returns a
partial Agent2Output with needs_clarification=True.  The backend orchestrator
is responsible for waiting for the human response before running Agent 3.

Critical design rule: NO hardcoded scoring or pattern detection logic.
The LLM receives all raw evidence and reasons holistically.

Band output schema
------------------
See api/models.py :: Agent2Output
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from api.models import Agent2Output, RiskLevel
from services.band_client import BandRoom
from services import aiml_client
from services import qr_handler

logger = logging.getLogger(__name__)


# ─── Prompt Builders ──────────────────────────────────────────────────────────


def _build_vision_prompt(
    agent1_narrative: str,
    agent1_risk: str,
    local_decode: dict | None,
) -> str:
    """
    Build the vision model prompt for QR image analysis.
    """
    if local_decode and local_decode.get("decoded_type") == "UPI_PAYMENT":
        params = local_decode.get("upi_params") or {}
        qr_block = (
            f"QR DECODED CONTENT: pa={params.get('pa')}, "
            f"pn={params.get('pn')}, "
            f"am={params.get('am')}"
        )
    else:
        qr_block = (
            "The QR could not be decoded locally. "
            "Please attempt to decode it from the image."
        )

    return f"""You are analyzing a QR code image for payment fraud indicators.

CONTEXT FROM PREVIOUS AGENT:
{agent1_narrative}
Agent 1 risk level: {agent1_risk}

{qr_block}

YOUR TASKS:
1. If QR is not decoded yet: read the QR code and identify pa (UPI ID), pn (payee name), am (amount) if visible.
2. Describe the visual context: where does this QR appear? (WhatsApp screenshot, official PDF, physical sticker, etc.)
3. Is there any merchant branding or logo visible near the QR? If yes, does it match the UPI destination?
4. Are there signs of tampering (QR overlaid on something, sticker on sticker)?
5. Is there any text suggesting "scan to RECEIVE money" or "refund" or "cashback"? This is ALWAYS a scam — you can ONLY send money by scanning a QR, never receive it.

Return JSON (no markdown, no code fences):
{{
  "decoded_pa": "UPI ID or null",
  "decoded_pn": "payee name or null",
  "decoded_am": "amount or null",
  "visual_context": "description of image context",
  "branding_visible": true or false,
  "branding_name": "brand name or null",
  "branding_matches_destination": true or false or null,
  "tampering_detected": true or false,
  "refund_receive_framing": true or false,
  "visual_summary": "2-sentence plain English observation"
}}"""


def _build_context_validation_prompt(
    band_context: str,
    upi_id: str | None,
    url: str | None,
    amount: float | None,
    product_description: str | None,
    source_type: str | None,
    additional_context: str | None,
    qr_analysis: dict | None,
    local_decode: dict | None,
) -> list[dict]:
    """
    Build the AIML API reasoning prompt for UPI context validation.
    Returns OpenAI-format message list.
    """
    destination = upi_id or url or "Not provided"

    # Build QR section
    qr_section = ""
    if qr_analysis or local_decode:
        pa = None
        pn = None
        am = None
        visual_context_str = "Not analyzed"
        refund_framing = False

        # Prefer local decode for factual fields
        if local_decode and local_decode.get("upi_params"):
            params = local_decode["upi_params"]
            pa = pa or params.get("pa")
            pn = pn or params.get("pn")
            am = am or params.get("am")

        if qr_analysis:
            pa = pa or qr_analysis.get("decoded_pa")
            pn = pn or qr_analysis.get("decoded_pn")
            am = am or qr_analysis.get("decoded_am")
            visual_context_str = qr_analysis.get("visual_context", "Not analyzed")
            refund_framing = qr_analysis.get("refund_receive_framing", False)

        qr_section = f"""
=== QR CODE ANALYSIS ===
Decoded UPI ID (pa): {pa or "could not determine"}
Payee name in QR (pn): {pn or "not found"}
Pre-filled amount: {am or "not specified"}
Visual context: {visual_context_str}
Refund/receive framing detected: {refund_framing}
Branding visible: {qr_analysis.get("branding_visible") if qr_analysis else "N/A"}
Branding matches destination: {qr_analysis.get("branding_matches_destination") if qr_analysis else "N/A"}
Tampering detected: {qr_analysis.get("tampering_detected") if qr_analysis else "N/A"}
Visual summary: {qr_analysis.get("visual_summary") if qr_analysis else "N/A"}
"""

    user_content = f"""You are Agent 2 in PayGuard AI, analyzing the human context around a payment.

=== BAND ROOM CONTEXT (Agent 1's findings) ===
{band_context}

=== USER'S PAYMENT CONTEXT ===
Payment destination: {destination}
Amount: \u20b9{amount if amount is not None else "Not specified"}
What they're paying for: {product_description or "Not specified"}
How they received this payment detail: {source_type or "Not specified"}
Additional context from user: "{additional_context or "None"}"
{qr_section}
=== YOUR ANALYSIS TASKS ===

1. UPI COHERENCE CHECK:
   - Does the UPI ID structure (username + PSP) make sense for the stated purchase?
   - Individual accounts (random usernames) vs merchant accounts (brand-like usernames)
   - PSP match: does the PSP suit the claimed merchant type?

2. PAYEE NAME vs UPI ID CHECK (if QR decoded):
   - The payee name (pn) is user-controlled text — anyone can write anything
   - Does it match the actual UPI ID (pa)?
   - "Amazon Refund Desk" as pn but "someone123@ybl" as pa = clear mismatch

3. SOCIAL ENGINEERING PATTERN:
   - Classify the pattern: refund_scam | olx_buyer_scam | fake_customer_support |
     fake_job_offer | romance_scam | lottery_scam | vendor_invoice_fraud | none | unknown
   - What manipulation tactics are present? (urgency, authority impersonation,
     refund/cashback framing, fear/threat, too-good-to-be-true)

4. CROSS-REFERENCE WITH AGENT 1:
   - Do Agent 1's findings and this social context tell a consistent fraud story?
   - Or does one contradict the other? How do you reconcile it?

5. HITL DECISION:
   - Is critical information missing that only the user can provide?
   - If yes: what single specific question would help most?

India-specific knowledge:
- No one needs to scan a QR code to RECEIVE money. Ever. QR scanning = SENDING money.
- OLX buyers sending UPI to sellers is a common scam vector
- "Refund" or "cashback" QR codes are always scams
- High amounts on first contact with unknown parties = high risk

Output JSON (no markdown, no code fences):
{{
  "upi_context_mismatch": true or false,
  "refund_scam_indicator": true or false,
  "social_engineering_pattern": "pattern string or none",
  "manipulation_signals": ["list", "of", "detected", "tactics"],
  "agent1_cross_reference": "1-2 sentences on how Agent 1 findings align or conflict",
  "source_risk_level": "LOW" or "MEDIUM" or "HIGH",
  "agent_narrative": "3-4 sentences. Be specific. Name the exact pattern. India-context language.",
  "needs_clarification": true or false,
  "clarification_question": "specific question or null"
}}"""

    system_prompt = (
        "You are Agent 2 in PayGuard AI, an Indian pre-payment fraud detection system. "
        "Your role is to assess the social engineering and UPI context signals around a payment. "
        "You do NOT apply rule-based thresholds. You reason holistically as a skilled fraud analyst. "
        "You MUST output ONLY valid JSON — no markdown, no prose, no code fences."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
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

    # Strip markdown code fences
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

    raise ValueError(f"Could not extract JSON from LLM response: {raw[:300]}")


# ─── Agent Entry Point ────────────────────────────────────────────────────────


async def run(
    band_room: BandRoom,
    qr_image_bytes: bytes = None,   # None if user didn't upload QR
    upi_id: str = None,             # directly provided UPI ID (if no QR)
    url: str = None,
    amount: float = None,
    product_description: str = None,
    source_type: str = None,
    additional_context: str = None,
) -> Agent2Output:
    """
    Agent 2 — QR Decode & UPI Context Validator.

    Flow
    ----
    1. Read Agent 1 output from Band room (wait up to 30s).
    2. If QR image provided:
       a. Attempt local decode via qr_handler.decode_qr_from_image().
       b. Send image to AIML API vision model for visual context analysis.
       c. Merge local decode + vision findings.
    3. Run UPI context validation (AIML reasoning) using band context + QR results.
    4. Determine if HITL is needed.
    5. If HITL: publish needs_clarification message to Band room.
    6. Publish full Agent2Output to Band room.
    7. Return Agent2Output.

    Parameters
    ----------
    band_room:           Active BandRoom — must already contain Agent 1's output.
    qr_image_bytes:      Raw image bytes of the QR code (optional).
    upi_id:              UPI VPA provided directly by the user (optional).
    url:                 Payment URL (optional).
    amount:              INR amount about to be paid.
    product_description: What the user is paying for.
    source_type:         How the user received the payment detail.
    additional_context:  Free-text notes from the user.

    Returns
    -------
    Agent2Output — Pydantic model published to the Band room.
    """
    logger.info(
        "Agent 2 starting | has_qr=%s | upi_id=%s | url=%s | amount=\u20b9%s",
        qr_image_bytes is not None, upi_id, url, amount,
    )

    # ── Step 1: Get Agent 1 context from Band room ─────────────────────────────
    logger.info("Agent 2: reading Agent 1 output from Band room...")
    agent1_msgs = await band_room.get_messages_by_agent("destination_intelligence")
    agent1_data = agent1_msgs[-1] if agent1_msgs else {}
    agent1_narrative = agent1_data.get("agent_narrative", "No Agent 1 output found.")
    agent1_risk = agent1_data.get("risk_level", "UNKNOWN")
    logger.info("Agent 2: Agent 1 risk_level=%s", agent1_risk)

    # ── Step 2: QR Analysis (if image provided) ────────────────────────────────
    local_decode: dict | None = None
    vision_analysis: dict | None = None
    qr_resolved_upi_id: str | None = None

    if qr_image_bytes:
        # Sub-task A: Local decode
        logger.info("Agent 2: attempting local QR decode via pyzbar...")
        local_decode = await qr_handler.decode_qr_from_image(qr_image_bytes)
        if local_decode:
            logger.info(
                "Agent 2: local decode success — type=%s raw='%s...'",
                local_decode.get("decoded_type"),
                local_decode.get("raw_data", "")[:60],
            )
            if local_decode.get("upi_params") and local_decode["upi_params"].get("pa"):
                qr_resolved_upi_id = local_decode["upi_params"]["pa"]
        else:
            logger.info("Agent 2: local decode found nothing — vision model will attempt decode")

        # Sub-task A: Vision analysis (always run, regardless of local decode)
        logger.info("Agent 2: sending image to AIML API vision model for visual analysis...")
        vision_prompt = _build_vision_prompt(
            agent1_narrative=agent1_narrative,
            agent1_risk=agent1_risk,
            local_decode=local_decode,
        )
        try:
            vision_raw = await aiml_client.chat_vision(qr_image_bytes, vision_prompt)
            vision_analysis = _extract_json(vision_raw)
            logger.info(
                "Agent 2: vision analysis complete — refund_framing=%s tampering=%s",
                vision_analysis.get("refund_receive_framing"),
                vision_analysis.get("tampering_detected"),
            )
            # If local decode failed but vision decoded a UPI ID, use it
            if not qr_resolved_upi_id and vision_analysis.get("decoded_pa"):
                qr_resolved_upi_id = vision_analysis["decoded_pa"]
        except Exception as exc:
            logger.error("Agent 2: vision analysis failed: %s", exc)
            vision_analysis = None

    # Resolve effective UPI ID
    effective_upi_id = qr_resolved_upi_id or upi_id

    # ── Step 3: UPI Context Validation ────────────────────────────────────────
    logger.info("Agent 2: running UPI context validation via AIML API reasoning...")
    band_context = await band_room.get_full_context()

    context_messages = _build_context_validation_prompt(
        band_context=band_context,
        upi_id=effective_upi_id,
        url=url,
        amount=amount,
        product_description=product_description,
        source_type=source_type,
        additional_context=additional_context,
        qr_analysis=vision_analysis,
        local_decode=local_decode,
    )

    try:
        context_raw = await aiml_client.chat_text(
            messages=context_messages,
            response_format={"type": "json_object"},
            temperature=0.15,
            max_tokens=2048,
        )
        context_data = _extract_json(context_raw)
    except Exception as exc:
        logger.error("Agent 2: context validation LLM call failed: %s", exc)
        # Safe degraded output
        context_data = {
            "upi_context_mismatch": False,
            "refund_scam_indicator": False,
            "social_engineering_pattern": "unknown",
            "manipulation_signals": [],
            "agent1_cross_reference": "Context validation encountered a technical error.",
            "source_risk_level": "MEDIUM",
            "agent_narrative": (
                "Agent 2 encountered a technical issue during context validation. "
                "The payment should be reviewed manually before proceeding."
            ),
            "needs_clarification": False,
            "clarification_question": None,
        }

    logger.info(
        "Agent 2: context validation complete | pattern=%s | source_risk=%s | needs_clarif=%s",
        context_data.get("social_engineering_pattern"),
        context_data.get("source_risk_level"),
        context_data.get("needs_clarification"),
    )

    # ── Step 4: HITL check ─────────────────────────────────────────────────────
    needs_clarification = bool(context_data.get("needs_clarification", False))
    clarification_question = context_data.get("clarification_question") if needs_clarification else None

    if needs_clarification and clarification_question:
        logger.info("Agent 2: HITL needed — publishing clarification request to Band room")
        hitl_message = {
            "type": "needs_clarification",
            "from_agent": "qr_upi_validator",
            "sequence": 2,
            "question": clarification_question,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await band_room.publish(hitl_message)
        logger.info("Agent 2: clarification question published: '%s'", clarification_question[:80])

    # ── Step 5: Build Agent2Output ─────────────────────────────────────────────
    # Extract fields from QR analysis
    payee_name_from_qr: str | None = None
    prefilled_amount: float | None = None
    visual_context_str: str | None = None

    if local_decode and local_decode.get("upi_params"):
        upi_p = local_decode["upi_params"]
        payee_name_from_qr = upi_p.get("pn")
        prefilled_amount = upi_p.get("am")

    if vision_analysis:
        payee_name_from_qr = payee_name_from_qr or vision_analysis.get("decoded_pn")
        if vision_analysis.get("decoded_am"):
            try:
                prefilled_amount = prefilled_amount or float(str(vision_analysis["decoded_am"]))
            except (ValueError, TypeError):
                pass
        visual_context_str = vision_analysis.get("visual_context")

    output = Agent2Output(
        decoded_upi_id=effective_upi_id,
        payee_name_from_qr=payee_name_from_qr,
        prefilled_amount=prefilled_amount,
        upi_context_mismatch=bool(context_data.get("upi_context_mismatch", False)),
        refund_scam_indicator=bool(context_data.get("refund_scam_indicator", False)),
        visual_context=visual_context_str,
        social_engineering_pattern=context_data.get("social_engineering_pattern"),
        manipulation_signals=context_data.get("manipulation_signals", []),
        agent_narrative=context_data.get("agent_narrative", ""),
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(
        "Agent 2 complete | refund_scam=%s | upi_mismatch=%s | pattern=%s",
        output.refund_scam_indicator,
        output.upi_context_mismatch,
        output.social_engineering_pattern,
    )

    # ── Step 6: Publish to Band room ───────────────────────────────────────────
    payload = output.model_dump()
    await band_room.publish(payload)
    logger.info("Agent 2: published result to Band room '%s'", band_room.name)

    return output
