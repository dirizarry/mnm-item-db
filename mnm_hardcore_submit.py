#!/usr/bin/env python3
"""Build a community Hardcore standing submission payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mnm_hardcore_parse import parse_char_select_text, profile_token

SCHEMA = "mnm-hardcore-submit/v1"
ROOT = Path(__file__).parent
DATA = ROOT / "data"


def build_submission(
    *,
    character: str,
    server: str,
    level: int,
    zone: str | None,
    race_class: str | None,
    ocr_text: str = "",
    image_sha256: str | None = None,
    submit_id: str | None = None,
    install_id: str | None = None,
) -> dict:
    parsed = parse_char_select_text(ocr_text) if ocr_text else {"hardcore_detected": True, "parse_ok": True}
    now = datetime.now(timezone.utc).isoformat()
    sid = submit_id or str(uuid.uuid4())
    iid = install_id or hashlib.sha256(sid.encode()).hexdigest()[:16]
    anchor = now
    return {
        "schema": SCHEMA,
        "submit_id": sid,
        "batch_id": sid,
        "install_id": iid,
        "generated_at": now,
        "profile": {
            "server": server,
            "character": character,
            "level": int(level),
            "zone": zone,
            "race_class": race_class,
            "status": "magnificent",
            "source": "screenshot",
            "kills": 0,
            "committed_at": anchor,
            "last_seen": anchor,
            "profile_token": profile_token(server, character, anchor),
        },
        "proof": {
            "hardcore_detected": bool(parsed.get("hardcore_detected", True)),
            "parse_ok": bool(parsed.get("parse_ok", True)),
            "ocr_text": (ocr_text or "")[:4000],
            "image_sha256": image_sha256,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build mnm-hardcore-submit/v1 JSON")
    ap.add_argument("--character", required=True)
    ap.add_argument("--server", default="betapvp")
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--zone", default="")
    ap.add_argument("--race-class", default="")
    ap.add_argument("--ocr-file", type=Path, help="OCR text file from screenshot")
    ap.add_argument("--out", type=Path, default=DATA / "hardcore-submit-payload.json")
    args = ap.parse_args()

    ocr = args.ocr_file.read_text(encoding="utf-8") if args.ocr_file and args.ocr_file.is_file() else ""
    payload = build_submission(
        character=args.character,
        server=args.server,
        level=args.level,
        zone=args.zone or None,
        race_class=args.race_class or None,
        ocr_text=ocr,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
