# PayGuard AI 🛡️

**Pre-payment fraud intelligence for Indian UPI payments.**  
Built for the [Band of Agents Hackathon 2026](https://lablab.ai).

> **Check before you pay.**

---

## What It Does

PayGuard AI sits between "user receives a payment detail" and "user hits Pay." Every day, millions of Indians lose money to lookalike domains, fake QR refund scams, and social-engineering attacks on OLX and WhatsApp. PayGuard AI intercepts that moment — you give it a UPI ID, URL, or QR code photo and it tells you **whether to trust it, why, and exactly what to do next.**

The system runs a sequential pipeline of 4 specialized AI agents, coordinated through a **Band room** that serves as the shared message bus. Each agent publishes its findings as a structured message; the next agent reads all prior messages before analysing. The result is a transparent, tamper-evident audit trail stored permanently in Band — shareable as a dispute-resolution artefact.

**Verdict system:** 🟢 SAFE · 🟡 VERIFY · 🔴 DANGER

---

## Architecture

```
User Input (URL / UPI ID / QR image)
        │
        ▼
  [FastAPI Backend]
        │  creates
        ▼
  [Band Room — txn-{uuid}]
        │
        ├─── Agent 1 ── Destination Intelligence   (Featherless AI / Llama 3.3 70B)
        │               WHOIS · VirusTotal · GSB · SSL · UPI VPA analysis
        │               → publishes risk_level + narrative to Band room
        │
        ├─── Agent 2 ── QR Decode & UPI Validator  (AIML API / GPT-4o Vision)
        │               pyzbar local decode + vision fallback · social engineering detection
        │               → publishes refund_scam_indicator, upi_context_mismatch
        │
        ├─── Agent 3 ── Web Intelligence           (Playwright + DDG + Reddit + AIML API)
        │               Screenshot analysis · web search · Reddit/Quora scrape
        │               Price anomaly detection (fair market price vs. asked amount)
        │               → publishes web_risk_level, fraud_complaints_found, price_intel
        │
        │   [HITL Gate] — pipeline pauses here if ANY agent flagged ambiguity
        │                 User answers via frontend → answer published to Band room
        │
        └─── Agent 4 ── Verdict Synthesis          (AIML API / Claude 3.5 Sonnet)
                        Reads full Band room history → produces final verdict
                        plain_english_summary · recommended_actions · ask_merchant
                        avoided_fraud_estimate
                        │
                        ▼
              Final Verdict + Shareable Report URL
              (persisted to SQLite via SQLAlchemy async)
```

**No agent communicates directly with another — Band room is the only shared state layer.**

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Agent Coordination** | [Band](https://band.ai) — room pub/sub as message bus |
| **Agent 1 LLM** | Featherless AI — `meta-llama/Llama-3.3-70B-Instruct` |
| **Agent 2/3/4 LLM** | AIML API — `gpt-4o` (vision) / `claude-3-5-sonnet` |
| **QR Decoding** | `pyzbar` (local) with AIML API vision fallback |
| **Web Crawling** | Playwright (headless Chromium) |
| **Web Search** | `duckduckgo-search` (free, no key) |
| **Social Search** | PRAW — Reddit API |
| **Domain Intel** | VirusTotal v3 · Google Safe Browsing v4 · WhoisJSON |
| **Backend** | FastAPI + Python 3.11+ · async throughout |
| **SSE Streaming** | Server-Sent Events — real-time agent updates to frontend |
| **Frontend** | React 18 + Vite · Framer Motion · Lucide icons |
| **Storage** | SQLite via SQLAlchemy async (aiosqlite) |
| **Package Manager** | `uv` |

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- `uv` package manager (`pip install uv` or see [docs.astral.sh/uv](https://docs.astral.sh/uv/))
- API keys for: Band, Featherless AI, AIML API, VirusTotal, Google Safe Browsing, WhoisJSON, Reddit

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Gautham-2002/pay-guard.git
cd pay-guard

# 2. Install Python dependencies
uv sync

# 3. Install Playwright Chromium
uv run playwright install chromium

# 4. Install frontend dependencies
cd payguard/frontend && npm install && cd ../..

# 5. Configure environment
cp .env.example .env
# Edit .env and fill in all API keys
```

### Running

**Terminal 1 — Backend**
```bash
uv run uvicorn api.main:app --reload --port 8000
```

**Terminal 2 — Frontend**
```bash
cd payguard/frontend
npm run dev
```

- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Verify API Connections

```bash
uv run python tests/test_connections.py
```

### Demo Mode (for recording)

1. Populate the cache once (calls real APIs):
   ```bash
   uv run python scripts/populate_demo_cache.py
   ```

2. Enable cache in `.env`:
   ```
   USE_DEMO_CACHE=true
   ```

3. Open the frontend with demo URL parameter:
   ```
   http://localhost:5173/?demo=true&scenario=2
   ```
   Scenario 1–5 maps to the 5 demo cases below.

---

## Project Structure

```
pay-guard/
├── agents/
│   ├── agent1_destination.py      # Featherless AI — domain/UPI intel
│   ├── agent2_qr_upi.py           # AIML API — QR decode & context validation
│   ├── agent3_web_intelligence.py # Playwright + DDG + Reddit synthesis
│   └── agent4_verdict.py          # AIML API — final verdict synthesis
├── services/
│   ├── band_client.py             # Band room pub/sub (create, publish, poll)
│   ├── featherless_client.py      # Featherless AI LLM wrapper (OpenAI-compat)
│   ├── aiml_client.py             # AIML API wrapper (text + vision)
│   ├── domain_intel.py            # WHOIS / VirusTotal / GSB / SSL + demo cache
│   ├── qr_handler.py              # pyzbar QR decode + UPI deep-link parser
│   ├── hitl_manager.py            # Human-in-the-loop question/answer flow
│   └── pipeline.py                # Sequential 4-agent orchestrator + state
├── api/
│   ├── main.py                    # FastAPI app factory + CORS + lifespan
│   ├── models.py                  # Pydantic schemas (all agents + routes)
│   ├── database.py                # SQLAlchemy async ORM (CheckRecord)
│   └── routes/
│       ├── check.py               # POST /check · GET /check/{id}/stream (SSE)
│       ├── report.py              # GET /report/{id} — shareable report
│       └── history.py             # GET /history — user's check history
├── payguard/
│   └── frontend/                  # React + Vite frontend
│       └── src/
│           └── pages/
│               ├── CheckPage.jsx  # Input form (URL / UPI / QR) + demo mode
│               ├── AnalysisPage.jsx  # Live agent timeline (SSE) + HITL
│               ├── VerdictPage.jsx   # Final verdict display
│               ├── ReportPage.jsx    # Shareable read-only report
│               ├── LibraryPage.jsx   # Scam pattern library
│               └── HistoryPage.jsx   # Check history dashboard
├── data/
│   ├── scam_patterns.json         # 6 Indian UPI scam pattern cards
│   └── demo_cache.json            # Pre-cached API responses (git-ignored)
├── scripts/
│   └── populate_demo_cache.py     # Cache populator for demo recording
├── tests/
│   ├── test_connections.py        # External API smoke tests
│   ├── test_agent1.py             # Agent 1 unit tests
│   ├── test_agent2.py             # Agent 2 unit tests
│   ├── test_agent3.py             # Agent 3 unit tests
│   ├── test_agent4.py             # Agent 4 unit tests
│   ├── test_band.py               # Band client tests
│   ├── test_full_pipeline.py      # End-to-end pipeline tests
│   └── test_qr_refund_scam.png    # Test QR: scammer123@ybl (Amazon Refund Desk)
├── .env.example                   # API key template
├── pyproject.toml                 # uv project config + dependencies
└── DEMO_SCRIPT.md                 # 3-minute demo script
```

---

## Agent Details

### Agent 1 — Destination Intelligence
**LLM:** Featherless AI / `meta-llama/Llama-3.3-70B-Instruct`  
**Purpose:** Establish whether the payment destination (URL or UPI ID) is technically legitimate.

Collects raw signals in parallel:
- **WHOIS** — domain age, registrar, country (WhoisJSON API)
- **VirusTotal** — URL scan + domain reputation (70+ AV engines)
- **Google Safe Browsing** — threat classification (MALWARE, SOCIAL_ENGINEERING, etc.)
- **SSL** — certificate validity, age, self-signed detection
- **UPI VPA parser** — PSP classification, username pattern (personal vs. merchant vs. random)

Publishes a structured `Agent1Output` to the Band room with `risk_level` (low/medium/high/critical) and `agent_narrative`.

---

### Agent 2 — QR Decode & UPI Validator
**LLM:** AIML API / `gpt-4o` (vision)  
**Purpose:** Decode QR codes and detect social engineering in UPI context.

- **Local decode** via `pyzbar` — fast, offline
- **Vision fallback** — AIML API GPT-4o reads the QR image if pyzbar fails
- Checks for **payee name / UPI ID mismatch** (e.g., "Amazon Refund Desk" but `pa=scammer@ybl`)
- Detects **refund scam pattern** (you cannot receive money by scanning a QR)
- Reads Agent 1's Band room messages for context before analysing

---

### Agent 3 — Web Intelligence
**LLM:** AIML API / `gpt-4o` + Playwright  
**Purpose:** Gather external evidence — what does the internet say about this destination?

- **Playwright screenshot** — captures the actual website, analyses with vision LLM
- **DuckDuckGo search** — `site:{domain}` + `"{domain}" scam review fraud`
- **Reddit PRAW** — searches r/india, r/IndianScams, r/personalfinance
- **Quora scrape** — via DDG results
- **Price intelligence** — compares asked amount vs. fair market price for the product
- Publishes `web_risk_level`, `fraud_complaints_found`, `price_intelligence` to Band

---

### Agent 4 — Verdict Synthesis
**LLM:** AIML API / `claude-3-5-sonnet` (or `gpt-4o` fallback)  
**Purpose:** Read all Band room messages and synthesise a final human-readable verdict.

- Reads the **full Band room history** (Agents 1, 2, 3 + any HITL responses)
- Produces structured `Agent4Output`:
  - `verdict` — SAFE / VERIFY / DANGER
  - `risk_score` — 0–100
  - `plain_english_summary` — 2–3 sentences a non-technical user can understand
  - `recommended_actions` — ordered list of what to do next
  - `ask_merchant` — questions to ask the seller to verify legitimacy
  - `avoided_fraud_estimate` — estimated INR saved if user follows advice

---

## Demo Scenarios

| # | Destination | Product | Amount | Source | Expected Verdict |
|---|---|---|---|---|---|
| 1 | `razorpay.com` | Payment gateway fee | ₹500 | Website | 🟢 SAFE |
| 2 | `razorpay-secure.co` | iPhone 15 | ₹5,000 | WhatsApp unknown | 🔴 DANGER |
| 3 | QR (`scammer123@ybl` / "Amazon Refund Desk") | Amazon refund | ₹9,999 | WhatsApp unknown | 🔴 DANGER |
| 4 | `merchant@ybl` | Used laptop | ₹1,200 | OLX marketplace | 🟡 VERIFY + HITL |
| 5 | `flipkart.com` (from phishing email) | Processing fee | ₹15,000 | Email | 🔴 DANGER |

Use `?demo=true&scenario=N` URL parameter to auto-fill the form with any scenario.

---

## Band Integration

Every payment check creates a **dedicated Band room** named `txn-{uuid}`.

| Event | Band message |
|---|---|
| Agent 1 completes | Publishes `{agent: "destination_intelligence", risk_level, narrative}` |
| Agent 2 completes | Publishes `{agent: "qr_upi_validator", refund_scam_indicator, mismatch}` |
| Agent 3 completes | Publishes `{agent: "web_intelligence", web_risk_level, fraud_complaints}` |
| HITL triggered | Agent publishes `{type: "hitl_request", question}` · pipeline pauses |
| User answers | Route handler publishes `{type: "human_response", answer}` to Band |
| Agent 4 completes | Publishes full verdict + `{type: "final_verdict"}` |

The Band room ID is surfaced in the verdict report — anyone with the room ID can verify the full agent audit trail.

---

## Featherless AI Usage

**Agent 1** exclusively uses Featherless AI to call `meta-llama/Llama-3.3-70B-Instruct` for holistic risk assessment.

Why Featherless for Agent 1?
- Agent 1 only needs text reasoning (no vision) — Llama 3.3 70B is highly capable for structured JSON output
- Featherless provides zero-infrastructure access to open-weight models with an OpenAI-compatible API
- The `FeatherlessClient` in `services/featherless_client.py` implements retry logic with JSON repair for robust production use

---

## AIML API Usage

**Agents 2, 3, and 4** use AIML API which provides access to both GPT-4o and Claude 3.5 Sonnet via a single OpenAI-compatible endpoint.

| Agent | Model | Why |
|---|---|---|
| Agent 2 | `gpt-4o` (vision) | QR image analysis — needs multimodal capability |
| Agent 3 | `gpt-4o` | Screenshot analysis + web synthesis |
| Agent 4 | `claude-3-5-sonnet` | Best-in-class instruction following for final verdicts |

The `AIMLClient` in `services/aiml_client.py` wraps both text and vision calls with exponential backoff and structured output parsing.

---

## Human-in-the-Loop (HITL)

Any agent can signal `needs_clarification: true` in its output. When this happens:

1. The pipeline pauses at the HITL gate
2. The agent's `hitl_question` is published to the Band room
3. The frontend (`AnalysisPage`) displays the question card
4. User types their answer and submits via `POST /api/check/{txn_id}/respond`
5. The answer is published to the Band room
6. The pipeline resumes (5-minute timeout if no answer)
7. Agent 4 reads the human answer as part of the full room context

This enables scenarios like: "Have you already sent the item?" when an OLX buyer seems suspicious.

---

*PayGuard AI · Band of Agents Hackathon · lablab.ai · June 2026*
