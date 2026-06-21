"""Crosswalk ledger item_hids against client bundles and wiki items."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from client_re.mnm_bundle import read_file
from client_re.paths import ROOT, bundles_dir, install_root

LEDGER_ITEMS = ROOT / "data" / "ledger-items.json"
WIKI_ITEMS = ROOT / "data" / "items.json"


def _load_ledger_keys() -> list[dict]:
    if not LEDGER_ITEMS.is_file():
        return []
    rows = json.loads(LEDGER_ITEMS.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        hid = r.get("item_hid")
        name = r.get("name")
        if hid and name:
            out.append({"item_hid": hid, "name": name})
    return out


def _wiki_name_index() -> dict[str, str]:
    if not WIKI_ITEMS.is_file():
        return {}
    items = json.loads(WIKI_ITEMS.read_text(encoding="utf-8"))
    idx: dict[str, str] = {}
    for it in items:
        t = it.get("title") or it.get("name")
        if t:
            idx[t.strip().casefold()] = t
    return idx


def scan_bundle_for_needles(path: Path, needles: list[bytes]) -> list[str]:
    try:
        stripped, _ = read_file(path)
    except (OSError, ValueError):
        return []
    return [n.decode("utf-8") for n in needles if n in stripped]


def crosswalk(root: Path | None = None, max_bundles: int = 0) -> dict:
    root = install_root(root)
    ledger = _load_ledger_keys()
    wiki_idx = _wiki_name_index()
    needles = [r["item_hid"].encode("utf-8") for r in ledger]
    {r["item_hid"]: r["name"] for r in ledger}

    bdir = bundles_dir(root)
    bundle_paths = sorted(bdir.glob("*.bundle")) if bdir.is_dir() else []
    if max_bundles:
        bundle_paths = bundle_paths[:max_bundles]

    hits: dict[str, list[str]] = {}
    for bp in bundle_paths:
        found = scan_bundle_for_needles(bp, needles)
        for hid in found:
            hits.setdefault(hid, []).append(bp.name)

    rows = []
    in_bundles = 0
    in_wiki = 0
    for r in ledger:
        hid = r["item_hid"]
        name = r["name"]
        bundle_files = hits.get(hid, [])
        wiki_title = wiki_idx.get(name.casefold())
        if bundle_files:
            in_bundles += 1
        if wiki_title:
            in_wiki += 1
        rows.append(
            {
                "item_hid": hid,
                "name": name,
                "wiki_title": wiki_title,
                "in_wiki": bool(wiki_title),
                "in_client_bundles": bool(bundle_files),
                "bundle_hits": bundle_files,
            }
        )

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "install_root": str(root),
        "ledger_items": len(ledger),
        "bundles_scanned": len(bundle_paths),
        "plaintext_hid_hits": in_bundles,
        "wiki_name_matches": in_wiki,
        "rows": rows,
        "interpretation": (
            "Zero plaintext_hid_hits is expected: item keys are Odin-serialized, not plain strings. "
            "Use Il2CppDumper + asset candidate blobs for static extraction, or runtime dump (Phase 4)."
        ),
    }


def write_crosswalk(out: Path, root: Path | None = None) -> dict:
    doc = crosswalk(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
