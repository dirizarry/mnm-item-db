#!/usr/bin/env python3
"""Extract monster/NPC combat data from the M&M wiki ({{Namedmobpage}}).

Crawls Category:NPCs and keeps pages with the Namedmobpage template (skips merchants).

Usage:
    python mnm_mob_db.py --pilot 50
    python mnm_mob_db.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from mnm_wiki import (
    category_members,
    fetch_contents,
    parse_level,
    parse_params,
    session,
    strip_markup,
    wiki_links,
)
from mnm_zones import parse_zone_field

OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

MOB_COLUMNS = [
    "title",
    "name",
    "format",
    "race",
    "class",
    "level_min",
    "level_max",
    "level_label",
    "zone",
    "zones",
    "location",
    "ac",
    "hp",
    "damage_per_hit",
    "attacks_per_round",
    "attack_speed",
    "special",
    "known_loot",
    "common_loot",
    "unique_loot",
    "related_quests",
    "opposing_factions",
    "categories",
    "raw_len",
]
JSON_FIELDS = {
    "zones",
    "known_loot",
    "common_loot",
    "unique_loot",
    "related_quests",
    "opposing_factions",
    "categories",
}


def extract_namedmobpage(text: str) -> str | None:
    m = re.search(r"\{\{Namedmobpage(.*?)\n\}\}", text, re.DOTALL | re.IGNORECASE)
    if not m:
        m = re.search(r"\{\{Namedmobpage(.*?)\}\}", text, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def num(val: str | None) -> float | int | None:
    if not val:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", strip_markup(val))
    if not m:
        return None
    f = float(m.group())
    return int(f) if f.is_integer() else f


def parse_mob(title: str, text: str) -> dict | None:
    box = extract_namedmobpage(text)
    if box is None:
        return None
    p = parse_params(box)
    lvl_min, lvl_max = parse_level(p.get("level"))
    zones = parse_zone_field(p.get("zone"))
    rec = {
        "title": title,
        "name": title,
        "format": "namedmob",
        "raw_len": len(text),
        "race": strip_markup(p.get("race")) or None,
        "class": strip_markup(p.get("class")) or None,
        "level_min": lvl_min,
        "level_max": lvl_max,
        "level_label": strip_markup(p.get("level")) or None,
        "zone": zones[0] if zones else None,
        "zones": zones,
        "location": strip_markup(p.get("location")) or None,
        "ac": num(p.get("ac")),
        "hp": num(p.get("hp")),
        "damage_per_hit": num(p.get("damage_per_hit")),
        "attacks_per_round": strip_markup(p.get("attacks_per_round")) or None,
        "attack_speed": strip_markup(p.get("attack_speed")) or None,
        "special": strip_markup(p.get("special")) or None,
        "known_loot": wiki_links(p.get("known_loot")),
        "common_loot": wiki_links(p.get("common_loot")),
        "unique_loot": wiki_links(p.get("unique_loot")),
        "related_quests": wiki_links(p.get("related_quests")),
        "opposing_factions": wiki_links(p.get("opposing_factions")),
        "categories": re.findall(r"\[\[Category:([^\]]+)\]\]", text),
    }
    return rec


def normalize_row(rec: dict) -> dict:
    row = {}
    for col in MOB_COLUMNS:
        v = rec.get(col)
        if col in JSON_FIELDS and v is not None:
            v = json.dumps(v, ensure_ascii=False)
        row[col] = v
    return row


def write_outputs(rows: list[dict], tag: str) -> tuple[Path, Path, Path]:
    json_path = OUT_DIR / f"monsters{tag}.json"
    db_path = OUT_DIR / f"monsters{tag}.db"
    report_path = OUT_DIR / f"monsters{tag}-report.txt"

    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    cols_def = ", ".join(f'"{c}"' for c in MOB_COLUMNS)
    conn.execute(f"CREATE TABLE monsters ({cols_def})")
    placeholders = ", ".join("?" for _ in MOB_COLUMNS)
    conn.executemany(
        f"INSERT INTO monsters VALUES ({placeholders})",
        [tuple(normalize_row(r)[c] for c in MOB_COLUMNS) for r in rows],
    )
    conn.commit()
    conn.close()

    with_loot = sum(
        1 for r in rows if r.get("known_loot") or r.get("common_loot") or r.get("unique_loot")
    )
    with_zone = sum(1 for r in rows if r.get("zones"))
    with_level = sum(1 for r in rows if r.get("level_min") is not None)
    lines = [
        f"M&M monster extraction report ({tag or 'full'})",
        f"Total mobs: {len(rows)}",
        f"With zone: {with_zone}",
        f"With level: {with_level}",
        f"With any loot listed: {with_loot}",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, db_path, report_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", type=int, metavar="N")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--category", default="Category:NPCs")
    args = ap.parse_args()

    s = session()
    print(f"Listing {args.category} ...")
    pool = category_members(s, args.category, None if args.all else max(args.pilot * 3, 200))
    print(f"  {len(pool)} pages")

    if args.all:
        titles = pool
        tag = ""
    else:
        titles = pool[: args.pilot * 3]
        tag = "-pilot"

    print(f"Fetching {len(titles)} pages ...")
    contents = fetch_contents(s, titles)

    rows: list[dict] = []
    skipped = 0
    for t in titles:
        rec = parse_mob(t, contents.get(t, ""))
        if rec:
            rows.append(rec)
        else:
            skipped += 1

    if not args.all:
        rows = rows[: args.pilot]

    json_path, db_path, report_path = write_outputs(rows, tag)
    print(f"\nParsed {len(rows)} mobs ({skipped} non-combat/merchant pages skipped).")
    print(f"  {json_path.name}")
    print(f"  {db_path.name}")
    print(f"  {report_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
