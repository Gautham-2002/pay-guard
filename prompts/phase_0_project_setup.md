# Phase 0 — Project Foundation & Setup

## Context
You are building **PayGuard AI** — a pre-payment fraud intelligence system for the Band of Agents Hackathon (lablab.ai, June 2026). It uses 4 AI agents coordinated through Band to analyze payment destinations (UPI ID, URL, QR code) before a user pays, detecting fraud and social engineering.

The full PRD is at: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md` — read it before starting.

This is Phase 0. Nothing has been built yet. Your job is to scaffold the entire project structure, install all dependencies, and verify every external API connection works.

---

## Task: Create the Complete Project Structure

Create the following folder and file structure inside `/home/gautham/Documents/personal-projects/band-hackathon/payguard/`:

```
payguard/
├── agents/
│   ├── __init__.py
│   ├── agent1_destination.py       # (empty stub with docstring)
│   ├── agent2_qr_upi.py            # (empty stub)
│   ├── agent3_web_intelligence.py  # (empty stub)
│   └── agent4_verdict.py           # (empty stub)
├── services/
│   ├── __init__.py
│   ├── band_client.py              # (empty stub)
│   ├── featherless_client.py       # (empty stub)
│   ├── aiml_client.py              # (empty stub)
│   ├── domain_intel.py             # (empty stub)
│   └── qr_handler.py              # (empty stub)
├── api/
│   ├── __init__.py
│   ├── main.py                     # (empty stub)
│   ├── models.py                   # (Pydantic models — build this now)
│   └── routes/
│       ├── __init__.py
│       ├── check.py                # (empty stub)
│       ├── report.py               # (empty stub)
│       └── history.py              # (empty stub)
├── data/
│   ├── scam_patterns.json          # (build this now — see below)
│   └── demo_cache.json             # (empty JSON object {})
├── tests/
│   ├── __init__.py
│   └── test_connections.py         # (build this now — see below)
├── frontend/                       # (empty, built in Phase 7)
├── .env.example                    # (build this now)
├── .env                            # (NOT committed — user fills in keys)
├── .gitignore
├── requirements.txt                # (build this now)
└── README.md                       # (minimal, build this now)
```

---

## Task 1: requirements.txt

```txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
httpx==0.27.0
openai>=1.35.0
python-dotenv==1.0.0
python-multipart==0.0.9
sqlalchemy==2.0.0
aiosqlite==0.20.0
ratelimit==2.2.1
playwright==1.44.0
duckduckgo-search==6.1.7
praw==7.7.1
beautifulsoup4==4.12.3
lxml==5.2.2
Levenshtein==0.25.1
pillow==10.3.0
python-jose[cryptography]==3.3.0
sse-starlette==2.1.0
```

After creating requirements.txt, run:
```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Task 2: .env.example

```bash
# Band
BAND_API_KEY=your_band_api_key_here

# Featherless AI (OpenAI-compatible, base_url = https://api.featherless.ai/v1)
FEATHERLESS_API_KEY=your_featherless_key_here

# AIML API (OpenAI-compatible, base_url = https://api.aimlapi.com/v2)
AIML_API_KEY=your_aiml_key_here

# Domain Intelligence
VIRUSTOTAL_API_KEY=your_virustotal_key_here
GOOGLE_SAFE_BROWSING_KEY=your_gsb_key_here
WHOISJSON_KEY=your_whoisjson_key_here

# Reddit (PRAW) — register app at reddit.com/prefs/apps
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=PayGuardAI/1.0 by /u/your_username

# App
DATABASE_URL=sqlite+aiosqlite:///./payguard.db
SECRET_KEY=generate_a_random_32_char_string_here
APP_PORT=8000
```

---

## Task 3: api/models.py — Pydantic Schemas

Build all request/response models:

```python
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

class SourceType(str, Enum):
    whatsapp_unknown = "whatsapp_unknown"
    whatsapp_known = "whatsapp_known"
    website = "website"
    sms = "sms"
    email = "email"
    in_person = "in_person"
    olx_marketplace = "olx_marketplace"
    social_media = "social_media"
    other = "other"

class VerdictLevel(str, Enum):
    SAFE = "SAFE"
    VERIFY = "VERIFY"
    DANGER = "DANGER"

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class CheckRequest(BaseModel):
    payment_url: Optional[str] = None
    upi_id: Optional[str] = None
    amount: float
    product_description: Optional[str] = None   # NEW: "What are you paying for?"
    source_type: SourceType
    additional_context: Optional[str] = ""
    # qr_image is handled as UploadFile in the route, not here

class PriceIntelligence(BaseModel):
    product_described: str
    amount_requested: float
    market_price_range: Optional[str] = None
    price_anomaly_type: Optional[str] = None   # too_low_bait | too_high | advance_fee | round_limit | type_mismatch | none
    price_narrative: str

class Agent1Output(BaseModel):
    agent: str = "destination_intelligence"
    sequence: int = 1
    destination_type: str   # UPI_ID | URL | BOTH
    upi_id: Optional[str] = None
    upi_psp: Optional[str] = None
    risk_level: RiskLevel
    top_signals: List[str]
    agent_narrative: str
    raw_evidence: dict
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    timestamp: str

class Agent2Output(BaseModel):
    agent: str = "qr_upi_validator"
    sequence: int = 2
    decoded_upi_id: Optional[str] = None
    payee_name_from_qr: Optional[str] = None
    prefilled_amount: Optional[float] = None
    upi_context_mismatch: bool = False
    refund_scam_indicator: bool = False
    visual_context: Optional[str] = None
    social_engineering_pattern: Optional[str] = None
    manipulation_signals: List[str] = []
    agent_narrative: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    timestamp: str

class Agent3Output(BaseModel):
    agent: str = "web_intelligence"
    sequence: int = 3
    website_crawled: bool = False
    screenshot_analysis: Optional[str] = None
    page_fraud_signals: List[str] = []
    fraud_complaints_found: bool = False
    complaint_sources: List[str] = []
    official_alternative_found: bool = False
    official_site: Optional[str] = None
    reddit_mentions: List[str] = []
    price_intelligence: Optional[PriceIntelligence] = None
    web_risk_level: RiskLevel
    agent_narrative: str
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    timestamp: str

class Agent4Output(BaseModel):
    agent: str = "verdict_synthesis"
    sequence: int = 4
    verdict: VerdictLevel
    risk_score: int   # 0-100
    plain_english_summary: str
    recommended_actions: List[str]
    ask_merchant: List[str] = []
    agent_agreement: str  # ALL_AGREE | PARTIAL_CONFLICT | FULL_CONFLICT
    conflict_resolution: Optional[str] = None
    avoided_fraud_estimate: Optional[str] = None
    band_room_id: str
    timestamp: str

class HITLMessage(BaseModel):
    type: str = "human_response"
    question_from_agent: str
    human_answer: str
    timestamp: str

class CheckResponse(BaseModel):
    txn_id: str
    band_room_id: str
    verdict: VerdictLevel
    risk_score: int
    plain_english_summary: str
    recommended_actions: List[str]
    ask_merchant: List[str]
    agent_narratives: dict
    price_intelligence: Optional[PriceIntelligence] = None
    report_url: str

class CheckStatus(BaseModel):
    txn_id: str
    status: str   # agent_1_running | agent_2_running | agent_3_running | hitl_waiting | agent_4_running | complete
    current_agent: Optional[str] = None
    hitl_question: Optional[str] = None
    result: Optional[CheckResponse] = None
```

---

## Task 4: data/scam_patterns.json

Create a JSON file with 6 scam pattern objects, each with these fields:
- `id`: slug string
- `name`: display name
- `description`: 2-sentence description
- `red_flags`: list of 4-5 red flag strings
- `what_to_do`: list of 3-4 action strings
- `example`: one real example string

Cover these patterns:
1. QR Refund Scam
2. OLX Buyer Scam
3. Fake Customer Support
4. Advance Fee / Job Offer Scam
5. Fake Lottery / Prize
6. Fake E-commerce / Too Good To Be True Deal

---

## Task 5: tests/test_connections.py

Write a test file that verifies all external API connections work. Each test should be independent and clearly report pass/fail. Tests:

1. `test_featherless_connection()` — make a simple chat completion call to `meta-llama/Llama-3.3-70B-Instruct` via Featherless. Prompt: "Reply with JSON: {status: 'ok'}". Assert response contains "ok".

2. `test_aiml_connection()` — make a simple chat completion to `gpt-4o` via AIML API. Same prompt. Assert response.

3. `test_virustotal_connection()` — call VT API to check `google.com`. Assert HTTP 200.

4. `test_safe_browsing_connection()` — call GSB API for `google.com`. Assert HTTP 200.

5. `test_whoisjson_connection()` — call WhoisJSON for `google.com`. Assert HTTP 200 and `created` field in response.

6. `test_duckduckgo_search()` — run `ddgs.text("site:google.com", max_results=3)`. Assert at least 1 result.

7. `test_reddit_connection()` — connect PRAW and search r/india for "payment". Assert at least 1 result.

8. `test_playwright_browser()` — launch headless Chromium, navigate to `https://example.com`, take screenshot, assert screenshot bytes > 0.

Run each test, print PASS/FAIL, and at the end print a summary. Use `asyncio.run()` for async tests.

---

## Task 6: .gitignore

```
.env
*.db
__pycache__/
*.pyc
.playwright/
node_modules/
frontend/dist/
*.png
*.jpg
*.jpeg
data/demo_cache.json
```

---

## Completion Criteria

You are done when:
- [ ] All folders and files exist at the correct paths
- [ ] `pip install -r requirements.txt` completes without errors
- [ ] `playwright install chromium` completes
- [ ] `python tests/test_connections.py` runs and reports clearly for each API
- [ ] `data/scam_patterns.json` has 6 complete scam pattern objects
- [ ] `api/models.py` has all Pydantic models with no import errors (`python -c "from api.models import *"` passes)

Do NOT implement any agent logic yet — only stubs with docstrings. That begins in Phase 1.
