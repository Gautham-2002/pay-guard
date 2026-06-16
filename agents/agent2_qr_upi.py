"""
Agent 2 — QR Decode & UPI Context Validator
=============================================
Power:   AIML API — gpt-4o (vision + reasoning)
Trigger: After Agent 1 publishes to the Band room.
Reads:   Agent 1 full output from Band.

Responsibilities
----------------
Job A — QR Decode & Visual Analysis (only when a QR image was uploaded):
  1. Decode the QR code using GPT-4o vision → extract pa (UPI ID), pn (payee
     name), am (pre-filled amount) from the upi://pay deep link.
  2. Check: does `pn` (payee name) match what `pa` (UPI ID) implies?
     e.g. pa=random123@ybl + pn=Amazon India → strong red flag.
  3. Check: is the pre-filled amount suspicious?
     ₹9,999 / ₹49,999 = common just-under-limit scam amounts.
  4. Analyse visual context: is this QR inside a WhatsApp screenshot, an
     official PDF, or a shop sticker?
  5. Detect: visible branding in the image that contradicts the UPI destination.
  6. Critical: is "refund" or "cashback" framing present?
     Users scan a QR to SEND money — never to receive it.

Job B — UPI–Purchase Context Validation:
  - Does the UPI ID make sense for this purchase?
    (buying from "a company website" but UPI is `personal_name@oksbi` = 🚩)
  - Does the payee name match the merchant the user claims to pay?
  - Cross-reference with Agent 1 evidence.

HITL trigger: posts `needs_clarification: true` to Band if context is
  missing or QR structure is unusual.

Band output schema
------------------
See api/models.py :: Agent2Output

Implemented in: Phase 2
"""

from __future__ import annotations

# TODO (Phase 2): Implement run() — decode QR image via AIML vision API,
#                 validate UPI context, cross-reference Agent 1 output,
#                 publish Agent2Output to Band room.


async def run(
    txn_id: str,
    band_room_id: str,
    agent1_output: dict,
    qr_image_bytes: bytes | None,
    amount: float,
    product_description: str | None,
    source_type: str,
    additional_context: str,
) -> dict:
    """
    Entry point for Agent 2.

    Parameters
    ----------
    txn_id:              Unique transaction ID for this check session.
    band_room_id:        Band room identifier to publish results into.
    agent1_output:       Full Agent1Output dict read from the Band room.
    qr_image_bytes:      Raw bytes of the uploaded QR image (None if not provided).
    amount:              INR amount the user is about to pay.
    product_description: What the user says they are paying for (optional).
    source_type:         How the payment detail was received.
    additional_context:  Free-text notes from the user.

    Returns
    -------
    Agent2Output-compatible dict published to the Band room.
    """
    raise NotImplementedError("Agent 2 is implemented in Phase 2")
