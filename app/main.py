"""FastAPI service: GET /health, POST /requests. /requests never returns 5xx."""
from __future__ import annotations

import json
import os
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config, llm
from app.pipeline import process_safely, safe_response
from app.schemas import TCCResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("tcc")

app = FastAPI(title="Validus TCC Desk Compliance Agent", version="1.0.0",
              description="Proposes TCC outcomes for emailed requests. Proposes only; never sends or processes.")

# The static frontend (frontend/, e.g. on Netlify) calls this API from another origin.
# CORS_ORIGINS: comma-separated list, default "*" (no cookies/credentials are used).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_data() -> None:
    if not config.DB_PATH.exists() or not config.CLAUSES_PATH.exists():
        log.info("build/ missing - running prepare_data")
        import subprocess
        import sys

        subprocess.run([sys.executable, str(config.ROOT / "scripts" / "prepare_data.py")], check=False)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {"service": "tcc-desk-agent", "endpoints": ["GET /health", "POST /requests"], "llm_enabled": llm.available(),
            "llm_model": config.LLM_MODEL if llm.available() else None}


@app.post("/requests")
async def requests_endpoint(request: Request) -> JSONResponse:
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise ValueError("body must be a JSON object")
    except Exception as e:
        try:
            body = (await request.body()).decode("utf-8", "replace")[:200]
        except Exception:
            body = ""
        return JSONResponse(safe_response({}, None, f"invalid JSON body: {e}; got {body!r}"))
    out = process_safely(raw)
    try:
        TCCResponse.model_validate(out)  # contract check
    except Exception as e:
        log.error("contract validation failed: %s", e)
        out = safe_response(raw, None, f"contract validation failed: {e}")
    return JSONResponse(json.loads(json.dumps(out, default=str)))
