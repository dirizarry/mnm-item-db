#!/usr/bin/env python3
"""Bundle ledger analytics for the local stats dashboard (site/stats/)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mnm_ledger_config import ledger_settings

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SITE_STATS = ROOT / "site" / "stats"


def _load(name: str, default):
    path = DATA / name
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_bundle() -> dict:
    manifest = _load("ledger-manifest.json", {})
    if not manifest:
        raise SystemExit("Missing data/ledger-manifest.json — run: python mine_local.py")

    kills = _load("ledger-kills.json", [])
    loot = _load("ledger-loot.json", [])
    coin = _load("ledger-coin.json", [])
    coin_events = _load("ledger-coin-events.json", [])
    drop_rates = _load("ledger-drop-rates.json", [])
    levelups = _load("ledger-levelups.json", [])
    vendor = _load("ledger-vendor-prices.json", [])
    zone_map = _load("zone_map_layout.json", {})

    cfg = ledger_settings()
    upload_url = cfg.get("upload_url")

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "manifest_at": manifest.get("generated_at"),
            "locallow": manifest.get("locallow"),
            "install_id": manifest.get("install_id"),
            "characters": manifest.get("characters", []),
            "servers": manifest.get("servers", []),
            "stats": manifest.get("stats", {}),
            "upload": {
                "schema": "mnm-ledger-upload/v1",
                "endpoint": upload_url,
                "configured": bool(upload_url),
            },
        },
        "zone_map": zone_map,
        "coin": coin,
        "coin_events": coin_events,
        "kills": kills,
        "loot": loot,
        "drop_rates": drop_rates,
        "levelups": levelups[-120:],
        "vendor_prices": sorted(vendor, key=lambda v: -v.get("sell_count", 0))[:40],
    }


def main() -> int:
    bundle = build_bundle()
    SITE_STATS.mkdir(parents=True, exist_ok=True)

    js = (
        "window.MNM_LEDGER_STATS = "
        + json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    (SITE_STATS / "ledger-stats.js").write_text(js, encoding="utf-8")

    payload_path = DATA / "ledger-upload-payload.json"
    if payload_path.is_file():
        import shutil

        shutil.copyfile(payload_path, SITE_STATS / "upload-payload.json")

    kb = (SITE_STATS / "ledger-stats.js").stat().st_size / 1024
    stats = bundle["meta"].get("stats", {})
    print(f"Wrote site/stats/ledger-stats.js ({kb:.0f} KB)")
    print(
        f"  kills={stats.get('kills', 0):,}  loot={stats.get('loot_events', 0):,}  "
        f"mobs={stats.get('mobs', 0):,}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
