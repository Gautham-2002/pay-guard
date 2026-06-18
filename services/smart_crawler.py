"""
Smart URL Resolver
==================
Classifies any submitted URL and decides the optimal crawl target for
Agent 3 — Web Intelligence.

Problem
-------
When a user submits a social media profile URL (e.g. Instagram, Facebook),
checking the *domain age* of instagram.com is meaningless. What matters is:
  1. Does the profile/post link to an actual product or store URL?
     → Crawl THAT URL for domain intel.
  2. If no product URL found, read the post captions and comments for
     fraud signals instead.

This module implements a generic decision tree — not hardcoded for Instagram
only — that works for any platform type.

Platform classification
-----------------------
The classification is LLM-driven (one fast AIML call) so it works for
new and niche platforms without code changes. Broad categories:

  direct_product       : Already a product/store/service page. Crawl as-is.
  marketplace_listing  : OLX, Meesho, Flipkart, etc. Crawl as-is.
  aggregator           : Linktree, bio.link, etc. Crawl as-is (many links).
  social_media_profile : Profile page (Instagram, Facebook, Twitter, etc.)
  social_media_post    : Individual post page

Crawl decision tree
-------------------
  direct_product / marketplace_listing / aggregator
    → CrawlTarget(url=original_url, platform="...", resolution="direct")

  social_media_profile
    → crawl profile page
    → LLM: extract product/store outbound URLs from bio + post captions
    → if found: CrawlTarget(url=product_url, resolution="product_extracted")
    → if not:   CrawlTarget(url=original_url, resolution="comment_context",
                             context_notes=bio+captions text)

  social_media_post
    → crawl post page
    → LLM: extract product/store URLs + read comments
    → if product URL found: CrawlTarget(url=product_url, resolution="product_extracted")
    → else: CrawlTarget(url=original_url, resolution="comment_context",
                         context_notes=caption+comments text)

Design rules
------------
- NEVER crawl OTHER social profiles discovered via links (e.g. a friend's
  profile linked in a post). Only crawl outbound e-commerce/store URLs.
- Never raises — returns a safe CrawlTarget(url=original_url) on any error.
- Playwright reused from agent3; no new dependencies.
- All LLM calls use AIML API (gpt-4o) which is already the agent3 dependency.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from services import aiml_client

logger = logging.getLogger(__name__)

# ─── Known social-media hostnames (used for quick guard: do NOT follow OTHER
# social profile links even if LLM suggests them) ─────────────────────────────

_SOCIAL_MEDIA_HOSTS = frozenset({
    "instagram.com", "www.instagram.com",
    "facebook.com", "www.facebook.com", "fb.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "tiktok.com", "www.tiktok.com",
    "youtube.com", "www.youtube.com", "youtu.be",
    "pinterest.com", "www.pinterest.com",
    "linkedin.com", "www.linkedin.com",
    "snapchat.com", "www.snapchat.com",
    "reddit.com", "www.reddit.com",
    "threads.net", "www.threads.net",
    "koo.com", "www.koo.com",
    "sharechat.com", "www.sharechat.com",
    "moj.life", "www.moj.life",
})

# ─── JSON extraction helper ────────────────────────────────────────────────────


def _extract_json(raw: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences gracefully."""
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
    raise ValueError(f"Could not extract JSON: {raw[:200]}")


# ─── Data Model ───────────────────────────────────────────────────────────────


@dataclass
class CrawlTarget:
    """
    The resolved crawl target returned by resolve_url_for_crawl().

    Attributes
    ----------
    url:                   The URL that Agent 3 should actually crawl.
    original_url:          The original URL submitted by the user.
    platform_type:         Classification of the original URL's platform.
    resolution_type:       How the crawl target was resolved.
    extracted_product_url: The product/store URL found on the social page (if any).
    context_notes:         Free-text notes for Agent 3's synthesis (bio, captions, comments).
    """

    url: str
    original_url: str
    platform_type: str = "direct"
    resolution_type: str = "direct"
    extracted_product_url: Optional[str] = None
    context_notes: str = ""


# ─── Step 1: Platform Classification ─────────────────────────────────────────


async def classify_url_platform(url: str) -> str:
    """
    Classify a URL into a platform category using a fast LLM call.

    Returns one of:
      "direct_product"       — a product, service, or business website
      "marketplace_listing"  — OLX, Flipkart, Meesho, Amazon, etc.
      "aggregator"           — Linktree, bio.link, Carrd, etc.
      "social_media_profile" — any social network profile page
      "social_media_post"    — a specific post on a social network

    Never raises — returns "direct_product" on error (safe default: crawl as-is).
    """
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # Quick structural pre-classification for well-known patterns
    # (avoids LLM call for the most common cases)
    if hostname not in _SOCIAL_MEDIA_HOSTS:
        # Could still be an obscure social platform — let LLM decide
        # But for speed, optimistically treat as direct for unknown hosts
        # The LLM override below only runs for social-looking domains
        known_marketplaces = {
            "olx.in", "flipkart.com", "amazon.in", "amazon.com",
            "meesho.com", "snapdeal.com", "myntra.com", "ajio.com",
            "nykaa.com", "jiomart.com", "indiamart.com", "tradeindia.com",
        }
        if hostname in known_marketplaces:
            logger.info("smart_crawler: %s classified as marketplace_listing (fast path)", hostname)
            return "marketplace_listing"
        # Unknown domain → treat as direct product (most common legitimate case)
        # We still run the LLM classification below for correctness
        pass

    messages = [
        {
            "role": "system",
            "content": (
                "You classify URLs for a payment fraud detection system. "
                "Given a URL, output ONLY valid JSON with one key: 'platform_type'. "
                "Valid values: 'direct_product', 'marketplace_listing', 'aggregator', "
                "'social_media_profile', 'social_media_post'. "
                "Choose 'direct_product' for any business/shop/service website. "
                "Choose 'social_media_profile' for any social network profile page. "
                "Choose 'social_media_post' for a specific post on a social network. "
                "No markdown. No explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Classify this URL: {url}\n\n"
                "Output only: {\"platform_type\": \"<value>\"}"
            ),
        },
    ]

    try:
        raw = await aiml_client.chat_text(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=64,
        )
        data = _extract_json(raw)
        platform = str(data.get("platform_type", "direct_product")).strip()
        valid = {
            "direct_product", "marketplace_listing", "aggregator",
            "social_media_profile", "social_media_post",
        }
        if platform not in valid:
            logger.warning("smart_crawler: unexpected platform_type '%s' — defaulting to direct_product", platform)
            platform = "direct_product"
        logger.info("smart_crawler: %s → platform_type=%s", url, platform)
        return platform
    except Exception as exc:
        logger.warning("smart_crawler: platform classification failed (default direct_product) — %s", exc)
        return "direct_product"


# ─── Step 2: Crawl Social Page with Playwright ────────────────────────────────


async def _crawl_social_page(url: str, max_scroll: int = 3) -> dict:
    """
    Use Playwright to crawl a social media profile or post page.

    Scrolls the page up to `max_scroll` times to load lazy content.
    Returns a dict with:
      - body_text: visible text on the page (up to 4000 chars)
      - all_links: list of outbound href links found
      - crawl_error: error string or None
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    # Mobile viewport — many social pages render better on mobile
                    viewport={"width": 390, "height": 844},
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"
                    ),
                )
                page = await context.new_page()

                # Block heavy resources to speed up crawl
                await page.route(
                    "**/*.{mp4,webm,ogg,mp3,wav,gif,svg}",
                    lambda route: route.abort(),
                )

                await page.goto(url, timeout=20000, wait_until="domcontentloaded")

                # Scroll to trigger lazy-loaded content (captions, comments)
                for _ in range(max_scroll):
                    await page.evaluate("window.scrollBy(0, 800)")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass  # timeout on scroll is fine

                body_text = await page.inner_text("body")
                body_text = body_text[:4000]

                # Extract all href links from the page
                links_raw = await page.evaluate(
                    "Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
                )
                all_links: list[str] = [
                    lnk for lnk in (links_raw or [])
                    if isinstance(lnk, str) and lnk.startswith("http")
                ][:100]  # cap at 100 links

                await browser.close()
                return {
                    "body_text": body_text,
                    "all_links": all_links,
                    "crawl_error": None,
                }
            except Exception as exc:
                await browser.close()
                raise exc

    except Exception as exc:
        logger.warning("smart_crawler: social page crawl failed for %s — %s", url, exc)
        return {
            "body_text": "",
            "all_links": [],
            "crawl_error": str(exc),
        }


# ─── Step 3: Extract Product URL from Social Page ─────────────────────────────


async def _extract_product_url(
    page_text: str,
    all_links: list[str],
    original_url: str,
) -> Optional[str]:
    """
    Use LLM to identify if any link on the social page is a product/store URL.

    Filters out:
      - Other social media profiles (irrelevant — they're not what we're checking)
      - The original URL itself
      - Short URLs / tracking URLs without identifiable destination

    Returns the best product/store URL, or None if none found.
    Never raises.
    """
    if not all_links and not page_text:
        return None

    # Pre-filter: remove links to other social profiles
    original_host = (urlparse(original_url).hostname or "").lower()
    candidate_links: list[str] = []
    for lnk in all_links:
        lnk_host = (urlparse(lnk).hostname or "").lower()
        # Skip: same platform, other social platforms, tracking/analytics URLs
        if lnk_host == original_host:
            continue
        if lnk_host in _SOCIAL_MEDIA_HOSTS:
            continue
        if any(tracker in lnk_host for tracker in ["google-analytics", "doubleclick", "facebook.net", "pixel"]):
            continue
        candidate_links.append(lnk)

    # Truncate to avoid token bloat
    links_str = "\n".join(candidate_links[:30]) if candidate_links else "(none)"
    text_preview = page_text[:1500] if page_text else "(no text)"

    messages = [
        {
            "role": "system",
            "content": (
                "You are helping a fraud detection system find the real seller website "
                "linked from a social media profile or post. "
                "Look for links to actual product pages, online stores, or e-commerce websites. "
                "IGNORE links to other social media profiles. "
                "IGNORE links to support pages, terms, or help pages. "
                "Output ONLY valid JSON. No markdown."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Social media page URL: {original_url}\n\n"
                f"PAGE TEXT (first 1500 chars):\n{text_preview}\n\n"
                f"OUTBOUND LINKS FOUND (excluding other social profiles):\n{links_str}\n\n"
                "Is there a product page, online store, or e-commerce URL in the links or "
                "mentioned in the text (e.g. in the bio or caption)?\n\n"
                "Output ONLY:\n"
                "{\"product_url\": \"https://...\" or null, "
                "\"confidence\": \"high\" or \"medium\" or \"low\", "
                "\"reason\": \"one sentence\"}"
            ),
        },
    ]

    try:
        raw = await aiml_client.chat_text(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=256,
        )
        data = _extract_json(raw)
        product_url = data.get("product_url")
        confidence = data.get("confidence", "low")
        reason = data.get("reason", "")

        if product_url and isinstance(product_url, str) and product_url.startswith("http"):
            # Only accept medium or high confidence findings
            if confidence in ("high", "medium"):
                logger.info(
                    "smart_crawler: product URL extracted | url=%s | confidence=%s | reason=%s",
                    product_url, confidence, reason,
                )
                return product_url
            else:
                logger.info(
                    "smart_crawler: low-confidence product URL skipped | url=%s | reason=%s",
                    product_url, reason,
                )
                return None

        logger.info("smart_crawler: no product URL found on social page (%s)", reason)
        return None

    except Exception as exc:
        logger.warning("smart_crawler: product URL extraction failed — %s", exc)
        return None


# ─── Step 4: Extract Context from Social Post (comments/captions) ─────────────


async def _extract_social_context(page_text: str, original_url: str) -> str:
    """
    Extract relevant fraud-detection context from a social page's text.

    Focuses on: captions, post text, visible comments, bio text.
    Returns a cleaned, truncated string for Agent 3's synthesis context.
    Never raises — returns empty string on error.
    """
    if not page_text:
        return ""

    messages = [
        {
            "role": "system",
            "content": (
                "You are extracting relevant text from a social media page for a "
                "payment fraud detection system. Extract ONLY: bio text, post captions, "
                "post descriptions, product details, price mentions, and any seller claims. "
                "Remove: navigation text, button labels, app prompts (e.g. 'Download the app'), "
                "usernames in navigation, generic social media UI text. "
                "Return a clean, condensed plain text summary. Max 500 words."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Social page: {original_url}\n\n"
                f"RAW PAGE TEXT:\n{page_text[:3000]}\n\n"
                "Extract the relevant context (bio, captions, product details, comments, "
                "price mentions). Output plain text only, no JSON."
            ),
        },
    ]

    try:
        context = await aiml_client.chat_text(
            messages=messages,
            temperature=0.1,
            max_tokens=600,
        )
        return context.strip()[:2000]
    except Exception as exc:
        logger.warning("smart_crawler: social context extraction failed — %s", exc)
        # Fall back to raw truncated text
        return page_text[:1000]


# ─── Main Entry Point ─────────────────────────────────────────────────────────


async def resolve_url_for_crawl(url: str) -> CrawlTarget:
    """
    Resolve the best URL for Agent 3 to crawl given the user's input URL.

    Decision tree
    -------------
    1. Classify platform type (LLM or fast path).
    2. If direct/marketplace/aggregator → return CrawlTarget(url=url, type="direct").
    3. If social_media_profile or social_media_post:
       a. Crawl the social page with Playwright.
       b. LLM: extract product/store URL from links + page text.
       c. If product URL found (medium/high confidence):
             → return CrawlTarget(url=product_url, resolution="product_extracted")
       d. Else:
             → LLM: extract bio/caption/comment context from page text
             → return CrawlTarget(url=original_url, resolution="comment_context",
                                   context_notes=extracted_context)

    Never raises — falls back to CrawlTarget(url=original_url) on any error.

    Parameters
    ----------
    url: The payment URL submitted by the user.

    Returns
    -------
    CrawlTarget with the recommended URL to crawl and contextual notes.
    """
    logger.info("smart_crawler: resolving crawl target for %s", url)

    # ── Step 1: Platform classification ───────────────────────────────────────
    try:
        platform_type = await classify_url_platform(url)
    except Exception as exc:
        logger.error("smart_crawler: classification failed (using direct) — %s", exc)
        platform_type = "direct_product"

    # ── Step 2: Non-social → crawl as-is ──────────────────────────────────────
    if platform_type not in ("social_media_profile", "social_media_post"):
        logger.info(
            "smart_crawler: non-social platform (%s) — crawling %s directly",
            platform_type, url,
        )
        return CrawlTarget(
            url=url,
            original_url=url,
            platform_type=platform_type,
            resolution_type="direct",
            extracted_product_url=None,
            context_notes="",
        )

    # ── Step 3: Social media — crawl the social page ──────────────────────────
    logger.info(
        "smart_crawler: social platform detected (%s) — crawling profile/post page...",
        platform_type,
    )
    crawl_result = await _crawl_social_page(url)

    if crawl_result.get("crawl_error"):
        logger.warning(
            "smart_crawler: could not crawl social page (%s) — falling back to direct",
            crawl_result["crawl_error"],
        )
        return CrawlTarget(
            url=url,
            original_url=url,
            platform_type=platform_type,
            resolution_type="direct",
            context_notes=(
                f"Social page crawl failed: {crawl_result['crawl_error']}. "
                "Domain age analysis will be run on the social platform domain instead."
            ),
        )

    page_text = crawl_result.get("body_text", "")
    all_links = crawl_result.get("all_links", [])

    # ── Step 4: Extract product/store URL from social page ────────────────────
    logger.info(
        "smart_crawler: extracted %d links from social page — looking for product URL...",
        len(all_links),
    )
    product_url = await _extract_product_url(
        page_text=page_text,
        all_links=all_links,
        original_url=url,
    )

    if product_url:
        # Verify the product URL is not itself a social media link
        product_host = (urlparse(product_url).hostname or "").lower()
        if product_host in _SOCIAL_MEDIA_HOSTS:
            logger.info(
                "smart_crawler: extracted URL is another social profile (%s) — not following",
                product_url,
            )
            product_url = None

    if product_url:
        logger.info(
            "smart_crawler: product URL found → crawling %s (from social page %s)",
            product_url, url,
        )
        return CrawlTarget(
            url=product_url,
            original_url=url,
            platform_type=platform_type,
            resolution_type="product_extracted",
            extracted_product_url=product_url,
            context_notes=(
                f"This is a {platform_type.replace('_', ' ')} ({url}). "
                f"A product/store URL was found on the page: {product_url}. "
                "Domain intelligence and fraud signals are being checked on the product URL."
            ),
        )

    # ── Step 5: No product URL — extract captions/comments as context ─────────
    logger.info(
        "smart_crawler: no product URL found on %s — extracting context for synthesis",
        url,
    )
    context_text = await _extract_social_context(
        page_text=page_text,
        original_url=url,
    )

    return CrawlTarget(
        url=url,
        original_url=url,
        platform_type=platform_type,
        resolution_type="comment_context",
        extracted_product_url=None,
        context_notes=(
            f"This is a {platform_type.replace('_', ' ')}. "
            "No outbound product/store URL was found. "
            "The analysis uses bio text, post captions, and visible comments from the social page. "
            f"\n\nSOCIAL PAGE CONTEXT:\n{context_text}"
        ),
    )
