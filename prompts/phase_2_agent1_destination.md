# Phase 2 — Agent 1: Destination Intelligence (Featherless AI)

## Context

You are building **PayGuard AI**. Phases 0 and 1 are complete:

- Project structure exists at `/home/gautham/Documents/personal-projects/band-hackathon/payguard/`
- `services/band_client.py` is complete and tested
- All Pydantic models are in `api/models.py`

The full PRD is at: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

**Agent 1** is the first agent in the sequential pipeline. It:

1. Collects raw signals about the payment destination (URL or UPI ID) from external APIs
2. Sends ALL raw data to **Featherless AI** (Llama 3.3 70B) as context
3. The LLM reasons holistically and returns a structured risk assessment
4. Publishes the result to the Band room

**Critical rule: No hardcoded scoring. No if/else thresholds. The LLM decides everything.**

---

## Task 1: Build services/domain_intel.py

This module collects raw data. It makes NO decisions — just fetches and returns raw API responses.

```python
import httpx, asyncio, ssl, os
from datetime import datetime

VT_KEY = os.getenv("VIRUSTOTAL_API_KEY")
GSB_KEY = os.getenv("GOOGLE_SAFE_BROWSING_KEY")
WJ_KEY = os.getenv("WHOISJSON_KEY")

async def fetch_virustotal_url(url: str, client: httpx.AsyncClient) -> dict:
    """
    Submit URL to VirusTotal for scanning.
    Returns: {malicious: int, suspicious: int, harmless: int, undetected: int, analysis_id: str}
    Rate limit: 4 req/min — caller must handle this.
    Docs: https://docs.virustotal.com/reference/scan-url
    """

async def fetch_virustotal_domain(domain: str, client: httpx.AsyncClient) -> dict:
    """
    Get domain report from VirusTotal.
    Returns: {reputation: int, categories: dict, last_analysis_stats: dict}
    Docs: https://docs.virustotal.com/reference/domain-info
    """

async def fetch_whois(domain: str, client: httpx.AsyncClient) -> dict:
    """
    Fetch WHOIS data for domain.
    Returns: {age_days: int, registrar: str, country: str, created: str, expires: str}
    API: https://whoisjson.com/free-domain-api
    Handle missing/null dates gracefully — return age_days: -1 if unknown.
    """

async def fetch_safe_browsing(url: str, client: httpx.AsyncClient) -> dict:
    """
    Check URL against Google Safe Browsing v4.
    Returns: {is_dangerous: bool, threat_types: list[str]}
    API: https://safebrowsing.googleapis.com/v4/threatMatches:find
    """

async def fetch_ssl_info(domain: str) -> dict:
    """
    Check SSL certificate using Python ssl module (no external API).
    Returns: {valid: bool, issuer: str, expires: str, age_days: int, is_self_signed: bool}
    If SSL fails entirely, return {valid: false, error: str}
    """

async def analyze_upi_vpa(upi_id: str) -> dict:
    """
    Parse UPI Virtual Payment Address. No external API — pure analysis.
    VPA format: username@psp
    Returns: {
        username: str,
        psp: str,
        psp_is_known: bool,  # check against known PSPs list
        psp_type: str,       # bank_psp | wallet_psp | unknown
        username_pattern: str,  # looks_personal | looks_merchant | random_string | unknown
        raw_vpa: str
    }
    Known PSPs: okaxis, oksbi, okhdfcbank, okicici, paytm, ybl, apl, ibl,
                upi, axl, sbi, cnrb, barodampay, jupiteraxis, fbl, rbl,
                timecosmos, ikwik, pingpay, myyes, yesbank, aubank,
                kotak, hsbc, citibank, dbs, postbank
    """

async def collect_all_signals(url: str = None, upi_id: str = None) -> dict:
    """
    Main entry point. Collects all available signals.
    If URL: fetch WHOIS, VT URL scan, VT domain report, GSB, SSL.
    If UPI ID: analyze VPA structure only (no domain APIs).
    If both: fetch all.
    Returns a unified dict with all raw evidence.
    """
```

---

## Task 2: Build services/featherless_client.py

```python
from openai import AsyncOpenAI
import os

featherless = AsyncOpenAI(
    api_key=os.getenv("FEATHERLESS_API_KEY"),
    base_url="https://api.featherless.ai/v1"
)

PRIMARY_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
FALLBACK_MODEL = "Qwen/Qwen2.5-72B-Instruct"

async def chat(messages: list[dict], response_format: dict = None, model: str = PRIMARY_MODEL) -> str:
    """
    Make a chat completion call to Featherless AI.
    - Always use response_format={"type": "json_object"} for structured outputs
    - On failure with PRIMARY_MODEL, retry once with FALLBACK_MODEL
    - On JSON parse failure, retry once with an explicit schema reminder appended to the prompt
    - Returns the raw string content of the response
    """
```

---

## Task 3: Build agents/agent1_destination.py

This is the full Agent 1 implementation.

```python
async def run(
    band_room: BandRoom,
    url: str = None,
    upi_id: str = None,
    amount: float = None,
    product_description: str = None,
    source_type: str = None,
    additional_context: str = None
) -> Agent1Output:
    """
    Agent 1 — Destination Intelligence.

    Flow:
    1. Collect raw signals via services/domain_intel.py
    2. Build a detailed LLM prompt with all raw evidence as context
    3. Call Featherless AI (Llama 3.3 70B) with the prompt
    4. Parse the LLM JSON response into Agent1Output
    5. Publish to Band room
    6. Return Agent1Output
    """
```

### The Featherless LLM Prompt (build this carefully)

The prompt must provide:

- All raw evidence as structured context
- Clear instructions on what to reason about
- The output JSON schema
- Explicit instruction: "Do not apply rules or thresholds. Reason about why this specific combination of signals is or is not suspicious."

Template structure:

```
You are Agent 1 in PayGuard AI, a pre-payment fraud detection system used in India.
Your role: analyze the payment destination and produce a risk assessment.

PAYMENT DESTINATION: {url or upi_id}
TYPE: {URL | UPI_ID}
AMOUNT BEING PAID: ₹{amount}
PRODUCT/SERVICE: {product_description or "Not specified"}
SOURCE: {source_type}
USER CONTEXT: {additional_context}

=== RAW EVIDENCE COLLECTED ===
{json.dumps(raw_evidence, indent=2)}

=== YOUR ANALYSIS TASK ===
Reason holistically about whether this payment destination is likely fraudulent.

Consider:
1. What does the combination of signals tell you — even if individually weak?
2. For URLs: does the domain age, SSL, and threat data paint a consistent picture?
3. For UPI IDs: does the VPA structure suggest a legitimate merchant or an individual/random account?
4. What would a sophisticated fraudster do to appear legitimate — and are those patterns visible here?
5. Are there signals that contradict each other (e.g., old domain but new SSL cert)?

India-specific context:
- Legitimate UPI merchant accounts typically use PSPs like paytm, razorpay, okaxis, oksbi
- Random-looking usernames in UPI IDs (e.g., "xkvb7722@ybl") are individual accounts, not merchants
- Domains registered < 30 days ago + payment context = very high fraud risk
- Even 1-2 VirusTotal malicious votes on a payment URL is significant

Output JSON with EXACTLY these keys:
{
  "risk_level": "LOW" or "MEDIUM" or "HIGH",
  "top_signals": ["2 to 4 specific findings as short strings"],
  "agent_narrative": "3-4 sentences of plain English reasoning. Be specific. Name exact values (e.g., 'domain is 3 days old'). India-appropriate language.",
  "confidence": 0.0 to 1.0,
  "needs_clarification": false,
  "clarification_question": null
}
```

---

## Task 4: Write tests/test_agent1.py

Test with real API calls using these scenarios:

```python
TEST_CASES = [
    {
        "name": "Legitimate domain",
        "url": "https://razorpay.com",
        "upi_id": None,
        "amount": 500,
        "expected_risk": "LOW",
    },
    {
        "name": "Suspicious lookalike domain",
        "url": "https://razorpay-secure.co",
        "upi_id": None,
        "amount": 9999,
        "expected_risk": "HIGH",
    },
    {
        "name": "Legitimate UPI handle",
        "url": None,
        "upi_id": "merchant@razorpay",
        "amount": 1200,
        "expected_risk": "LOW",
    },
    {
        "name": "Suspicious individual UPI",
        "url": None,
        "upi_id": "xkvb7722@ybl",
        "amount": 15000,
        "expected_risk": "MEDIUM or HIGH",
    },
]
```

For each test:

1. Create a Band room
2. Run agent1.run() with the test inputs
3. Assert `risk_level` is not None
4. Assert `agent_narrative` is a non-empty string with > 50 characters
5. Assert `top_signals` has at least 1 item
6. Assert the message was published to the Band room (call `room.get_messages()` and check)
7. Print the full agent output for manual review

---

## Completion Criteria

- [ ] `services/domain_intel.py` — all 6 functions implemented, handles errors gracefully (never raises, returns error dict instead)
- [ ] `services/featherless_client.py` — working with PRIMARY and FALLBACK model retry logic
- [ ] `agents/agent1_destination.py` — full implementation, publishes to Band
- [ ] `python tests/test_agent1.py` — all 4 scenarios produce a structured output and publish to Band
- [ ] The Featherless LLM prompt results in valid JSON every time (test this by running 3 times)
- [ ] No hardcoded thresholds anywhere in the agent
