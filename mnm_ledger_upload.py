#!/usr/bin/env python3
"""Package ledger analytics for optional upload to the MNM Item DB site.

Builds an aggregated, privacy-conscious payload from data/ledger-*.json.
Upload is a stub until a server endpoint exists — dry-run always writes
data/ledger-upload-payload.json.

Usage:
    python mnm_ledger_upload.py --dry-run
    python mnm_ledger_upload.py --upload   # POST if MNM_UPLOAD_URL is set
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from mnm_ledger_config import ledger_settings

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SCHEMA = "mnm-ledger-upload/v2"
# v2 adds per-observation dedup tokens so the server can UNION observations across
# users/re-uploads instead of summing them. See PROVENANCE.md.
TOKEN_SCHEME = "mnm-dedup/v1"


def _load(path: Path) -> list | dict:
    if not path.is_file():
        return [] if path.name != "ledger-manifest.json" else {}
    return json.loads(path.read_text(encoding="utf-8"))


def _top_drop_rates(rows: list[dict], limit: int = 60) -> list[dict]:
    out = []
    for row in sorted(rows, key=lambda r: -r.get("kills", 0))[:limit]:
        items = sorted(row.get("items") or [], key=lambda i: -i.get("loot_count", 0))[:8]
        out.append(
            {
                "mob_name": row.get("mob_name"),
                "zone": row.get("zone"),
                "kills": row.get("kills"),
                "loot_events": row.get("loot_events"),
                "loots_per_kill": row.get("loots_per_kill"),
                "items": items,
            }
        )
    return out


def _scrub_heatmap(heatmap: list[dict], share_characters: bool) -> list[dict]:
    """Drop character names from heatmap cells unless the user opted in to sharing.

    `server` is a shard name (not PII) and is kept; `character` is the player identity.
    """
    if share_characters:
        return heatmap if isinstance(heatmap, list) else []
    return [
        {k: v for k, v in cell.items() if k != "character"}
        for cell in (heatmap if isinstance(heatmap, list) else [])
    ]


def _loot_confirmations(drops: list[dict], limit: int = 500) -> list[dict]:
    """Wiki-enrichment tuples: item, mob, zone, observed count + dedup tokens."""
    rows = sorted(drops, key=lambda d: -d.get("count", 0))[:limit]
    return [
        {
            "item_name": d.get("item_name"),
            "item_hid": d.get("item_hid"),
            "mob_name": d.get("mob_name"),
            "zone": d.get("zone"),
            "count": d.get("count"),
            # Hashed per-observation identities for cross-user / idempotent dedup.
            "dedup_tokens": d.get("dedup_tokens") or [],
        }
        for d in rows
    ]


def _hardcore_profiles(rows: list[dict]) -> list[dict]:
    return [
        {
            "server": r.get("server"),
            "character": r.get("character"),
            "level": r.get("level"),
            "zone": r.get("zone"),
            "kills": r.get("kills"),
            "status": r.get("status"),
            "committed_at": r.get("committed_at"),
            "last_seen": r.get("last_seen"),
            "profile_token": r.get("profile_token"),
            "source": r.get("source"),
        }
        for r in rows
        if r.get("status") in {"magnificent", "candidate"}
    ]


def build_payload(*, share_characters: bool = False, share_hardcore: bool = False) -> dict:
    manifest = _load(DATA / "ledger-manifest.json")
    if not manifest:
        raise SystemExit("Missing data/ledger-manifest.json — run: python mine_local.py")

    heatmap = _load(DATA / "ledger-kill-heatmap.json")
    drop_rates = _load(DATA / "ledger-drop-rates.json")
    drops = _load(DATA / "ledger-drops.json")
    levelups = _load(DATA / "ledger-levelups.json")
    mobs = _load(DATA / "ledger-mobs.json")
    vendor = _load(DATA / "ledger-vendor-prices.json")

    install_id = manifest.get("install_id")
    if not install_id:
        install_id = hashlib.sha256(str(manifest.get("locallow", "")).encode()).hexdigest()[:16]

    payload = {
        "schema": SCHEMA,
        "token_scheme": TOKEN_SCHEME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "install_id": install_id,
        "batch_id": str(uuid.uuid4()),
        "client": "mnm-item-db",
        "manifest": {
            "generated_at": manifest.get("generated_at"),
            "stats": manifest.get("stats"),
            "locallow_hint": Path(str(manifest.get("locallow", ""))).name,
        },
        "summary": manifest.get("stats", {}),
        "heatmap": _scrub_heatmap(heatmap, share_characters),
        "drop_rates": _top_drop_rates(drop_rates if isinstance(drop_rates, list) else []),
        "loot_confirmations": _loot_confirmations(drops if isinstance(drops, list) else []),
        "levelups_by_day": _levelups_by_day(
            levelups if isinstance(levelups, list) else [], share_characters
        ),
        "top_mobs": [
            {
                "name": m.get("name"),
                "kill_count": m.get("kill_count"),
                "level_min": m.get("level_min"),
                "level_max": m.get("level_max"),
                "zones": m.get("zones"),
                "dedup_tokens": m.get("dedup_tokens") or [],
            }
            for m in sorted(
                mobs if isinstance(mobs, list) else [], key=lambda m: -m.get("kill_count", 0)
            )[:40]
        ],
        "vendor_prices": sorted(
            vendor if isinstance(vendor, list) else [],
            key=lambda v: -v.get("sell_count", 0),
        )[:80],
    }
    if share_characters:
        payload["characters"] = manifest.get("characters", [])
        payload["servers"] = manifest.get("servers", [])
    if share_characters and share_hardcore:
        hardcore = _load(DATA / "ledger-hardcore.json")
        payload["hardcore_profiles"] = _hardcore_profiles(
            hardcore if isinstance(hardcore, list) else []
        )
    return payload


def _levelups_by_day(levelups: list[dict], share_characters: bool) -> list[dict]:
    rows = []
    for lu in levelups:
        row = {
            "day": lu.get("day"),
            "new_level": lu.get("new_level"),
            "old_level": lu.get("old_level"),
            "zone": lu.get("zone"),
        }
        if share_characters:
            row["character"] = lu.get("character")
        rows.append(row)
    return rows


def write_payload(payload: dict, path: Path | None = None) -> Path:
    path = path or DATA / "ledger-upload-payload.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def upload_payload(payload: dict, url: str, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", "X-MNM-Schema": SCHEMA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    return {"status_code": resp.status_code, "body": resp.text[:2000]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build / upload ledger analytics bundle")
    ap.add_argument(
        "--dry-run", action="store_true", help="Write payload only (default without --upload)"
    )
    ap.add_argument(
        "--upload", action="store_true", help="POST payload when MNM_UPLOAD_URL is configured"
    )
    ap.add_argument(
        "--share-characters", action="store_true", help="Include character names in payload"
    )
    ap.add_argument(
        "--share-hardcore",
        action="store_true",
        help="Include Magnificent standings (requires --share-characters)",
    )
    args = ap.parse_args()

    cfg = ledger_settings()
    share = args.share_characters or bool(cfg.get("share_characters"))
    share_hc = args.share_hardcore or bool(cfg.get("share_hardcore"))
    payload = build_payload(share_characters=share, share_hardcore=share_hc)
    out = write_payload(payload)
    kb = out.stat().st_size / 1024
    print(f"Wrote {out} ({kb:.0f} KB, schema {SCHEMA})")

    if args.upload:
        url = cfg.get("upload_url")
        if not url:
            print("Upload skipped: set MNM_UPLOAD_URL in config/ledger.env")
            print("Stub endpoint shape: POST /api/ledger/v1/ingest with JSON body")
            return 0
        result = upload_payload(payload, url, cfg.get("upload_token"))
        print(f"Upload -> HTTP {result['status_code']}")
        if result["status_code"] >= 400:
            print(result["body"])
            return 1
        print("Upload accepted (stub — verify server implements ingest).")
    else:
        print("Dry-run only. Use --upload when MNM_UPLOAD_URL is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
