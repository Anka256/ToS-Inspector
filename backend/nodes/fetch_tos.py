"""
fetch_tos.py — Node 1 of the LangGraph pipeline.

3-tier ToS fetching strategy:
  Tier 1: Try domain-specific overrides + known URL patterns (requests + BeautifulSoup)
  Tier 2: DuckDuckGo search fallback
  Tier 3: Playwright headless browser fallback (networkidle + extra wait)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from backend.state import AppState

logger = logging.getLogger(__name__)

# Generic ToS path patterns tried in Tier 1 after domain-specific overrides
TOS_PATHS = [
    "/terms",
    "/terms-of-service",
    "/terms-and-conditions",
    "/tos",
    "/legal/terms",
    "/legal",
    "/privacy",
    "/privacy-policy",
    "/user-agreement",
]

# Domain-specific known ToS URLs — tried FIRST before generic path patterns.
# Add entries here for any site whose ToS lives at a non-standard path.
DOMAIN_TOS_OVERRIDES: dict[str, list[str]] = {
    "www.tiktok.com": [
        "https://www.tiktok.com/legal/page/row/terms-of-service/en",
        "https://www.tiktok.com/legal/terms-of-service",
    ],
    "tiktok.com": [
        "https://www.tiktok.com/legal/page/row/terms-of-service/en",
        "https://www.tiktok.com/legal/terms-of-service",
    ],
    "www.spotify.com": [
        "https://www.spotify.com/legal/end-user-agreement/",
        "https://www.spotify.com/us/legal/end-user-agreement/",
    ],
    "open.spotify.com": [
        "https://www.spotify.com/legal/end-user-agreement/",
    ],
    "twitter.com": [
        "https://twitter.com/en/tos",
    ],
    "x.com": [
        "https://x.com/en/tos",
        "https://twitter.com/en/tos",
    ],
    "www.instagram.com": [
        "https://www.instagram.com/legal/terms/",
    ],
    "instagram.com": [
        "https://www.instagram.com/legal/terms/",
    ],
    "www.facebook.com": [
        "https://www.facebook.com/legal/terms",
    ],
    "facebook.com": [
        "https://www.facebook.com/legal/terms",
    ],
    "www.linkedin.com": [
        "https://www.linkedin.com/legal/user-agreement",
        "https://www.linkedin.com/legal/privacy-policy",
    ],
    "linkedin.com": [
        "https://www.linkedin.com/legal/user-agreement",
        "https://www.linkedin.com/legal/privacy-policy",
    ],
    "www.youtube.com": [
        "https://www.youtube.com/t/terms",
    ],
    "www.quora.com": [
        "https://www.quora.com/about/tos",
        "https://www.quora.com/about/privacy",
    ],
    "quora.com": [
        "https://www.quora.com/about/tos",
        "https://www.quora.com/about/privacy",
    ],
}

# Domains known to aggressively block bots (999 status, login walls, JS-only rendering).
# For these, Tier 1 static requests are skipped entirely — Playwright is used immediately.
PLAYWRIGHT_REQUIRED_DOMAINS: set[str] = {
    "linkedin.com",
    "www.linkedin.com",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
    "twitter.com",
    "x.com",
    "quora.com",
    "www.quora.com",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

MIN_TEXT_LENGTH = 500        # minimum chars for a single attempt to be considered non-empty
MIN_CONTENT_LENGTH = 2000   # minimum chars to proceed with analysis

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "url_cache.json")
CACHE_TTL_DAYS = 30


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(domain: str, url: str, tier: int) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        cache = _load_cache()
        cache[domain] = {
            "url": url,
            "tier": tier,
            "fetched_at": datetime.now().isoformat(),
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
        logger.debug("Cache saved for %s → %s (tier %d)", domain, url, tier)
    except Exception as exc:
        logger.warning("Cache write failed (non-fatal): %s", exc)


def _extract_text_from_html(html: str) -> str:
    """Extract clean plaintext from HTML, removing boilerplate elements."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["nav", "footer", "header", "script", "style", "noscript"]):
        tag.decompose()

    for selector in ["main", "article"]:
        container = soup.find(selector)
        if container:
            return container.get_text(separator="\n", strip=True)

    divs = soup.find_all("div")
    if divs:
        best = max(divs, key=lambda d: len(d.get_text(strip=True)), default=None)
        if best:
            text = best.get_text(separator="\n", strip=True)
            if len(text) >= MIN_TEXT_LENGTH:
                return text

    return soup.get_text(separator="\n", strip=True)


def _fetch_url(url: str, timeout: int = 15) -> tuple[str, str]:
    """Fetch URL and return (html, final_url)."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.text, resp.url


def _tier1_fetch(root_url: str) -> tuple[str, str] | None:
    """Try domain-specific overrides first, then generic ToS path patterns.
    Returns (text, successful_url) on success, or None on failure.
    """
    parsed = urlparse(root_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    domain = parsed.netloc

    override_urls = DOMAIN_TOS_OVERRIDES.get(domain, [])
    generic_urls = [base + path for path in TOS_PATHS]
    candidates = override_urls + generic_urls

    for try_url in candidates:
        try:
            html, _ = _fetch_url(try_url)
            text = _extract_text_from_html(html)
            char_count = len(text)
            print(f"[Tier 1] Tried {try_url} → {char_count} chars")
            if char_count >= MIN_TEXT_LENGTH:
                logger.info("Tier 1 success: %s | %d chars retrieved", try_url, char_count)
                return text, try_url
        except Exception as exc:
            print(f"[Tier 1] Tried {try_url} → ERROR: {exc}")
            continue

    return None


def _tier2_ddg_search(domain: str) -> str | None:
    """Use DuckDuckGo instant-answer API to find ToS URL, then fetch it."""
    query = f'"{domain}" terms of service site:{domain}'
    ddg_url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_redirect": 1, "no_html": 1}

    try:
        resp = requests.get(ddg_url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()

        candidate_url = data.get("AbstractURL") or ""
        if not candidate_url:
            for t in data.get("RelatedTopics", []):
                if isinstance(t, dict) and t.get("FirstURL"):
                    candidate_url = t["FirstURL"]
                    break

        if candidate_url:
            html, _ = _fetch_url(candidate_url)
            text = _extract_text_from_html(html)
            char_count = len(text)
            print(f"[Tier 2] DuckDuckGo result: {candidate_url} → {char_count} chars")
            if char_count >= MIN_TEXT_LENGTH:
                logger.info("Tier 2 success via DDG: %s | %d chars retrieved", candidate_url, char_count)
                return text
        else:
            print(f"[Tier 2] DuckDuckGo returned no candidate URL for: {domain}")

    except Exception as exc:
        print(f"[Tier 2] DuckDuckGo failed: {exc}")
        logger.warning("Tier 2 DDG search failed: %s", exc)

    return None


async def _tier3_playwright(url: str, extra_urls: list[str] | None = None) -> tuple[str, str] | None:
    """
    Render pages via Playwright headless Chromium.
    Tries `extra_urls` first (domain overrides), then falls back to `url`.
    Uses networkidle wait + 2s extra settle time for JS-heavy pages.
    Returns (text, successful_url) on success, or None on failure.
    """
    try:
        from playwright.async_api import async_playwright  # lazy import

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            # Use same User-Agent header as requests to bypass headless detection
            page = await browser.new_page(user_agent=HEADERS["User-Agent"])

            attempts = list(extra_urls or []) + [url]

            for attempt_url in attempts:
                try:
                    try:
                        # Attempt to load the page. If it times out or fails (e.g. infinite tracking loading),
                        # we catch the error below and still attempt to scrape the currently loaded DOM.
                        await page.goto(attempt_url, wait_until="networkidle", timeout=15000)
                    except Exception as goto_exc:
                        print(f"[Tier 3] Playwright goto warning (continuing to extract text): {goto_exc}")
                        logger.warning("Playwright page.goto timed out or failed on %s: %s", attempt_url, goto_exc)

                    await page.wait_for_timeout(2000)  # extra 2s for late JS rendering
                    text = await page.evaluate("document.body.innerText")
                    char_count = len(text) if text else 0
                    print(f"[Tier 3] Playwright on {attempt_url} → {char_count} chars")

                    if text and char_count >= MIN_TEXT_LENGTH:
                        await browser.close()
                        logger.info(
                            "Tier 3 Playwright success for: %s | %d chars retrieved",
                            attempt_url, char_count,
                        )
                        return text, attempt_url

                except Exception as exc:
                    print(f"[Tier 3] Playwright on {attempt_url} → ERROR: {exc}")
                    logger.warning("Tier 3 Playwright attempt failed (%s): %s", attempt_url, exc)

            await browser.close()

    except Exception as exc:
        print(f"[Tier 3] Playwright setup failed: {exc}")
        logger.warning("Tier 3 Playwright failed: %s", exc)

    return None


async def fetch_tos(state: AppState) -> AppState:
    """
    LangGraph node: fetch ToS text from the given URL using a 3-tier strategy.
    Writes tos_text (and raw_html where applicable) into state.
    """
    url: str = state["url"]
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path

    # Pass domain overrides to Playwright so it tries them before the root URL
    domain_overrides = DOMAIN_TOS_OVERRIDES.get(domain, [])
    playwright_required = domain in PLAYWRIGHT_REQUIRED_DOMAINS

    try:
        text: str | None = None
        successful_url: str = url

        # ── Cache check ──────────────────────────────────────────────────────
        _cache = _load_cache()
        _cached = _cache.get(domain)
        if _cached and _cached.get("url"):
            _age = datetime.now() - datetime.fromisoformat(_cached["fetched_at"])
            if _age < timedelta(days=CACHE_TTL_DAYS):
                logger.info("Cache hit for %s → trying %s", domain, _cached["url"])
                try:
                    if playwright_required:
                        result = await _tier3_playwright(_cached["url"], extra_urls=[])
                    else:
                        _html, _ = _fetch_url(_cached["url"])
                        cached_text = _extract_text_from_html(_html)
                        result = (cached_text, _cached["url"]) if len(cached_text) >= MIN_TEXT_LENGTH else None
                    if result:
                        cached_text, _ = result
                        if len(cached_text) >= MIN_CONTENT_LENGTH:
                            logger.info("Cache fetch success for %s: %d chars", domain, len(cached_text))
                            return {**state, "tos_text": cached_text, "raw_html": ""}
                        else:
                            logger.warning("Cached URL returned insufficient content, invalidating for %s", domain)
                            _save_cache(domain, "", 0)  # invalidate
                    else:
                        logger.warning("Cached URL failed for %s — proceeding with normal fetch", domain)
                        _save_cache(domain, "", 0)  # invalidate
                except Exception as exc:
                    logger.warning("Cached URL error for %s: %s — proceeding with normal fetch", domain, exc)
            else:
                logger.info("Cache expired for %s, re-fetching", domain)

        # ── Tier 1: static fetch ─────────────────────────────────────────────
        if playwright_required:
            logger.info("Domain %s is in PLAYWRIGHT_REQUIRED_DOMAINS — skipping Tier 1", domain)
        else:
            result1 = _tier1_fetch(url)
            if result1:
                text, successful_url = result1
                _save_cache(domain, successful_url, tier=1)

        # ── Tier 2: DuckDuckGo search ────────────────────────────────────────
        if not text and not playwright_required:
            logger.info("Tier 1 exhausted, trying DDG search for: %s", domain)
            ddg_text = _tier2_ddg_search(domain)
            if ddg_text:
                text = ddg_text
                # DDG doesn't expose the exact URL cleanly; cache as domain root
                _save_cache(domain, url, tier=2)

        # ── Tier 3: Playwright headless ──────────────────────────────────────
        if not text:
            logger.info("Tier 2 exhausted, trying Playwright for: %s", url)
            result3 = await _tier3_playwright(url, extra_urls=domain_overrides)
            if result3:
                text, successful_url = result3
                _save_cache(domain, successful_url, tier=3)

        if not text:
            raise RuntimeError(f"All fetch tiers failed for {url}")

        # ── Minimum content guard ────────────────────────────────────────────
        char_count = len(text)
        if char_count < MIN_CONTENT_LENGTH:
            logger.warning(
                "Insufficient ToS content for %s: only %d chars (minimum %d)",
                url, char_count, MIN_CONTENT_LENGTH,
            )
            return {
                **state,
                "tos_text": "",
                "raw_html": "",
                "error": "Could not retrieve sufficient ToS content for this site.",
            }

        logger.info("fetch_tos complete: %d chars will be analyzed", char_count)
        return {**state, "tos_text": text, "raw_html": ""}

    except Exception as exc:
        logger.error("fetch_tos node error: %s", exc)
        return {**state, "tos_text": "", "raw_html": "", "error": str(exc)}
