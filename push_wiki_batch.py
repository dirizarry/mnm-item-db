#!/usr/bin/env python3
"""Push wiki fixes listed in a gen_wiki_zone_fixes manifest.

Usage:
    python push_wiki_batch.py data/wiki-fixes/zones/mob-zone-manifest.json
    python push_wiki_batch.py data/wiki-fixes/zones/item-dropsfrom-manifest.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path, help="JSON manifest from gen_wiki_zone_fixes.py")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, metavar="N")
    args = ap.parse_args()

    if not args.manifest.is_file():
        raise SystemExit(f"Missing {args.manifest}")

    entries = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.limit:
        entries = entries[: args.limit]

    ok = 0
    for e in entries:
        page = e["page"]
        file = ROOT / e["file"]
        summary = e.get("summary", "Zone normalization fix")
        cmd = [
            sys.executable,
            str(ROOT / "push_wiki.py"),
            "--page",
            page,
            "--file",
            str(file),
            "--summary",
            summary,
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        print(f"{'[dry-run] ' if args.dry_run else ''}{page}")
        r = subprocess.run(cmd)
        if r.returncode == 0:
            ok += 1
        else:
            print(f"  FAILED (exit {r.returncode})", file=sys.stderr)

    print(f"\n{ok}/{len(entries)} succeeded")
    return 0 if ok == len(entries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
