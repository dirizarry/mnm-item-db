#!/usr/bin/env python3
"""Unified sync orchestrator for the local thin client.

Runs the full local-first pipeline in a deterministic order with change detection:
  game patch check → ledger extract → relations → site bundles → crowd → upload

Usage:
    python sync_manifest.py                    # default local sync
    python sync_manifest.py --wiki             # also refresh wiki crawl
    python sync_manifest.py --upload           # POST upload bundle if configured
    python sync_manifest.py --force            # ignore incremental skip
    python sync_manifest.py --json             # machine-readable report
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent


@dataclass
class StepResult:
    name: str
    status: str  # ok | skipped | failed | warning
    detail: str = ""
    changes: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncReport:
    started_at: str
    finished_at: str = ""
    steps: list[StepResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def add(self, step: StepResult) -> None:
        self.steps.append(step)

    def to_dict(self) -> dict:
        return asdict(self)


def _step(name: str, fn, *, skip_reason: str | None = None) -> StepResult:
    if skip_reason:
        return StepResult(name, "skipped", skip_reason)
    try:
        detail, changes = fn()
        return StepResult(name, "ok", detail, changes or {})
    except Exception as exc:
        return StepResult(name, "failed", str(exc))


def detect_game_patch(data_dir: Path) -> StepResult:
    """Fast patch check — compares manifest entry count and key file sizes only."""

    def run():
        from client_re.paths import game_assembly, game_db_path, il2cpp_metadata, install_root
        from client_re.version import read_client_manifest
        from client_re.watch_patch import FP_PATH, load_previous

        install = install_root()
        if not install.is_dir():
            return "Game install not found — client RE skipped", {"patched": False}

        prev = load_previous()
        if not prev:
            return "No client fingerprint baseline yet", {"patched": False, "baseline": str(FP_PATH)}

        changes: list[str] = []
        manifest = read_client_manifest(install)
        if prev.get("manifest_entries") != len(manifest):
            changes.append(f"manifest entries: {prev.get('manifest_entries')} -> {len(manifest)}")

        for label, path in (
            ("game_assembly", game_assembly(install)),
            ("global_metadata", il2cpp_metadata(install)),
            ("game_db", game_db_path(install)),
        ):
            if not path.is_file():
                continue
            st = path.stat()
            old = prev.get(label) or {}
            if old.get("size") and old.get("size") != st.st_size:
                changes.append(f"{label} size: {old.get('size')} -> {st.st_size}")

        patched = bool(changes)
        return (
            f"{'Patch detected' if patched else 'No patch'}: {len(changes)} change(s)",
            {"patched": patched, "changes": changes},
        )

    return _step("game_patch", run)


def extract_ledger(locallow: Path, data_dir: Path, *, incremental: bool, force: bool) -> StepResult:
    def run():
        import mnm_ledger_db
        mnm_ledger_db.OUT = data_dir
        stats = mnm_ledger_db.run(
            locallow, ledger=True, journal=True,
            incremental=incremental, force=force,
        )
        return (
            f"{stats['files']:,} files, {stats['kills']:,} kills, {stats['drops']:,} drops"
            + (" (unchanged — skipped parse)" if stats.get("skipped") else ""),
            {"stats": stats, "skipped": bool(stats.get("skipped"))},
        )

    return _step("ledger_extract", run)


def run_client_re(data_dir: Path, *, force: bool, patch_detected: bool) -> StepResult:
    if not force and not patch_detected:
        return StepResult("client_re", "skipped", "No game patch detected")
    try:
        from mnm_client_db import run_fingerprint, run_crosswalk
        from client_re.paths import DATA_CLIENT, install_root
        import client_re.paths as cr_paths

        cr_paths.DATA_CLIENT = data_dir / "client"
        install = install_root()
        if not install.is_dir():
            return StepResult("client_re", "skipped", "Game install not found")
        run_fingerprint(install)
        run_crosswalk(install)
        from client_re.signatures import resolve_signatures
        from client_re.mnmlib.types import generate_types_catalog
        from client_re.combat_memory import memory_capture_status

        generate_types_catalog()
        sig = resolve_signatures(install)
        mem = memory_capture_status(install)
        detail = (
            f"Fingerprint + crosswalk; signatures {sum(1 for e in sig.get('resolved') or [] if e.get('ok'))} hits; "
            f"memory mode={mem.get('recommended_mode')}"
        )
        return StepResult("client_re", "ok", detail, {"install": str(install), "combat_memory": mem})
    except Exception as exc:
        return StepResult("client_re", "warning", f"Partial: {exc}")


def refresh_wiki(data_dir: Path, site_dir: Path) -> StepResult:
    def run():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "mnm_item_db.py"), "--all"], check=True)
        subprocess.run([sys.executable, str(ROOT / "mnm_mob_db.py"), "--all"], check=True)
        return "Wiki crawl complete", {}

    return _step("wiki_refresh", run)


def build_relations(data_dir: Path) -> StepResult:
    if not (data_dir / "items.json").is_file():
        return StepResult("relations", "skipped", "Missing data/items.json")
    try:
        import build_relations
        build_relations.DATA = data_dir
        build_relations.ITEMS_PATH = data_dir / "items.json"
        build_relations.MOBS_PATH = data_dir / "monsters.json"
        build_relations.LEDGER_DROPS_PATH = data_dir / "ledger-drops.json"
        build_relations.CROWD_DROPS_PATH = data_dir / "crowd-drops.json"
        build_relations.GAME_DB = data_dir / "game.db"
        build_relations.main()
        drops_n = len(json.loads((data_dir / "drops.json").read_text(encoding="utf-8")))
        return StepResult("relations", "ok", f"{drops_n:,} drop edges in game.db", {"drops": drops_n})
    except Exception as exc:
        return StepResult("relations", "failed", str(exc))


def build_site_bundles(data_dir: Path, site_dir: Path) -> StepResult:
    details: list[str] = []
    changes: dict[str, Any] = {}
    try:
        import build_site
        build_site.DATA = data_dir
        build_site.SITE = site_dir
        build_site.main()
        details.append("item browser")
        import build_ledger_site
        build_ledger_site.DATA = data_dir
        build_ledger_site.SITE_STATS = site_dir / "stats"
        build_ledger_site.main()
        details.append("stats dashboard")
        import build_hardcore_site
        build_hardcore_site.main()
        details.append("hardcore board")
        import build_personal_site
        build_personal_site.main(data_dir=data_dir, site_dir=site_dir)
        details.append("personal overlay")
        import build_combat_site
        build_combat_site.main(data_dir=data_dir, site_dir=site_dir)
        details.append("combat stats")
        changes["bundles"] = details
        return StepResult("site_bundles", "ok", ", ".join(details), changes)
    except Exception as exc:
        return StepResult("site_bundles", "failed", str(exc))


def aggregate_crowd(data_dir: Path) -> StepResult:
    inbox = data_dir / "crowd-inbox"
    if not inbox.is_dir() or not any(inbox.glob("*.json")):
        return StepResult("crowd_aggregate", "skipped", "No files in data/crowd-inbox/")

    def run():
        import subprocess
        subprocess.run(
            [sys.executable, str(ROOT / "mnm_crowd_aggregate.py"), "--inbox", str(inbox)],
            check=True,
        )
        return "Crowd inbox aggregated", {}

    return _step("crowd_aggregate", run)


def package_upload(data_dir: Path, site_dir: Path, *, do_upload: bool) -> StepResult:
    if not (data_dir / "ledger-manifest.json").is_file():
        return StepResult("upload", "skipped", "No ledger manifest")
    try:
        from mnm_ledger_config import ledger_settings
        from mnm_ledger_upload import build_payload, upload_payload, write_payload

        cfg = ledger_settings()
        import mnm_ledger_upload
        mnm_ledger_upload.DATA = data_dir
        payload = build_payload(
            share_characters=bool(cfg.get("share_characters")),
            share_hardcore=bool(cfg.get("share_hardcore")),
        )
        out = write_payload(payload, data_dir / "ledger-upload-payload.json")
        site_stats = site_dir / "stats"
        site_stats.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(out, site_stats / "upload-payload.json")
        detail = f"Payload {out.stat().st_size // 1024} KB"
        if do_upload and cfg.get("upload_url"):
            res = upload_payload(payload, cfg["upload_url"], cfg.get("upload_token"))
            detail += f" · HTTP {res['status_code']}"
        elif do_upload:
            detail += " · upload URL not configured"
        return StepResult("upload", "ok", detail, {"path": str(out)})
    except Exception as exc:
        return StepResult("upload", "failed", str(exc))


def run_sync(
    *,
    locallow: Path,
    data_dir: Path | None = None,
    site_dir: Path | None = None,
    incremental: bool = True,
    force: bool = False,
    wiki: bool = False,
    upload: bool = False,
    client_re: bool = False,
) -> SyncReport:
    data_dir = data_dir or ROOT / "data"
    site_dir = site_dir or ROOT / "site"
    report = SyncReport(started_at=datetime.now(timezone.utc).isoformat())

    patch_step = detect_game_patch(data_dir)
    report.add(patch_step)
    patch_detected = patch_step.changes.get("patched", False)

    if wiki:
        report.add(refresh_wiki(data_dir, site_dir))

    report.add(extract_ledger(locallow, data_dir, incremental=incremental, force=force))

    if client_re or patch_detected:
        report.add(run_client_re(data_dir, force=client_re, patch_detected=patch_detected))

    report.add(aggregate_crowd(data_dir))
    report.add(build_relations(data_dir))
    report.add(build_site_bundles(data_dir, site_dir))
    report.add(package_upload(data_dir, site_dir, do_upload=upload))

    ok = sum(1 for s in report.steps if s.status == "ok")
    failed = sum(1 for s in report.steps if s.status == "failed")
    report.summary = {"ok": ok, "failed": failed, "skipped": len(report.steps) - ok - failed}
    report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


def print_report(report: SyncReport) -> None:
    print(f"\n=== Sync complete ({report.summary.get('ok', 0)} ok, "
          f"{report.summary.get('failed', 0)} failed) ===")
    for step in report.steps:
        mark = {"ok": "+", "skipped": "-", "failed": "!", "warning": "~"}.get(step.status, "?")
        print(f"  [{mark}] {step.name}: {step.detail}")
    print()


def main() -> int:
    from mnm_ledger_config import ledger_settings
    from mnm_local import default_locallow

    ap = argparse.ArgumentParser(description="Unified MnM Item DB sync")
    ap.add_argument("--path", type=Path, default=None, help="LocalLow game logs folder")
    ap.add_argument("--data", type=Path, default=None, help="Data output directory")
    ap.add_argument("--site", type=Path, default=None, help="Site output directory")
    ap.add_argument("--wiki", action="store_true", help="Refresh wiki crawl before sync")
    ap.add_argument("--upload", action="store_true", help="POST upload bundle if URL configured")
    ap.add_argument("--client-re", action="store_true", help="Force client RE refresh")
    ap.add_argument("--force", action="store_true", help="Force full ledger re-parse")
    ap.add_argument("--no-incremental", action="store_true", help="Disable incremental ledger skip")
    ap.add_argument("--json", action="store_true", help="Print JSON report")
    args = ap.parse_args()

    cfg = ledger_settings()
    locallow = args.path or (Path(cfg["locallow"]) if cfg.get("locallow") else default_locallow())
    if not locallow.is_dir():
        print(f"LocalLow path not found: {locallow}", file=sys.stderr)
        return 1

    report = run_sync(
        locallow=locallow,
        data_dir=args.data,
        site_dir=args.site,
        incremental=not args.no_incremental,
        force=args.force,
        wiki=args.wiki,
        upload=args.upload,
        client_re=args.client_re,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_report(report)
    return 1 if report.summary.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
