#!/usr/bin/env python3
"""Bundle Magnificent (hardcore) standings for site/hardcore/."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from mnm_ledger_config import ledger_settings

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SITE = ROOT / "site" / "hardcore"


def _load(name: str, default):
    path = DATA / name
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_bundle() -> dict:
    manifest = _load("ledger-manifest.json", {})
    local = _load("ledger-hardcore.json", [])
    crowd = _load("crowd-hardcore.json", [])
    cfg = ledger_settings()
    upload_url = cfg.get("upload_url")

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "manifest_at": manifest.get("generated_at"),
            "install_id": manifest.get("install_id"),
            "servers": manifest.get("servers", []),
            "hardcore_n": len(local) if isinstance(local, list) else 0,
            "crowd_n": len(crowd) if isinstance(crowd, list) else 0,
            "submit": {
                "endpoint": upload_url,
                "configured": bool(upload_url),
            },
        },
        "local": local if isinstance(local, list) else [],
        "crowd": crowd if isinstance(crowd, list) else [],
    }


def main() -> int:
    cfg = ledger_settings()
    upload_url = cfg.get("upload_url")
    bundle = build_bundle()
    SITE.mkdir(parents=True, exist_ok=True)

    js_path = SITE / "hardcore-data.js"
    js_path.write_text(
        "window.MNM_HARDCORE = " + json.dumps(bundle, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    submit_cfg = {
        "endpoint": upload_url,
        "token": cfg.get("upload_token"),
        "configured": bool(upload_url),
    }
    (SITE / "submit-config.js").write_text(
        "window.MNM_HARDCORE_SUBMIT = " + json.dumps(submit_cfg, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    crowd_src = DATA / "crowd-hardcore.json"
    if crowd_src.is_file():
        shutil.copyfile(crowd_src, SITE / "crowd-hardcore.json")
    else:
        (SITE / "crowd-hardcore.json").write_text("[]\n", encoding="utf-8")

    print(f"Wrote {js_path} ({len(bundle['local'])} local, {len(bundle['crowd'])} crowd)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
