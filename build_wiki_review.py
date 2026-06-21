#!/usr/bin/env python3
"""Build the wiki loot-fix review bundle for site/wiki-review/."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mnm_wiki import fetch_contents, session
from wiki_review_state import rejected_ids

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LOOT_DIR = DATA / "wiki-fixes" / "loot"
SITE_REVIEW = ROOT / "site" / "wiki-review"
WIKI_BASE = "https://monstersandmemories.miraheze.org/wiki/"

REVIEW_HEADER_RE = re.compile(
    r"<!--\s*mnm-review\s+(\{.*?\})\s*-->", re.DOTALL
)
LEGACY_HEADER_RE = re.compile(
    r"<!--\s*mnm loot fix:\s*(.+?)\s+adds\s+(\d+)\s+(item|mob)", re.I
)


def wiki_page_url(title: str) -> str:
    return WIKI_BASE + title.replace(" ", "_")


def push_command(page: str, rel_file: str) -> str:
    return f'python push_wiki.py --page "{page}" --file {rel_file} --dry-run'


def make_review_header(*, page: str, kind: str, adds: list[str], new_page: bool = False) -> str:
    meta: dict = {"page": page, "kind": kind, "adds": adds}
    if new_page:
        meta["new_page"] = True
    return f"<!-- mnm-review {json.dumps(meta, ensure_ascii=False)} -->\n"


def parse_fix_file(path: Path) -> tuple[dict | None, str]:
    """Return (metadata, wikitext body without header comment)."""
    text = path.read_text(encoding="utf-8")
    m = REVIEW_HEADER_RE.match(text.lstrip())
    if m:
        meta = json.loads(m.group(1))
        body = text[m.end() :].lstrip("\n")
        return meta, body
    m2 = LEGACY_HEADER_RE.match(text.lstrip())
    if m2:
        page = m2.group(1).strip()
        kind = "mob" if m2.group(3).lower() == "item" else m2.group(3).lower()
        if path.name.startswith("item-"):
            kind = "item"
        elif path.name.startswith("mob-"):
            kind = "mob"
        body = text.split("\n", 1)[1] if "\n" in text else ""
        return {"page": page, "kind": kind, "adds": []}, body.lstrip("\n")
    return None, text


def entry_from_files(
    path: Path,
    *,
    before: str,
    after: str,
    meta: dict,
) -> dict:
    page = meta["page"]
    kind = meta.get("kind") or ("mob" if path.name.startswith("mob-") else "item")
    rel = path.relative_to(ROOT).as_posix()
    return {
        "id": path.stem,
        "kind": kind,
        "page": page,
        "file": rel,
        "adds": meta.get("adds") or [],
        "before": before,
        "after": after,
        "wiki_url": wiki_page_url(page),
        "push_dry": push_command(page, rel),
        "push": push_command(page, rel).replace(" --dry-run", ""),
        "new_page": bool(meta.get("new_page")),
    }


def collect_from_loot_dir(loot_dir: Path | None = None) -> tuple[list[dict], dict]:
    empty_stats = {"skipped_rejected": 0, "skipped_unchanged": 0}
    loot_dir = loot_dir or LOOT_DIR
    if not loot_dir.is_dir():
        return [], empty_stats
    paths = sorted(loot_dir.glob("*.wiki"))
    if not paths:
        return [], empty_stats

    pages: list[str] = []
    parsed: list[tuple[Path, dict, str]] = []
    for path in paths:
        meta, after = parse_fix_file(path)
        if not meta or not meta.get("page"):
            continue
        pages.append(meta["page"])
        parsed.append((path, meta, after))

    sess = session()
    contents = fetch_contents(sess, sorted(set(pages)))
    fold_map = {k.casefold(): v for k, v in contents.items()}

    entries = []
    skipped_rejected = 0
    skipped_unchanged = 0
    reject = rejected_ids()
    for path, meta, after in parsed:
        if path.stem in reject:
            skipped_rejected += 1
            continue
        page = meta["page"]
        before = contents.get(page) or fold_map.get(page.casefold()) or ""
        if before.strip() == after.strip():
            skipped_unchanged += 1
            continue
        entries.append(entry_from_files(path, before=before, after=after, meta=meta))
    stats = {
        "skipped_rejected": skipped_rejected,
        "skipped_unchanged": skipped_unchanged,
    }
    return entries, stats


def write_review_bundle(
    entries: list[dict],
    site_dir: Path | None = None,
    *,
    stats: dict | None = None,
) -> Path:
    site_dir = site_dir or SITE_REVIEW
    site_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
    }
    if stats:
        meta.update(stats)
    bundle = {"meta": meta, "fixes": entries}
    out = site_dir / "review-data.js"
    out.write_text(
        "window.MNM_WIKI_REVIEW = "
        + json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return out


def main() -> int:
    entries, stats = collect_from_loot_dir()
    if not entries:
        print(f"No loot fixes found in {LOOT_DIR}")
        if stats["skipped_unchanged"]:
            print(f"  {stats['skipped_unchanged']} on disk but already match live wiki (pushed or stale)")
        if stats["skipped_rejected"]:
            print(f"  {stats['skipped_rejected']} rejected")
        write_review_bundle([], stats=stats)
        print(f"  Cleared {SITE_REVIEW / 'review-data.js'}")
        return 0
    out = write_review_bundle(entries, stats=stats)
    print(f"Wrote {out} ({len(entries)} fix(es))")
    if stats["skipped_unchanged"]:
        print(f"  Skipped {stats['skipped_unchanged']} unchanged (already on wiki)")
    if stats["skipped_rejected"]:
        print(f"  Skipped {stats['skipped_rejected']} rejected")
    print("Open: site/wiki-review/index.html (serve site/ or repo root over HTTP)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
