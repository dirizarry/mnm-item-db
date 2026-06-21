#!/usr/bin/env python3
"""Build relational drop graph + unified SQLite from items.json and monsters.json.

Outputs:
  data/game.db       — items, monsters, drops, zones tables
  data/drops.json    — edge list for the static site
  data/zones.json    — zone index summary
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from mnm_provenance import client_hid_matches_mob, score_edge
from mnm_zones import (
    load_mob_canon,
    mob_zone_entries,
    normalize_item_drops,
    normalize_mob_record,
    normalize_zone_name,
    write_zone_audit,
)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
ITEMS_PATH = DATA / "items.json"
MOBS_PATH = DATA / "monsters.json"
LEDGER_DROPS_PATH = DATA / "ledger-drops.json"
CROWD_DROPS_PATH = DATA / "crowd-drops.json"
GAME_DB = DATA / "game.db"


def norm_key(title: str) -> str:
    return title.strip().casefold()


def load_json(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_and_normalize(items_path: Path, mobs_path: Path) -> tuple[list[dict], list[dict]]:
    items = load_json(items_path)
    mobs = load_json(mobs_path)
    mob_canon = load_mob_canon(mobs_path)
    for m in mobs:
        m["_zone_raw"] = m.get("zone")
        normalize_mob_record(m)
    for it in items:
        normalize_item_drops(it, mob_canon)
    return items, mobs


def canonical_titles(items: list[dict], mobs: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    item_canon: dict[str, str] = {}
    mob_canon: dict[str, str] = {}
    for it in items:
        t = it.get("title") or it.get("name") or ""
        if t:
            item_canon[norm_key(t)] = t
        if it.get("name"):
            item_canon.setdefault(norm_key(it["name"]), t or it["name"])
    for m in mobs:
        t = m.get("title") or m.get("name") or ""
        if t:
            mob_canon[norm_key(t)] = t
    return item_canon, mob_canon


def resolve_item(name: str, item_canon: dict[str, str]) -> str | None:
    return item_canon.get(norm_key(name))


def resolve_mob(name: str, mob_canon: dict[str, str]) -> str | None:
    return mob_canon.get(norm_key(name))


def build_drops(items: list[dict], mobs: list[dict], ledger_drops: list[dict] | None = None,
                crowd_drops: list[dict] | None = None) -> list[dict]:
    item_canon, mob_canon = canonical_titles(items, mobs)
    edges: dict[tuple, dict] = {}

    def add(item_title: str | None, mob_title: str | None, zone: str | None,
            loot_kind: str, via: str, *, item_hid: str | None = None,
            mob_name: str | None = None, observations: int = 0,
            contributors: int = 0) -> None:
        if not item_title or not mob_title:
            return
        key = (item_title, mob_title, zone or "")
        e = edges.get(key) or {
            "item_title": item_title,
            "mob_title": mob_title,
            "zone": zone,
            "loot_kind": loot_kind,
            "via_mob": False,
            "via_item": False,
            "via_client": False,
            "via_ledger": False,
            "via_crowd": False,
            "observations": 0,
            "contributors": 0,
        }
        if via == "mob":
            e["via_mob"] = True
        elif via == "ledger":
            e["via_ledger"] = True
            e["observations"] += observations
            e["contributors"] = max(e["contributors"], contributors)
        elif via == "crowd":
            e["via_crowd"] = True
            e["observations"] += observations
            e["contributors"] += contributors
        else:
            e["via_item"] = True
        # Client-derived structural confirmation: the item's internal id encodes the mob.
        if item_hid and client_hid_matches_mob(item_hid, mob_name or mob_title):
            e["via_client"] = True
        # prefer finer loot_kind
        rank = {"unique": 4, "known": 3, "common": 2, "drop": 1, "ledger": 1, "crowd": 1}
        if rank.get(loot_kind, 0) > rank.get(e["loot_kind"], 0):
            e["loot_kind"] = loot_kind
        if zone and not e.get("zone"):
            e["zone"] = zone
        edges[key] = e

    for m in mobs:
        mt = m.get("title")
        zone = m.get("zone")
        for it in m.get("unique_loot") or []:
            add(resolve_item(it, item_canon), mt, zone, "unique", "mob")
        for it in m.get("known_loot") or []:
            add(resolve_item(it, item_canon), mt, zone, "known", "mob")
        for it in m.get("common_loot") or []:
            add(resolve_item(it, item_canon), mt, zone, "common", "mob")

    for it in items:
        item_t = it.get("title")
        zones = [z for z in (normalize_zone_name(z) for z in it.get("drops_zones") or []) if z]
        zone = zones[0] if len(zones) == 1 else None
        for mob_name in it.get("drops_mobs") or []:
            mt = resolve_mob(mob_name, mob_canon)
            z = zone
            if not z and len(zones) == 1:
                z = zones[0]
            add(item_t, mt, z, "drop", "item")

    for row in ledger_drops or []:
        item_t = resolve_item(row.get("item_name", ""), item_canon) or row.get("item_name")
        mob_t = resolve_mob(row.get("mob_name", ""), mob_canon) or row.get("mob_name")
        zone = normalize_zone_name(row.get("zone"))
        add(item_t, mob_t, zone, "ledger", "ledger",
            item_hid=row.get("item_hid"), mob_name=row.get("mob_name"),
            observations=int(row.get("count") or 0),
            contributors=len(row.get("sources") or []) or 1)

    for row in crowd_drops or []:
        item_t = resolve_item(row.get("item_name", "") or row.get("item_title", ""), item_canon) \
            or row.get("item_name") or row.get("item_title")
        mob_t = resolve_mob(row.get("mob_name", "") or row.get("mob_title", ""), mob_canon) \
            or row.get("mob_name") or row.get("mob_title")
        zone = normalize_zone_name(row.get("zone"))
        add(item_t, mob_t, zone, "crowd", "crowd",
            item_hid=row.get("item_hid"), mob_name=row.get("mob_name"),
            observations=int(row.get("observations") or 0),
            contributors=int(row.get("contributors") or 0))

    for e in edges.values():
        e.update(score_edge(e))

    return sorted(edges.values(), key=lambda e: (e["item_title"], e["mob_title"]))


def build_zones(mobs: list[dict], drops: list[dict]) -> list[dict]:
    zones: dict[str, dict] = defaultdict(lambda: {"mob_count": 0, "drop_count": 0, "mobs": set()})
    for m in mobs:
        for z in mob_zone_entries(m):
            zones[z]["mob_count"] += 1
            zones[z]["mobs"].add(m["title"])
    for d in drops:
        z = normalize_zone_name(d.get("zone"))
        if z:
            zones[z]["drop_count"] += 1
    out = []
    for name, data in sorted(zones.items()):
        out.append({
            "name": name,
            "mob_count": data["mob_count"],
            "drop_count": data["drop_count"],
        })
    return out


def write_game_db(items: list[dict], mobs: list[dict], drops: list[dict]) -> None:
    if GAME_DB.exists():
        GAME_DB.unlink()
    conn = sqlite3.connect(GAME_DB)
    conn.execute("""
        CREATE TABLE items (
            title TEXT PRIMARY KEY,
            name TEXT,
            slot TEXT,
            dmg REAL,
            delay REAL,
            ac REAL,
            classes TEXT,
            level_acq INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE monsters (
            title TEXT PRIMARY KEY,
            name TEXT,
            race TEXT,
            class TEXT,
            level_min INTEGER,
            level_max INTEGER,
            zone TEXT,
            location TEXT,
            damage_per_hit REAL
        )
    """)
    conn.execute("""
        CREATE TABLE drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_title TEXT NOT NULL,
            mob_title TEXT NOT NULL,
            zone TEXT,
            loot_kind TEXT,
            via_mob INTEGER,
            via_item INTEGER,
            via_client INTEGER,
            via_ledger INTEGER,
            via_crowd INTEGER,
            observations INTEGER,
            contributors INTEGER,
            confidence REAL,
            status TEXT,
            conflict INTEGER,
            UNIQUE(item_title, mob_title, zone)
        )
    """)
    conn.execute("""
        CREATE TABLE zones (
            name TEXT PRIMARY KEY,
            mob_count INTEGER,
            drop_count INTEGER
        )
    """)

    for it in items:
        conn.execute(
            "INSERT OR IGNORE INTO items (title, name, slot, dmg, delay, ac, classes) VALUES (?,?,?,?,?,?,?)",
            (it.get("title"), it.get("name"), it.get("slot"), it.get("dmg"), it.get("delay"),
             it.get("ac"), it.get("classes")),
        )
    for m in mobs:
        conn.execute(
            """INSERT OR IGNORE INTO monsters
               (title, name, race, class, level_min, level_max, zone, location, damage_per_hit)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (m.get("title"), m.get("name"), m.get("race"), m.get("class"),
             m.get("level_min"), m.get("level_max"), m.get("zone"), m.get("location"),
             m.get("damage_per_hit")),
        )
    for d in drops:
        conn.execute(
            """INSERT OR IGNORE INTO drops
               (item_title, mob_title, zone, loot_kind, via_mob, via_item, via_client,
                via_ledger, via_crowd, observations, contributors, confidence, status, conflict)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["item_title"], d["mob_title"], d.get("zone"), d["loot_kind"],
             int(d["via_mob"]), int(d["via_item"]), int(d.get("via_client", False)),
             int(d.get("via_ledger", False)), int(d.get("via_crowd", False)),
             int(d.get("observations", 0)), int(d.get("contributors", 0)),
             float(d.get("confidence", 0.0)), d.get("status"), int(d.get("conflict", False))),
        )
    zones = build_zones(mobs, drops)
    for z in zones:
        conn.execute(
            "INSERT OR IGNORE INTO zones (name, mob_count, drop_count) VALUES (?,?,?)",
            (z["name"], z["mob_count"], z["drop_count"]),
        )
    conn.commit()
    conn.close()


def main() -> int:
    if not ITEMS_PATH.is_file():
        raise SystemExit(f"Missing {ITEMS_PATH}")
    if not MOBS_PATH.is_file():
        raise SystemExit(f"Missing {MOBS_PATH}. Run: python mnm_mob_db.py --all")

    items, mobs = load_and_normalize(ITEMS_PATH, MOBS_PATH)
    if not items:
        raise SystemExit(f"No items in {ITEMS_PATH}")
    if not mobs:
        raise SystemExit(f"No monsters in {MOBS_PATH}")

    ledger_drops = load_json(LEDGER_DROPS_PATH)
    crowd_drops = load_json(CROWD_DROPS_PATH)
    drops = build_drops(items, mobs, ledger_drops, crowd_drops)
    zones = build_zones(mobs, drops)
    write_game_db(items, mobs, drops)

    (DATA / "drops.json").write_text(json.dumps(drops, indent=2, ensure_ascii=False), encoding="utf-8")
    (DATA / "zones.json").write_text(json.dumps(zones, indent=2, ensure_ascii=False), encoding="utf-8")
    audit = write_zone_audit(mobs, items, DATA / "zones-audit.txt")

    linked_items = len({d["item_title"] for d in drops})
    linked_mobs = len({d["mob_title"] for d in drops})
    both = sum(1 for d in drops if d["via_mob"] and d["via_item"])
    ledger_only = sum(1 for d in drops if d.get("via_ledger") and not d["via_mob"] and not d["via_item"])
    ledger_confirmed = sum(1 for d in drops if d.get("via_ledger") and (d["via_mob"] or d["via_item"]))
    confirmed = sum(1 for d in drops if d.get("status") == "confirmed")
    crowd_cand = sum(1 for d in drops if d.get("status") == "crowd_candidate")
    conflicts = sum(1 for d in drops if d.get("conflict"))
    via_client = sum(1 for d in drops if d.get("via_client"))
    avg_conf = (sum(d.get("confidence", 0.0) for d in drops) / len(drops)) if drops else 0.0
    print(f"Relations: {len(drops)} drop links ({linked_items} items, {linked_mobs} mobs, {both} confirmed both sides)")
    if ledger_drops:
        print(f"  Ledger: {len(ledger_drops)} raw links -> {ledger_confirmed} confirmed wiki, {ledger_only} ledger-only")
    if crowd_drops:
        print(f"  Crowd: {len(crowd_drops)} aggregated links merged")
    print(f"  Provenance: {confirmed} confirmed, {via_client} client-encoded, "
          f"{crowd_cand} crowd-candidates (wiki gaps), {conflicts} conflicts to review; "
          f"avg confidence {avg_conf:.2f}")
    print(f"Zones indexed: {len(zones)} (canonical: {audit['canonical']}, with mobs: {audit['zones_with_mobs']})")
    print(f"  {GAME_DB.name}")
    print(f"  drops.json")
    print(f"  zones-audit.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
