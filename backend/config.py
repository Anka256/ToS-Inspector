import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

ANALYSIS_MODEL: str = "google/gemini-2.5-flash"
AGGREGATOR_MODEL: str = "anthropic/claude-haiku-4.5"

MAX_CHUNK_TOKENS: int = 6000
CHUNK_OVERLAP_TOKENS: int = 600   # ~10%
MAX_TOTAL_TOKENS: int = 80000     # hard cap before chunking

CATEGORIES: list[str] = [
    "Data Collection & Sharing",
    "Content Ownership",
    "Account & Service Termination",
    "Policy Change Rights",
    "Legal Rights & Disputes",
    "Payment & Subscription Traps",
    "Sensitive & Children's Data",
]

HTTP_REFERER: str = "https://tos-inspector.local"
