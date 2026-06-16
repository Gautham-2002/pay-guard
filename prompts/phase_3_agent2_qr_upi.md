# Phase 3 — Agent 2: QR Decode & UPI Context Validator (AIML API Vision)

## Context
You are building **PayGuard AI**. Phases 0–2 are complete:
- `services/band_client.py` works
- `services/featherless_client.py` works
- `agents/agent1_destination.py` is complete and tested
- All models are in `api/models.py`

The full PRD is at: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

**Agent 2** runs AFTER Agent 1 publishes to Band. It reads Agent 1's output from Band before starting. It has two jobs:
1. **QR Code Decode & Visual Analysis** (if user uploaded a QR image) — uses AIML API vision model
2. **UPI–Purchase Context Validation** — uses AIML API reasoning model

**Key UPI QR fact:** A UPI QR encodes `upi://pay?pa=merchant@paytm&pn=PayeeName&am=500&cu=INR`
- `pa` = actual UPI ID (where money goes — cannot be faked in the link itself)
- `pn` = payee display name (CAN be anything — "Amazon Refund Team", "Flipkart Support")
- `am` = pre-filled amount

The most important check: **does `pn` match what `pa` implies?** A mismatch is a strong fraud signal.

---

## Task 1: Build services/aiml_client.py

```python
from openai import AsyncOpenAI
import os, base64

aiml = AsyncOpenAI(
    api_key=os.getenv("AIML_API_KEY"),
    base_url="https://api.aimlapi.com/v2"
)

VISION_MODEL = "gpt-4o"
REASONING_MODEL = "gpt-4o"

async def chat_text(messages: list[dict], response_format: dict = None) -> str:
    """Text-only chat completion via AIML API. Returns response content string."""

async def chat_vision(image_bytes: bytes, text_prompt: str) -> str:
    """
    Vision chat completion. Encodes image as base64 data URL.
    Sends: [{role: user, content: [{type: text, text: prompt}, {type: image_url, image_url: {url: data:image/...}}]}]
    Always compress image to max 1MB before sending (use Pillow).
    Returns response content string.
    """

def compress_image(image_bytes: bytes, max_size_kb: int = 1024) -> bytes:
    """Use Pillow to resize image if > max_size_kb. Returns compressed bytes."""
```

---

## Task 2: Build services/qr_handler.py

```python
async def decode_qr_from_image(image_bytes: bytes) -> dict | None:
    """
    Attempt to decode a QR code from image bytes using the `opencv-python` or `pyzbar` library.
    
    Install: pip install pyzbar pillow
    
    Returns:
    {
        "raw_data": "upi://pay?pa=merchant@paytm&pn=MerchantName&am=500&cu=INR",
        "decoded_type": "UPI_PAYMENT" | "URL" | "TEXT" | "UNKNOWN",
        "upi_params": {          # only if decoded_type == UPI_PAYMENT
            "pa": "merchant@paytm",
            "pn": "MerchantName",
            "am": "500",
            "cu": "INR"
        } or None
    }
    
    If QR cannot be decoded locally, return None (the AIML vision model will handle it).
    Never raise — return None on any error.
    
    Parse UPI deep links using urllib.parse.parse_qs on the query string.
    """
```

---

## Task 3: Build agents/agent2_qr_upi.py

```python
async def run(
    band_room: BandRoom,
    qr_image_bytes: bytes = None,    # None if user didn't upload QR
    upi_id: str = None,              # directly provided UPI ID (if no QR)
    url: str = None,
    amount: float = None,
    product_description: str = None,
    source_type: str = None,
    additional_context: str = None
) -> Agent2Output:
    """
    Agent 2 — QR Decode & UPI Context Validator.
    
    Flow:
    1. Read Agent 1 output from Band room
    2. If QR image provided: attempt local decode (qr_handler.py), then AIML vision analysis
    3. Run UPI context validation (AIML reasoning)
    4. Determine if HITL is needed
    5. Publish to Band room
    6. Return Agent2Output
    """
```

### Sub-task A: QR Image Analysis

If `qr_image_bytes` is provided:

**Step 1 — Local decode attempt:**
Call `services/qr_handler.py:decode_qr_from_image()`. If successful, you have the UPI params.

**Step 2 — AIML API Vision analysis:**
Regardless of local decode result, send the image to AIML API vision for visual context analysis.

Build this prompt for the vision model:
```
You are analyzing a QR code image for payment fraud indicators.

CONTEXT FROM PREVIOUS AGENT:
{agent1_output.agent_narrative}
Agent 1 risk level: {agent1_output.risk_level}

{if local decode succeeded:}
QR DECODED CONTENT: pa={pa}, pn={pn}, am={am}
{else:}
The QR could not be decoded locally. Please attempt to decode it from the image.

YOUR TASKS:
1. If QR is not decoded yet: read the QR code and identify pa (UPI ID), pn (payee name), am (amount) if visible.
2. Describe the visual context: where does this QR appear? (WhatsApp screenshot, official PDF, physical sticker, etc.)
3. Is there any merchant branding or logo visible near the QR? If yes, does it match the UPI destination?
4. Are there signs of tampering (QR overlaid on something, sticker on sticker)?
5. Is there any text suggesting "scan to RECEIVE money" or "refund" or "cashback"? This is ALWAYS a scam — you can ONLY send money by scanning a QR, never receive it.

Return JSON:
{
  "decoded_pa": "UPI ID or null",
  "decoded_pn": "payee name or null",
  "decoded_am": "amount or null",
  "visual_context": "description of image context",
  "branding_visible": true/false,
  "branding_name": "brand name or null",
  "branding_matches_destination": true/false/null,
  "tampering_detected": true/false,
  "refund_receive_framing": true/false,
  "visual_summary": "2-sentence plain English observation"
}
```

### Sub-task B: UPI Context Validation

After QR analysis (or if no QR was provided), run the context validation.

Read Agent 1's full output from Band room using `band_room.get_full_context()`.

Build this AIML API reasoning prompt:
```
You are Agent 2 in PayGuard AI, analyzing the human context around a payment.

=== BAND ROOM CONTEXT (Agent 1's findings) ===
{band_room.get_full_context()}

=== USER'S PAYMENT CONTEXT ===
Payment destination: {upi_id or url}
Amount: ₹{amount}
What they're paying for: {product_description or "Not specified"}
How they received this payment detail: {source_type}
Additional context from user: "{additional_context}"

{if qr_analysis:}
=== QR CODE ANALYSIS ===
Decoded UPI ID (pa): {pa}
Payee name in QR (pn): {pn}
Pre-filled amount: {am}
Visual context: {visual_context}
Refund/receive framing detected: {refund_receive_framing}

=== YOUR ANALYSIS TASKS ===

1. UPI COHERENCE CHECK:
   - Does the UPI ID structure (username + PSP) make sense for the stated purchase?
   - Individual accounts (random usernames) vs merchant accounts (brand-like usernames)
   - PSP match: does the PSP suit the claimed merchant type?
   
2. PAYEE NAME vs UPI ID CHECK (if QR decoded):
   - The payee name ({pn}) is user-controlled text — anyone can write anything
   - Does it match the actual UPI ID ({pa})?
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

Output JSON:
{
  "upi_context_mismatch": true/false,
  "refund_scam_indicator": true/false,
  "social_engineering_pattern": "pattern string or none",
  "manipulation_signals": ["list", "of", "detected", "tactics"],
  "agent1_cross_reference": "1-2 sentences on how Agent 1 findings align or conflict",
  "source_risk_level": "LOW" or "MEDIUM" or "HIGH",
  "agent_narrative": "3-4 sentences. Be specific. Name the exact pattern. India-context language.",
  "needs_clarification": true/false,
  "clarification_question": "specific question or null"
}
```

### HITL Logic

If `needs_clarification: true` in the LLM output:
1. Publish a special HITL message to Band:
```json
{
  "type": "needs_clarification",
  "from_agent": "qr_upi_validator",
  "sequence": 2,
  "question": "{clarification_question}",
  "timestamp": "..."
}
```
2. Return from `run()` with a partial `Agent2Output` that includes `needs_clarification: true`
3. The backend will handle waiting for human response before running Agent 3

---

## Task 4: tests/test_agent2.py

Test scenarios:

```python
TEST_CASES = [
    {
        "name": "OLX buyer scam context",
        "upi_id": "buyer123@oksbi",
        "amount": 1200,
        "source_type": "olx_marketplace",
        "additional_context": "A buyer on OLX sent me this UPI ID to pay for my old laptop",
        "expected_pattern": "olx_buyer_scam"
    },
    {
        "name": "Refund scam context",
        "upi_id": "refund@paytm",
        "amount": 9999,
        "source_type": "whatsapp_unknown",
        "additional_context": "They said I need to scan QR to get my Amazon refund",
        "expected": "refund_scam_indicator=True"
    },
    {
        "name": "Legitimate vendor payment",
        "upi_id": "vendor@razorpay",
        "amount": 5000,
        "source_type": "website",
        "additional_context": "Paying for software subscription on the company website",
        "expected_risk": "LOW"
    },
]
```

For each: run agent2 (using a pre-populated Band room with a mock Agent 1 output), assert structured output, assert Band room message published.

---

## Completion Criteria

- [ ] `services/aiml_client.py` — both text and vision functions work with AIML API
- [ ] `services/qr_handler.py` — local QR decode works (test with a real UPI QR code image)
- [ ] `agents/agent2_qr_upi.py` — handles both QR + no-QR cases correctly
- [ ] HITL message published to Band when `needs_clarification=true`
- [ ] `python tests/test_agent2.py` — all 3 scenarios pass
- [ ] Vision model correctly detects refund framing when present in context
- [ ] No hardcoded scoring or pattern matching — LLM decides everything
