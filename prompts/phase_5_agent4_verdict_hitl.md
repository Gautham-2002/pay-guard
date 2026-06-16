# Phase 5 — Agent 4: Verdict Synthesis + Agent 5 (HITL Backbone)

## Context
Phases 0–4 are complete. All 3 intelligence agents work and publish to Band.
PRD: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

This phase builds:
1. **Agent 4** — reads the complete Band room (all 3 agents + any HITL responses) and produces the final verdict using AIML API
2. **HITL backbone** — the mechanism for pausing the pipeline when an agent needs clarification

---

## Task 1: Build agents/agent4_verdict.py

```python
async def run(band_room: BandRoom, payload: CheckPayload) -> Agent4Output:
    """
    Agent 4 — Verdict Synthesis.
    
    1. Read the full Band room context (all agents + any human responses)
    2. Check if any HITL messages are unresolved — if so, wait for human response
    3. Call AIML API with the complete context
    4. Parse and publish the final verdict to Band
    5. Return Agent4Output
    """
```

### The Verdict Synthesis Prompt

This is the most critical prompt in the system. Build it carefully.

```
You are Agent 4 — the final decision-maker in PayGuard AI, a pre-payment fraud detection 
system for Indian users. Three specialist agents have analyzed a payment and published their 
findings. You must read all findings and synthesize a final verdict.

=== COMPLETE BAND ROOM — ALL AGENT FINDINGS ===
{band_room.get_full_context()}

=== PAYMENT DETAILS ===
Payment destination: {url or upi_id or "QR code decoded by Agent 2"}
Amount: ₹{amount}
What user is paying for: {product_description or "Not specified"}
How they received this: {source_type}
User's context: "{additional_context}"

=== YOUR SYNTHESIS TASK ===

1. AGREEMENT ASSESSMENT: Do all three agents agree, partially agree, or conflict?
   - If agents conflict: explain which agent's findings are more reliable and why
   - Example conflict: Agent 1 says LOW (domain is old), Agent 2 says HIGH (refund scam framing) 
     → Agent 2's social context is more relevant for this type of fraud

2. INTERACTION EFFECTS: How do findings from different agents reinforce each other?
   - Example: Agent 1 MEDIUM (new domain) + Agent 2 HIGH (refund scam) + Agent 3 HIGH 
     (Reddit complaints) = the convergence makes this clearly DANGER, not just MEDIUM

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
   - "Ask the OLX buyer to use a video call to show the product before you pay"
   Examples of BAD (generic — do not do this):
   - "Be careful"
   - "Verify the merchant"

7. ASK THE MERCHANT (only for VERIFY verdicts):
   2-3 specific verification questions the user can ask to confirm legitimacy.
   Examples: "Share your GST registration number", "Send an email from your company domain"
   For DANGER: leave this empty — don't suggest verifying an obvious scam.

8. AVOIDED FRAUD ESTIMATE (only for DANGER):
   State the amount the user would have lost: "₹{amount}"

Return JSON with EXACTLY these keys:
{
  "verdict": "SAFE" or "VERIFY" or "DANGER",
  "risk_score": integer 0-100,
  "plain_english_summary": "string",
  "recommended_actions": ["string", "string"],
  "ask_merchant": ["string"] or [],
  "agent_agreement": "ALL_AGREE" or "PARTIAL_CONFLICT" or "FULL_CONFLICT",
  "conflict_resolution": "string explaining how conflict was resolved" or null,
  "avoided_fraud_estimate": "₹X,XXX" or null
}
```

---

## Task 2: Build HITL Backbone (services/hitl_manager.py)

The HITL backbone manages the pause/resume pattern when an agent needs user input.

```python
class HITLManager:
    """
    Manages the Human-in-the-Loop flow via Band room.
    
    When an agent sets needs_clarification=True:
    1. The agent publishes a HITL message to the Band room
    2. HITLManager detects this and signals the backend to pause
    3. Backend returns a "hitl_waiting" status to the frontend
    4. Frontend shows the question to the user
    5. User answers → frontend POSTs to /check/{txn_id}/respond
    6. Backend publishes the human response to Band room
    7. HITLManager signals the pipeline to resume
    8. The next agent reads the human response from Band and continues
    """
    
    async def check_hitl_needed(self, band_room: BandRoom) -> dict | None:
        """
        Check if any message in the room has type="needs_clarification".
        Returns the HITL message if found and not yet answered, else None.
        """
    
    async def submit_human_response(self, band_room: BandRoom, question: str, answer: str) -> None:
        """
        Publish the user's answer to the Band room as a human_response message.
        Format: {type: "human_response", question: str, human_answer: str, timestamp: str}
        """
    
    async def wait_for_human_response(self, band_room: BandRoom, timeout: int = 300) -> str | None:
        """
        Poll Band room for a human_response message. Returns the answer string or None on timeout.
        """
    
    async def is_hitl_resolved(self, band_room: BandRoom) -> bool:
        """
        Check if a human_response exists in the room for the pending HITL question.
        """
```

---

## Task 3: tests/test_agent4.py

Build a test that runs the full 4-agent pipeline on 2 demo scenarios:

**Scenario 1: Clear DANGER**
Pre-populate a Band room with mock outputs:
- Agent 1: `risk_level=HIGH`, narrative about 2-day-old domain
- Agent 2: `social_engineering_pattern=refund_scam`, `refund_scam_indicator=true`
- Agent 3: `fraud_complaints_found=true`, `web_risk_level=HIGH`

Run Agent 4. Assert:
- `verdict == "DANGER"`
- `risk_score >= 70`
- `plain_english_summary` mentions refund or scam
- `recommended_actions` has at least 2 items
- `ask_merchant == []`
- Result published to Band room

**Scenario 2: VERIFY with conflict**
Pre-populate with:
- Agent 1: `risk_level=LOW` (legit domain)
- Agent 2: `source_risk_level=HIGH` (OLX buyer context)
- Agent 3: `web_risk_level=MEDIUM`

Run Agent 4. Assert:
- `verdict == "VERIFY"`
- `agent_agreement != "ALL_AGREE"`
- `conflict_resolution` is a non-empty string
- `ask_merchant` has at least 1 item

---

## Task 4: tests/test_full_pipeline.py

Run the complete sequential pipeline on one real scenario end-to-end:

Input: `razorpay-secure.co`, ₹9,999, source=whatsapp_unknown, product="iPhone 15 Pro"

1. Create Band room
2. Run Agent 1 → assert publishes to Band
3. Run Agent 2 (no QR image) → reads Agent 1 from Band → assert publishes
4. Run Agent 3 → reads Agent 1+2 from Band → assert publishes
5. Run Agent 4 → reads all from Band → assert publishes final verdict
6. Assert final verdict is DANGER
7. Print the complete Band room content (all messages in order)
8. Assert Band room has exactly 4 agent messages

---

## Completion Criteria
- [ ] Agent 4 produces valid JSON verdict for both test scenarios
- [ ] HITL manager publishes and reads human responses from Band correctly
- [ ] Full pipeline test (all 4 agents) completes and Band room has 4 messages
- [ ] Agent 4 verdict for DANGER scenario has: verdict=DANGER, non-empty actions, empty ask_merchant
- [ ] Agent 4 resolves agent conflicts explicitly in `conflict_resolution`
- [ ] No hardcoded verdict logic — LLM decides everything
