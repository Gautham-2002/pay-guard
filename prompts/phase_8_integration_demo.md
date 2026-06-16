# Phase 8 — Integration, Demo Caching & Polish

## Context
Phases 0–7 are complete. All 4 agents work, the FastAPI backend is running, and the React frontend is built.
PRD: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

This phase focuses on end-to-end integration, pre-caching demo scenarios for reliable demo/video recording, and final polish. No new features — this is about making everything work together flawlessly.

---

## Task 1: Run Full End-to-End Integration Test

Run all 5 demo scenarios from the PRD end-to-end (frontend → backend → all 4 agents → verdict → UI). Fix any integration bugs found.

### Demo Scenarios to test:

| # | Destination | Product | Amount | Source | Expected Verdict |
|---|---|---|---|---|---|
| 1 | razorpay.com | Payment gateway fee | ₹500 | website | 🟢 SAFE |
| 2 | razorpay-secure.co | iPhone 15 | ₹5,000 | whatsapp_unknown | 🔴 DANGER |
| 3 | QR image (create a UPI QR with pa=scammer@ybl, pn=Amazon Refund) | Amazon refund | ₹9,999 | whatsapp_unknown | 🔴 DANGER |
| 4 | merchant@ybl | Used laptop | ₹1,200 | olx_marketplace | 🟡 VERIFY |
| 5 | flipkart.com | Processing fee | ₹15,000 | email | 🔴 DANGER |

For scenario 3, create a test QR code image:
```python
# Use qrcode library: pip install qrcode[pil]
import qrcode
qr = qrcode.make("upi://pay?pa=scammer123@ybl&pn=Amazon+Refund+Desk&am=9999&cu=INR")
qr.save("tests/test_qr_refund_scam.png")
```

---

## Task 2: Build Demo Cache System

Pre-cache all external API responses for the 5 demo scenarios so the demo video can be recorded without live API calls (avoids rate limits and network issues).

### Create data/demo_cache.json structure:

```json
{
  "razorpay.com": {
    "virustotal": { ... actual VT response ... },
    "whois": { ... actual WHOIS response ... },
    "safe_browsing": { "is_dangerous": false, "threat_types": [] },
    "ssl": { "valid": true, "age_days": 1825, "issuer": "..." }
  },
  "razorpay-secure.co": {
    "virustotal": { ... },
    "whois": { ... },
    ...
  }
}
```

### Populate the cache:
Write a script `scripts/populate_demo_cache.py` that:
1. Calls real APIs for each of the 5 demo domains/UPIs
2. Saves responses to `data/demo_cache.json`

### Make agents use the cache:
In `services/domain_intel.py`, at the top of each fetch function, check the cache:
```python
async def fetch_virustotal_url(url: str, client: httpx.AsyncClient) -> dict:
    domain = extract_domain(url)
    cached = load_cache(domain, "virustotal")
    if cached and os.getenv("USE_DEMO_CACHE", "false") == "true":
        return cached
    # ... real API call ...
```

Set `USE_DEMO_CACHE=true` in `.env` when recording the demo video.

---

## Task 3: Fix Any Issues Found During Integration

Common issues to check and fix:

1. **CORS errors** — ensure backend allows requests from `http://localhost:5173`
2. **SSE stream disconnects** — add reconnection logic in frontend AnalysisPage
3. **Featherless JSON parse failure** — verify retry logic in `featherless_client.py` works
4. **Rate limits** — ensure VirusTotal rate limiter (4 req/min) is working correctly
5. **QR decode failure** — if pyzbar fails to decode QR, ensure AIML vision fallback runs
6. **Playwright timeout** — if a site doesn't load in 15s, ensure graceful fallback
7. **Band room timeout** — if an agent doesn't publish within 60s, ensure partial results are used
8. **HITL flow** — test the full HITL cycle: agent flags → frontend shows question → user answers → pipeline resumes

---

## Task 4: Create a Demo Mode Flag

Add `?demo=true` URL parameter support to the frontend. When in demo mode:
- Pre-fill the check form with demo scenario data (one of the 5 scenarios)
- Show a "DEMO MODE" banner
- Use the cached responses

This makes it easy to demonstrate during judging without typing in all fields.

---

## Task 5: Write README.md

Create a comprehensive README at `payguard/README.md`:

```markdown
# PayGuard AI 🛡️

Pre-payment fraud intelligence system for the Band of Agents Hackathon 2026.

## What it does
[2-paragraph summary]

## Architecture
[Diagram of 4-agent sequential pipeline with Band]

## Tech Stack
[Table of all technologies]

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- API keys for: Band, Featherless AI, AIML API, VirusTotal, Google Safe Browsing, WhoisJSON, Reddit

### Installation
[Step-by-step with commands]

### Running
[How to start backend + frontend]

## Agent Details
[Brief description of each agent]

## Demo Scenarios
[Table of 5 scenarios with expected verdicts]

## Band Integration
[How Band rooms are used — room creation, agent publishing, HITL, audit trail]

## Featherless AI Usage
[How and why Featherless is used for Agent 1]

## AIML API Usage
[How AIML API vision and reasoning are used for Agents 2, 3, 4]
```

---

## Task 6: Pre-record Demo Script (document only)

Create `DEMO_SCRIPT.md` at the project root with:

```markdown
# PayGuard AI — Demo Script (3 minutes)

## 0:00 — Introduction (20 seconds)
"PayGuard AI is a pre-payment fraud detection system. Before you pay, tell us 
the payment destination and how you received it. Our 4 AI agents — coordinated 
through Band — analyze it and tell you if it's safe."

## 0:20 — Demo Scenario 1: SAFE (30 seconds)
- Enter: razorpay.com, ₹500, Website, "Payment gateway fee"
- Show live Band room feed (3 agents analyzing)
- Show SAFE verdict
- "All agents agree — legitimate 14-year-old domain, verified payment processor"

## 0:50 — Demo Scenario 2: DANGER — Lookalike Domain (30 seconds)  
- Enter: razorpay-secure.co, ₹5,000, WhatsApp unknown, "iPhone 15"
- Highlight: Agent 1 flags suspicious domain
- Highlight: Agent 3 price intelligence — iPhone for ₹5,000 is a bait scam
- Show DANGER verdict + recommended actions

## 1:20 — Demo Scenario 3: DANGER — QR Refund Scam (40 seconds)
- Upload the test QR image (pa=scammer@ybl, pn=Amazon Refund Desk)
- Select: "They said scan to get my refund"
- Show Agent 2: "Payee name says 'Amazon Refund Desk' but UPI ID is scammer@ybl — clear mismatch"
- Show DANGER verdict: "You cannot receive money by scanning a QR code"

## 2:00 — Demo: Band Room Audit Trail (20 seconds)
- Show the Band room ID in the report
- "Every analysis is permanently logged in Band — tamper-evident, shareable for dispute resolution"

## 2:20 — Demo: Human-in-the-Loop (30 seconds)
- Run Scenario 4 (OLX buyer)
- When HITL triggers: "Have you already shipped the item?"
- Show user answering, pipeline resuming
- Show VERIFY verdict with Ask Merchant questions

## 2:50 — Closing (10 seconds)
"PayGuard AI — check before you pay."
```

---

## Completion Criteria
- [ ] All 5 demo scenarios run end-to-end and produce correct verdicts
- [ ] Demo cache populated with real API responses for all 5 scenarios
- [ ] `USE_DEMO_CACHE=true` mode works without making live API calls
- [ ] HITL flow works end-to-end: agent pauses → user answers → pipeline resumes
- [ ] README.md is complete and accurate
- [ ] QR test image created at `tests/test_qr_refund_scam.png`
- [ ] Demo mode URL parameter (`?demo=true`) pre-fills the form
- [ ] No console errors in frontend during any demo scenario
- [ ] `DEMO_SCRIPT.md` written and reviewed
