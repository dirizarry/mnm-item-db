#!/usr/bin/env python3
"""Combat chat capture CLI — OCR a dedicated in-game combat window for damage/healing.

The game routes Combat/Ability/Buff/Death messages to configurable chat windows.
Use the built-in ``combat`` window with large font + high contrast for best results.

Usage:
    python mnm_combat_capture.py --layout          # show window/channel routing + region estimate
    python mnm_combat_capture.py --setup            # print OCR setup recommendations
    python mnm_combat_capture.py --region 3260 827 620 293 --once   # single OCR sample
    python mnm_combat_capture.py --pick-region      # visual drag-to-select region picker
    python mnm_combat_capture.py --watch            # continuous capture (Ctrl+C to stop)
    python mnm_combat_capture.py --parse-file combat-sample.txt    # test parser only

Requires (Windows):
    pip install -r requirements-combat.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mnm_chat_windows import load_layout, pick_character_dir, setup_recommendations
from mnm_combat_ocr import available_backends, ocr_region, ocr_region_lines
from mnm_combat_text import parse_lines
from mnm_combat_watch import EVENTS_PATH, LIVE_PATH, reparse_state_frame, run_watch
from mnm_local import default_locallow
from mnm_paths import data_dir, load_settings, save_settings


def _print_layout(locallow: Path) -> int:
    layout = load_layout(locallow)
    if layout.get("error"):
        print(layout["error"])
        return 1
    print(f"Character: {layout['server']}/{layout['character']}")
    print(f"Resolution: {layout.get('resolution')}  UI scale: {layout.get('ui_scale')}")
    print(f"Combat channels routed: {layout['combat_channel_count']}")
    print(f"Meter-relevant: {len(layout.get('combat_meter_channels') or [])} categories")
    est = layout.get("combat_region_estimate")
    if est:
        print(f"Estimated region: left={est['left']} top={est['top']} "
              f"width={est['width']} height={est['height']} ({est['source']})")
    print(f"OCR backends: {', '.join(available_backends()) or 'NONE — install requirements-combat.txt'}")
    return 0


def _print_setup(locallow: Path) -> int:
    layout = load_layout(locallow)
    for tip in setup_recommendations(layout):
        print(f"  • {tip}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture combat chat via OCR (Option C)")
    ap.add_argument("--path", type=Path, default=None, help="LocalLow root")
    ap.add_argument("--layout", action="store_true", help="Show chat window layout + region estimate")
    ap.add_argument("--setup", action="store_true", help="Print in-game setup tips for OCR")
    ap.add_argument("--region", nargs=4, type=int, metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"),
                    help="Screen capture rectangle (pixels)")
    ap.add_argument("--watch", action="store_true", help="Continuous OCR until interrupted")
    ap.add_argument("--once", action="store_true", help="Single OCR pass (with --region or saved region)")
    ap.add_argument("--interval", type=float, default=1.5, help="Poll interval seconds (--watch)")
    ap.add_argument("--backend", choices=["windows", "tesseract"], default=None)
    ap.add_argument("--parse-file", type=Path, help="Parse a text file (no OCR)")
    ap.add_argument("--save-region", action="store_true",
                    help="Save --region to client-settings.json as combat_region")
    ap.add_argument("--pick-region", action="store_true",
                    help="Open visual region picker and save to client-settings.json")
    ap.add_argument("--export-filters", action="store_true",
                    help="Write data/combat-filter-ui.json from in-game menu catalog")
    ap.add_argument("--reparse-frame", action="store_true",
                    help="Re-parse last OCR frame rows from combat-capture-state.json")
    args = ap.parse_args()

    if args.export_filters:
        from mnm_combat_channels import write_filter_ui

        out = data_dir() / "combat-filter-ui.json"
        doc = write_filter_ui(out)
        print(f"Wrote {out} ({len(doc.get('presets', {}))} presets, menu keys: {list(doc.get('menu', {}).keys())})")
        return 0

    if args.reparse_frame:
        summary = reparse_state_frame()
        print(f"Raw OCR rows: {summary['raw_row_count']} -> merged lines: {summary['merged_line_count']}")
        print(f"Parsed events: {summary['parsed_from_frame']}")
        print(f"Damage out: {summary['damage_out']}  in: {summary['damage_in']}")
        print(f"Heal out: {summary['heal_out']}  in: {summary['heal_in']}")
        for i, line in enumerate(summary.get("merged_lines") or [], 1):
            print(f"  {i:2}. {line}")
        return 0

    if args.pick_region:
        from mnm_region_selector import pick_screen_region, region_to_str
        from mnm_game_window import attach_window_lock, game_window_status

        region = pick_screen_region()
        if not region:
            print("Region pick cancelled.")
            return 1
        region = attach_window_lock(region)
        settings = load_settings()
        settings["combat_region"] = region
        path = save_settings(settings)
        lock_note = (
            f" — {game_window_status()}"
            if region.get("window_lock")
            else " — game window not found; using screen pixels"
        )
        print(f"Saved combat_region {region_to_str(region)} to {path}{lock_note}")
        return 0

    if args.parse_file:
        text = args.parse_file.read_text(encoding="utf-8", errors="replace")
        events = parse_lines(text)
        print(json.dumps(events, indent=2, ensure_ascii=False))
        print(f"Parsed {len(events)} events from {args.parse_file}")
        return 0

    locallow = args.path or default_locallow()
    if args.layout:
        return _print_layout(locallow)
    if args.setup:
        return _print_setup(locallow)

    settings = load_settings()
    region = None
    if args.region:
        l, t, w, h = args.region
        region = {"left": l, "top": t, "width": w, "height": h, "source": "cli"}
    elif settings.get("combat_region"):
        region = dict(settings["combat_region"])
    else:
        layout = load_layout(locallow)
        region = layout.get("combat_region_estimate")

    if not region:
        print("No capture region. Run --layout for an estimate or pass --region L T W H")
        return 1

    if args.save_region and args.region:
        settings["combat_region"] = region
        path = save_settings(settings)
        print(f"Saved combat_region to {path}")

    if not available_backends():
        print("No OCR backend available. pip install -r requirements-combat.txt")
        return 1

    window_lock = bool(settings.get("combat_window_lock", True))

    if args.once:
        lines = ocr_region_lines(region, backend=args.backend, window_lock=window_lock)
        print(f"--- {len(lines)} OCR lines ---")
        for i, line in enumerate(lines, 1):
            print(f"{i:2}. {line}")
        events = parse_lines("\n".join(lines))
        print(f"--- Parsed {len(events)} events ---")
        for e in events[:20]:
            print(e)
        return 0

    if args.watch:
        from mnm_combat_streams import resolve_capture_streams
        from mnm_combat_watch import run_combat_watch

        settings = load_settings()
        streams = resolve_capture_streams(settings, default_locallow())
        if streams:
            mode = "game window" if window_lock else "screen"
            print(
                f"Watching {len(streams)} OCR stream(s) ({mode}) every {args.interval}s "
                f"→ data/combat-events.json (chronological, matches on-screen chat)\n"
                f"Ctrl+C to stop\n",
            )
            print(f"Backends: {available_backends()}")

            def on_ev(ev):
                if "error" in ev:
                    print(f"[ocr error] {ev['error']}")
                else:
                    print(f"[{ev.get('kind')}] {ev.get('raw', '')[:80]}")

            try:
                run_combat_watch(
                    capture="ocr",
                    streams=streams,
                    interval=args.interval,
                    backend=args.backend,
                    window_lock=window_lock,
                    on_event=on_ev,
                )
            except KeyboardInterrupt:
                print(f"\nStopped. Events: {EVENTS_PATH}  Live: {LIVE_PATH}")
                return 0
            return 0

        mode = "game window" if window_lock else "screen"
        print(f"Watching region {region} ({mode}) every {args.interval}s (Ctrl+C to stop)")
        print(f"Backends: {available_backends()}")
        import threading
        stop = threading.Event()

        def on_ev(ev):
            if "error" in ev:
                print(f"[ocr error] {ev['error']}")
            else:
                print(f"[{ev.get('kind')}] {ev.get('raw', '')[:80]}")

        try:
            run_watch(
                region,
                interval=args.interval,
                backend=args.backend,
                window_lock=window_lock,
                stop_event=stop,
                on_event=on_ev,
            )
        except KeyboardInterrupt:
            stop.set()
            print(f"\nStopped. Events: {EVENTS_PATH}  Live: {LIVE_PATH}")
            return 0

    # Default: show layout
    return _print_layout(locallow)


if __name__ == "__main__":
    raise SystemExit(main())
