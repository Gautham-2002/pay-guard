"""
Agent 3 — Web Intelligence Agent
==================================
Power:   Playwright (headless Chromium) + duckduckgo-search (free, no key)
         + PRAW/Reddit (free) + BeautifulSoup + AIML API for final synthesis
Trigger: After Agent 2 publishes to the Band room.

Pipeline steps
--------------
1. Website Crawl (Playwright) + screenshot  [skipped if no URL]
2. Screenshot visual analysis (AIML API vision)
3. Web search: DDG fraud complaints + official site + UPI fraud + price
4. Reddit search via PRAW
5. Quora scrape via BeautifulSoup
6. Price intelligence (DDG + AIML API)
7. Final synthesis (AIML API)

HITL: If crawl_error is set, ask user for description.

Band output schema: api/models.py :: Agent3Output
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, quote_plus

import httpx

from api.models import Agent3Output, PriceIntelligence, RiskLevel
from services.band_client import BandRoom
from services import aiml_client

logger = logging.getLogger(__name__)

# ─── JSON extraction helper ────────────────────────────────────────────────────


def _extract_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    stripped = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip().rstrip("`").strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        pass
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start: i + 1])
                    except (json.JSONDecodeError, TypeError):
                        break
    raise ValueError(f"Could not extract JSON: {raw[:300]}")


# ─── Step 1: Website Crawl ─────────────────────────────────────────────────────


async def crawl_website(url: str) -> dict:
    """
    Use Playwright to crawl the URL. Returns crawl data or crawl_error on failure.
    Never raises.
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                title = await page.title()

                # Extract text (truncated to 3000 chars)
                body_text = await page.inner_text("body")
                body_text = body_text[:3000]

                # Full-page screenshot as bytes
                screenshot_bytes = await page.screenshot(full_page=True)

                # Meta description
                meta_desc = await page.evaluate(
                    "document.querySelector('meta[name=\"description\"]')?.content || ''"
                )

                # Check for contact/about pages and GST in text
                text_lower = body_text.lower()
                has_contact = "contact" in text_lower
                has_about = "about" in text_lower
                has_gst = bool(re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b", body_text))

                await browser.close()
                return {
                    "url": url,
                    "title": title,
                    "meta_description": meta_desc,
                    "body_text": body_text,
                    "screenshot_bytes": screenshot_bytes,
                    "has_contact_page": has_contact,
                    "has_about_page": has_about,
                    "has_gst_number": has_gst,
                    "crawl_error": None,
                }
            except Exception as exc:
                await browser.close()
                raise exc
    except Exception as exc:
        logger.error("crawl_website error for %s: %s", url, exc)
        return {"crawl_error": str(exc), "screenshot_bytes": None, "url": url}


# ─── Step 2: Screenshot Visual Analysis ───────────────────────────────────────


async def analyze_screenshot(screenshot_bytes: bytes, url: str, band_context: str) -> dict:
    """
    Send screenshot to AIML API vision (gpt-4o) to detect fraud signals.
    Returns structured dict. Never raises — returns safe defaults on error.
    """
    prompt = f"""You are analyzing a website screenshot for payment fraud indicators.

URL: {url}

PRIOR AGENT FINDINGS (Band room context):
{band_context[:1500]}

YOUR TASKS — examine the screenshot and identify:
1. Urgency manipulation: countdown timers, "limited time", "pay now" pressure
2. Excessive fake discounts: 70%+ off claims, suspiciously low prices
3. Missing trust signals: no contact info, no about page, no address, no GST number
4. Brand impersonation: visual copy of known brands (Razorpay, Flipkart, Amazon, etc.)
5. Fake legitimacy badges: "NPCI verified", "RBI approved", "100% safe" etc.
6. Poor quality signals: spelling errors, broken images, amateurish design

Return ONLY valid JSON (no markdown, no prose):
{{
  "fraud_signals_detected": ["list of specific signals found"],
  "brand_impersonation": "brand name being impersonated or null",
  "urgency_present": true or false,
  "trust_signals_present": true or false,
  "screenshot_narrative": "2-3 sentence plain English description of what you see and any fraud concerns"
}}"""

    try:
        raw = await aiml_client.chat_vision(screenshot_bytes, prompt)
        return _extract_json(raw)
    except Exception as exc:
        logger.error("analyze_screenshot error: %s", exc)
        return {
            "fraud_signals_detected": [],
            "brand_impersonation": None,
            "urgency_present": False,
            "trust_signals_present": True,
            "screenshot_narrative": f"Screenshot analysis failed: {exc}",
        }


# ─── Step 3: DDG Web Search ────────────────────────────────────────────────────


async def search_web_intelligence(domain: str | None, upi_id: str | None, product: str | None) -> dict:
    """
    Run up to 4 DDG searches. Returns structured results dict.
    """
    from duckduckgo_search import DDGS  # type: ignore

    results = {
        "fraud_complaints": [],
        "official_site_results": [],
        "upi_fraud_results": [],
        "price_results": [],
    }

    def _ddg_search(query: str, max_results: int = 5) -> list:
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception as exc:
            logger.warning("DDG search failed for '%s': %s", query, exc)
            return []

    loop = asyncio.get_event_loop()

    if domain:
        r1 = await loop.run_in_executor(None, _ddg_search, f'"{domain}" scam OR fraud OR complaint')
        results["fraud_complaints"] = r1
        await asyncio.sleep(1)

        r2 = await loop.run_in_executor(None, _ddg_search, f'"{domain}" official site')
        results["official_site_results"] = r2
        await asyncio.sleep(1)

    if upi_id:
        r3 = await loop.run_in_executor(None, _ddg_search, f'"UPI {upi_id}" fraud OR scam')
        results["upi_fraud_results"] = r3
        await asyncio.sleep(1)

    if product:
        r4 = await loop.run_in_executor(None, _ddg_search, f'"{product}" price India')
        results["price_results"] = r4

    return results


# ─── Step 4: Reddit Search ─────────────────────────────────────────────────────


async def search_reddit(query: str) -> list:
    """
    Search Reddit via PRAW (sync, run in executor).
    Returns list of {title, subreddit, score, url, snippet}.
    """
    def _reddit_search():
        try:
            import praw  # type: ignore
            import os

            reddit = praw.Reddit(
                client_id=os.getenv("REDDIT_CLIENT_ID", ""),
                client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
                user_agent="PayGuard:v1.0 (by /u/payguard_bot)",
            )
            subreddits = "india+LegalAdviceIndia+personalfinanceindia+Scams"
            submissions = reddit.subreddit(subreddits).search(
                query, sort="relevance", limit=10
            )
            posts = []
            for s in submissions:
                posts.append({
                    "title": s.title,
                    "subreddit": str(s.subreddit),
                    "score": s.score,
                    "url": s.url,
                    "snippet": (s.selftext or "")[:300],
                })
            return posts
        except Exception as exc:
            logger.warning("Reddit search failed for '%s': %s", query, exc)
            return []

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _reddit_search)


# ─── Step 5: Quora Scrape ──────────────────────────────────────────────────────


async def scrape_quora(domain: str) -> list:
    """
    HTTP GET Quora search for '{domain} scam'. Parse with BeautifulSoup.
    Returns list of {question, snippet}, max 5.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore

        search_url = f"https://www.quora.com/search?q={quote_plus(domain + ' scam')}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(search_url, headers=headers)

        soup = BeautifulSoup(resp.text, "lxml")
        results = []

        # Quora search result question titles
        question_elements = soup.select(".q-box span") or soup.find_all("span", class_=re.compile("question"))
        for el in question_elements[:10]:
            text = el.get_text(strip=True)
            if len(text) > 20 and "?" in text:
                results.append({"question": text, "snippet": ""})
            if len(results) >= 5:
                break

        # Fallback: grab any paragraph text mentioning scam/fraud
        if not results:
            for tag in soup.find_all(["h2", "h3", "p"])[:20]:
                text = tag.get_text(strip=True)
                if len(text) > 20 and any(w in text.lower() for w in ["scam", "fraud", "cheat"]):
                    results.append({"question": text[:200], "snippet": ""})
                if len(results) >= 5:
                    break

        return results[:5]
    except Exception as exc:
        logger.warning("scrape_quora error for '%s': %s", domain, exc)
        return []


# ─── Step 6: Price Intelligence ────────────────────────────────────────────────


async def analyze_price_intelligence(
    product: str,
    amount: float,
    price_search_results: list,
    band_context: str,
) -> dict:
    """
    Use AIML API (gpt-4o) to reason about price anomalies for the given product/amount.
    """
    price_snippets = "\n".join(
        f"- {r.get('title', '')}: {r.get('body', r.get('snippet', ''))[:200]}"
        for r in price_search_results[:5]
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are Agent 3 in PayGuard AI, an Indian pre-payment fraud detection system. "
                "You reason about price anomalies as a skilled fraud analyst. "
                "You MUST output ONLY valid JSON — no markdown, no code fences."
            ),
        },
        {
            "role": "user",
            "content": f"""Analyze whether ₹{amount} is a reasonable price for "{product}" in India.

MARKET PRICE SEARCH RESULTS:
{price_snippets if price_snippets else "No price data found."}

PRIOR AGENT FINDINGS:
{band_context[:800]}

FRAUD PRICING PATTERNS to reason about (do NOT apply as rigid rules — reason holistically):
- Too low bait: impossibly cheap price to lure victim
- Too high / fake invoice: inflated price far above market
- Advance fee: small upfront for a promised large payout
- Round number under limit: ₹9,999 / ₹49,999 (deliberately below bank alert thresholds)
- Type mismatch: amount doesn't match the product type (e.g. ₹15,000 "shipping fee")

Based on your knowledge of Indian market prices and the search results, assess the price.

Return ONLY valid JSON:
{{
  "market_price_range": "estimated range in INR or null if unknown",
  "price_assessment": "reasonable | suspicious | unknown",
  "price_anomaly_type": "too_low_bait | too_high | advance_fee | round_limit | type_mismatch | none",
  "price_narrative": "2-3 sentences explaining your price reasoning"
}}""",
        },
    ]

    try:
        raw = await aiml_client.chat_text(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.15,
            max_tokens=1024,
        )
        return _extract_json(raw)
    except Exception as exc:
        logger.error("analyze_price_intelligence error: %s", exc)
        return {
            "market_price_range": None,
            "price_assessment": "unknown",
            "price_anomaly_type": "none",
            "price_narrative": f"Price analysis encountered a technical error: {exc}",
        }


# ─── Step 7: Final Synthesis ───────────────────────────────────────────────────


async def synthesize_all(all_findings: dict, band_context: str) -> dict:
    """
    Final AIML API call — synthesize all evidence into one coherent risk narrative.
    """
    findings_str = json.dumps(all_findings, ensure_ascii=False, indent=2)[:4000]

    messages = [
        {
            "role": "system",
            "content": (
                "You are Agent 3 in PayGuard AI, an Indian pre-payment fraud detection system. "
                "You synthesize all web intelligence evidence into a final risk assessment. "
                "You do NOT apply hardcoded rules — you reason holistically. "
                "You MUST output ONLY valid JSON."
            ),
        },
        {
            "role": "user",
            "content": f"""You have completed a full web intelligence investigation on a payment. Synthesize ALL evidence below.

=== BAND ROOM CONTEXT (Agent 1 + Agent 2 findings) ===
{band_context[:1200]}

=== WEB INTELLIGENCE FINDINGS ===
{findings_str}

Based on ALL the evidence (crawl data, screenshot analysis, DDG search, Reddit, Quora, price intelligence, and prior agents), provide a final unified risk assessment.

Return ONLY valid JSON:
{{
  "web_risk_level": "LOW" or "MEDIUM" or "HIGH",
  "fraud_complaints_found": true or false,
  "complaint_sources": ["list of source names where complaints were found, e.g. Reddit, DDG, Quora"],
  "official_alternative_found": true or false,
  "official_site": "URL of official site if found, or null",
  "page_fraud_signals": ["list of specific fraud signals detected on the page"],
  "agent_narrative": "4-5 sentences. Be specific. Reference actual evidence found. India-context language."
}}""",
        },
    ]

    try:
        raw = await aiml_client.chat_text(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.15,
            max_tokens=2048,
        )
        return _extract_json(raw)
    except Exception as exc:
        logger.error("synthesize_all error: %s", exc)
        return {
            "web_risk_level": "MEDIUM",
            "fraud_complaints_found": False,
            "complaint_sources": [],
            "official_alternative_found": False,
            "official_site": None,
            "page_fraud_signals": [],
            "agent_narrative": f"Web intelligence synthesis failed due to a technical error: {exc}. Manual review recommended.",
        }


# ─── Agent Entry Point ─────────────────────────────────────────────────────────


async def run(
    band_room: BandRoom,
    url: str | None = None,
    upi_id: str | None = None,
    amount: float | None = None,
    product_description: str | None = None,
    source_type: str | None = None,
    additional_context: str | None = None,
) -> Agent3Output:
    """
    Agent 3 — Web Intelligence Agent.

    Flow
    ----
    1. Read Agent 1 + 2 context from Band room.
    2. If URL provided: crawl website, analyze screenshot.
    3. DDG web search (fraud complaints, official site, UPI fraud, price).
    4. Reddit PRAW search.
    5. Quora scrape.
    6. Price intelligence (if product_description provided).
    7. Synthesize all findings via AIML API.
    8. HITL if crawl failed.
    9. Publish Agent3Output to Band room.
    10. Return Agent3Output.
    """
    logger.info(
        "Agent 3 starting | url=%s | upi_id=%s | amount=₹%s | product=%s",
        url, upi_id, amount, product_description,
    )

    # ── Step 1: Get full Band context ──────────────────────────────────────────
    band_context = await band_room.get_full_context()
    logger.info("Agent 3: read Band context (%d chars)", len(band_context))

    # Extract domain from URL if present
    domain: str | None = None
    if url:
        try:
            domain = urlparse(url).netloc or url
        except Exception:
            domain = url

    # ── Step 2: Website Crawl (if URL provided) ────────────────────────────────
    crawl_data: dict = {}
    screenshot_bytes: bytes | None = None
    website_crawled = False

    if url:
        logger.info("Agent 3: crawling website %s ...", url)
        crawl_data = await crawl_website(url)
        screenshot_bytes = crawl_data.get("screenshot_bytes")
        if not crawl_data.get("crawl_error"):
            website_crawled = True
            logger.info(
                "Agent 3: crawl success — title='%s' has_gst=%s",
                crawl_data.get("title"), crawl_data.get("has_gst_number"),
            )
        else:
            logger.warning("Agent 3: crawl failed — %s", crawl_data.get("crawl_error"))

    # ── Step 2b: Screenshot Analysis ──────────────────────────────────────────
    screenshot_result: dict = {}
    if screenshot_bytes and url:
        logger.info("Agent 3: analyzing screenshot via AIML vision...")
        screenshot_result = await analyze_screenshot(screenshot_bytes, url, band_context)
        logger.info(
            "Agent 3: screenshot analysis — urgency=%s brand_impersonation=%s",
            screenshot_result.get("urgency_present"),
            screenshot_result.get("brand_impersonation"),
        )

    # ── Step 3: DDG Web Search ─────────────────────────────────────────────────
    logger.info("Agent 3: running DDG web intelligence searches...")
    search_results = await search_web_intelligence(domain, upi_id, product_description)
    logger.info(
        "Agent 3: DDG search complete — fraud_complaints=%d price_results=%d",
        len(search_results.get("fraud_complaints", [])),
        len(search_results.get("price_results", [])),
    )

    # ── Step 4: Reddit Search ──────────────────────────────────────────────────
    reddit_query = domain or upi_id or (product_description or "")
    reddit_results: list = []
    if reddit_query:
        logger.info("Agent 3: searching Reddit for '%s'...", reddit_query[:60])
        reddit_results = await search_reddit(reddit_query)
        logger.info("Agent 3: Reddit returned %d posts", len(reddit_results))

    # ── Step 5: Quora Scrape ───────────────────────────────────────────────────
    quora_results: list = []
    if domain:
        logger.info("Agent 3: scraping Quora for '%s scam'...", domain)
        quora_results = await scrape_quora(domain)
        logger.info("Agent 3: Quora returned %d results", len(quora_results))

    # ── Step 6: Price Intelligence ─────────────────────────────────────────────
    price_data: dict | None = None
    if product_description and amount is not None:
        logger.info("Agent 3: running price intelligence for '%s' at ₹%s...", product_description, amount)
        price_data = await analyze_price_intelligence(
            product=product_description,
            amount=amount,
            price_search_results=search_results.get("price_results", []),
            band_context=band_context,
        )
        logger.info(
            "Agent 3: price intelligence — assessment=%s anomaly=%s",
            price_data.get("price_assessment"),
            price_data.get("price_anomaly_type"),
        )

    # ── Step 7: Final Synthesis ────────────────────────────────────────────────
    all_findings = {
        "crawl_data": {
            k: v for k, v in crawl_data.items()
            if k != "screenshot_bytes"  # bytes not JSON-serialisable
        },
        "screenshot_analysis": screenshot_result,
        "search_results": {
            "fraud_complaints": search_results.get("fraud_complaints", [])[:5],
            "official_site_results": search_results.get("official_site_results", [])[:5],
            "upi_fraud_results": search_results.get("upi_fraud_results", [])[:5],
            "price_results": search_results.get("price_results", [])[:5],
        },
        "reddit_findings": reddit_results[:5],
        "quora_findings": quora_results,
        "price_intelligence": price_data,
    }

    logger.info("Agent 3: synthesizing all findings via AIML API...")
    synthesis = await synthesize_all(all_findings, band_context)
    logger.info(
        "Agent 3: synthesis complete — web_risk_level=%s fraud_complaints_found=%s",
        synthesis.get("web_risk_level"),
        synthesis.get("fraud_complaints_found"),
    )

    # ── HITL Trigger ───────────────────────────────────────────────────────────
    needs_clarification = False
    clarification_question = None

    if crawl_data.get("crawl_error") and url:
        needs_clarification = True
        clarification_question = (
            "The website appears to be down or unreachable. "
            "Can you describe what you saw on the site, or share a screenshot?"
        )
        logger.info("Agent 3: HITL triggered — site unreachable, publishing clarification...")
        hitl_message = {
            "type": "needs_clarification",
            "from_agent": "web_intelligence",
            "sequence": 3,
            "question": clarification_question,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await band_room.publish(hitl_message)

    # ── Build Agent3Output ─────────────────────────────────────────────────────
    reddit_mentions = [
        f"r/{r.get('subreddit')}: {r.get('title', '')[:100]}"
        for r in reddit_results[:5]
    ]

    price_intelligence_obj: PriceIntelligence | None = None
    if price_data and product_description and amount is not None:
        price_intelligence_obj = PriceIntelligence(
            product_described=product_description,
            amount_requested=amount,
            market_price_range=price_data.get("market_price_range"),
            price_anomaly_type=price_data.get("price_anomaly_type"),
            price_narrative=price_data.get("price_narrative", ""),
        )

    # Resolve risk level safely
    raw_risk = (synthesis.get("web_risk_level") or "MEDIUM").upper()
    try:
        web_risk_level = RiskLevel(raw_risk)
    except ValueError:
        web_risk_level = RiskLevel.MEDIUM

    output = Agent3Output(
        website_crawled=website_crawled,
        screenshot_analysis=screenshot_result.get("screenshot_narrative"),
        page_fraud_signals=synthesis.get("page_fraud_signals", [])
            + screenshot_result.get("fraud_signals_detected", []),
        fraud_complaints_found=bool(synthesis.get("fraud_complaints_found", False)),
        complaint_sources=synthesis.get("complaint_sources", []),
        official_alternative_found=bool(synthesis.get("official_alternative_found", False)),
        official_site=synthesis.get("official_site"),
        reddit_mentions=reddit_mentions,
        price_intelligence=price_intelligence_obj,
        web_risk_level=web_risk_level,
        agent_narrative=synthesis.get("agent_narrative", ""),
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(
        "Agent 3 complete | web_risk=%s | fraud_complaints=%s | price_anomaly=%s",
        output.web_risk_level,
        output.fraud_complaints_found,
        output.price_intelligence.price_anomaly_type if output.price_intelligence else "N/A",
    )

    # ── Publish to Band ────────────────────────────────────────────────────────
    await band_room.publish(output.model_dump())
    logger.info("Agent 3: published result to Band room '%s'", band_room.name)

    return output
