#!/usr/bin/env python3
"""Generate wiki fix files for missing loot lines from crowd-confirmed drops.

Reads data/drops.json for edges where the mob page lacks known_loot or the item
page lacks dropsfrom. Uses the wiki's dropsfrom layout: zone headers on plain
[[Zone]] lines, mobs on * [[mob]] bullets (no inline zone suffix).

Usage:
    python gen_wiki_loot_fixes.py                  # all candidates
    python gen_wiki_loot_fixes.py --min-confidence 0.7
    python gen_wiki_loot_fixes.py --limit 20       # pilot batch
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from mnm_wiki import fetch_contents, parse_params, session, wiki_links
from mnm_zones import normalize_zone_name

from build_wiki_review import entry_from_files, make_review_header, write_review_bundle
from wiki_page_stubs import stub_item_page, stub_namedmob_page
from wiki_review_state import rejected_ids

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT_DIR = DATA / "wiki-fixes" / "loot"

NAMEDMOBPAGE_RE = re.compile(r"(\{\{Namedmobpage)(.*?)(\n\}\}|\}\})", re.DOTALL | re.IGNORECASE)
ITEMPAGE_RE = re.compile(r"(\{\{Itempage)(.*?)(\n\}\}|\}\})", re.DOTALL | re.IGNORECASE)
LOOT_FIELDS = ("known_loot", "common_loot", "unique_loot")
WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def wiki_title_key(title: str) -> str:
    """Loose match for wiki titles that differ by spaces vs hyphens."""
    return re.sub(r"[\s\-_]+", " ", title.strip()).casefold()


def title_matches(a: str, b: str) -> bool:
    return wiki_title_key(a) == wiki_title_key(b)

def replace_multiline_param(box: str, key: str, new_value: str) -> str:
    key_fold = key.lower()
    parts = re.split(r"(\n\s*\|)", box)
    out: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        if i + 1 < len(parts) and re.fullmatch(r"\n\s*\|", parts[i + 1]) and "=" in part:
            param_key, _, _ = part.partition("=")
            pk = param_key.strip().lstrip("|").strip().lower()
            if pk == key_fold:
                out.append(part.partition("=")[0] + "=")
                out.append("\n")
                out.append(new_value.rstrip())
                out.append(parts[i + 1])
                i += 2
                continue
        out.append(part)
        i += 1
    return "".join(out)


def slug(title: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()[:80]


def load_items_index() -> dict[str, dict]:
    path = DATA / "items.json"
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {it["title"]: it for it in rows if it.get("title")}


def _has_empirical(d: dict) -> bool:
    return bool(d.get("via_ledger") or d.get("via_crowd") or (d.get("observations") or 0) > 0)


def load_mobs_index() -> dict[str, dict]:
    path = DATA / "monsters.json"
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {m["title"]: m for m in rows if m.get("title")}


def mob_lists_item(mob_rec: dict, item_title: str) -> bool:
    for field in LOOT_FIELDS:
        if any(title_matches(i or "", item_title) for i in mob_rec.get(field) or []):
            return True
    return False


def edge_needs_mob_fix(edge: dict, mobs_index: dict[str, dict]) -> bool:
    if edge.get("via_mob"):
        return False
    mob = edge.get("mob_title") or ""
    item = edge.get("item_title") or ""
    mob_rec = mobs_index.get(mob)
    if mob_rec and mob_lists_item(mob_rec, item):
        return False
    return _has_empirical(edge)


def edge_needs_item_fix(edge: dict, items_index: dict[str, dict]) -> bool:
    if edge.get("via_item"):
        return False
    item = edge.get("item_title") or ""
    mob = edge.get("mob_title") or ""
    it = items_index.get(item)
    if it:
        if any(title_matches(m or "", mob) for m in it.get("drops_mobs") or []):
            return False
    return _has_empirical(edge)


def load_candidates(min_conf: float, items_index: dict[str, dict], mobs_index: dict[str, dict]) -> list[dict]:
    path = DATA / "drops.json"
    if not path.is_file():
        return []
    drops = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for d in drops:
        if float(d.get("confidence") or 0) < min_conf:
            continue
        if edge_needs_mob_fix(d, mobs_index) or edge_needs_item_fix(d, items_index):
            out.append(d)
    return sorted(out, key=lambda x: -float(x.get("confidence") or 0))


def _page_text(contents: dict[str, str], title: str) -> str:
    if title in contents:
        return contents[title]
    fold = title.casefold()
    for key, text in contents.items():
        if key.casefold() == fold:
            return text
    return ""


def parse_dropsfrom_sections(raw: str) -> tuple[list[str], list[list]]:
    """Return preamble lines and ordered [[zone], [mob, ...]] sections."""
    preamble: list[str] = []
    sections: list[list] = []
    current_zone: str | None = None
    current_mobs: list[str] = []

    def flush() -> None:
        nonlocal current_zone, current_mobs
        if current_zone is not None or current_mobs:
            sections.append([current_zone, current_mobs])
        current_zone = None
        current_mobs = []

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        zm = re.fullmatch(r"\[\[([^\]|]+)\]\]", s)
        if zm:
            flush()
            current_zone = zm.group(1).strip()
            continue
        mob_names = [name.strip() for name in WIKI_LINK_RE.findall(s)]
        if mob_names:
            for name in mob_names:
                if not any(title_matches(name, m) for m in current_mobs):
                    current_mobs.append(name)
        else:
            if current_zone is None and not current_mobs:
                preamble.append(line.rstrip())
            elif current_mobs:
                current_mobs[-1] = f"{current_mobs[-1]}\n{line.rstrip()}"
    flush()
    return preamble, sections


def format_dropsfrom_block(preamble: list[str], sections: list[list]) -> str:
    lines = list(preamble)
    for zone, mobs in sections:
        if zone:
            lines.append(f"[[{zone}]]")
        for mob in mobs:
            lines.append(f"* [[{mob}]]")
    return "\n".join(lines)


def mob_loot_from_box(box: str) -> set[str]:
    p = parse_params(box)
    listed: set[str] = set()
    for field in LOOT_FIELDS:
        for link in wiki_links(p.get(field)):
            listed.add(wiki_title_key(link))
    return listed


def mob_lists_item_in_box(box: str, item_title: str) -> bool:
    return wiki_title_key(item_title) in mob_loot_from_box(box)


def pick_loot_field(box: str) -> str:
    p = parse_params(box)
    if (p.get("common_loot") or "").strip():
        return "common_loot"
    if (p.get("known_loot") or "").strip():
        return "known_loot"
    if (p.get("unique_loot") or "").strip():
        return "unique_loot"
    return "common_loot"


def append_mob_loot(box: str, item_title: str) -> str | None:
    if mob_lists_item_in_box(box, item_title):
        return None
    field = pick_loot_field(box)
    p = parse_params(box)
    existing = (p.get(field) or "").strip()
    new_line = f"* [[{item_title}]]"
    new_val = f"{existing}\n{new_line}".strip() if existing else new_line
    return replace_multiline_param(box, field, new_val)


def fix_mob_page(text: str, item_title: str) -> str | None:
    nm = NAMEDMOBPAGE_RE.search(text)
    if not nm:
        return None
    prefix, box, suffix = nm.group(1), nm.group(2), nm.group(3)
    new_box = append_mob_loot(box, item_title)
    if not new_box:
        return None
    return text[: nm.start()] + prefix + new_box + suffix + text[nm.end() :]


def mob_in_sections(mob_title: str, sections: list[list]) -> bool:
    return any(
        any(title_matches(m, mob_title) for m in mobs)
        for _, mobs in sections
    )


def append_dropsfrom(box: str, mob_title: str, zone: str | None) -> str | None:
    p = parse_params(box)
    existing = (p.get("dropsfrom") or "").strip()
    if not existing or "not dropped" in existing.lower():
        return None

    preamble, sections = parse_dropsfrom_sections(existing)
    if mob_in_sections(mob_title, sections):
        return None

    nz = normalize_zone_name(zone) if zone else None
    if nz:
        for sec in sections:
            z = sec[0]
            if z and z.casefold() == nz.casefold():
                sec[1].append(mob_title)
                break
        else:
            sections.append([nz, [mob_title]])
    elif sections:
        sections[-1][1].append(mob_title)
    else:
        sections.append([None, [mob_title]])

    new_val = format_dropsfrom_block(preamble, sections)
    if new_val.strip() == existing.strip():
        return None
    return replace_multiline_param(box, "dropsfrom", new_val)


def fix_item_page(text: str, mob_title: str, zone: str | None) -> str | None:
    im = ITEMPAGE_RE.search(text)
    if not im:
        return None
    prefix, box, suffix = im.group(1), im.group(2), im.group(3)
    new_box = append_dropsfrom(box, mob_title, zone)
    if not new_box:
        return None
    return text[: im.start()] + prefix + new_box + suffix + text[im.end() :]


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate wiki loot fix wikitext from drop candidates")
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0, help="Max drop edges to process (0 = all; not page count)")
    ap.add_argument("--dry-run", action="store_true", help="List candidates only")
    ap.add_argument(
        "--create-missing",
        action="store_true",
        help="Stub new wiki pages when the mob/item page does not exist yet (review before push)",
    )
    args = ap.parse_args()

    items_index = load_items_index()
    mobs_index = load_mobs_index()
    candidates = load_candidates(args.min_confidence, items_index, mobs_index)
    if args.limit:
        candidates = candidates[: args.limit]

    if not candidates:
        print("No loot fix candidates found in data/drops.json")
        return 0

    mob_candidates = [c for c in candidates if edge_needs_mob_fix(c, mobs_index)]
    item_candidates = [c for c in candidates if edge_needs_item_fix(c, items_index)]

    print(
        f"Found {len(candidates)} edge(s): "
        f"{len(mob_candidates)} mob-page, {len(item_candidates)} item-page"
    )
    if args.dry_run:
        for c in candidates[:30]:
            flags = []
            if edge_needs_mob_fix(c, mobs_index):
                flags.append("mob")
            if edge_needs_item_fix(c, items_index):
                flags.append("item")
            print(
                f"  {c.get('confidence', 0):.2f}  {c['item_title']} <- {c['mob_title']}  "
                f"({c.get('status')}) [{'/'.join(flags)}]"
            )
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sess = session()
    titles = sorted(
        {c["item_title"] for c in item_candidates} | {c["mob_title"] for c in mob_candidates}
    )
    print(f"Fetching {len(titles)} wiki page(s)…")
    contents = fetch_contents(sess, titles)

    rejected = rejected_ids()
    written = 0
    skipped_rejected = 0
    skipped_no_wiki = 0
    stubbed_pages = 0
    review_entries: list[dict] = []
    mob_edges: dict[str, list[dict]] = {}
    item_edges: dict[str, list[dict]] = {}
    for edge in mob_candidates:
        mob_edges.setdefault(edge["mob_title"], []).append(edge)
    for edge in item_candidates:
        item_edges.setdefault(edge["item_title"], []).append(edge)

    for mob, edges in mob_edges.items():
        mob_text = _page_text(contents, mob)
        new_page = False
        if not mob_text:
            if not args.create_missing:
                skipped_no_wiki += 1
                print(f"  skip mob (no wiki page): {mob}")
                continue
            zones = [
                normalize_zone_name(e.get("zone")) or e.get("zone")
                for e in edges
                if e.get("zone")
            ]
            mob_text = stub_namedmob_page(mob, [z for z in zones if z])
            new_page = True
            stubbed_pages += 1
            print(f"  mob stub (new page): {mob}")
        mob_fix = mob_text
        applied = []
        for edge in edges:
            next_fix = fix_mob_page(mob_fix, edge["item_title"])
            if next_fix:
                mob_fix = next_fix
                applied.append(edge["item_title"])
        if applied and mob_fix != mob_text:
            out = OUT_DIR / f"mob-{slug(mob)}.wiki"
            fix_id = out.stem
            if fix_id in rejected:
                skipped_rejected += 1
                print(f"  skip mob (rejected): {mob}")
                continue
            header = make_review_header(page=mob, kind="mob", adds=applied, new_page=new_page)
            out.write_text(header + mob_fix, encoding="utf-8")
            review_entries.append(
                entry_from_files(
                    out,
                    before=mob_text if not new_page else "",
                    after=mob_fix,
                    meta={"page": mob, "kind": "mob", "adds": applied, "new_page": new_page},
                )
            )
            written += 1
            print(f"  mob fix: {out.name} (+{len(applied)} items)")

    for item, edges in item_edges.items():
        item_text = _page_text(contents, item)
        new_page = False
        if not item_text:
            if not args.create_missing:
                skipped_no_wiki += 1
                print(f"  skip item (no wiki page): {item}")
                continue
            item_rec = items_index.get(item)
            if not item_rec:
                for it in items_index.values():
                    if title_matches(it.get("title") or "", item):
                        item_rec = it
                        break
            item_text = stub_item_page(item, item_rec)
            new_page = True
            stubbed_pages += 1
            print(f"  item stub (new page): {item}")
        item_fix = item_text
        applied = []
        for edge in edges:
            next_fix = fix_item_page(item_fix, edge["mob_title"], edge.get("zone"))
            if next_fix:
                item_fix = next_fix
                applied.append(f"{edge['mob_title']}" + (f" @ {edge.get('zone')}" if edge.get("zone") else ""))
        if applied and item_fix != item_text:
            out = OUT_DIR / f"item-{slug(item)}.wiki"
            fix_id = out.stem
            if fix_id in rejected:
                skipped_rejected += 1
                print(f"  skip item (rejected): {item}")
                continue
            adds_clean = [a.split(" @ ")[0] for a in applied]
            header = make_review_header(page=item, kind="item", adds=adds_clean, new_page=new_page)
            out.write_text(header + item_fix, encoding="utf-8")
            review_entries.append(
                entry_from_files(
                    out,
                    before=item_text if not new_page else "",
                    after=item_fix,
                    meta={"page": item, "kind": "item", "adds": adds_clean, "new_page": new_page},
                )
            )
            written += 1
            print(f"  item fix: {out.name} (+{len(applied)} mobs)")

    print(f"Wrote {written} wikitext file(s) to {OUT_DIR}")
    if skipped_no_wiki:
        print(
            f"  Skipped {skipped_no_wiki} with no wiki page"
            " — re-run with --create-missing to generate stubs"
        )
    if stubbed_pages:
        print(f"  {stubbed_pages} new page stub(s) (review carefully before push)")
    if skipped_rejected:
        print(f"  Skipped {skipped_rejected} rejected page(s) — see data/wiki-fixes/loot/review-state.json")
    review_path = write_review_bundle(
        review_entries,
        stats={
            "candidate_edges": len(candidates),
            "written": written,
            "skipped_rejected": skipped_rejected,
            "skipped_no_wiki": skipped_no_wiki,
            "stubbed_pages": stubbed_pages,
        },
    )
    print(f"Review UI: {review_path.relative_to(ROOT)}")
    print("  Open http://127.0.0.1:<port>/site/wiki-review/index.html (serve repo root over HTTP)")
    print("  Or: python -m http.server 8080  from site/ -> http://localhost:8080/wiki-review/")
    print("Publish after review: python push_wiki.py --page \"<Title>\" --file <path>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
