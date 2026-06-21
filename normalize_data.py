#!/usr/bin/env python3
"""Persist zone-normalized monsters.json and items.json to data/.

Usage:
    python normalize_data.py              # normalize + overwrite JSON
    python normalize_data.py --backup     # keep dated .bak copies first
    python normalize_data.py --audit-only # report only, no writes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mnm_zones import (
    discover_alias_candidates,
    load_mob_canon,
    normalize_item_drops,
    normalize_mob_record,
    persist_normalized_data,
    write_zone_audit,
)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
ITEMS_PATH = DATA / "items.json"
MOBS_PATH = DATA / "monsters.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backup", action="store_true", help="Save .bak-YYYY-MM-DD before overwrite")
    ap.add_argument("--audit-only", action="store_true", help="Write zones-audit.txt only")
    args = ap.parse_args()

    if not ITEMS_PATH.is_file():
        raise SystemExit(f"Missing {ITEMS_PATH}")
    if not MOBS_PATH.is_file():
        raise SystemExit(f"Missing {MOBS_PATH}")

    raw_mobs = json.loads(MOBS_PATH.read_text(encoding="utf-8"))
    alias_candidates = discover_alias_candidates(raw_mobs)

    if args.audit_only:
        items = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))
        mobs = list(raw_mobs)
        mob_canon = load_mob_canon(MOBS_PATH)
        for m in mobs:
            normalize_mob_record(m)
        for it in items:
            normalize_item_drops(it, mob_canon)
        audit = write_zone_audit(mobs, items, DATA / "zones-audit.txt")
        print(f"Audit only -> zones-audit.txt ({audit['zones_with_mobs']} zones with mobs)")
        return 0

    items, mobs, audit = persist_normalized_data(ITEMS_PATH, MOBS_PATH, backup=args.backup)

    print(f"Normalized {len(items)} items, {len(mobs)} monsters")
    print(f"  zones indexed: {audit['zones_with_mobs']} ({audit['canonical']} canonical)")
    print(f"  unknown item drops: {audit['unknown_item_drops']}")
    print(f"  noncanonical item zones: {audit['noncanonical_item_zones']}")
    if alias_candidates:
        print(f"  alias candidates from raw mob zones: {len(alias_candidates)}")
        for raw, canon in sorted(alias_candidates.items()):
            print(f"    {raw!r} -> {canon!r}")
    print(f"  {ITEMS_PATH.name}")
    print(f"  {MOBS_PATH.name}")
    print(f"  zones-audit.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
