"""
Agent 3 — Web Intelligence Agent
==================================
Power:   Playwright (headless Chromium) + duckduckgo-search (free, no key)
         + PRAW/Reddit (free) + BeautifulSoup + AIML API for final synthesis
Trigger: After Agent 2 publishes to the Band room.
Reads:   Agent 1 + Agent 2 full outputs from Band.
Scope:   Full pipeline for URL inputs; web-search only for UPI-only inputs.

Pipeline steps
--------------
Step 1 — Website Crawl (Playwright):
  - Navigate to URL, capture full-page screenshot.
  - Feed screenshot to AIML API vision: detect fraud signals (urgency language,
    fake timers, excessive discounts, missing contact info, mismatched branding).
  - Extract text: page title, about page, contact info, GST/company registration,
    reviews, pricing.

Step 2 — Web Search (duckduckgo-search):
  Four targeted DDG queries:
    1. "{domain}" scam OR fraud OR complaint
    2. "{domain}" official website  (impersonation check)
    3. "UPI {upi_id}" fraud OR scam
    4. "{product_description}" price India  (only if product field provided)

Step 3 — Reddit Search (PRAW):
  Subreddits: r/india, r/LegalAdviceIndia, r/personalfinanceindia, r/Scams
  Fetch top posts/comments mentioning the domain or UPI ID.

Step 4 — Quora Scrape (BeautifulSoup):
  HTTP scrape of Quora search for "{domain} scam".
  Extract question titles and visible answer snippets.

Step 5 — Price Intelligence (DDG + AIML API):
  Runs ONLY if product_description is provided.
  DDG searches for market prices → LLM reasons about whether the user's
  amount is normal, suspiciously low (bait), or suspiciously high (fake invoice).
  Anomaly types: too_low_bait | too_high | advance_fee | round_limit | type_mismatch

Step 6 — AIML API Final Synthesis:
  All evidence (screenshot, crawl text, search results, Reddit/Quora findings,
  price intelligence) passed to AIML reasoning model for a unified narrative.

HITL triggers:
  - Website unreachable.
  - Product description is vague and price anomaly is detected.

Band output schema
------------------
See api/models.py :: Agent3Output

Implemented in: Phase 3
"""

from __future__ import annotations

# TODO (Phase 3): Implement run() — orchestrate all 6 pipeline steps,
#                 synthesise evidence via AIML API, publish Agent3Output to Band.


async def run(
    txn_id: str,
    band_room_id: str,
    agent1_output: dict,
    agent2_output: dict,
    amount: float,
    product_description: str | None,
    source_type: str,
    additional_context: str,
) -> dict:
    """
    Entry point for Agent 3.

    Parameters
    ----------
    txn_id:              Unique transaction ID for this check session.
    band_room_id:        Band room identifier to publish results into.
    agent1_output:       Full Agent1Output dict read from the Band room.
    agent2_output:       Full Agent2Output dict read from the Band room.
    amount:              INR amount the user is about to pay.
    product_description: What the user says they are paying for (optional).
    source_type:         How the payment detail was received.
    additional_context:  Free-text notes from the user.

    Returns
    -------
    Agent3Output-compatible dict published to the Band room.
    """
    raise NotImplementedError("Agent 3 is implemented in Phase 3")
