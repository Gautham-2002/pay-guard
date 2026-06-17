# 🛡️ PayGuard AI

**Pre-payment fraud intelligence for Indian UPI payments.**
Built for the [Band of Agents Hackathon](https://lablab.ai) — June 2026.

---

## What it does

PayGuard AI sits between "user receives a payment detail" and "user hits Pay."
You give it a UPI ID, URL, or QR code photo — it tells you whether to trust it, why, and exactly what to do.

**Verdict system:** 🟢 SAFE · 🟡 VERIFY · 🔴 DANGER

---

## Architecture

4 AI agents coordinated sequentially through a Band room:

```
User Input
    ↓
[Band Room — txn-{id}]
    ↓
Agent 1 — Destination Intelligence    (Featherless AI / Llama 3.3 70B)
    ↓
Agent 2 — QR Decode & UPI Validator   (AIML API / GPT-4o vision)
    ↓
Agent 3 — Web Intelligence            (Playwright + DDG + Reddit + AIML API)
    ↓ [HITL Gate — if ambiguity detected]
Agent 4 — Verdict Synthesis           (AIML API / GPT-4o or Claude 3.5)
    ↓
Final Verdict + Shareable Report URL
```

No agent communicates directly with another — Band room is the only shared layer.

---

## Stack

| Layer | Technology |
|---|---|
| Agent Coordination | Band (band.ai) |
| Agent 1 LLM | Featherless AI — Llama 3.3 70B |
| Agent 2/3/4 LLM | AIML API — GPT-4o / Claude 3.5 |
| Web Crawling | Playwright (headless Chromium) |
| Web Search | duckduckgo-search (free, no key) |
| Reddit | PRAW (free) |
| Domain Intel | VirusTotal · WhoisJSON · optional Google Safe Browsing |
| Backend | FastAPI + Python 3.11+ |
| Frontend | React + Vite (Phase 7) |
| Storage | SQLite via SQLAlchemy async |
| Package manager | uv |

---

## Quickstart

### 1. Install dependencies

```bash
uv sync
uv run playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your API keys in .env
```

`BAND_API_KEY` is a Band Agent API key for the FastAPI app shell. The app uses
it to create rooms, recruit Agent 1, and seed the first @mention. In practice,
Band's `/agent/...` API rejects normal user keys here.

For the cleanest flow, create a dedicated app-shell/bridge Remote Agent in Band
and use that API key for `BAND_API_KEY`. Avoid reusing Agent 1's key if possible:
the app may need to mention Agent 1, and self-mentions can be rejected by Band.
The four runnable specialist remote-agent keys still live in `agent_config.yaml`.

For the four specialist Band agents, also copy `agent_config.example.yaml` to
`agent_config.yaml`, create one Band Remote Agent for each key in that file,
and add `FEATHERLESS_API_KEY` / `AIML_API_KEY` to `.env`.

Install the Band remote-agent SDK:

```bash
uv sync --extra remote-agents
```

### 3. Start Band remote agents

Each process connects to Band, waits for @mentions, runs its local specialist
logic directly, publishes structured task events, and hands off by @mention:

```bash
uv run payguard-agent1
uv run payguard-agent2
uv run payguard-agent3
uv run payguard-agent4
```

The FastAPI app creates a Band room, recruits Agent 1 by handle, and seeds the
initial @mention. The remote agents perform the specialist analysis and hand off
through Band.

### 4. Verify all API connections

```bash
uv run python tests/test_connections.py
```

### 5. Start the API server

```bash
uv run uvicorn api.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

---

## Project Structure

```
pay-guard/
├── agents/                     # 4-agent pipeline (Phase 1–4)
│   ├── agent1_destination.py   # Featherless AI — domain/UPI intel
│   ├── agent2_qr_upi.py        # AIML API — QR decode & context validation
│   ├── agent3_web_intelligence.py  # Playwright + DDG + Reddit synthesis
│   ├── agent4_verdict.py       # AIML API — final verdict
│   ├── remote_runtime.py       # No-hop Band SDK runtime and handoff adapter
│   └── remote_agent*.py        # Band remote-agent runners
├── services/                   # API clients & utilities
│   ├── band_client.py          # Band remote-agent rooms/events/context
│   ├── featherless_client.py   # Featherless AI wrapper
│   ├── aiml_client.py          # AIML API wrapper (text + vision)
│   ├── domain_intel.py         # WHOIS / VirusTotal / GSB / SSL
│   ├── qr_artifacts.py         # QR image artifact handoff for Band agents
│   └── qr_handler.py           # QR decode + UPI deep-link parser
├── api/                        # FastAPI application (Phase 5)
│   ├── main.py                 # App factory + CORS + routers
│   ├── models.py               # Pydantic schemas for all agents + routes
│   └── routes/                 # check / report / history endpoints
├── data/
│   └── scam_patterns.json      # 6 Indian UPI scam pattern cards
├── tests/
│   └── test_connections.py     # External API smoke tests
├── frontend/                   # React + Vite (Phase 7)
├── .env.example                # API key template
└── pyproject.toml              # uv project config + dependencies
```

---

## Implementation Phases

| Phase | Focus |
|---|---|
| **Phase 0** ✅ | Project scaffold, dependencies, Pydantic models, API connection tests |
| Phase 1 | Agent 1 — Destination Intelligence (Featherless + domain APIs) |
| Phase 2 | Agent 2 — QR Decode & UPI Validator (AIML vision) |
| Phase 3 | Agent 3 — Web Intelligence (Playwright + DDG + Reddit) |
| Phase 4 | Agent 4 — Verdict Synthesis |
| Phase 5 | FastAPI routes + SSE + HITL + SQLite persistence |
| Phase 6 | Band room integration end-to-end |
| Phase 7 | React + Vite frontend |
| Phase 8 | Polish, demo scenarios, deployment |

---

## Demo Scenarios

| Input | Product | Amount | Expected Verdict |
|---|---|---|---|
| `razorpay.com` — company website | Payment gateway fee | ₹500 | 🟢 SAFE |
| `razorpay-secure.co` — WhatsApp | "iPhone 15" | ₹5,000 | 🔴 DANGER |
| QR from WhatsApp — "for refund" | "Refund from Amazon" | ₹9,999 | 🔴 DANGER |
| `merchant@ybl` — OLX buyer | Used laptop | ₹1,200 | 🟡 VERIFY + HITL |
| `flipkart.com` from `flipkart-help.com` | "Processing fee" | ₹15,000 | 🔴 DANGER |

---

*PayGuard AI · Band of Agents Hackathon · lablab.ai · June 2026*
