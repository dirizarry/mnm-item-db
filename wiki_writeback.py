#!/usr/bin/env python3
"""Export admin-approved corrections from the service into a wiki write-back manifest.

This is the moderated bridge between the Phase B service and the existing
push_wiki.py tooling. It only ever exports edits a moderator explicitly approved
in the admin UI, and it does NOT touch the wiki itself — a human still reviews the
manifest and runs push_wiki.py per page. That keeps the wiki write-back human-gated.

Usage:
    python wiki_writeback.py                 # read approved edits from the service DB
    python wiki_writeback.py --min-confidence 0.9
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server import db

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "wiki-writeback-queue.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export approved wiki corrections")
    ap.add_argument("--min-confidence", type=float, default=0.0)
    args = ap.parse_args()

    db.migrate()
    approved = [
        e
        for e in db.wiki_queue(state="approved")
        if (e.get("confidence") or 0) >= args.min_confidence
    ]

    manifest = {
        "schema": "mnm-wiki-writeback/v1",
        "count": len(approved),
        "edits": [
            {
                "item": e["item_title"],
                "mob": e["mob_title"],
                "zone": e["zone"],
                "kind": e["edit_kind"],
                "confidence": e["confidence"],
                "observations": e["observations"],
                "reason": e["reason"],
            }
            for e in approved
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT} ({len(approved)} approved edits)")
    if approved:
        print("Next: review the manifest, generate page wikitext, then publish with:")
        print('  python push_wiki.py --page "<Item or Mob page>" --file <generated.wiki>')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
