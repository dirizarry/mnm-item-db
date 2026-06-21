#!/usr/bin/env python3
"""One-command local play analytics pipeline.

Delegates to sync_manifest.py for the full unified sync loop.

Usage:
    python mine_local.py
    python mine_local.py --upload
    python mine_local.py --wiki --upload
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mnm_ledger_config import ledger_settings
from mnm_local import default_locallow

ROOT = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Mine M&M local logs → full sync")
    ap.add_argument("--path", type=Path, default=None, help="LocalLow Monsters and Memories folder")
    ap.add_argument("--journal-only", action="store_true")
    ap.add_argument("--ledger-only", action="store_true")
    ap.add_argument(
        "--no-site", action="store_true", help="Skip site bundles (ledger extract only)"
    )
    ap.add_argument("--no-upload", action="store_true", help="Skip upload payload")
    ap.add_argument("--upload", action="store_true", help="POST payload if MNM_UPLOAD_URL set")
    ap.add_argument(
        "--upload-dry-run", action="store_true", help="Write data/ledger-upload-payload.json"
    )
    ap.add_argument("--share-characters", action="store_true")
    ap.add_argument("--share-hardcore", action="store_true")
    ap.add_argument("--relations", action="store_true", help="(always on in unified sync)")
    ap.add_argument("--wiki", action="store_true", help="Refresh wiki crawl before sync")
    ap.add_argument("--force", action="store_true", help="Force full ledger re-parse")
    ap.add_argument("--client-re", action="store_true", help="Force client RE refresh")
    args = ap.parse_args()

    if args.journal_only or args.ledger_only or args.no_site:
        # Legacy narrow modes — run ledger extract directly
        from mnm_ledger_db import run as extract_run

        cfg = ledger_settings()
        locallow = args.path or (
            Path(cfg["locallow"]) if cfg.get("locallow") else default_locallow()
        )
        if not locallow.is_dir():
            print(f"LocalLow path not found:\n  {locallow}", file=sys.stderr)
            return 1
        extract_run(
            locallow,
            ledger=not args.journal_only,
            journal=not args.ledger_only,
            force=args.force,
        )
        if not args.no_site and not args.journal_only:
            from build_ledger_site import main as build_stats

            build_stats()
        return 0

    from sync_manifest import main as sync_main

    sys.argv = [str(ROOT / "sync_manifest.py")]
    if args.path:
        sys.argv += ["--path", str(args.path)]
    if args.wiki:
        sys.argv.append("--wiki")
    if args.upload or args.upload_dry_run:
        sys.argv.append("--upload")
    if args.force:
        sys.argv.append("--force")
    if args.client_re:
        sys.argv.append("--client-re")
    return sync_main()


if __name__ == "__main__":
    raise SystemExit(main())
