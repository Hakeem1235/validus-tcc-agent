"""Runtime configuration from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("TCC_DATA_DIR", ROOT / "Data"))
BUILD_DIR = Path(os.getenv("TCC_BUILD_DIR", ROOT / "build"))
DB_PATH = BUILD_DIR / "tcc.db"
CLAUSES_PATH = BUILD_DIR / "clauses.json"
RULES_PATH = ROOT / "app" / "policy" / "rules.yaml"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()  # gemini | none
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "30"))

# USD per 1M tokens (input, output). Override with LLM_PRICE_IN / LLM_PRICE_OUT.
PRICE_TABLE = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-2.5-pro": (1.25, 10.00),
}


def price_for(model: str) -> tuple[float, float]:
    if os.getenv("LLM_PRICE_IN") and os.getenv("LLM_PRICE_OUT"):
        return float(os.environ["LLM_PRICE_IN"]), float(os.environ["LLM_PRICE_OUT"])
    for k in sorted(PRICE_TABLE, key=len, reverse=True):
        if model.startswith(k):
            return PRICE_TABLE[k]
    return (0.0, 0.0)
