"""Website crawling helpers with an optional Playwright-free mode for low-memory hosts."""

from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)


def playwright_enabled() -> bool:
    """Return False when DISABLE_PLAYWRIGHT is set (Render free tier, etc.)."""
    return os.getenv("DISABLE_PLAYWRIGHT", "").lower() not in ("1", "true", "yes")


async def crawl_page(url: str, *, body_limit: int = 3000) -> dict:
    """
    Crawl a URL and return the same shape as agent3's Playwright crawl.

    Uses Playwright when enabled; otherwise falls back to httpx + regex parsing.
    Never raises.
    """
    if playwright_enabled():
        return await _crawl_with_playwright(url, body_limit=body_limit)
    return await _crawl_with_http(url, body_limit=body_limit)


async def crawl_social_page(url: str, *, body_limit: int = 4000) -> dict:
    """Crawl a social profile/post page. Playwright-free mode uses httpx only."""
    if playwright_enabled():
        return await _crawl_social_with_playwright(url, body_limit=body_limit)
    return await _crawl_social_with_http(url, body_limit=body_limit)


async def _crawl_with_playwright(url: str, *, body_limit: int) -> dict:
    try:
        from playwright.async_api import async_playwright  # type: ignore

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ],
            )
            try:
                page = await browser.new_page()
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                title = await page.title()
                body_text = (await page.inner_text("body"))[:body_limit]
                screenshot_bytes = await page.screenshot(full_page=True)
                meta_desc = await page.evaluate(
                    "document.querySelector('meta[name=\"description\"]')?.content || ''"
                )
                text_lower = body_text.lower()
                await browser.close()
                return _build_crawl_result(
                    url=url,
                    title=title,
                    meta_desc=meta_desc,
                    body_text=body_text,
                    screenshot_bytes=screenshot_bytes,
                    text_lower=text_lower,
                )
            except Exception as exc:
                await browser.close()
                raise exc
    except Exception as exc:
        logger.error("Playwright crawl failed for %s: %s", url, exc)
        return {"crawl_error": str(exc), "screenshot_bytes": None, "url": url}


async def _crawl_social_with_playwright(url: str, *, body_limit: int) -> dict:
    try:
        from playwright.async_api import async_playwright  # type: ignore

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 390, "height": 844},
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"
                    ),
                )
                page = await context.new_page()
                await page.route("**/*.{mp4,webm,ogg,mp3,wav,gif,svg}", lambda route: route.abort())
                await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 800)")
                body_text = (await page.inner_text("body"))[:body_limit]
                links_raw = await page.evaluate(
                    "Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"
                )
                all_links = [
                    lnk for lnk in (links_raw or [])
                    if isinstance(lnk, str) and lnk.startswith("http")
                ][:100]
                await browser.close()
                return {"body_text": body_text, "all_links": all_links, "crawl_error": None}
            except Exception as exc:
                await browser.close()
                raise exc
    except Exception as exc:
        logger.warning("Playwright social crawl failed for %s — %s", url, exc)
        return {"body_text": "", "all_links": [], "crawl_error": str(exc)}


async def _crawl_with_http(url: str, *, body_limit: int) -> dict:
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "PayGuardAI/1.0"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_tag.get("content", "") if meta_tag else ""
        body_text = soup.get_text(" ", strip=True)[:body_limit]
        text_lower = body_text.lower()
        logger.info("HTTP crawl (no Playwright) succeeded for %s", url)
        return _build_crawl_result(
            url=url,
            title=title,
            meta_desc=meta_desc,
            body_text=body_text,
            screenshot_bytes=None,
            text_lower=text_lower,
        )
    except Exception as exc:
        logger.warning("HTTP crawl failed for %s — %s", url, exc)
        return {"crawl_error": str(exc), "screenshot_bytes": None, "url": url}


async def _crawl_social_with_http(url: str, *, body_limit: int) -> dict:
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "lxml")
        body_text = soup.get_text(" ", strip=True)[:body_limit]
        all_links = [
            a["href"]
            for a in soup.find_all("a", href=True)
            if str(a["href"]).startswith("http")
        ][:100]
        return {"body_text": body_text, "all_links": all_links, "crawl_error": None}
    except Exception as exc:
        logger.warning("HTTP social crawl failed for %s — %s", url, exc)
        return {"body_text": "", "all_links": [], "crawl_error": str(exc)}


def _build_crawl_result(
    *,
    url: str,
    title: str,
    meta_desc: str,
    body_text: str,
    screenshot_bytes: bytes | None,
    text_lower: str,
) -> dict:
    return {
        "url": url,
        "title": title,
        "meta_description": meta_desc,
        "body_text": body_text,
        "screenshot_bytes": screenshot_bytes,
        "has_contact_page": "contact" in text_lower,
        "has_about_page": "about" in text_lower,
        "has_gst_number": bool(
            re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b", body_text)
        ),
        "crawl_error": None,
    }
