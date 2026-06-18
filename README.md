# PayGuard AI

**Pre-payment fraud intelligence for Indian UPI payments.**

> Check before you pay.

---

## What It Does

PayGuard AI sits between "user receives a payment detail" and "user hits Pay."
The user submits a UPI ID, payment URL, or QR code image, plus transaction
context such as amount, source channel, and what they are paying for. PayGuard
returns a simple verdict, explains the evidence, and gives concrete next steps.

**Verdict system:** SAFE | VERIFY | DANGER

The project targets Indian UPI fraud patterns including lookalike domains, fake
refund QR codes, marketplace advance-fee scams, suspicious payment links, and
social-engineering context mismatches.

---

## Architecture

```text
User Input (URL / UPI ID / QR image)
    |
    v
Agent 0 - Input Guardrail
    Featherless AI / meta-llama/Llama-3.3-70B-Instruct + structural validators
    Fallback model: Qwen/Qwen2.5-72B-Instruct
    Rejects malformed, off-topic, or nonsensical requests before room creation
    |
    v
FastAPI Backend
    Creates txn-{uuid} Band room
    Recruits / mentions Agent 1
    Streams status to frontend over SSE
    |
    v
[Band Room - txn-{uuid}]
    |
    v
Agent 1 - Destination Intelligence
    Featherless AI / meta-llama/Llama-3.3-70B-Instruct
    Fallback model: Qwen/Qwen2.5-72B-Instruct
    WHOIS, VirusTotal, Safe Browsing when enabled, SSL, UPI VPA analysis
    |
    v
Agent 2 - QR Decode & UPI Validator
    pyzbar local decode + AIML API / gpt-4o vision and reasoning
    UPI QR parsing, refund-scam detection, payee/context mismatch checks
    |
    v
Agent 3 - Web Intelligence
    Playwright + DuckDuckGo + optional Reddit + AIML API / gpt-4o
    Website/screenshot analysis, complaint search, price anomaly intelligence
    |
    v
[HITL Gate - if clarification is needed]
    User answer is published back into the Band room
    |
    v
Agent 4 - Verdict Synthesis
    AIML API / claude-3-5-sonnet
    Fallback model: gpt-4o
    Reads full room context and produces final verdict
    |
    v
Final Verdict + Shareable Report URL + SQLite History
```

No specialist agent communicates directly with another specialist agent. The
Band room is the shared collaboration layer for agent findings, handoffs, and
human responses.

---

## Stack

| Layer | Technology |
|---|---|
| Agent coordination | Band rooms, Band Agent API, Band Remote Agent SDK |
| Agent 0 guardrail LLM | Featherless AI - `meta-llama/Llama-3.3-70B-Instruct`, fallback `Qwen/Qwen2.5-72B-Instruct` |
| Agent 1 LLM | Featherless AI - `meta-llama/Llama-3.3-70B-Instruct`, fallback `Qwen/Qwen2.5-72B-Instruct` |
| Agent 2 LLM | AIML API - `gpt-4o` for QR vision and UPI context reasoning |
| Agent 3 LLM | AIML API - `gpt-4o` for screenshot, price, and web evidence synthesis |
| Agent 4 LLM | AIML API - `claude-3-5-sonnet`, fallback `gpt-4o` |
| QR decoding | `pyzbar` local decode with AIML `gpt-4o` vision support |
| Web crawling | Playwright headless Chromium |
| Web search | `duckduckgo-search` |
| Social search | PRAW / Reddit, disabled by default in `.env.example` |
| Domain intel | VirusTotal, WhoisJSON, optional Google Safe Browsing, SSL checks |
| Backend | FastAPI, Python 3.11+, SQLAlchemy async, SSE |
| Frontend | React 19, Vite 8, React Router, Framer Motion, Lucide icons |
| Storage | SQLite via `aiosqlite` |
| Package manager | `uv` |

---

## Quickstart

### 1. Install Python Dependencies

```bash
uv sync --extra remote-agents
uv run playwright install chromium
```

`uv sync --extra remote-agents` installs the Band SDK used by the specialist
remote-agent processes.

### 2. Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

### 3. Configure Environment

```bash
cp .env.example .env
cp agent_config.example.yaml agent_config.yaml
```

Fill in `.env`:

- `BAND_API_KEY`: Band Agent API key for the FastAPI app shell. Prefer a
  dedicated app-shell / bridge Remote Agent key so the app can create rooms and
  mention Agent 1.
- `FEATHERLESS_API_KEY`: used by Agent 0 and Agent 1.
- `AIML_API_KEY`: used by Agents 2-4.
- `VIRUSTOTAL_API_KEY` and `WHOISJSON_KEY`: used by domain intelligence.
- Optional: `ENABLE_SAFE_BROWSING=true` with `GOOGLE_SAFE_BROWSING_KEY`.
- Optional: `ENABLE_REDDIT=true` with PRAW credentials.

Fill in `agent_config.yaml` with four Band Remote Agents:

1. `destination_intelligence`
2. `qr_upi_validator`
3. `web_intelligence`
4. `verdict_synthesis`

Each entry needs the Band agent UUID, API key, handle, display name, model, and
`next_agent_key` for handoff routing.

### 4. Start the Band Remote Agents

Run each process in a separate terminal:

```bash
uv run payguard-agent1
uv run payguard-agent2
uv run payguard-agent3
uv run payguard-agent4
```

These processes connect to Band, wait for @mentions, execute their local
specialist logic, publish structured PayGuard payloads, and hand off to the next
configured agent.

### 5. Start the API

```bash
uv run uvicorn api.main:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### 6. Start the Frontend

```bash
cd frontend
npm run dev
```

- Frontend: http://localhost:5173
- Vite proxies `/api` to http://localhost:8000

### 7. Verify Connections

```bash
uv run python tests/test_connections.py
```

---

## API Surface

| Route | Purpose |
|---|---|
| `POST /api/check` | Submit a URL, UPI ID, or QR image for analysis |
| `GET /api/check/{txn_id}/status` | SSE stream of pipeline status changes |
| `GET /api/check/{txn_id}/stream` | SSE stream of Band-room agent events |
| `POST /api/check/{txn_id}/respond` | Submit HITL answer as JSON |
| `POST /api/check/{txn_id}/hitl` | Deprecated form-based HITL alias |
| `GET /api/report/{txn_id}` | Shareable read-only verdict report |
| `GET /api/history` | Check history and aggregate stats |
| `GET /health` | Liveness probe |

---

## Project Structure

```text
pay-guard/
├── agents/
│   ├── agent0_guardrail.py             # Pre-Band input guardrail
│   ├── agent1_destination.py           # Destination intelligence
│   ├── agent2_qr_upi.py                # QR decode and UPI validation
│   ├── agent3_web_intelligence.py      # Web, search, complaint, price intel
│   ├── agent4_verdict.py               # Final verdict synthesis
│   ├── band_config.py                  # Remote agent config loader
│   ├── remote_runtime.py               # Band SDK runtime and handoff adapter
│   └── remote_agent*.py                # Specialist remote-agent CLIs
├── api/
│   ├── main.py                         # FastAPI app, middleware, route wiring
│   ├── models.py                       # Pydantic contracts
│   ├── database.py                     # SQLAlchemy async persistence
│   ├── rate_limiter.py                 # POST /api/check rate limiting
│   └── routes/
│       ├── check.py                    # Submit, stream, HITL endpoints
│       ├── report.py                   # Shareable report endpoint
│       └── history.py                  # History endpoint
├── services/
│   ├── band_client.py                  # Band room API wrapper
│   ├── pipeline.py                     # Room seeding and progress monitor
│   ├── hitl_manager.py                 # Band-backed human response flow
│   ├── featherless_client.py           # Featherless wrapper
│   ├── aiml_client.py                  # AIML text and vision wrapper
│   ├── domain_intel.py                 # WHOIS / VT / GSB / SSL
│   ├── qr_artifacts.py                 # QR bytes handoff for remote agents
│   ├── qr_handler.py                   # QR decode and UPI deep-link parser
│   └── smart_crawler.py                # Web crawling helpers
├── frontend/
│   ├── src/pages/                      # Check, analysis, verdict, report, library, history
│   ├── src/data/scam_patterns.json     # Frontend scam library data
│   └── vite.config.js                  # Vite dev proxy to backend
├── data/
│   └── scam_patterns.json              # Backend scam pattern cards
├── scripts/
│   ├── create_demo_qr.py
│   ├── populate_demo_cache.py
│   └── seed_db.py
├── tests/
│   ├── test_agent*.py
│   ├── test_band*.py
│   ├── test_full_pipeline.py
│   ├── test_remote_config.py
│   └── test_connections.py
├── .env.example
├── agent_config.example.yaml
├── pyproject.toml
└── DEMO_SCRIPT.md
```

---

## Agent Details

### Agent 0 - Input Guardrail

Runs synchronously in `POST /api/check` before Band room creation.

- Performs structural checks for URLs, UPI IDs, amount range, and destination presence.
- Uses Featherless AI `meta-llama/Llama-3.3-70B-Instruct` for short semantic coherence checks.
- Falls back to `Qwen/Qwen2.5-72B-Instruct` through the same Featherless client if the primary model fails.
- Rejects clearly off-topic field content, such as code requests or internal-system questions.
- Fails open on internal errors so valid users are not blocked by an LLM/API outage.

### Agent 1 - Destination Intelligence

Runs as a Band Remote Agent.

- Uses Featherless AI `meta-llama/Llama-3.3-70B-Instruct` for structured destination risk reasoning.
- Falls back to `Qwen/Qwen2.5-72B-Instruct` through the shared Featherless client if needed.
- Checks domain age, registrar data, VirusTotal, optional Google Safe Browsing, SSL, and UPI VPA patterns.
- Publishes `Agent1Output` with `risk_level`, `top_signals`, raw evidence, and narrative.
- Hands off to Agent 2 through Band.

### Agent 2 - QR Decode & UPI Validator

Runs as a Band Remote Agent.

- Decodes QR locally with `pyzbar`.
- Uses AIML API `gpt-4o` for QR image visual context and UPI/social-engineering reasoning.
- Parses UPI deep links and detects refund QR scams.
- Flags payee name, UPI ID, amount, and context mismatches.
- Publishes `Agent2Output` and hands off to Agent 3 through Band.

### Agent 3 - Web Intelligence

Runs as a Band Remote Agent.

- Crawls and screenshots websites with Playwright.
- Searches for complaints, scam reports, official alternatives, and contextual web evidence.
- Uses AIML API `gpt-4o` for screenshot analysis, price anomaly reasoning, and final web evidence synthesis.
- Produces price anomaly intelligence when product and amount are available.
- Publishes `Agent3Output` and hands off to Agent 4 through Band.

### Agent 4 - Verdict Synthesis

Runs as a Band Remote Agent.

- Reads the full Band room context: Agents 1-3 outputs and any human response.
- Uses AIML API `claude-3-5-sonnet` for verdict synthesis, with AIML `gpt-4o` as fallback.
- Produces `SAFE`, `VERIFY`, or `DANGER` with a 0-100 risk score.
- Returns plain-English summary, recommended actions, merchant verification questions, and conflict resolution.
- Publishes the final payload consumed by the API and frontend.

---

## Human-in-the-Loop

Any Band agent can publish a `needs_clarification` message. The API detects it,
sets the transaction status to `hitl_waiting`, and the frontend shows the
question. The user response is posted to `/api/check/{txn_id}/respond` and
published into the same Band room as `human_response`, where subsequent agents
can read it as normal shared context.

## Development Checks

```bash
uv run pytest
cd frontend && npm run lint && npm run build
```

Use `uv run python tests/test_connections.py` for live external API smoke tests.
