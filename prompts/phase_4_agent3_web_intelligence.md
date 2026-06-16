# Phase 4 — Agent 3: Web Intelligence Agent

## Context
Phases 0–3 are complete. Agent 1 (Featherless AI) and Agent 2 (AIML API Vision) are working.
PRD: `/home/gautham/Documents/personal-projects/band-hackathon/PayGuard_AI_PRD_v3.md`

Agent 3 runs AFTER Agent 2 and reads both prior agents from Band. It does 6 things:
1. Website crawl (Playwright) + screenshot
2. Screenshot visual analysis (AIML API vision)
3. Web search for fraud complaints + official site (duckduckgo-search — free, no API key)
4. Reddit search for fraud mentions (PRAW — free)
5. Quora scrape for fraud questions (BeautifulSoup)
6. Price intelligence — is the amount reasonable for the product? (DDG + AIML API)

For UPI-only inputs (no URL): skip steps 1–2, run steps 3–6 only.

---

## Task 1: Build agents/agent3_web_intelligence.py

### Sub-function: crawl_website(url) -> dict
Use `playwright.async_api`. Launch headless Chromium. Navigate with 15s timeout. Take full-page screenshot (bytes). Extract `page.inner_text("body")` truncated to 3000 chars, page title, meta description. Detect presence of contact/about pages and GST number in text. On ANY error return `{"crawl_error": str, "screenshot_bytes": None}`. Never raise.

### Sub-function: analyze_screenshot(screenshot_bytes, url, band_context) -> dict
Send screenshot to AIML API vision (`gpt-4o`). Prompt the model to identify:
- Urgency manipulation (countdown timers, "limited time", "pay now")
- Excessive fake discounts (70%+ off claims)
- Missing trust signals (no contact, no about, no address, no GST)
- Brand impersonation (visual copy of known brands)
- Fake legitimacy badges ("NPCI verified", "RBI approved")
- Poor quality signals (spelling errors, broken images)

Include band_context so the model has Agent 1+2 findings. Return JSON: `{fraud_signals_detected: list, brand_impersonation: str|null, urgency_present: bool, trust_signals_present: bool, screenshot_narrative: str}`

### Sub-function: search_web_intelligence(domain, upi_id, product) -> dict
Use `duckduckgo_search.DDGS`. Run up to 4 searches with `max_results=5` each and `asyncio.sleep(1)` between them:
1. `"{domain}" scam OR fraud OR complaint`
2. `"{domain}" official site`
3. `"UPI {upi_id}" fraud OR scam`
4. `"{product}" price India` (only if product provided)

Return: `{fraud_complaints: list, official_site_results: list, upi_fraud_results: list, price_results: list}`

### Sub-function: search_reddit(query) -> list
Use PRAW (sync, run in `loop.run_in_executor`). Search `india+LegalAdviceIndia+personalfinanceindia+Scams`. Query = domain or upi_id. Sort=relevance, limit=10. Return list of `{title, subreddit, score, url, snippet}`. On any error return `[]`.

### Sub-function: scrape_quora(domain) -> list
HTTP GET `https://www.quora.com/search?q={domain}+scam` with browser-like User-Agent. Parse HTML with BeautifulSoup. Extract question titles and answer snippets from search results. Return list of `{question, snippet}` max 5. On error return `[]`.

### Sub-function: analyze_price_intelligence(product, amount, price_search_results, band_context) -> dict
Call AIML API (`gpt-4o`) with this context:
- Product being purchased and amount in INR
- Price search results from DDG
- Band room context (Agent 1+2 findings)

Ask the LLM to reason about: Is ₹{amount} reasonable for "{product}" in India? What is the typical market price range? Does this fit any fraud pricing pattern?

Fraud pricing patterns to reason about (tell the LLM about these, do NOT hardcode):
- Too low bait: impossibly cheap to lure victim
- Too high / fake invoice: inflated price
- Advance fee: small upfront payment for a promised large payment
- Round number under limit: ₹9,999 / ₹49,999 (deliberately under bank alert thresholds)
- Type mismatch: amount doesn't match product type (₹15,000 "shipping fee")

Return JSON: `{market_price_range: str|null, price_assessment: str, price_anomaly_type: str, price_narrative: str}`

### Sub-function: synthesize_all(all_findings, band_context) -> dict
Final AIML API call. Pass ALL collected evidence: crawl data, screenshot analysis, search results, Reddit/Quora findings, price intelligence, and the full Band room context. Ask LLM to synthesize a single coherent web intelligence risk narrative. Return JSON: `{web_risk_level: LOW|MEDIUM|HIGH, fraud_complaints_found: bool, complaint_sources: list, official_alternative_found: bool, official_site: str|null, page_fraud_signals: list, agent_narrative: str}`

### HITL trigger
If `crawl_error` is set (site unreachable), set `needs_clarification=True` and `clarification_question="The website appears to be down. Can you describe what you saw, or share a screenshot?"`. Publish HITL message to Band before returning.

### Main run() function
Assemble all sub-functions in order. Always publish complete output to Band room. Return `Agent3Output`.

---

## Task 2: tests/test_agent3.py

Four test cases:
1. Known suspicious domain (`razorpay-secure.co`) — expect `web_risk_level=HIGH`
2. Legitimate domain (`razorpay.com`) — expect `web_risk_level=LOW`
3. UPI only + low price for iPhone — expect `price_anomaly_type=too_low_bait`
4. UPI only + reasonable price for course subscription — expect `price_assessment=reasonable`

For each: create Band room, pre-populate with mock Agent 1+2 outputs, run agent3.run(), assert output structure, assert Band message published.

---

## Completion Criteria
- [ ] Playwright crawl works on a real URL
- [ ] AIML vision analyzes screenshot with structured output
- [ ] DDG search returns results without API key
- [ ] PRAW Reddit search returns posts
- [ ] Price intelligence flags a ₹5,000 iPhone as suspicious
- [ ] All findings synthesized into one coherent narrative
- [ ] Agent 3 publishes to Band room
- [ ] No hardcoded fraud rules — LLM decides
