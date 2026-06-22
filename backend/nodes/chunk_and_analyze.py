"""
chunk_and_analyze.py — Node 3 of the LangGraph pipeline.

Splits the ToS text into overlapping chunks and fires parallel async LLM calls
(one per chunk) using AsyncOpenAI pointed at OpenRouter.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import tiktoken
from openai import AsyncOpenAI
from pydantic import ValidationError

from backend.config import (
    ANALYSIS_MODEL,
    CHUNK_OVERLAP_TOKENS,
    HTTP_REFERER,
    MAX_CHUNK_TOKENS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)
from backend.state import AppState, CategoryFinding

logger = logging.getLogger(__name__)

_enc = tiktoken.get_encoding("cl100k_base")

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a legal analysis expert specializing in Terms of Service and Privacy Policy documents.
Analyze the provided text excerpt and identify issues across these 7 categories:

1. Data Collection & Sharing — third-party sharing, ad targeting, data sale
2. Content Ownership — who owns uploaded content, platform license rights
3. Account & Service Termination — ban without warning, data recovery rights
4. Policy Change Rights — unilateral changes, notification obligations
5. Legal Rights & Disputes — mandatory arbitration, class action waiver, jurisdiction
6. Payment & Subscription Traps — auto-renewal, hidden fees, cancellation conditions
7. Sensitive & Children's Data — health data, location tracking, COPPA compliance

For each category where you find relevant content, return a structured finding.

Severity calibration — judge relative to industry norms, not in isolation:
- green: user-friendly clause, above industry average, no concerns
- yellow: standard industry practice, worth knowing but not alarming
- red: notably worse than industry average, user rights meaningfully restricted
- blocker: unacceptable clause that would give a reasonable person serious pause about using the service

Important: Legal compliance clauses (age minimums, COPPA, GDPR notices, jurisdiction declarations,
standard liability caps, 30-day change notices) are NOT inherently red flags. Rate them based on
whether they are harmful to the user, not merely because they are legal boilerplate.

Also set `is_industry_standard: true` when the finding describes a clause that is essentially
unavoidable boilerplate present in virtually all major platforms (e.g. "users must be 13+",
"we may update this policy", "California law governs", "we may terminate accounts").

Be specific. Always include direct quotes from the text as evidence.
Return ONLY valid JSON. No prose outside JSON.

Each finding object must have exactly these fields:
{
  "category": "<one of the 7 category names>",
  "status": "<green|yellow|red|blocker>",
  "headline": "<max 12 words, user-facing summary>",
  "details": "<1-3 sentence explanation>",
  "evidence": ["<direct quote 1>", "<direct quote 2>"],
  "is_industry_standard": <true|false>
}

If a category has no relevant content in this excerpt, omit it entirely — do not return a finding for it."""


# ── Chunking ───────────────────────────────────────────────────────────────────


def _split_into_chunks(text: str) -> list[str]:
    """
    Split text into overlapping chunks of MAX_CHUNK_TOKENS.
    Prefer paragraph boundaries (\n\n) over mid-sentence splits.
    """
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_tokens: list[int] = []
    current_text_parts: list[str] = []
    overlap_buffer: list[str] = []  # last N paragraphs for overlap

    for para in paragraphs:
        para_tokens = _enc.encode(para)

        # If adding this paragraph would exceed chunk size, flush current chunk
        if len(current_tokens) + len(para_tokens) > MAX_CHUNK_TOKENS and current_tokens:
            chunks.append("\n\n".join(current_text_parts))

            # Build overlap: take last paragraphs up to CHUNK_OVERLAP_TOKENS
            overlap_parts: list[str] = []
            overlap_count = 0
            for part in reversed(current_text_parts):
                part_tokens = len(_enc.encode(part))
                if overlap_count + part_tokens > CHUNK_OVERLAP_TOKENS:
                    break
                overlap_parts.insert(0, part)
                overlap_count += part_tokens

            # Start new chunk from overlap
            current_text_parts = overlap_parts
            current_tokens = _enc.encode("\n\n".join(overlap_parts))

        current_text_parts.append(para)
        current_tokens.extend(para_tokens)

    # Flush remainder
    if current_text_parts:
        chunks.append("\n\n".join(current_text_parts))

    logger.info("Split ToS into %d chunks", len(chunks))
    return chunks


# ── LLM call ──────────────────────────────────────────────────────────────────


async def _analyze_chunk(
    client: AsyncOpenAI, chunk: str, chunk_index: int
) -> list[CategoryFinding]:
    """Call the analysis LLM for a single chunk and parse the JSON response."""
    try:
        response = await client.chat.completions.create(
            model=ANALYSIS_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"ToS excerpt:\n\n{chunk}"},
            ],
            temperature=0.1,
            max_tokens=4096,
        )

        raw = response.choices[0].message.content or ""

        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        data: Any = json.loads(raw)
        if not isinstance(data, list):
            data = [data]

        findings: list[CategoryFinding] = []
        for item in data:
            try:
                findings.append(CategoryFinding(**item))
            except (ValidationError, TypeError) as exc:
                logger.warning("Chunk %d: invalid finding skipped: %s", chunk_index, exc)

        logger.info("Chunk %d: got %d findings", chunk_index, len(findings))
        return findings

    except Exception as exc:
        logger.error("Chunk %d analysis failed: %s", chunk_index, exc)
        return []


# ── Node entry point ───────────────────────────────────────────────────────────


async def chunk_and_analyze(state: AppState) -> AppState:
    """
    LangGraph node: split the ToS text into chunks and analyze them in parallel.
    """
    if state.get("error") or not state.get("tos_text"):
        return state

    tos_text: str = state["tos_text"]
    chunks = _split_into_chunks(tos_text)

    client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        default_headers={"HTTP-Referer": HTTP_REFERER},
    )

    # Fire all chunk analyses in parallel
    tasks = [_analyze_chunk(client, chunk, i) for i, chunk in enumerate(chunks)]
    chunk_findings: list[list[CategoryFinding]] = await asyncio.gather(*tasks)

    return {**state, "chunks": chunks, "chunk_findings": chunk_findings}
