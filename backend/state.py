from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel
from typing_extensions import TypedDict


class CategoryFinding(BaseModel):
    """Structured finding for one of the 7 risk categories."""

    category: str
    status: Literal["green", "yellow", "red", "blocker"]
    headline: str      # max 12 words, user-facing
    details: str       # 1-3 sentence explanation
    evidence: list[str]  # direct quotes or clause references from the ToS
    is_industry_standard: bool = False  # True if this is standard legal boilerplate (half-weight deduction)


class FinalReport(BaseModel):
    """Aggregated risk report for a full ToS document."""

    site_name: str
    overall_score: int           # 0–100, higher = safer
    overall_status: Literal["green", "yellow", "red", "blocker"]
    categories: list[CategoryFinding]   # one per category, deduplicated
    analysis_time_seconds: float


class AppState(TypedDict):
    """LangGraph pipeline state passed between all nodes."""

    url: str                                  # input URL
    raw_html: str                             # fetched HTML (may be empty if Playwright used)
    tos_text: str                             # cleaned plaintext
    token_count: int                          # token estimate
    chunks: list[str]                         # split chunks
    chunk_findings: list[list[CategoryFinding]]  # findings per chunk
    final_report: Optional[FinalReport]       # aggregated output
    error: Optional[str]                      # set on failure
