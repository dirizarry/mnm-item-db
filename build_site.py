#!/usr/bin/env python3
"""Build the static site data bundle from data/items.json (+ monsters, drops).

Writes site/items.js, site/monsters.js, site/drops.js for file:// or static hosting.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections import defaultdict
from pathlib import Path

from mnm_zones import load_mob_canon, normalize_item_drops, normalize_mob_record

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SITE = ROOT / "site"

ITEM_KEEP = [
    "title", "name", "slot", "skill", "size", "classes", "races",
    "ac", "dmg", "delay", "str", "sta", "agi", "dex", "int", "wis", "cha",
    "hp", "mana", "weight",
    "cold_resist", "fire_resist", "magic_resist", "poison_resist",
    "disease_resist", "electric_resist", "corruption_resist", "holy_resist",
    "magic", "lore", "unique", "nodrop", "effect",
    "source_types", "drops_zones", "drops_mobs", "crafted", "tradeskills",
    "components", "quests", "vendor_value",
]

MOB_KEEP = [
    "title", "name", "race", "class", "level_min", "level_max", "level_label",
    "zone", "zones", "location", "ac", "hp", "damage_per_hit", "attacks_per_round",
    "attack_speed", "special", "known_loot", "common_loot", "unique_loot", "related_quests",
    "categories",
]


def slim_items(rows: list[dict], mob_canon: dict[str, str]) -> list[dict]:
    slim = []
    for r in rows:
        normalize_item_drops(r, mob_canon)
        item = {k: r.get(k) for k in ITEM_KEEP if r.get(k) not in (None, "", False)}
        item["title"] = r.get("title")
        item["name"] = r.get("name") or r.get("title")
        slim.append(item)
    return slim


def slim_mobs(rows: list[dict]) -> list[dict]:
    slim = []
    for r in rows:
        normalize_mob_record(r)
        m = {k: r.get(k) for k in MOB_KEEP if r.get(k) not in (None, "", False, [])}
        m["title"] = r.get("title")
        m["name"] = r.get("name") or r.get("title")
        slim.append(m)
    return slim


def drop_indexes(drops: list[dict]) -> dict:
    by_item: dict[str, list] = defaultdict(list)
    by_mob: dict[str, list] = defaultdict(list)
    for d in drops:
        conf = round(d.get("confidence", 0.0), 2) if d.get("confidence") is not None else None
        by_item[d["item_title"]].append({
            "mob": d["mob_title"],
            "zone": d.get("zone"),
            "kind": d.get("loot_kind"),
            "conf": conf,
            "status": d.get("status"),
            "conflict": bool(d.get("conflict")),
            "you": bool(d.get("via_ledger")),
        })
        by_mob[d["mob_title"]].append({
            "item": d["item_title"],
            "zone": d.get("zone"),
            "kind": d.get("loot_kind"),
            "conf": conf,
            "status": d.get("status"),
            "conflict": bool(d.get("conflict")),
            "you": bool(d.get("via_ledger")),
        })
    return {"byItem": dict(by_item), "byMob": dict(by_mob)}


def main() -> int:
    items_path = DATA / "items.json"
    if not items_path.exists():
        raise SystemExit(f"Missing {items_path}. Run: python mnm_item_db.py --all")
    mob_canon = load_mob_canon(DATA / "monsters.json")
    items = slim_items(json.loads(items_path.read_text(encoding="utf-8")), mob_canon)

    mobs_path = DATA / "monsters.json"
    mobs = slim_mobs(json.loads(mobs_path.read_text(encoding="utf-8"))) if mobs_path.exists() else []

    drops_path = DATA / "drops.json"
    drops_raw = json.loads(drops_path.read_text(encoding="utf-8")) if drops_path.exists() else []
    drops = drop_indexes(drops_raw)

    SITE.mkdir(exist_ok=True)
    meta = {
        "generated": dt.date.today().isoformat(),
        "item_count": len(items),
        "mob_count": len(mobs),
        "drop_links": len(drops_raw),
        "source": "Monsters & Memories wiki",
    }
    (SITE / "items.js").write_text(
        "window.MNM_META = " + json.dumps(meta) + ";\n"
        "window.MNM_ITEMS = " + json.dumps(items, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    (SITE / "monsters.js").write_text(
        "window.MNM_MOBS = " + json.dumps(mobs, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    (SITE / "drops.js").write_text(
        "window.MNM_DROPS = " + json.dumps(drops, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    shutil.copyfile(items_path, SITE / "items.json")
    if mobs_path.exists():
        shutil.copyfile(mobs_path, SITE / "monsters.json")

    size_kb = (SITE / "items.js").stat().st_size / 1024
    mob_kb = (SITE / "monsters.js").stat().st_size / 1024 if mobs else 0
    print(f"Wrote site/items.js ({len(items)} items, {size_kb:.0f} KB)")
    if mobs:
        print(f"Wrote site/monsters.js ({len(mobs)} mobs, {mob_kb:.0f} KB)")
        print(f"Wrote site/drops.js ({len(drops_raw)} drop links)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
