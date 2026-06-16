# Phase 7 — React + Vite Frontend

## Context
Phases 0–6 are complete. The FastAPI backend is running at `http://localhost:8000`.
PRD: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

Build the full React + Vite frontend at `/home/gautham/Documents/personal-projects/band-hackathon/payguard/frontend/`.

The UI must be **premium and polished** — not a prototype. Dark theme, glassmorphism, smooth animations. The user must be wowed at first glance.

---

## Task 0: Initialize the Vite Project

```bash
cd /home/gautham/Documents/personal-projects/band-hackathon/payguard
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install react-router-dom axios framer-motion lucide-react
```

Configure Vite proxy in `vite.config.js`:
```js
server: {
  proxy: {
    '/api': 'http://localhost:8000'
  }
}
```

---

## Task 1: Design System (src/index.css)

Build a complete design system. Dark theme with these tokens:

```css
:root {
  --bg-primary: #0a0a0f;
  --bg-secondary: #12121a;
  --bg-card: rgba(255,255,255,0.04);
  --bg-card-hover: rgba(255,255,255,0.07);
  --border: rgba(255,255,255,0.08);
  --border-accent: rgba(99,102,241,0.4);
  
  /* Verdict colors */
  --safe: #10b981;
  --safe-bg: rgba(16,185,129,0.1);
  --verify: #f59e0b;
  --verify-bg: rgba(245,158,11,0.1);
  --danger: #ef4444;
  --danger-bg: rgba(239,68,68,0.1);
  
  /* Text */
  --text-primary: #f8fafc;
  --text-secondary: #94a3b8;
  --text-muted: #475569;
  
  /* Accent */
  --accent: #6366f1;
  --accent-light: #818cf8;
  
  --radius: 16px;
  --radius-sm: 10px;
}
```

Use Google Fonts: `Inter` (import in index.html).

Global styles: box-sizing, dark background, smooth scrolling, no text selection on UI elements.

Utility classes: `.glass` (glassmorphism card), `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.verdict-safe`, `.verdict-verify`, `.verdict-danger`, `.risk-badge`.

---

## Task 2: Page — CheckPage (src/pages/CheckPage.jsx)

The main entry point. A clean, focused form.

**Layout:** Centered card, max-width 640px. Header with PayGuard AI logo + tagline: "Check before you pay."

**Form sections:**

**Section 1 — Payment Destination** (required — at least one)
- Tab switcher: "URL/Link" | "UPI ID" | "QR Code"
- URL tab: text input with placeholder "https://example.com/pay"
- UPI tab: text input with placeholder "merchant@paytm"
- QR tab: drag-and-drop file upload area with dashed border, "Upload QR code image" + file icon. Show preview thumbnail when file selected. Accept image/* only.

**Section 2 — Payment Details**
- Amount field: INR prefix symbol (₹), number input, placeholder "0.00"
- Product/service field: text input, placeholder "What are you paying for? (e.g. iPhone 15, Freelance work)" — label: "What are you paying for? (helps us check if the price is fair)"

**Section 3 — How You Received This**
- Dropdown: WhatsApp from unknown number | WhatsApp from known contact | Website link | SMS | Email | In person | OLX / marketplace | Other
- Text area: "Tell us more (optional)" — placeholder: "e.g. They said it's for a refund, I'm buying a phone from OLX"

**CTA:** Large "Analyze Now 🛡️" button. Full width. Disabled if no destination provided.

On submit: POST to `/api/check` as multipart/form-data. Redirect to `/analysis/{txn_id}`.

---

## Task 3: Page — AnalysisPage (src/pages/AnalysisPage.jsx)

Live progress screen while agents are working. Route: `/analysis/:txn_id`

**Layout:** Centered, max-width 560px.

**Header:** "Analyzing your payment..." with a subtle pulsing shield icon.

**Agent Progress Timeline:**
Four agent cards in vertical order, each with:
- Agent icon + name
- Status badge: "Waiting..." (gray) → "Analyzing..." (blue, pulsing) → "Complete ✓" (green) or "Flagged ⚠" (yellow/red)
- When complete: show a one-line preview of the agent's finding

Agent names and icons:
- 🔍 Destination Intelligence (Featherless AI)
- 📷 QR & UPI Validator (AIML API Vision)
- 🌐 Web Intelligence (Playwright + Search)
- ⚖️ Verdict Synthesis (AIML API)

**Live Band Room Feed (collapsible section):**
Small expandable panel at bottom: "Band Room Activity" showing raw agent messages as they arrive.

**SSE Connection:**
Connect to `/api/check/{txn_id}/stream`. On each event:
- `agent_update`: update the corresponding agent card
- `hitl_required`: show the HITL question card (see below)
- `complete`: redirect to `/verdict/{txn_id}`
- `error`: show error state

**HITL Question Card:**
When `hitl_required` event received, pause the progress animation and show a card:
- Question text (from event data)
- Text area for user answer
- "Submit Answer" button
- On submit: POST to `/api/check/{txn_id}/respond` with `{answer: string}`, then resume SSE

---

## Task 4: Page — VerdictPage (src/pages/VerdictPage.jsx)

The core output page. Route: `/verdict/:txn_id`

On mount: GET `/api/report/{txn_id}`.

**Section 1 — Verdict Hero**
Full-width verdict banner with colored background matching verdict:
- 🟢 SAFE: green gradient
- 🟡 VERIFY: amber gradient  
- 🔴 DANGER: red gradient

Large verdict icon (shield with checkmark/warning/X). Risk score ring (animated SVG circle). Verdict label. Plain English summary (large, readable text).

**Section 2 — What To Do**
Numbered action cards. Each card has an icon and specific action text. For DANGER: "Report to Cybercrime" card always appears at the top. For VERIFY: "Ask the Merchant" expandable section with question chips.

**Section 3 — Why (Agent Breakdown)**
Three expandable accordion cards — one per intelligence agent:
- Each shows the agent's name, model used (Featherless AI / AIML API), and narrative
- Price intelligence appears in Agent 3's card if available: shows market price range vs amount requested with a visual indicator

**Section 4 — Human Gate**
For VERIFY: Two buttons: "I'll Verify First" (primary) | "Proceed Anyway" (secondary/outlined)
For DANGER: Red warning box + text input where user must type "I UNDERSTAND THE RISK" before "Override" button becomes active

**Section 5 — Footer Actions**
"Share This Report" button (copies `/report/{txn_id}` URL to clipboard).
"Check Another Payment" button (goes back to home).

---

## Task 5: Page — ReportPage (src/pages/ReportPage.jsx)

Read-only shareable report. Route: `/report/:txn_id`

Same data as VerdictPage but without the human gate. Add a header banner: "PayGuard AI Analysis Report • {date}" with the Band room ID displayed. Clean, printable layout. Add a "Powered by PayGuard AI" footer with a link to the app.

---

## Task 6: Page — LibraryPage (src/pages/LibraryPage.jsx)

Scam pattern library. Route: `/library`

Load from `/home/gautham/Documents/personal-projects/band-hackathon/payguard/data/scam_patterns.json` (embed in bundle or serve via backend).

Grid of 6 scam pattern cards. Each card:
- Icon + scam type name
- 2-sentence description
- Expandable: red flag checklist + what to do list
- "Check a Payment" CTA button

Search/filter bar at top.

---

## Task 7: Page — HistoryPage (src/pages/HistoryPage.jsx)

Route: `/history`. Load from `GET /api/history`.

**Stats bar:** Total checks | ✅ Safe | ⚠️ Verify | 🚨 Danger | 💰 Fraud Avoided: ₹X

**Table/list of past checks** with columns: Date | Destination | Amount | Product | Verdict chip | Actions (view report)

Color-coded verdict chips.

---

## Task 8: Navigation (src/App.jsx)

```jsx
// Routes
/ → CheckPage
/analysis/:txn_id → AnalysisPage
/verdict/:txn_id → VerdictPage
/report/:txn_id → ReportPage
/library → LibraryPage
/history → HistoryPage
```

Top navigation bar: PayGuard AI logo/name (left) + nav links: "Check Payment" | "Scam Library" | "History" (right).

---

## Design Requirements (Non-Negotiable)

1. **Dark theme throughout** — `#0a0a0f` background
2. **Glassmorphism cards** — `backdrop-filter: blur(12px)`, semi-transparent backgrounds
3. **Smooth animations** — use `framer-motion` for page transitions, card reveals, progress updates
4. **Agent progress** — pulsing animation while an agent is running (CSS keyframes)
5. **Verdict reveal** — animate the risk score circle filling up (SVG strokeDashoffset animation)
6. **Mobile responsive** — all pages work on 375px width
7. **Loading states** — skeleton loaders, not spinners

---

## Completion Criteria
- [ ] `npm run dev` starts without errors
- [ ] CheckPage renders with all form sections, tab switcher, file upload
- [ ] AnalysisPage connects to SSE and updates agent cards in real time
- [ ] HITL question card appears and submits correctly
- [ ] VerdictPage shows verdict hero, agent breakdown, human gate
- [ ] Human gate for DANGER requires typing "I UNDERSTAND THE RISK"
- [ ] LibraryPage shows 6 scam pattern cards with expand/collapse
- [ ] HistoryPage loads and shows stats + past checks
- [ ] All pages are mobile responsive
- [ ] Design is premium — dark theme, glassmorphism, smooth animations
