"""
preprocess.py — Node 2 of the LangGraph pipeline.

Counts tokens and intelligently truncates the ToS text if it exceeds MAX_TOTAL_TOKENS.
Truncation strategy: take first 40% + middle 20% + last 40% to keep legally dense sections.
"""

from __future__ import annotations

import logging

import tiktoken

from backend.config import MAX_TOTAL_TOKENS
from backend.state import AppState

logger = logging.getLogger(__name__)

# Use cl100k_base as a universal approximate tokenizer for all OpenRouter models
_enc = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _truncate_intelligently(text: str, max_tokens: int) -> tuple[str, int]:
    """
    Keep first 40% + middle 20% + last 40% of the text by token count.
    This preserves the introduction, critical middle clauses, and conclusion/arbitration sections.
    """
    tokens = _enc.encode(text)
    total = len(tokens)

    if total <= max_tokens:
        return text, total

    first_count = int(max_tokens * 0.40)
    mid_count = int(max_tokens * 0.20)
    last_count = max_tokens - first_count - mid_count

    first_tokens = tokens[:first_count]

    mid_start = (total - mid_count) // 2
    mid_tokens = tokens[mid_start : mid_start + mid_count]

    last_tokens = tokens[-last_count:]

    separator = _enc.encode("\n\n[... section omitted for length ...]\n\n")
    combined = first_tokens + separator + mid_tokens + separator + last_tokens

    truncated_text = _enc.decode(combined)
    final_count = len(combined)

    logger.info(
        "Truncated ToS from %d to %d tokens (%.1f%% retained)",
        total,
        final_count,
        final_count / total * 100,
    )
    return truncated_text, final_count


def preprocess(state: AppState) -> AppState:
    """
    LangGraph node: token-count the ToS text and truncate if necessary.
    """
    # Skip if upstream fetch already failed
    if state.get("error") or not state.get("tos_text"):
        return state

    tos_text: str = state["tos_text"]
    raw_count = _count_tokens(tos_text)
    logger.info("Raw ToS token count: %d", raw_count)

    if raw_count > MAX_TOTAL_TOKENS:
        tos_text, token_count = _truncate_intelligently(tos_text, MAX_TOTAL_TOKENS)
    else:
        token_count = raw_count

    return {**state, "tos_text": tos_text, "token_count": token_count}
