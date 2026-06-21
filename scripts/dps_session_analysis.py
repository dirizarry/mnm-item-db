#!/usr/bin/env python3
"""Analyze combat-events.json for DPS meter viability (memory + message_blob)."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mnm_paths import data_dir


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def outgoing_damage(e: dict) -> bool:
    if not e.get("amount"):
        return False
    if e.get("kind") not in ("melee", "ability", "dot", "damage"):
        return False
    if e.get("direction") == "outgoing":
        return True
    raw = e.get("raw") or ""
    return raw.startswith("You ") or raw.startswith("Your ")


def dps_window(events: list[dict], label: str) -> dict:
    hits = [e for e in events if outgoing_damage(e)]
    if len(hits) < 2:
        return {"label": label, "hits": len(hits), "total": sum(e.get("amount") or 0 for e in hits)}
    ts = [parse_ts(e["ts"]) for e in hits if parse_ts(e["ts"])]
    if len(ts) < 2:
        return {"label": label, "hits": len(hits), "total": sum(e.get("amount") or 0 for e in hits)}
    dur = max((ts[-1] - ts[0]).total_seconds(), 1.0)
    total = sum(e.get("amount") or 0 for e in hits)
    return {
        "label": label,
        "hits": len(hits),
        "total": total,
        "duration_s": round(dur, 1),
        "dps": round(total / dur, 1),
        "start": ts[0].isoformat(),
        "end": ts[-1].isoformat(),
    }


def ability_breakdown(events: list[dict]) -> list[tuple[str, int, int]]:
    by: dict[str, list[int]] = defaultdict(list)
    for e in events:
        if not outgoing_damage(e):
            continue
        key = e.get("ability") or e.get("verb") or e.get("kind") or "?"
        by[key].append(e.get("amount") or 0)
    rows = [(k, len(v), sum(v)) for k, v in by.items()]
    rows.sort(key=lambda x: -x[2])
    return rows


def main() -> int:
    path = data_dir() / "combat-events.json"
    events = json.loads(path.read_text(encoding="utf-8"))
    print("=== DPS viability report ===\n")
    print(f"Events file: {path}")
    print(f"Total events: {len(events)}")

    by_mode = Counter(e.get("memory_mode") for e in events)
    by_source = Counter(e.get("source") for e in events)
    print(f"Source: {dict(by_source)}")
    print(f"Memory mode: {dict(by_mode)}")

    # Full session (current file — mostly polluted text_scan)
    full = dps_window(events, "FULL SESSION (all events)")
    print(f"\n--- {full['label']} ---")
    for k, v in full.items():
        if k != "label":
            print(f"  {k}: {v}")

    # Last 30 minutes only
    parsed = [(e, parse_ts(e.get("ts"))) for e in events if parse_ts(e.get("ts"))]
    if parsed:
        t_end = max(t for _, t in parsed)
        t0 = t_end - timedelta(minutes=30)
        recent = [e for e, t in parsed if t >= t0]
        w30 = dps_window(recent, "LAST 30 MIN")
        print(f"\n--- {w30['label']} ---")
        for k, v in w30.items():
            if k != "label":
                print(f"  {k}: {v}")

    # Bone carver encounter (user test fight)
    bc = [e for e in events if "bone carver" in (e.get("raw") or "").lower() and outgoing_damage(e)]
    bc_you = [
        e for e in bc if (e.get("actor") == "You" or (e.get("raw") or "").startswith("Your "))
    ]
    wbc = dps_window(bc_you, "YOU vs bone carver (all session duplicates)")
    print(f"\n--- {wbc['label']} ---")
    for k, v in wbc.items():
        if k != "label":
            print(f"  {k}: {v}")
    print("  unique raw lines:", len({e.get("raw") for e in bc_you}))
    print(
        "  duplicate multiplier:",
        round(len(bc_you) / max(len({e.get("raw") for e in bc_you}), 1), 2),
    )

    print("\n  Last 15 You vs bone carver hits:")
    for e in bc_you[-15:]:
        print(f"    {e.get('amount'):3} {e.get('memory_mode', '?'):12} {(e.get('raw') or '')[:60]}")

    print("\n--- Ability breakdown (You outgoing, bone carver) ---")
    for name, cnt, total in ability_breakdown(bc_you)[:10]:
        print(f"  {total:4} dmg  ({cnt}x)  {name}")

    # Quality flags
    print("\n=== Reliability assessment ===")
    text_scan = sum(1 for e in events if e.get("memory_mode") == "text_scan")
    blob = sum(1 for e in events if e.get("memory_mode") == "message_blob")
    glued = sum(1 for e in events if (e.get("raw") or "").count(" for ") > 2)
    partial = sum(1 for e in events if e.get("kind") == "damage")
    same_ts = Counter(e.get("ts") for e in events)
    burst_ts = sum(1 for t, c in same_ts.items() if c > 5 and t)

    print(f"  text_scan events (zone heap noise): {text_scan}")
    print(f"  message_blob events (UI-order tail): {blob}")
    print(f"  partial kind=damage parses: {partial}")
    print(f"  glued multi-hit lines: {glued}")
    print(f"  poll timestamps with >5 events: {burst_ts}")

    if blob == 0:
        print("\n  VERDICT: No message_blob capture in this file yet.")
        print("  DPS from full session is NOT reliable (text_scan mixes zone + duplicates).")
        print("  Re-run: discover-struct then watch --source memory on a clean fight.")
    elif blob > 0 and partial / max(len(events), 1) < 0.05:
        print("\n  VERDICT: message_blob data can support encounter DPS with seq/ts ordering.")
    else:
        print("\n  VERDICT: Partial — needs clean message_blob session + encounter boundaries.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
