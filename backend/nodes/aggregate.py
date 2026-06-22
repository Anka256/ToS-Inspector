"""
aggregate.py — Node 4 (final) of the LangGraph pipeline.

Merges per-chunk findings into one FinalReport using a second LLM call
(AGGREGATOR_MODEL) for high-quality deduplication and synthesis.
Falls back to rule-based aggregation if the LLM call fails.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from backend.config import (
    AGGREGATOR_MODEL,
    CATEGORIES,
    HTTP_REFERER,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)
from backend.state import AppState, CategoryFinding, FinalReport

logger = logging.getLogger(__name__)

# Severity ordering for comparison
SEVERITY_ORDER = {"green": 0, "yellow": 1, "red": 2, "blocker": 3}

SCORE_DEDUCTIONS: dict[str, int] = {
    "green": 0,
    "yellow": -5,
    "red": -10,
    "blocker": -20,
}


def _worst_status(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: SEVERITY_ORDER.get(s, 0), default="green")


def _calculate_score(findings: list[CategoryFinding]) -> int:
    score = 100
    for f in findings:
        deduction = SCORE_DEDUCTIONS.get(f.status, 0)
        # Industry-standard boilerplate gets half-weight penalty
        if f.is_industry_standard and deduction < 0:
            deduction = deduction // 2
        score += deduction
    return max(0, min(100, score))


def _rule_based_aggregate(
    all_findings: list[CategoryFinding],
) -> list[CategoryFinding]:
    """
    Fallback aggregation: group by category, keep highest-severity finding,
    merge evidence lists (deduplicated), combine complementary details.
    """
    by_category: dict[str, list[CategoryFinding]] = {}
    for f in all_findings:
        by_category.setdefault(f.category, []).append(f)

    merged: list[CategoryFinding] = []
    for category in CATEGORIES:
        findings = by_category.get(category, [])
        if not findings:
            # No findings for this category — report green (no concerns found)
            merged.append(
                CategoryFinding(
                    category=category,
                    status="green",
                    headline="No significant issues found",
                    details="No relevant clauses were identified in this ToS for this category.",
                    evidence=[],
                )
            )
            continue

        # Keep the finding with the highest severity
        best = max(findings, key=lambda f: SEVERITY_ORDER.get(f.status, 0))

        # Merge evidence from all findings in this category
        seen_evidence: set[str] = set()
        merged_evidence: list[str] = []
        for f in findings:
            for ev in f.evidence:
                norm = ev.strip().lower()
                if norm not in seen_evidence:
                    seen_evidence.add(norm)
                    merged_evidence.append(ev)

        # Combine details if different findings have complementary context
        if len(findings) > 1:
            all_details = list(dict.fromkeys(f.details for f in findings))
            combined_details = " ".join(all_details[:2])  # cap at 2 sentences
        else:
            combined_details = best.details

        merged.append(
            CategoryFinding(
                category=category,
                status=best.status,
                headline=best.headline,
                details=combined_details,
                evidence=merged_evidence[:5],  # cap evidence list
            )
        )

    return merged


AGGREGATOR_SYSTEM = """You are a senior legal analyst.
You will receive a list of findings from different sections of the same Terms of Service document.
Your task: produce ONE consolidated finding per category by:
1. Merging findings for the same category (keeping the most severe status)
2. Combining and deduplicating evidence quotes
3. Writing a clear, final headline (max 12 words) and details (1-3 sentences)
4. Setting is_industry_standard: true if the finding describes unavoidable legal boilerplate
   common to virtually all major platforms (age limits, jurisdiction clauses, standard change notices)

CRITICAL — You must only use these exact 7 category names. Do not create, rename, or merge into new category names:
1. Data Collection & Sharing
2. Content Ownership
3. Account & Service Termination
4. Policy Change Rights
5. Legal Rights & Disputes
6. Payment & Subscription Traps
7. Sensitive & Children's Data

If a finding doesn't fit cleanly into one of these 7, assign it to the closest matching category.

Return ONLY a valid JSON array of exactly 7 objects (one per category). Each object must have:
{
  "category": "<one of the 7 category names above — exactly as written>",
  "status": "<green|yellow|red|blocker>",
  "headline": "<max 12 words>",
  "details": "<1-3 sentences>",
  "evidence": ["<quote>"],
  "is_industry_standard": <true|false>
}

Include ALL 7 categories. For categories with no findings, use status "green" and note no issues found."""


def _llm_aggregate(all_findings: list[CategoryFinding]) -> list[CategoryFinding] | None:
    """Use the aggregator LLM to merge findings intelligently."""
    try:
        client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            default_headers={"HTTP-Referer": HTTP_REFERER},
        )

        findings_json = json.dumps(
            [f.model_dump() for f in all_findings], indent=2
        )

        response = client.chat.completions.create(
            model=AGGREGATOR_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": AGGREGATOR_SYSTEM},
                {"role": "user", "content": f"Findings to merge:\n{findings_json}"},
            ],
            temperature=0.1,
            max_tokens=4096,
        )

        raw = response.choices[0].message.content or ""
        raw = raw.strip()
        # Strip markdown code fences if the model wraps output in ```json ... ```
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw.strip())

        data: Any = json.loads(raw)
        # Model may return {"findings": [...]} or a bare array
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [data])
        if not isinstance(data, list):
            data = [data]

        merged = [CategoryFinding(**item) for item in data]
        # Ensure all 7 categories are present
        present = {f.category for f in merged}
        for cat in CATEGORIES:
            if cat not in present:
                merged.append(
                    CategoryFinding(
                        category=cat,
                        status="green",
                        headline="No significant issues found",
                        details="No relevant clauses were identified for this category.",
                        evidence=[],
                    )
                )

        logger.info("LLM aggregation succeeded: %d categories", len(merged))
        return merged

    except Exception as exc:
        logger.warning("LLM aggregation failed, using rule-based fallback: %s", exc)
        return None


def aggregate(state: AppState) -> AppState:
    """
    LangGraph node: merge all per-chunk findings into a FinalReport.
    """
    if state.get("error") and not state.get("chunk_findings"):
        # Nothing to aggregate — propagate error
        return state

    start_time: float = state.get("_start_time", time.time())  # type: ignore[call-overload]

    # Flatten all findings
    all_findings: list[CategoryFinding] = []
    for chunk_list in state.get("chunk_findings", []):
        all_findings.extend(chunk_list)

    logger.info("Aggregating %d total findings across all chunks", len(all_findings))

    # Try LLM aggregation first; fall back to rule-based
    if all_findings:
        merged = _llm_aggregate(all_findings) or _rule_based_aggregate(all_findings)
    else:
        # No findings at all — all green
        merged = [
            CategoryFinding(
                category=cat,
                status="green",
                headline="No significant issues found",
                details="No relevant clauses were identified for this category.",
                evidence=[],
            )
            for cat in CATEGORIES
        ]

    overall_score = _calculate_score(merged)
    if overall_score >= 75:
        overall_status = "green"
    elif overall_score >= 60:
        overall_status = "yellow"
    elif overall_score >= 40:
        overall_status = "red"
    else:
        overall_status = "blocker"

    # Extract site name from URL
    url: str = state.get("url", "")
    try:
        site_name = urlparse(url).netloc.replace("www.", "")
    except Exception:
        site_name = url

    elapsed = time.time() - start_time

    report = FinalReport(
        site_name=site_name,
        overall_score=overall_score,
        overall_status=overall_status,
        categories=merged,
        analysis_time_seconds=round(elapsed, 1),
    )

    return {**state, "final_report": report}
