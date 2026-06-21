#!/usr/bin/env python3
"""Combat OCR session quality report (current workspace session)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mnm_paths import data_dir, load_settings, settings_path


def _load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _stream_labels(settings: dict) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in settings.get("combat_streams") or []:
        sid = row.get("id")
        if sid:
            labels[sid] = f"{row.get('label') or sid} ({row.get('window_id') or '?'})"
    return labels


def _frame_lines(state: dict) -> list[str]:
    """Last OCR frame rows — supports multi-stream capture state keys."""
    stream_ids = state.get("stream_ids") or []
    lines: list[str] = []
    for sid in stream_ids:
        key = f"prev_frame_lines_{sid}"
        chunk = state.get(key) or []
        if chunk:
            lines.append(f"--- stream {sid} ---")
            lines.extend(chunk[-6:])
    legacy = state.get("prev_frame_lines") or []
    if legacy and not stream_ids:
        lines.extend(legacy[-8:])
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze combat OCR session in the active workspace")
    ap.add_argument("--data", type=Path, default=None, help="Override data directory")
    ap.add_argument(
        "--rebuild-site", action="store_true", help="Refresh site/stats/combat-stats.js"
    )
    args = ap.parse_args()

    data = args.data or data_dir()
    settings = load_settings()
    events_path = data / "combat-events.json"
    state_path = data / "combat-capture-state.json"
    live_path = data / "combat-live.json"

    if not events_path.is_file():
        print(f"No session at {events_path}")
        print(f"Workspace data dir: {data}")
        print(f"Settings: {settings_path()}")
        return 1

    events = _load_json(events_path, [])
    state = _load_json(state_path, {})
    live = _load_json(live_path, {})
    labels = _stream_labels(settings)

    raw_lines = [e.get("raw") or "" for e in events]
    unique_raw = set(raw_lines)
    stream_ids = sorted({e.get("stream_id") or "default" for e in events})

    print("=== Session overview ===")
    print(f"Data dir: {data}")
    print(f"Events: {len(events)}")
    print(f"Unique raw lines: {len(unique_raw)}")
    print(f"Dup ratio: {len(events) / max(len(unique_raw), 1):.1f}x")
    if events:
        print(f"Session: {events[0].get('ts')} -> {events[-1].get('ts')}")
    if live:
        print(
            f"Live counters: dmg out={live.get('damage_out')} in={live.get('damage_in')} "
            f"events={live.get('event_count')} updated={live.get('updated_at')}"
        )

    print(f"\n=== OCR streams ({len(stream_ids)}) ===")
    for sid in stream_ids:
        sub = [e for e in events if (e.get("stream_id") or "default") == sid]
        print(f"  {labels.get(sid, sid)}: {len(sub)} events")
        if sub:
            kinds = Counter(e.get("kind") for e in sub)
            print(f"    kinds: {dict(kinds)}")

    configured = settings.get("combat_streams") or []
    if configured:
        print(f"\nConfigured streams in settings: {len(configured)}")
        for s in configured:
            ch = len(s.get("channels") or [])
            filt = f"{ch} filters" if ch else "all channels"
            r = s.get("region") or {}
            reg = (
                f"{r.get('left')},{r.get('top')} {r.get('width')}x{r.get('height')}"
                if r.get("width")
                else "no region"
            )
            print(f"  [{s.get('id')}] {s.get('label')} window={s.get('window_id')} {reg} ({filt})")

    with_channel = sum(1 for e in events if e.get("channel"))
    with_outcome = sum(1 for e in events if e.get("outcome"))
    if events:
        print(
            f"\nWith channel: {with_channel}/{len(events)} ({100 * with_channel / len(events):.0f}%)"
        )
        print(
            f"With outcome: {with_outcome}/{len(events)} ({100 * with_outcome / len(events):.0f}%)"
        )

    print("\n=== By kind ===")
    for k, v in Counter(e.get("kind") for e in events).most_common():
        print(f"  {k}: {v}")

    damage_gaps = [e for e in events if e.get("kind") == "damage"]
    print(f"\n=== kind=damage (partial parse): {len(damage_gaps)} ===")
    for e in damage_gaps[:5]:
        print(f"  {e['raw'][:95]}")

    glued = []
    for e in events:
        raw = e.get("raw") or ""
        if (
            len(re.findall(r"for \d+ point", raw)) > 1
            or "pet" in raw.lower()
            and raw.count(" for ") > 1
        ):
            glued.append(e)
    print(f"\n=== Glued/merged OCR lines: {len(glued)} ===")
    for e in glued[:10]:
        print(f"  amt={e.get('amount')} stream={e.get('stream_id')}")
        print(f"    {e['raw'][:110]}")

    junk = [e for e in events if "{" in e.get("raw", "") or 'pet":' in e.get("raw", "")]
    print(f"\n=== JSON/editor junk: {len(junk)} ===")

    cnt = Counter(raw_lines)
    dups = sorted([(r, c) for r, c in cnt.items() if c > 3], key=lambda x: -x[1])
    print(f"\n=== Most repeated lines (>3x): {len(dups)} ===")
    for r, c in dups[:8]:
        print(f"  {c}x: {r[:78]}")

    print("\n=== Capture state (last frame per stream) ===")
    for line in _frame_lines(state)[-20:]:
        print(f"  {line[:90]}")

    if args.rebuild_site:
        from build_combat_site import main as build_combat

        build_combat(data_dir=data)
        print("\nRebuilt site/stats/combat-stats.js")

    return 0


if __name__ == "__main__":
    sys.exit(main())
