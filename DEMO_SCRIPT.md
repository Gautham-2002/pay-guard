# PayGuard AI — Demo Script (3 minutes)

> **Quick setup before recording:**  
> 1. `USE_DEMO_CACHE=true` in `.env` (run `scripts/populate_demo_cache.py` first)  
> 2. Backend running: `uv run uvicorn api.main:app --reload --port 8000`  
> 3. Frontend running: `cd payguard/frontend && npm run dev`  
> 4. Open: `http://localhost:5173/?demo=true`

---

## 0:00 — Introduction (20 seconds)

**Screen:** Landing page / CheckPage

**Say:**
> "PayGuard AI is a pre-payment fraud detection system.  
> Before you pay, tell us the payment destination and how you received it.  
> Our 4 AI agents — coordinated through Band — analyze it and tell you if it's safe."

**Action:** Point to the trust badges at the bottom: Destination Intel · QR & UPI Check · Web Search · AI Verdict

---

## 0:20 — Scenario 1: SAFE — Legitimate Payment Gateway (30 seconds)

**Screen:** `http://localhost:5173/?demo=true&scenario=1` (auto-filled)

**Form shows:**
- URL: `https://razorpay.com`
- Amount: ₹500
- Source: Website
- Product: Payment gateway fee

**Say:**
> "Scenario 1 — someone is asking you to pay ₹500 on Razorpay."

**Action:** Click **🛡️ Analyze Now**

**Screen:** AnalysisPage — watch all 4 agent cards turn green one by one

**Say:**
> "Watch the 4 agents run sequentially — each one publishes its findings to the Band room  
> before the next one starts."

**Screen:** VerdictPage showing 🟢 SAFE

**Say:**
> "All agents agree — legitimate 14-year-old domain, verified payment processor,  
> clean VirusTotal score. Safe to proceed."

---

## 0:50 — Scenario 2: DANGER — Lookalike Domain (30 seconds)

**Screen:** `http://localhost:5173/?demo=true&scenario=2`

**Form shows:**
- URL: `https://razorpay-secure.co`
- Amount: ₹5,000
- Source: WhatsApp from unknown number
- Product: iPhone 15

**Say:**
> "Scenario 2 — same as before but notice the URL: `razorpay-secure.co` — NOT razorpay.com."

**Action:** Click **🛡️ Analyze Now**

**Screen:** AnalysisPage — Agent 1 card turns red

**Say:**
> "Agent 1 immediately flags this — domain registered 3 months ago,  
> zero reputation on VirusTotal, suspicious registrar."

**Screen:** Agent 3 card turns red with price intel

**Say:**
> "Agent 3 confirms: no legitimate web presence, AND...  
> an iPhone 15 for ₹5,000 is a price bait — market price is ₹79,000.  
> That's a 94% discount. Classic bait scam."

**Screen:** VerdictPage showing 🔴 DANGER

---

## 1:20 — Scenario 3: DANGER — QR Refund Scam (40 seconds)

**Screen:** `http://localhost:5173/?demo=true&scenario=3`

**Form shows:**
- Tab: QR Code
- Amount: ₹9,999
- Source: WhatsApp from unknown number
- Context: "Scan this QR to get an Amazon refund"

**Say:**
> "Scenario 3 — someone sent a QR code saying 'scan to get your ₹9,999 Amazon refund.'  
> Upload the test QR."

**Action:** Upload `tests/test_qr_refund_scam.png` into the QR dropzone, click **Analyze Now**

**Screen:** AnalysisPage — Agent 2 immediately flags

**Say:**
> "Agent 2 decodes the QR. Look at this finding:  
> Payee name says 'Amazon Refund Desk' — but the UPI ID is `scammer123@ybl`.  
> Classic mismatch."

**Screen:** VerdictPage 🔴 DANGER

**Say:**
> "The key insight: you CANNOT receive money by scanning a QR code.  
> Scanning sends money — this is a refund scam."

---

## 2:00 — Band Room Audit Trail (20 seconds)

**Screen:** VerdictPage / ReportPage — show Band room ID

**Say:**
> "Every analysis is permanently logged in a dedicated Band room.  
> The room ID is surfaced in the report — tamper-evident, shareable for  
> dispute resolution. You can show this to your bank or police."

**Action:** Point to the Band Room ID badge / copy icon in the report

---

## 2:20 — Scenario 4: VERIFY — Human-in-the-Loop (30 seconds)

**Screen:** `http://localhost:5173/?demo=true&scenario=4`

**Form shows:**
- UPI ID: `merchant@ybl`
- Amount: ₹1,200
- Source: OLX marketplace
- Product: Used laptop

**Action:** Click **🛡️ Analyze Now**

**Screen:** AnalysisPage — pipeline pauses, HITL card appears

**Say:**
> "Scenario 4 — an OLX buyer wants to buy your used laptop.  
> Agent 2 detects ambiguity and pauses the pipeline to ask you a question."

**Screen:** HITL card showing question e.g. "Have you already shipped the item?"

**Say:**
> "The agent needs context to give you the right advice.  
> I'll type my answer..."

**Action:** Type "No, I haven't shipped it yet" → Submit Answer

**Screen:** Pipeline resumes → VerdictPage showing 🟡 VERIFY

**Say:**
> "VERIFY verdict with specific questions to ask the buyer  
> before handing over the laptop. This is human-in-the-loop AI."

---

## 2:50 — Closing (10 seconds)

**Screen:** CheckPage (clean state)

**Say:**
> "PayGuard AI — check before you pay.  
> 4 agents. 1 Band room. Real-time fraud intelligence."

---

## Quick Reference

| Scenario | URL Parameter | Expected |
|---|---|---|
| Razorpay legit | `?demo=true&scenario=1` | 🟢 SAFE |
| Lookalike domain | `?demo=true&scenario=2` | 🔴 DANGER |
| QR refund scam | `?demo=true&scenario=3` | 🔴 DANGER |
| OLX buyer (HITL) | `?demo=true&scenario=4` | 🟡 VERIFY |
| Flipkart fee scam | `?demo=true&scenario=5` | 🔴 DANGER |

## Notes

- Keep `USE_DEMO_CACHE=true` in `.env` during recording — avoids rate limits
- The Band room feed (⚡ Band Room Activity accordion) shows real-time agent messages — open it for Scenario 2 to show the live pub/sub
- The AnalysisPage `TXN:` badge shows the live transaction ID — great B-roll shot
- For Scenario 3, have `tests/test_qr_refund_scam.png` ready on your desktop for quick drag-and-drop
