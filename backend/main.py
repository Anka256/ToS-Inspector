"""
main.py — FastAPI entry point for the ToS Inspector backend.

Run with:
    uvicorn backend.main:app --reload --port 8000

Architecture note:
  Instead of invoking the full LangGraph pipeline as one opaque unit, we call
  the nodes directly in sequence. This lets us short-circuit after the cheap
  fetch+preprocess step on an analysis cache hit, avoiding LLM calls entirely.
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Node functions (called directly so we can cache between steps)
from backend.nodes.aggregate import aggregate
from backend.nodes.cache import get_cached_analysis, save_analysis_cache
from backend.nodes.chunk_and_analyze import chunk_and_analyze
from backend.nodes.fetch_tos import fetch_tos
from backend.nodes.preprocess import preprocess
from backend.state import AppState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ToS Inspector",
    description="Analyzes Terms of Service documents and returns structured risk reports.",
    version="1.0.0",
)

# TODO: restrict to your Railway domain + chrome-extension:// after deploy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit exceeded. Please wait."},
    )


@app.on_event("startup")
async def startup_event():
    os.makedirs("backend/data", exist_ok=True)
    for cache_file in ["backend/data/url_cache.json", "backend/data/analysis_cache.json"]:
        if not os.path.exists(cache_file):
            with open(cache_file, "w") as f:
                f.write("{}")
    logger.info("ToS Inspector backend started successfully")



# ── Request model ──────────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    url: str
    force_refresh: bool = False   # if True, bypass analysis cache and re-run LLMs


# ── Helpers ────────────────────────────────────────────────────────────────────


def normalize_url(raw: str) -> str:
    """
    Add https:// if missing, return root domain URL.
    e.g. "spotify.com" → "https://spotify.com"
    """
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}"


# ── Endpoints ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>ToS Inspector - Privacy Policy</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: #1e293b;
            background-color: #f8fafc;
            margin: 0;
            padding: 40px 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            box-sizing: border-box;
        }
        .card {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            max-width: 600px;
            width: 100%;
        }
        h1 {
            color: #6366f1;
            font-size: 24px;
            margin-bottom: 20px;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 10px;
        }
        p {
            line-height: 1.6;
            font-size: 16px;
            color: #475569;
            margin: 15px 0;
        }
        .highlight {
            font-weight: 500;
            color: #0f172a;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>Privacy Policy</h1>
        <p class="highlight">ToS Inspector does not collect or store any personal user data.</p>
        <p>Analysis is performed on publicly available Terms of Service documents only.</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content, status_code=200)


@app.post("/analyze")
@limiter.limit("20/hour")
async def analyze(request: Request, analyze_request: AnalyzeRequest):
    """
    Runs the ToS analysis pipeline and returns a FinalReport.

    Node execution order:
      fetch_tos → preprocess → [cache check] → chunk_and_analyze → aggregate

    On a cache hit (same ToS content as last time), chunk_and_analyze and
    aggregate are skipped entirely — no LLM calls are made.
    """
    url = normalize_url(analyze_request.url)
    domain = urlparse(url).netloc
    logger.info("Starting analysis for: %s (force_refresh=%s)", url, analyze_request.force_refresh)

    start = time.time()

    initial_state: AppState = {
        "url": url,
        "raw_html": "",
        "tos_text": "",
        "token_count": 0,
        "chunks": [],
        "chunk_findings": [],
        "final_report": None,
        "error": None,
        "_start_time": start,  # type: ignore[typeddict-unknown-key]
    }

    try:
        # ── Step 1: Fetch ToS (cheap — HTTP / Playwright) ──────────────────
        state: AppState = await fetch_tos(initial_state)

        if state.get("error"):
            raise HTTPException(
                status_code=422,
                detail={"error": state["error"], "url": url},
            )

        # ── Step 2: Preprocess (cheap — token counting only) ──────────────
        state = preprocess(state)

        tos_text = state.get("tos_text", "")

        # ── Step 3: Analysis cache check ───────────────────────────────────
        if not analyze_request.force_refresh and tos_text:
            cached_report = get_cached_analysis(domain, tos_text)
            if cached_report:
                logger.info(
                    "Analysis cache hit for %s — returning cached report in %.1fs",
                    domain,
                    time.time() - start,
                )
                return cached_report

        # ── Step 4: LLM analysis (expensive) ──────────────────────────────
        state = await chunk_and_analyze(state)

        if state.get("error") and not state.get("chunk_findings"):
            raise HTTPException(
                status_code=422,
                detail={"error": state["error"], "url": url},
            )

        # ── Step 5: Aggregate findings into FinalReport ────────────────────
        state = aggregate(state)

        report = state.get("final_report")
        if report is None:
            raise HTTPException(
                status_code=422,
                detail={"error": "Analysis produced no report", "url": url},
            )

        report_dict = report.model_dump()

        # ── Step 6: Persist to analysis cache ──────────────────────────────
        if tos_text:
            save_analysis_cache(domain, tos_text, report_dict)

        logger.info(
            "Analysis complete for %s | score=%d | time=%.1fs",
            url,
            report.overall_score,
            report.analysis_time_seconds,
        )
        return report_dict

    except HTTPException:
        raise  # re-raise FastAPI exceptions as-is
    except Exception as exc:
        logger.error("Pipeline error for %s: %s", url, exc)
        raise HTTPException(
            status_code=422,
            detail={"error": str(exc), "url": url},
        )
