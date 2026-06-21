#!/usr/bin/env python3
"""Bundle personal ledger stats for the main item browser (site/personal.js)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent


def _load(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def build_index(data_dir: Path) -> dict:
    drops = _load(data_dir / "ledger-drops.json", [])
    rates = _load(data_dir / "ledger-drop-rates.json", [])
    manifest = _load(data_dir / "ledger-manifest.json", {})

    by_item: dict[str, list] = defaultdict(list)
    by_mob: dict[str, list] = defaultdict(list)

    for row in drops:
        item = row.get("item_name") or row.get("item_title")
        mob = row.get("mob_name") or row.get("mob_title")
        if not item or not mob:
            continue
        by_item[item].append(
            {
                "mob": mob,
                "zone": row.get("zone"),
                "count": row.get("count", 1),
            }
        )
        by_mob[mob].append(
            {
                "item": item,
                "zone": row.get("zone"),
                "count": row.get("count", 1),
            }
        )

    rate_by_mob: dict[str, dict] = {}
    for mob_row in rates:
        mob = mob_row.get("mob_name")
        if not mob:
            continue
        rate_by_mob[mob] = {
            "kills": mob_row.get("kills", 0),
            "items": {
                it["item_name"]: {
                    "drop_rate": it.get("drop_rate"),
                    "loot_count": it.get("loot_count"),
                }
                for it in (mob_row.get("items") or [])
                if it.get("item_name")
            },
        }

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "install_id": manifest.get("install_id"),
            "characters": manifest.get("characters", []),
            "has_data": bool(drops),
        },
        "byItem": dict(by_item),
        "byMob": dict(by_mob),
        "rates": rate_by_mob,
    }


def main(data_dir: Path | None = None, site_dir: Path | None = None) -> int:
    data_dir = data_dir or ROOT / "data"
    site_dir = site_dir or ROOT / "site"
    bundle = build_index(data_dir)
    js = (
        "window.MNM_PERSONAL = "
        + json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "personal.js").write_text(js, encoding="utf-8")
    n = len(bundle["byItem"])
    print(f"  site/personal.js ({n:,} items with personal drop data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
