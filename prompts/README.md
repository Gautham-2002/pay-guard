# PayGuard AI — Phase Execution Guide

**PRD (Source of Truth):** `PayGuard_AI_PRD_v3.md` (in the artifacts directory) — read this before anything else.

Run the phases IN ORDER. Do not skip. Each phase builds on the previous.

---

## Phase Map

| Phase | File | What Gets Built | Key Tech |
|---|---|---|---|
| **Phase 0** | `phase_0_project_setup.md` | Project structure, requirements, Pydantic models, API connection tests | Python, FastAPI skeleton |
| **Phase 1** | `phase_1_band_integration.md` | Band client wrapper — room create, publish, read, HITL polling | Band SDK |
| **Phase 2** | `phase_2_agent1_destination.md` | Domain/UPI intelligence + Featherless AI LLM reasoning | Featherless AI (Llama 3.3 70B) |
| **Phase 3** | `phase_3_agent2_qr_upi.md` | QR decode, visual analysis, UPI–context validation | AIML API Vision (GPT-4o) |
| **Phase 4** | `phase_4_agent3_web_intelligence.md` | Website crawl, search, Reddit, Quora, price intelligence | Playwright, DDG, PRAW, AIML API |
| **Phase 5** | `phase_5_agent4_verdict_hitl.md` | Verdict synthesis + HITL backbone | AIML API (GPT-4o / Claude) |
| **Phase 6** | `phase_6_fastapi_backend.md` | Full API — all routes, SSE stream, database, HITL endpoints | FastAPI, SQLAlchemy, SSE |
| **Phase 7** | `phase_7_frontend.md` | Full React UI — 6 pages, live agent feed, verdict display | React + Vite, Framer Motion |
| **Phase 8** | `phase_8_integration_demo.md` | End-to-end integration, demo caching, README, demo script | All of the above |

---

## What Each Phase Produces

**After Phase 0:**
- Full folder structure exists
- All Python deps installed
- `python tests/test_connections.py` → all APIs respond

**After Phase 1:**
- Band rooms can be created and messages published/read
- `python tests/test_band.py` → all 6 tests pass

**After Phase 2:**
- Agent 1 runs and publishes domain/UPI intelligence to Band
- `python tests/test_agent1.py` → 4 scenarios output structured verdicts

**After Phase 3:**
- Agent 2 decodes QR codes via AIML vision and validates UPI context
- `python tests/test_agent2.py` → 3 scenarios pass

**After Phase 4:**
- Agent 3 crawls websites, searches DDG/Reddit/Quora, analyzes prices
- `python tests/test_agent3.py` → 4 scenarios pass

**After Phase 5:**
- Agent 4 synthesizes all agents' findings into a final verdict
- HITL manager can pause/resume the pipeline via Band room messages
- `python tests/test_full_pipeline.py` → complete 4-agent run succeeds

**After Phase 6:**
- `POST /api/check` runs the full pipeline and returns a verdict
- SSE stream sends real-time agent progress events
- All 5 REST endpoints work

**After Phase 7:**
- Full React app running at localhost:5173
- All 6 pages working and wired to the backend
- Live agent feed updates in real time

**After Phase 8:**
- All 5 demo scenarios work end-to-end
- Demo cache populated (no live API calls needed for demo)
- README written, demo script ready

---

## Architecture Reminder

```
User (React Frontend)
    ↓ POST /api/check (multipart)
FastAPI Backend
    ↓ creates Band room txn-{id}
Band Room (persistent shared context)
    ↓
Agent 1 — Featherless AI (Llama 3.3 70B)
  → collects: WHOIS, VirusTotal, GSB, SSL, UPI analysis
  → LLM reasons holistically → publishes to Band
    ↓ Agent 2 reads Band
Agent 2 — AIML API Vision (GPT-4o)
  → decodes QR → analyzes payee name vs UPI ID
  → classifies social engineering pattern → publishes to Band
  → may trigger HITL (user questioned via Band room)
    ↓ Agent 3 reads Band
Agent 3 — Playwright + DDG + PRAW + AIML API
  → crawls website → analyzes screenshot
  → searches for fraud complaints → checks Reddit/Quora
  → compares price vs market → publishes to Band
    ↓ Agent 4 reads Band (all 3 agents + any HITL responses)
Agent 4 — AIML API (GPT-4o)
  → synthesizes all findings → produces final verdict
  → publishes to Band (complete audit trail)
    ↓
FastAPI → Response to Frontend → VerdictPage
```

---

## Key Rules (Never Break These)

1. **No agent-to-agent direct calls** — agents only read/write Band rooms
2. **No hardcoded thresholds or rules** — every risk decision is made by an LLM
3. **Band room is the audit trail** — every message persists, nothing is lost
4. **Sequential execution** — 1 → 2 → 3 → 4, each reads all previous
5. **All tools are free/open-source** — Playwright, DDG search, PRAW, BeautifulSoup
6. **Featherless for Agent 1, AIML API for Agents 2/3/4** — this is the hackathon requirement

---

## Environment Variables Required

```
BAND_API_KEY
FEATHERLESS_API_KEY
AIML_API_KEY
VIRUSTOTAL_API_KEY
GOOGLE_SAFE_BROWSING_KEY
WHOISJSON_KEY
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
REDDIT_USER_AGENT
DATABASE_URL
SECRET_KEY
USE_DEMO_CACHE (set to "true" for demo recording)
```

---

*PayGuard AI — Band of Agents Hackathon · June 2026 · lablab.ai*
