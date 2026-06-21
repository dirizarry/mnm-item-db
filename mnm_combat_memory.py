#!/usr/bin/env python3
"""CLI for combat capture — OCR (UI log) or memory harvest (zone heap)."""

from __future__ import annotations

import argparse
import json
import sys

from client_re.combat_memory import (
    ensure_signatures,
    memory_capture_status,
    poll_combat_lines,
)
from mnm_combat_text import parse_message_list
from mnm_combat_watch import run_combat_watch, run_memory_watch


def main() -> int:
    ap = argparse.ArgumentParser(description="MnM combat capture (OCR or memory)")
    ap.add_argument("--status", action="store_true", help="Print readiness report")
    ap.add_argument("--resolve", action="store_true", help="Resolve and cache GameAssembly signatures")
    ap.add_argument("--scan-once", action="store_true", help="One-shot memory text scan")
    ap.add_argument(
        "--watch",
        action="store_true",
        help="Poll and append to combat-events.json (see --source)",
    )
    ap.add_argument(
        "--source",
        choices=("auto", "ocr", "memory"),
        default="auto",
        help="auto=OCR when combat_region/streams configured, else memory; "
        "ocr=on-screen chat windows; memory=zone heap (won't match combat log UI)",
    )
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--mode", choices=("auto", "text_scan", "structured"), default="auto")
    ap.add_argument("--discover-struct", action="store_true", help="Discover combat buffer layout (needs active combat)")
    ap.add_argument("--json", action="store_true", help="Emit scan results as JSON")
    args = ap.parse_args()

    if args.resolve:
        from client_re.signatures import resolve_signatures

        doc = resolve_signatures()
        print(json.dumps(doc, indent=2))
        return 0

    if args.discover_struct:
        from client_re.discover_combat_struct import discover_and_apply

        doc = discover_and_apply()
        print(json.dumps(doc, indent=2))
        return 0 if doc.get("success") else 1

    if args.status:
        from mnm_combat_watch import resolve_capture_backend
        from mnm_paths import load_settings

        doc = memory_capture_status()
        settings = load_settings()
        doc["capture_source_auto"] = resolve_capture_backend("auto")
        doc["has_ocr_region"] = bool(settings.get("combat_streams") or settings.get("combat_region"))
        print(json.dumps(doc, indent=2))
        return 0 if doc.get("process_running") or doc.get("has_ocr_region") else 1

    if args.scan_once:
        ensure_signatures()
        lines, mode = poll_combat_lines(mode=None if args.mode == "auto" else args.mode)
        if args.json:
            events = parse_message_list(lines)
            for e in events:
                e["source"] = "memory"
                e["memory_mode"] = mode
            print(json.dumps({"mode": mode, "lines": lines, "events": events}, indent=2))
        else:
            print(f"mode={mode} lines={len(lines)}")
            for line in lines[:50]:
                print(line)
            if len(lines) > 50:
                print(f"... ({len(lines) - 50} more)")
        return 0

    if args.watch:
        capture = args.source
        if capture == "auto":
            from mnm_combat_watch import resolve_capture_backend

            capture = resolve_capture_backend("auto")

        if capture == "ocr":
            from mnm_paths import load_settings

            settings = load_settings()
            if not (settings.get("combat_streams") or settings.get("combat_region")):
                print(
                    "No combat_region configured. Run:\n"
                    "  python mnm_combat_capture.py --pick-region\n"
                    "or configure OCR streams in the desktop client.",
                    file=sys.stderr,
                )
                return 1
            print(
                "Watching on-screen combat chat (OCR) → data/combat-events.json\n"
                "Lines match your combat window in chronological order.\n"
                "Press Ctrl+C to stop.\n",
                file=sys.stderr,
            )

            def on_ev(ev: dict) -> None:
                if "error" in ev:
                    print(f"[error] {ev['error']}", file=sys.stderr)
                elif ev.get("amount") or ev.get("kind") in ("death", "cast", "miss"):
                    print(
                        f"[{ev.get('kind')}] {ev.get('raw', '')[:80]}",
                        file=sys.stderr,
                    )

            try:
                summary = run_combat_watch(
                    capture="ocr",
                    interval=max(args.interval, 1.0),
                    memory_mode=None if args.mode == "auto" else args.mode,
                    on_event=on_ev,
                )
            except KeyboardInterrupt:
                print("\nStopped.", file=sys.stderr)
                return 0
            print(json.dumps(summary, indent=2))
            return 0

        mode = None if args.mode == "auto" else args.mode
        print(
            "Memory watch (zone heap — does NOT match on-screen combat log).\n"
            "For chronological pairing with your combat window, use:\n"
            "  python mnm_combat_memory.py --watch --source ocr\n"
            "Press Ctrl+C to stop.\n",
            file=sys.stderr,
        )

        def on_ev(ev: dict) -> None:
            if "error" in ev:
                print(f"[error] {ev['error']}", file=sys.stderr)
            elif ev.get("info"):
                print(f"[info] {ev['info']}", file=sys.stderr)
            elif ev.get("amount"):
                print(
                    f"[{ev.get('kind')}] {ev.get('raw', '')[:80]}",
                    file=sys.stderr,
                )

        try:
            summary = run_memory_watch(
                interval=args.interval,
                once=False,
                memory_mode=mode,
                on_event=on_ev,
            )
        except KeyboardInterrupt:
            print("\nStopped.", file=sys.stderr)
            return 0
        print(json.dumps(summary, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
