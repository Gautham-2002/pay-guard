# PayGuard AI Frontend

React + Vite frontend for PayGuard AI, the pre-payment fraud intelligence app
for Indian UPI payments.

The frontend lets users submit a URL, UPI ID, or QR image, watch the Band-backed
agent workflow in real time, answer human-in-the-loop questions, and review the
final verdict or shareable report.

---

## Screens

| Route | Page | Purpose |
|---|---|---|
| `/` | Check Payment | URL / UPI / QR submission form with source, amount, product, and context fields |
| `/analysis/:txn_id` | Analysis | Live SSE timeline for agent progress and HITL prompts |
| `/verdict/:txn_id` | Verdict | Final SAFE / VERIFY / DANGER result and recommended actions |
| `/report/:txn_id` | Report | Shareable read-only report |
| `/library` | Scam Library | Indian UPI scam pattern cards |
| `/history` | History | Prior checks and aggregate history data |

---

## Backend Contract

The Vite dev server proxies `/api` to `http://localhost:8000`.

Frontend calls:

| Endpoint | Used for |
|---|---|
| `POST /api/check` | Start a payment check with multipart form data |
| `GET /api/check/{txn_id}/status` | Status-change SSE stream |
| `GET /api/check/{txn_id}/stream` | Band-room agent update SSE stream |
| `POST /api/check/{txn_id}/respond` | Submit HITL answer |
| `GET /api/report/{txn_id}` | Fetch report data |
| `GET /api/history` | Fetch check history |

`POST /api/check` may return:

- `202` with `txn_id`, stream URLs, response URL, and report URL.
- `400` with `error: "guardrail_rejection"` when Agent 0 rejects invalid or off-topic input.
- `429` with rate-limit metadata when the backend sliding-window limiter is active.

---

## Agent Workflow Display

The UI reflects the current backend workflow:

```text
Agent 0 - Input Guardrail
    Provider: Featherless AI
    Model: meta-llama/Llama-3.3-70B-Instruct
    Fallback: Qwen/Qwen2.5-72B-Instruct
    Runs before navigation to analysis
    Rejection is shown inline on the check form

Agents 1-4 - Band Remote Agents
    Agent 1: Destination Intelligence
        Provider: Featherless AI
        Model: meta-llama/Llama-3.3-70B-Instruct
        Fallback: Qwen/Qwen2.5-72B-Instruct
    Agent 2: QR Decode & UPI Validator
        Provider: AIML API
        Model: gpt-4o
    Agent 3: Web Intelligence
        Provider: AIML API
        Model: gpt-4o
    Agent 4: Verdict Synthesis
        Provider: AIML API
        Model: claude-3-5-sonnet
        Fallback: gpt-4o
```

Agent 0 does not appear as a Band-room step because it runs before the room is
created. The analysis timeline focuses on the four Band Remote Agents.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Build tool | Vite 8 |
| UI framework | React 19 |
| Routing | React Router 7 |
| HTTP | Axios |
| Animation | Framer Motion |
| Icons | Lucide React |
| Styling | Plain CSS modules per page plus shared app styles |

---

## Setup

From the repository root:

```bash
cd frontend
npm install
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

Run the backend separately from the repository root:

```bash
uv run uvicorn api.main:app --reload --port 8000
```

API docs:

```text
http://localhost:8000/docs
```

---

## Scripts

```bash
npm run dev
npm run build
npm run lint
npm run preview
```

## Project Structure

```text
frontend/
├── index.html
├── package.json
├── vite.config.js               # /api proxy to backend
├── public/
│   ├── favicon.svg
│   └── icons.svg
└── src/
    ├── App.jsx                  # Router and navigation
    ├── App.css
    ├── main.jsx
    ├── index.css
    ├── data/
    │   └── scam_patterns.json
    └── pages/
        ├── CheckPage.jsx        # Form, QR upload, guardrail/rate-limit errors
        ├── AnalysisPage.jsx     # SSE progress and HITL UI
        ├── VerdictPage.jsx      # Final result page
        ├── ReportPage.jsx       # Shareable report page
        ├── LibraryPage.jsx      # Scam pattern library
        └── HistoryPage.jsx      # History dashboard
```
