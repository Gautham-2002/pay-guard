# 🛡️ PayGuard AI — Product Requirements Document

**Version:** 3.1 — Source of Truth
**Hackathon:** Band of Agents Hackathon — lablab.ai (June 12–19, 2026)
**Status:** ✅ LOCKED

---

## 1. The Problem We Are Solving

Over **12.64 lakh UPI fraud incidents worth ₹981 crore** occurred in India in FY 2024-25. 1 in 5 UPI users have been defrauded. Common vectors: QR codes sent over WhatsApp ("scan this to get your refund"), UPI IDs from fake customer support, payment links from cloned e-commerce websites.

**The gap:** Payment apps have zero intelligence between "user receives a payment detail" and "user hits Pay."

**PayGuard AI fills that gap.** It is a pre-payment fraud intelligence assistant. The user tells us: what they're about to pay (UPI ID / URL / QR code) and where they got it from. We tell them whether to trust it, why, and exactly what to do.

---

## 2. What the User Does

| Field                        | Input                                                    | Examples                                                                            |
| ---------------------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| **Payment Destination**      | UPI ID, URL, or QR code image upload                     | `merchant@paytm`, `https://flipkart-sale.in/pay`, QR photo                          |
| **Payment Amount**           | INR amount                                               | ₹9,999                                                                              |
| **What are you paying for?** | Product/service description _(optional but recommended)_ | "iPhone 15 Pro 256GB", "Freelance logo design", "Shipping charges", "Online course" |
| **How They Got It**          | Dropdown + free text                                     | "WhatsApp from unknown", "Website I found on Google", "OLX buyer sent me"           |
| **Additional Context**       | Free text                                                | "They said scan to get refund", "I'm buying a phone"                                |

> **Why the product/service field matters:** If the user says they're paying ₹5,000 for an iPhone, that is a fraud signal. If they're paying ₹1,20,000, it is normal. Without knowing what they're buying, we cannot assess whether the amount makes sense.

**System returns:**

- 🟢 SAFE / 🟡 VERIFY / 🔴 DANGER verdict with risk score
- Plain-English explanation (specific, no jargon, India-context)
- Specific recommended actions
- "Ask the merchant" checklist (if VERIFY)
- Shareable report URL linked to Band room audit log

---

## 3. The 4-Agent Architecture

Sequential execution via Band. Each agent reads all previous agents' Band room output before running. **Accuracy over speed. Zero rule-based logic — every decision is made by an LLM reasoning over context.**

```
User Input
    ↓
[Band Room Created — txn-{id}]
    ↓
Agent 1 — Destination Intelligence (Featherless AI)
    ↓ publishes to Band
Agent 2 — QR Decode & UPI Context Validation (AIML API Vision)
    ↓ reads Agent 1, publishes to Band
Agent 3 — Web Intelligence (Playwright + DDG + Reddit + AIML API)
    ↓ reads Agent 1+2, publishes to Band
[HITL Gate — if any agent flags ambiguity, user answers via Band]
    ↓
Agent 4 — Verdict Synthesis (AIML API)
    ↓ reads all agents from Band, publishes final verdict
```

---

## 4. Agent Specifications

---

### 🔍 Agent 1 — Destination Intelligence Agent

**Power:** Featherless AI — `meta-llama/Llama-3.3-70B-Instruct`
**Trigger:** Always runs first.
**Input:** Raw URL or UPI ID (if QR uploaded, Agent 2 decodes it first and passes UPI ID back to Agent 1 on a re-run, OR Agent 1 runs after Agent 2 decodes — team to decide flow).

**What it collects (raw data, no decisions):**

- WHOIS: domain age, registrar, country of registration
- VirusTotal: malicious/suspicious votes from 70+ engines
- Google Safe Browsing: phishing/malware flag
- SSL certificate: validity, issuance date, issuing authority
- UPI VPA structure: parse `username@psp`, assess PSP suffix

**What the Featherless LLM reasons about:**

- Are any signals individually minor but collectively alarming?
- Does the UPI handle pattern suggest an individual vs a merchant account?
- What would a sophisticated fraudster do to appear legitimate here?
- Are there inconsistencies between what appears legitimate and what the data shows?

**Publishes to Band:**

```json
{
  "agent": "destination_intelligence",
  "sequence": 1,
  "destination_type": "UPI_ID | URL | BOTH",
  "upi_id": "merchant@paytm",
  "upi_psp": "paytm",
  "risk_level": "LOW | MEDIUM | HIGH",
  "top_signals": ["list of key findings"],
  "agent_narrative": "3-4 sentence LLM reasoning",
  "raw_evidence": {},
  "needs_clarification": false,
  "clarification_question": null
}
```

---

### 📷 Agent 2 — QR Decode & UPI Context Validator

**Power:** AIML API — `gpt-4o` (vision + reasoning)
**Trigger:** After Agent 1 publishes.
**Reads from Band:** Agent 1 full output.

**About UPI QR codes:**
A UPI QR code encodes a deep link:
`upi://pay?pa=merchant@paytm&pn=MerchantName&am=500&cu=INR`

- `pa` = payee UPI ID (what actually matters)
- `pn` = payee name (can be faked by anyone)
- `am` = pre-filled amount (can be manipulated)

**Job A — QR Decode & Visual Analysis (if QR image uploaded):**
The AIML API vision model:

1. Decodes the QR → extracts `pa` (UPI ID), `pn` (name), `am` (amount)
2. Checks: does `pn` (payee name) match what the `pa` (UPI ID) implies? `pa=random123@ybl` + `pn=Amazon India` = strong red flag
3. Checks: is the pre-filled amount suspicious? (₹9,999, ₹49,999 = common just-under-limit scam amounts)
4. Analyzes visual context: is this QR in a WhatsApp screenshot? Official PDF? Shop sticker?
5. Detects: any visible branding in the image that contradicts the UPI destination?
6. Critical check: is "refund" or "cashback" mentioned? No one scans a QR to _receive_ money — you only scan to _send_.

**Job B — UPI–Purchase Context Validation:**
Given the user's stated reason for payment and source, the LLM reasons:

- Does the UPI ID make sense for this purchase? (Buying from "a company website" but UPI is `personal_name@oksbi` = individual account, not merchant)
- Does the payee name match the merchant the user claims to be paying?
- Cross-reference with Agent 1: "Agent 1 confirmed this domain is 3 days old. The QR says payee is 'Flipkart Refund Desk' but the UPI ID `someone123@ybl` has no connection to Flipkart's payment infrastructure."

**Can trigger HITL:** If context is missing or QR structure is unusual, posts `needs_clarification` to Band.

**Publishes to Band:**

```json
{
  "agent": "qr_upi_validator",
  "sequence": 2,
  "decoded_upi_id": "merchant@paytm",
  "payee_name_from_qr": "Flipkart Refund Desk",
  "prefilled_amount": 9999,
  "upi_context_mismatch": true,
  "refund_scam_indicator": true,
  "visual_context": "QR in WhatsApp screenshot. No branding.",
  "social_engineering_pattern": "refund_scam",
  "manipulation_signals": ["refund_framing", "urgency"],
  "agent_narrative": "LLM narrative...",
  "needs_clarification": false,
  "clarification_question": null
}
```

---

### 🌐 Agent 3 — Web Intelligence Agent

**Power:** Playwright (open source) + duckduckgo-search (free, no API key) + PRAW/Reddit (free) + BeautifulSoup + AIML API for synthesis
**Trigger:** After Agent 2 publishes.
**Reads from Band:** Agent 1 + Agent 2 full outputs.
**Scope:** Runs fully for URL inputs. For UPI-only inputs, runs web search only (no crawl).

**Step 1 — Website Crawl (Playwright, headless Chromium):**

- Navigate to the URL, take full-page screenshot
- Screenshot → AIML API vision: detect fraud signals (urgency language, fake timers, excessive discounts, missing contact info, mismatched branding)
- Extract text: page title, about page, contact info, GST/company registration, reviews, pricing

**Step 2 — Web Search (duckduckgo-search — free, no API key needed):**
Four searches:

1. `"{domain}" scam OR fraud OR complaint` — existing fraud reports?
2. `"{domain}" official website` — is there a verified official site this is impersonating?
3. `"UPI {upi_id}" fraud OR scam` — UPI-specific fraud reports?
4. `"{product_description}" price India` — market price lookup _(only if product field provided)_

**Step 3 — Reddit Search (PRAW — free non-commercial):**
Search subreddits: `r/india`, `r/LegalAdviceIndia`, `r/personalfinanceindia`, `r/Scams`
Fetch top posts/comments mentioning the domain or UPI ID. Flag fraud warnings.

**Step 4 — Quora Scrape (BeautifulSoup):**
HTTP scrape of Quora search results for `"{domain} scam"`. Extract question titles and visible answer snippets.

**Step 5 — Price Intelligence (duckduckgo-search + AIML API):**
_Only runs if the user provided a product/service description._

This step answers: **Is the amount the user is being asked to pay reasonable for what they claim to be buying?**

How it works:

- Run targeted DDG searches: `"{product}" price India`, `"{product}" buy online India`, `"{product}" flipkart OR amazon price`
- Collect the top search result snippets — these contain price mentions from real listings
- If the product maps to a known category (electronics, clothing, services), also search for typical price ranges: `"{product category}" average price India 2024`
- Pass all of this — the raw search snippets, the user's stated amount, and the product description — to the AIML API LLM

The LLM reasons about:

- What is the typical market price range for this product/service in India?
- Is the user's amount within a normal range, suspiciously low ("too good to be true"), or suspiciously high (inflated invoice / advance fee)?
- Are there specific fraud patterns associated with this price point? (e.g., ₹9,999 for an iPhone = classic scam; ₹5,000 "advance" for a ₹50,000 job = advance fee fraud)
- Does the amount being requested match the type of product? (Paying for "shipping" but the amount is ₹15,000 = suspicious)
- The LLM is explicitly told: **do not flag based on rules** — reason about whether this specific combination of product + amount + context is suspicious

Price anomaly types the LLM is primed to detect:
| Anomaly | Example | Why suspicious |
|---|---|---|
| Too low (bait) | iPhone 15 for ₹5,000 | Classic fake product scam — lures victim with impossible price |
| Too high (gouging/fake invoice) | ₹25,000 "processing fee" for a ₹10,000 product | Inflated charges, fake invoice fraud |
| Advance fee pattern | ₹2,000 "advance" before receiving ₹50,000 job payment | Classic advance fee / Nigerian prince variant |
| Round number under limit | ₹9,999 or ₹49,999 for any product | Deliberately priced to stay under UPI/bank alert thresholds |
| Mismatch with product type | ₹15,000 for "courier charges" | Fake customs/shipping fee scam |

**Step 6 — AIML API Final Synthesis:**
Pass all collected evidence (screenshot analysis, crawled text, search results, Reddit/Quora findings, AND price intelligence findings) to AIML API reasoning model. The LLM synthesizes a single coherent web intelligence risk narrative covering all dimensions.

**Can trigger HITL:** If website is unreachable OR product description is vague and price anomaly is detected, posts clarification to Band.

**Publishes to Band:**

```json
{
  "agent": "web_intelligence",
  "sequence": 3,
  "website_crawled": true,
  "screenshot_analysis": "LLM description of visual fraud signals...",
  "page_fraud_signals": ["fake_countdown", "no_contact_info"],
  "fraud_complaints_found": true,
  "complaint_sources": ["Reddit r/india: 'Scammed by this site'"],
  "official_alternative_found": true,
  "official_site": "flipkart.com",
  "reddit_mentions": ["post snippet 1"],
  "price_intelligence": {
    "product_described": "iPhone 15 Pro 256GB",
    "amount_requested": 5000,
    "market_price_range": "₹1,10,000 – ₹1,30,000",
    "price_anomaly_type": "too_low_bait",
    "price_narrative": "The user is being asked to pay ₹5,000 for an iPhone 15 Pro whose market price is over ₹1,10,000. This is a classic fake product listing scam."
  },
  "web_risk_level": "HIGH",
  "agent_narrative": "LLM narrative combining all findings...",
  "needs_clarification": false
}
```

---

### ⚖️ Agent 4 — Verdict Synthesis & Recommendation Agent

**Power:** AIML API — `gpt-4o` or `claude-3-5-sonnet`
**Trigger:** After Agent 3 publishes (and after any HITL responses are in Band).
**Reads from Band:** Full room — all 3 agent outputs + any human responses.

**What the LLM does:**

- Reads all three narratives holistically — does not apply weighted averages
- Identifies agreements, conflicts, and interaction effects between agents
- E.g.: "Agent 1: MEDIUM. Agent 2: HIGH (refund scam). Agent 3: HIGH (Reddit complaints). Three independent agents converge on DANGER."
- Generates plain-English summary in India-context language
- Generates specific, contextual recommended actions — not generic advice
- Generates "Ask the merchant" checklist if VERIFY
- Estimates "avoided fraud amount" if DANGER

**Publishes to Band:**

```json
{
  "agent": "verdict_synthesis",
  "sequence": 4,
  "verdict": "SAFE | VERIFY | DANGER",
  "risk_score": 88,
  "plain_english_summary": "specific, plain language, fraud type named",
  "recommended_actions": ["specific action 1", "specific action 2"],
  "ask_merchant": ["question 1", "question 2"],
  "agent_agreement": "ALL_AGREE | PARTIAL_CONFLICT | FULL_CONFLICT",
  "conflict_resolution": null,
  "avoided_fraud_estimate": "₹9,999",
  "band_room_id": "txn-abc123"
}
```

---

## 5. Human-in-the-Loop (HITL) via Band Room

### Mechanism

Any Agent 1–3 can publish with `needs_clarification: true` and a specific question to the Band room. The agent pipeline pauses. The frontend detects this message type in its Band room poll/SSE stream, shows a question card to the user. The user answers in the UI. The backend publishes the answer to Band as a `human_response` message. The next agent reads both the prior output and the human response from Band before running.

### HITL Triggers

| Agent   | Situation                                        | Question                                                                                                                            |
| ------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Agent 2 | No context given, refund framing detected        | "Did they ask you to scan this QR to _receive_ money, or to pay? (Important: you only scan a QR to send money — never to receive.)" |
| Agent 2 | QR payee name contradicts user's stated merchant | "The QR payee name is '{pn}' but you said you're paying '{merchant}'. Can you confirm who you're actually paying?"                  |
| Agent 3 | Website unreachable                              | "The website is currently down. Can you share a screenshot of what you saw on the site?"                                            |
| Agent 3 | Ambiguous search results                         | "Have you dealt with this merchant before, or is this your first time?"                                                             |

### Why this is authentic Band HITL

- Band room is the async channel: agents don't know about the user directly; they just read the room
- Human joins the room as a participant; their message is a first-class Band room post
- The next agent reads the human's Band message exactly as it reads another agent's message

---

## 6. Input Types & Handling

| Input                           | Processing                                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **URL**                         | Agent 1: WHOIS/VT/SSL analysis. Agent 3: Playwright crawl + search.                                                 |
| **UPI ID**                      | Agent 1: VPA structure + PSP analysis. Agent 2: context relevance check. Agent 3: web search for UPI fraud reports. |
| **QR Code Image** (file upload) | Agent 2 vision decodes the QR → extracts UPI ID and payee name → cross-checks. Agent 1 receives extracted UPI ID.   |
| **Source Context**              | Agent 2 classifies social engineering pattern. All agents factor it into reasoning.                                 |

---

## 7. Additional Features

**7.1 "Ask the Merchant" Smart Generator** — Agent 4 generates contextual verification questions specific to the fraud scenario detected. Not generic.

**7.2 Shareable Report URL** — Read-only verdict page at `/report/{txn_id}`. Full agent narratives, Band room ID reference. Share with police complaint, cybercrime.gov.in, friends.

**7.3 Avoided Fraud Dashboard** — History of all checks, aggregate "fraud avoided: ₹X" counter.

**7.4 Scam Pattern Library** — Browsable cards for Indian UPI scam types: QR refund scam, OLX buyer scam, fake customer support, fake job offer, fake lottery. Each with red flag checklist.

**7.5 Real-Time Fraud Alert Feed** — Curated, anonymized display of recent fraud patterns. Styled as live feed for demo.

---

## 8. Technology Stack

| Layer              | Technology                                  | Cost                   |
| ------------------ | ------------------------------------------- | ---------------------- |
| Agent Coordination | Band (band.ai)                              | Free for builders      |
| Agent 1 LLM        | Featherless AI — Llama 3.3 70B              | Subscription/free tier |
| Agent 2/3/4 LLM    | AIML API — GPT-4o / Claude 3.5              | Have API key           |
| Web Crawling       | Playwright (open source)                    | Free                   |
| Web Search         | duckduckgo-search (`ddgs`)                  | Free, no API key       |
| Reddit Search      | PRAW                                        | Free, non-commercial   |
| Quora              | BeautifulSoup HTML scrape                   | Free                   |
| Domain Intel       | VirusTotal, Google Safe Browsing, WhoisJSON | Free tiers             |
| Backend            | FastAPI + Python 3.11+                      | Free                   |
| Frontend           | React + Vite                                | Free                   |
| Storage            | SQLite (demo)                               | Free                   |

---

## 9. Verdict System

| Verdict   | Score  | User Action                                    |
| --------- | ------ | ---------------------------------------------- |
| 🟢 SAFE   | 0–30   | Proceed normally                               |
| 🟡 VERIFY | 31–65  | Must choose "Verify First" or "Proceed Anyway" |
| 🔴 DANGER | 66–100 | Must type "I UNDERSTAND THE RISK" to override  |

---

## 10. Prize Alignment

| Prize                          | Evidence                                                                                                                                               |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Best Use of Featherless AI** | Agent 1 entirely on Featherless. Llama 3.3 70B reasons over raw WHOIS/VT/SSL/UPI signals — structured intelligence pipeline, not a prompt wrapper.     |
| **Best Use of AI/ML API**      | Agent 2 (vision: QR decode + visual analysis), Agent 3 (web intelligence synthesis), Agent 4 (verdict synthesis) — three agents, two modalities.       |
| **Best Multi-Agent / Band**    | 4 agents + 1 human participant in Band room. HITL via Band room messages. No agent-to-agent direct communication — Band room is the only shared layer. |
| **Innovation**                 | UPI context validation, web intelligence, and HITL via Band are novel in any consumer payment safety tool.                                             |

---

## 11. Demo Scenarios

| #   | Input                                          | Product              | Amount  | Verdict          | Key Story                                                                                                          |
| --- | ---------------------------------------------- | -------------------- | ------- | ---------------- | ------------------------------------------------------------------------------------------------------------------ |
| 1   | `razorpay.com`, "Company website"              | Payment gateway fee  | ₹500    | 🟢 SAFE          | All 4 agents clean. Amount reasonable for product.                                                                 |
| 2   | `razorpay-secure.co`, "WhatsApp unknown"       | "iPhone 15"          | ₹5,000  | 🔴 DANGER        | Lookalike domain + Agent 3 price intelligence: market price ₹1.1L — ₹5,000 is a bait scam.                         |
| 3   | QR from WhatsApp, "For refund"                 | "Refund from Amazon" | ₹9,999  | 🔴 DANGER        | Agent 2: refund framing (you scan to send, not receive). Price: ₹9,999 is a classic under-limit amount.            |
| 4   | `merchant@ybl`, "OLX buyer sent"               | Used laptop          | ₹1,200  | 🟡 VERIFY + HITL | UPI handle is individual account. Price is suspiciously low for a laptop. Agent triggers HITL.                     |
| 5   | `flipkart.com`, email from `flipkart-help.com` | "Processing fee"     | ₹15,000 | 🔴 DANGER        | Agent 2: fake email domain. Agent 3 price: ₹15,000 for a "courier processing fee" = classic customs/shipping scam. |

---

## 12. Finalized Decisions

| Decision        | Choice                                                                              |
| --------------- | ----------------------------------------------------------------------------------- |
| QR input        | File upload only                                                                    |
| Agent execution | Sequential 1→2→3→4 via Band                                                         |
| Agent 1 model   | Llama 3.3 70B via Featherless                                                       |
| HITL            | Band room async channel — agent posts question, user responds via UI posted to Band |
| Web search      | duckduckgo-search (free, no key)                                                    |
| Reddit          | PRAW (free, non-commercial)                                                         |
| Report sharing  | Shareable URL `/report/{txn_id}`                                                    |
| Frontend        | React + Vite                                                                        |

---

_PayGuard AI — PRD v3.1 | Band of Agents Hackathon · June 2026 · lablab.ai_
_This is the source of truth. All engineering decisions flow from here._
