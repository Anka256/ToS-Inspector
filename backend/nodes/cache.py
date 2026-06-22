"""
cache.py — Analysis result cache keyed by (domain, ToS content hash).

A cache hit means the same ToS text was seen before, so re-running the LLM
pipeline would produce the same output. The hash acts as a content fingerprint,
so any change to the live ToS automatically invalidates the entry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

ANALYSIS_CACHE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "analysis_cache.json"
)


def _hash_tos(text: str) -> str:
    """16-char SHA-256 prefix — enough to detect ToS changes, cheap to store."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def get_cached_analysis(domain: str, tos_text: str) -> dict | None:
    """
    Return the cached FinalReport dict if the ToS content hasn't changed.
    Returns None on miss, expired entry, or any I/O error.
    """
    try:
        with open(ANALYSIS_CACHE_FILE) as f:
            cache = json.load(f)
        entry = cache.get(domain)
        if entry and entry.get("tos_hash") == _hash_tos(tos_text):
            logger.info(
                "Analysis cache hit for %s (cached at %s)",
                domain,
                entry.get("cached_at", "?"),
            )
            return entry["report"]
    except Exception:
        pass
    return None


def save_analysis_cache(domain: str, tos_text: str, report: dict) -> None:
    """Persist a FinalReport dict alongside its content hash for future hits."""
    try:
        os.makedirs(os.path.dirname(ANALYSIS_CACHE_FILE), exist_ok=True)
        try:
            with open(ANALYSIS_CACHE_FILE) as f:
                cache = json.load(f)
        except Exception:
            cache = {}

        cache[domain] = {
            "tos_hash": _hash_tos(tos_text),
            "cached_at": datetime.now().isoformat(),
            "report": report,
        }

        with open(ANALYSIS_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)

        logger.info("Analysis result cached for %s", domain)
    except Exception as exc:
        logger.warning("Analysis cache write failed (non-fatal): %s", exc)
