"""Phase B service: ingest API + shared DB + aggregation/trust + moderated wiki queue.

Run:
    pip install -r server/requirements.txt
    uvicorn server.app:app --reload --port 8000

Auth (env vars):
    MNM_ADMIN_TOKEN     required for /api/admin/* (set a strong secret)
    MNM_INGEST_TOKEN    optional; if set, ingest requires this bearer token
    MNM_ALLOW_ANONYMOUS default "1"; set "0" to require MNM_INGEST_TOKEN

Identity model (Phase B step 1): anonymous opaque install_id for contributors, a
shared admin token for moderators. Discord OAuth for per-user/guild accounts is the
planned next step (see SERVER.md) and slots in behind the same admin dependency.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import db
from .aggregate import run_aggregation

ACCEPTED_SCHEMAS = {"mnm-ledger-upload/v1", "mnm-ledger-upload/v2", "mnm-hardcore-submit/v1"}
MAX_BYTES = int(os.environ.get("MNM_MAX_BYTES", "2000000"))
RATE_PER_HOUR = int(os.environ.get("MNM_RATE_PER_HOUR", "30"))

app = FastAPI(title="MnM Item DB Service", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Ensure schema exists as soon as the app module loads (idempotent, forward-only).
db.migrate()


@app.on_event("startup")
def _startup() -> None:
    db.migrate()


def require_admin(authorization: str = Header(default="")) -> str:
    token = os.environ.get("MNM_ADMIN_TOKEN")
    if not token:
        raise HTTPException(503, "admin disabled: set MNM_ADMIN_TOKEN")
    if authorization != f"Bearer {token}":
        raise HTTPException(401, "unauthorized")
    return "admin"


# --- public / ingest ------------------------------------------------------------

@app.get("/api/ledger/v1/health")
def health() -> dict:
    return {"ok": True, "schema": sorted(ACCEPTED_SCHEMAS), "stats": db.stats()}


@app.post("/api/ledger/v1/ingest")
async def ingest(request: Request, authorization: str = Header(default=""),
                 x_mnm_schema: str = Header(default="")) -> JSONResponse:
    ingest_token = os.environ.get("MNM_INGEST_TOKEN")
    allow_anon = os.environ.get("MNM_ALLOW_ANONYMOUS", "1") == "1"
    if ingest_token:
        if authorization != f"Bearer {ingest_token}":
            raise HTTPException(401, "unauthorized")
    elif not allow_anon:
        raise HTTPException(503, "ingest disabled")

    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "payload too large")
    try:
        import json
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "invalid json")

    schema = payload.get("schema") or x_mnm_schema
    if schema not in ACCEPTED_SCHEMAS:
        raise HTTPException(422, f"unsupported schema; accepted {sorted(ACCEPTED_SCHEMAS)}")

    install_id = str(payload.get("install_id") or "anon")[:64]
    batch_id = str(payload.get("batch_id") or uuid.uuid4())[:64]
    share = bool(payload.get("characters"))

    if db.recent_payload_count(install_id, 3600) >= RATE_PER_HOUR:
        raise HTTPException(429, "rate limited")

    stored = db.record_payload(install_id, batch_id, schema, share, payload)
    return JSONResponse(
        status_code=202 if stored else 200,
        content={"accepted": stored, "duplicate": not stored, "batch_id": batch_id},
    )


@app.get("/api/data/stats")
def data_stats() -> dict:
    return db.stats()


@app.get("/api/data/drops")
def data_drops(status: str | None = None, limit: int = 1000, offset: int = 0) -> dict:
    limit = max(1, min(limit, 5000))
    return {"drops": db.dataset_drops(status=status, limit=limit, offset=offset)}


@app.delete("/api/data/install/{install_id}")
def forget(install_id: str) -> dict:
    """Self-service right-to-be-forgotten: knowledge of the opaque install_id authorizes deletion."""
    removed = db.forget_install(install_id[:64])
    return {"forgotten": install_id[:64], "payloads_removed": removed}


# --- admin: aggregation + moderation -------------------------------------------

@app.post("/api/admin/aggregate")
def admin_aggregate(_: str = Depends(require_admin)) -> dict:
    return run_aggregation()


@app.get("/api/admin/conflicts")
def admin_conflicts(limit: int = 500, _: str = Depends(require_admin)) -> dict:
    return {"conflicts": db.dataset_drops(status="crowd_candidate", limit=limit)}


@app.get("/api/admin/wiki-queue")
def admin_wiki_queue(state: str = "pending", _: str = Depends(require_admin)) -> dict:
    return {"queue": db.wiki_queue(state=state or None)}


@app.post("/api/admin/wiki-queue/{queue_id}/decide")
def admin_decide(queue_id: int, state: str, _: str = Depends(require_admin)) -> dict:
    if state not in {"approved", "rejected"}:
        raise HTTPException(400, "state must be 'approved' or 'rejected'")
    ok = db.decide_wiki(queue_id, state, by="admin")
    if not ok:
        raise HTTPException(404, "queue item not found or already decided")
    return {"id": queue_id, "state": state}


@app.get("/api/admin/wiki-export")
def admin_wiki_export(_: str = Depends(require_admin)) -> dict:
    """Approved corrections, shaped for the existing push_wiki.py write-back tooling."""
    approved = db.wiki_queue(state="approved")
    return {
        "schema": "mnm-wiki-export/v1",
        "edits": [
            {
                "item": e["item_title"],
                "mob": e["mob_title"],
                "zone": e["zone"],
                "kind": e["edit_kind"],
                "confidence": e["confidence"],
                "observations": e["observations"],
            }
            for e in approved
        ],
    }


@app.get("/admin")
def admin_ui() -> FileResponse:
    return FileResponse(Path(__file__).parent / "admin.html")
