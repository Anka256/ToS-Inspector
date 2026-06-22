# ToS Inspector

**AI-powered Terms of Service risk analysis — right in your browser's side panel.**

---

## Architecture

```
Chrome Extension (Side Panel)
     │  POST /analyze { url }
     ▼
FastAPI Backend  →  LangGraph Pipeline
                       fetch_tos → preprocess → chunk_and_analyze → aggregate
                                                        ↓
                                               asyncio.gather() — parallel LLM calls
```

---

## Quick Start

### 1. Backend Setup

```bash
cd "ToS Inspector"

# Create & activate venv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure API key
cp .env.example .env
# Edit .env — add your OPENROUTER_API_KEY from https://openrouter.ai/

# Start the server
uvicorn backend.main:app --reload --port 8000
```

### 2. Chrome Extension Setup

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder from this project
5. Click the ToS Inspector icon in the toolbar → Side panel opens

---

## How It Works

| Step | Node | Description |
|------|------|-------------|
| 1 | `fetch_tos` | 3-tier fetching: known paths → DuckDuckGo search → Playwright headless |
| 2 | `preprocess` | Token counting with tiktoken; intelligent truncation if > 80k tokens |
| 3 | `chunk_and_analyze` | Split into 6k-token chunks; parallel async LLM analysis via OpenRouter |
| 4 | `aggregate` | Merge findings per category; calculate risk score (0–100) |

---

## Risk Categories

| # | Category | Key Concerns |
|---|----------|-------------|
| 1 | Data Collection & Sharing | Third-party sharing, ad targeting, data sale |
| 2 | Content Ownership | Platform license on uploads, deletion rights |
| 3 | Account & Service Termination | No-warning bans, data export |
| 4 | Policy Change Rights | Unilateral changes, notification obligations |
| 5 | Legal Rights & Disputes | Mandatory arbitration, class action waiver |
| 6 | Payment & Subscription Traps | Auto-renewal, hidden fees |
| 7 | Sensitive & Children's Data | Health/location data, COPPA, GDPR |

---

## Score System

| Status | Color | Score Impact |
|--------|-------|-------------|
| green | 🟢 | 0 |
| yellow | 🟡 | −5 per finding |
| red | 🔴 | −15 per finding |
| blocker | 🟣 | −25 per finding |

---

## Models Used (via OpenRouter)

- **Analysis**: `google/gemini-flash-2.5` — fast parallel chunk processing
- **Aggregation**: `anthropic/claude-haiku-4` — high-quality deduplication

---

## File Structure

```
ToS Inspector/
├── backend/
│   ├── main.py              # FastAPI app + /analyze endpoint
│   ├── config.py            # Models, tokens, categories
│   ├── graph.py             # LangGraph pipeline definition
│   ├── state.py             # TypedDict + Pydantic models
│   └── nodes/
│       ├── fetch_tos.py     # 3-tier ToS fetching
│       ├── preprocess.py    # Token counting & truncation
│       ├── chunk_and_analyze.py  # Parallel LLM analysis
│       └── aggregate.py     # Report assembly
├── extension/
│   ├── manifest.json        # Manifest V3
│   ├── background.js        # Service worker
│   ├── sidepanel.html       # UI structure
│   ├── sidepanel.css        # Dark glassmorphism design
│   ├── sidepanel.js         # All UI logic
│   └── icons/               # Extension icons
├── requirements.txt
├── .env.example
└── notes.txt
```
