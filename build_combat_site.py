#!/usr/bin/env python3
"""Bundle combat OCR session data for the stats dashboard."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent

TOTAL_KEYS = (
    "event_count",
    "damage_out",
    "damage_in",
    "heal_out",
    "heal_in",
    "pvp_event_count",
    "pvp_incoming_count",
    "by_kind",
    "by_outcome",
    "by_channel",
    "session_start",
    "updated_at",
)


def _load(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _live_totals(live: dict) -> dict:
    """Normalize combat-live.json into dashboard totals (flat fields, not nested)."""
    if live.get("totals") and isinstance(live["totals"], dict):
        return dict(live["totals"])
    return {k: live[k] for k in TOTAL_KEYS if k in live}


def _stream_labels(settings: dict) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in settings.get("combat_streams") or []:
        sid = row.get("id")
        if sid:
            labels[sid] = row.get("label") or sid
    return labels


def _by_stream(events: list[dict], labels: dict[str, str]) -> dict:
    buckets: dict[str, dict] = defaultdict(lambda: {
        "events": 0,
        "damage_out": 0,
        "damage_in": 0,
        "heal_out": 0,
        "heal_in": 0,
    })
    for e in events:
        sid = e.get("stream_id") or "default"
        b = buckets[sid]
        b["events"] += 1
        amt = e.get("amount") or 0
        k = e.get("kind") or ""
        direction = e.get("direction")
        pet = e.get("pet")
        if k in ("melee", "ability", "dot", "damage") and amt:
            if direction == "outgoing" or (pet and e.get("actor") == pet):
                b["damage_out"] += amt
            elif direction == "incoming":
                b["damage_in"] += amt
        elif k == "heal" and direction == "outgoing":
            b["heal_out"] += amt
        elif k == "heal" and direction == "incoming":
            b["heal_in"] += amt
    out = {}
    for sid, stats in buckets.items():
        out[sid] = {
            **stats,
            "label": labels.get(sid) or sid,
        }
    return out


def build_bundle(data_dir: Path, settings: dict | None = None) -> dict:
    events = _load(data_dir / "combat-events.json", [])
    live = _load(data_dir / "combat-live.json", {})
    settings = settings or _load(data_dir.parent / "client-settings.json", {})
    if not settings:
        try:
            from mnm_paths import load_settings
            settings = load_settings()
        except Exception:
            settings = {}

    totals = _live_totals(live)
    if not totals.get("event_count") and events:
        from mnm_combat_watch import aggregate_session

        totals = aggregate_session(events)

    labels = _stream_labels(settings)
    streams_cfg = settings.get("combat_streams") or []

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "has_data": bool(events or totals.get("event_count")),
            "stream_count": len({e.get("stream_id") for e in events if e.get("stream_id")}) or len(streams_cfg) or (1 if events else 0),
            "session_start": events[0].get("ts") if events else totals.get("session_start"),
            "session_end": events[-1].get("ts") if events else totals.get("updated_at"),
        },
        "totals": totals,
        "by_stream": _by_stream(events, labels),
        "streams": [
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "window_id": s.get("window_id"),
                "channel_count": len(s.get("channels") or []),
            }
            for s in streams_cfg
        ],
        "recent": events[-50:] if events else [],
        "live": live,
    }


def write_bundle(data_dir: Path, site_dir: Path, settings: dict | None = None) -> dict:
    bundle = build_bundle(data_dir, settings=settings)
    js = "window.MNM_COMBAT = " + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";\n"
    stats_dir = site_dir / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "combat-stats.js").write_text(js, encoding="utf-8")
    return bundle


def main(data_dir: Path | None = None, site_dir: Path | None = None) -> int:
    from mnm_paths import data_dir as default_data_dir, site_dir as default_site_dir, load_settings

    data_dir = data_dir or default_data_dir()
    site_dir = site_dir or default_site_dir()
    settings = load_settings()
    bundle = write_bundle(data_dir, site_dir, settings=settings)
    print(
        f"  site/stats/combat-stats.js "
        f"({bundle['meta']['event_count']:,} events, "
        f"{bundle['meta'].get('stream_count', 1)} stream(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
