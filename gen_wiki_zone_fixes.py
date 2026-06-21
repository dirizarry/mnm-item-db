#!/usr/bin/env python3
"""Generate wiki fix files for zone / dropsfrom normalization.

Fetches live wiki pages, applies formatting fixes, writes to data/wiki-fixes/zones/.
Review with --dry-run via push_wiki.py before publishing.

Usage:
    python gen_wiki_zone_fixes.py --mobs          # Namedmobpage |zone= plain text
    python gen_wiki_zone_fixes.py --items         # Itempage |dropsfrom= zone/mob lines
    python gen_wiki_zone_fixes.py --all
    python gen_wiki_zone_fixes.py --all --limit 5 # pilot
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from mnm_wiki import fetch_contents, parse_params, session
from mnm_zones import (
    canonical_zones,
    format_zone_param,
    load_mob_canon,
    mob_needs_zone_fix,
    normalize_zone_name,
    parse_zone_field,
    sanitize_item_drops,
)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT_DIR = DATA / "wiki-fixes" / "zones"
ITEMS_PATH = DATA / "items.json"
MOBS_PATH = DATA / "monsters.json"

NAMEDMOBPAGE_RE = re.compile(r"(\{\{Namedmobpage)(.*?)(\n\}\}|\}\})", re.DOTALL | re.IGNORECASE)
ITEMPAGE_RE = re.compile(r"(\{\{Itempage)(.*?)(\n\}\}|\}\})", re.DOTALL | re.IGNORECASE)
ZONE_LINE_RE = re.compile(r"^(\|\s*zone\s*=\s*)(.*)$", re.IGNORECASE | re.MULTILINE)
DROPSFROM_LINE_RE = re.compile(r"^(\|\s*dropsfrom\s*=\s*)(.*)$", re.IGNORECASE | re.MULTILINE)


def slug(title: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()[:80]


def fix_namedmobpage_zone(box: str, zones: list[str]) -> str | None:
    p = parse_params(box)
    raw = p.get("zone")
    if not mob_needs_zone_fix(raw, zones):
        return None
    new_val = format_zone_param(zones)
    return ZONE_LINE_RE.sub(rf"\1{new_val}", box, count=1)


def fix_mob_page(text: str, zones: list[str]) -> str | None:
    m = NAMEDMOBPAGE_RE.search(text)
    if not m:
        return None
    prefix, box, suffix = m.group(1), m.group(2), m.group(3)
    new_box = fix_namedmobpage_zone(box, zones)
    if not new_box:
        return None
    return text[: m.start()] + prefix + new_box + suffix + text[m.end() :]


def classify_dropsfrom_links(
    links: list[str],
    mob_canon: dict[str, str],
) -> tuple[list[str], list[str]]:
    zones: list[str] = []
    mobs: list[str] = []
    canon = canonical_zones()
    for link in links:
        if link.startswith("File:"):
            continue
        nz = normalize_zone_name(link)
        if nz and nz in canon:
            if nz not in zones:
                zones.append(nz)
        elif (
            link.strip().casefold() in mob_canon
            or re.match(r"^(a|an)\s+", link, re.I)
            or nz
            and nz not in canon
        ):
            if link not in mobs:
                mobs.append(link)
    return zones, mobs


def format_dropsfrom_block(zones: list[str], mobs: list[str]) -> str:
    lines: list[str] = []
    for z in zones:
        lines.append(f"[[{z}]]")
    for mob in mobs:
        lines.append(f"*[[{mob}]]")
    return "\n".join(lines)


def fix_item_dropsfrom(box: str, mob_canon: dict[str, str]) -> str | None:
    p = parse_params(box)
    raw = p.get("dropsfrom", "")
    if not raw or "not dropped" in raw.lower():
        return None
    all_links: list[str] = []
    for line in raw.splitlines():
        all_links += re.findall(r"\[\[([^\]|]+)", line)
    if not all_links:
        return None
    zones, mobs = classify_dropsfrom_links(all_links, mob_canon)
    cleaned_zones, cleaned_mobs = sanitize_item_drops(zones, mobs, mob_canon)
    new_block = format_dropsfrom_block(cleaned_zones, cleaned_mobs)
    old_block = raw.strip()
    if new_block.strip() == old_block:
        return None
    return DROPSFROM_LINE_RE.sub(
        lambda m: f"{m.group(1)}\n{new_block}",
        box,
        count=1,
    )


def fix_item_page(text: str, mob_canon: dict[str, str]) -> str | None:
    m = ITEMPAGE_RE.search(text)
    if not m:
        return None
    prefix, box, suffix = m.group(1), m.group(2), m.group(3)
    new_box = fix_item_dropsfrom(box, mob_canon)
    if not new_box:
        return None
    return text[: m.start()] + prefix + new_box + suffix + text[m.end() :]


def items_needing_fix(items: list[dict], mob_canon: dict[str, str]) -> list[str]:
    queue_path = DATA / "zones-wiki-queue.json"
    if queue_path.is_file():
        q = json.loads(queue_path.read_text(encoding="utf-8"))
        if q.get("items"):
            return list(q["items"])
    titles: list[str] = []
    for it in items:
        z0 = list(it.get("drops_zones") or [])
        m0 = list(it.get("drops_mobs") or [])
        z1, m1 = sanitize_item_drops(z0, m0, mob_canon)
        if z0 != z1 or m0 != m1:
            titles.append(it["title"])
    return titles


def mobs_needing_fix(mobs: list[dict]) -> list[tuple[str, list[str]]]:
    queue_path = DATA / "zones-wiki-queue.json"
    if queue_path.is_file():
        q = json.loads(queue_path.read_text(encoding="utf-8"))
        if q.get("mobs"):
            return [(m["title"], m["zones"]) for m in q["mobs"]]
    out: list[tuple[str, list[str]]] = []
    for m in mobs:
        raw = m.get("zone")
        zones = parse_zone_field(raw)
        if mob_needs_zone_fix(raw, zones):
            out.append((m["title"], zones))
    return out


def write_manifest(entries: list[dict], path: Path) -> None:
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def gen_mob_fixes(limit: int | None) -> list[dict]:
    mobs = json.loads(MOBS_PATH.read_text(encoding="utf-8"))
    targets = mobs_needing_fix(mobs)
    if limit:
        targets = targets[:limit]
    if not targets:
        print("No mob zone fixes needed.")
        return []

    s = session()
    titles = [t for t, _ in targets]
    zones_by_title = dict(targets)
    print(f"Fetching {len(titles)} mob pages ...")
    contents = fetch_contents(s, titles)

    manifest: list[dict] = []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for title in titles:
        text = contents.get(title, "")
        zones = zones_by_title[title]
        fixed = fix_mob_page(text, zones)
        if not fixed:
            continue
        fname = f"mob-{slug(title)}.wiki"
        out_path = OUT_DIR / fname
        out_path.write_text(fixed, encoding="utf-8")
        manifest.append(
            {
                "page": title,
                "file": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "kind": "mob_zone",
                "zones": zones,
                "summary": "Normalize Namedmobpage zone to plain canonical names",
            }
        )
    write_manifest(manifest, OUT_DIR / "mob-zone-manifest.json")
    print(f"Wrote {len(manifest)} mob fixes -> {OUT_DIR}")
    return manifest


def gen_item_fixes(limit: int | None) -> list[dict]:
    items = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))
    mob_canon = load_mob_canon(MOBS_PATH)
    titles = items_needing_fix(items, mob_canon)
    if limit:
        titles = titles[:limit]
    if not titles:
        print("No item dropsfrom fixes needed.")
        return []

    s = session()
    print(f"Fetching {len(titles)} item pages ...")
    contents = fetch_contents(s, titles)

    manifest: list[dict] = []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for title in titles:
        text = contents.get(title, "")
        fixed = fix_item_page(text, mob_canon)
        if not fixed:
            continue
        fname = f"item-{slug(title)}.wiki"
        out_path = OUT_DIR / fname
        out_path.write_text(fixed, encoding="utf-8")
        manifest.append(
            {
                "page": title,
                "file": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                "kind": "item_dropsfrom",
                "summary": "Normalize Itempage dropsfrom: zones on plain lines, mobs on * bullets",
            }
        )
    write_manifest(manifest, OUT_DIR / "item-dropsfrom-manifest.json")
    print(f"Wrote {len(manifest)} item fixes -> {OUT_DIR}")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mobs", action="store_true", help="Generate mob zone fixes")
    ap.add_argument("--items", action="store_true", help="Generate item dropsfrom fixes")
    ap.add_argument("--all", action="store_true", help="Both --mobs and --items")
    ap.add_argument("--limit", type=int, metavar="N", help="Pilot: only first N pages per kind")
    args = ap.parse_args()
    if not (args.mobs or args.items or args.all):
        ap.error("Specify --mobs, --items, or --all")

    if args.all or args.mobs:
        gen_mob_fixes(args.limit)
    if args.all or args.items:
        gen_item_fixes(args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
