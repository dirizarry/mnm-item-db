"""Live combat chat capture: OCR the combat window and parse damage/healing lines.

Also supports **Option F** read-only memory harvest (``run_memory_watch``) for bulk
zone-wide text — **not** for matching the on-screen combat log. Use OCR (default when
``combat_region`` / ``combat_streams`` are configured) for chronological pairing.

Uses **line-level** OCR (Windows OcrResult.lines / Tesseract word rows) plus
scroll-aware frame diffing so each new chat row is parsed once — not the whole
window as a single blob.

Outputs:
  data/combat-events.json      parsed events (append-only session)
  data/combat-live.json        rolling session stats for dashboard
  data/combat-capture-state.json  last frame rows (resume without replay)
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mnm_combat_ocr import (
    available_backends,
    capture_region,
    diff_chat_lines,
    ocr_image_lines,
)
from mnm_combat_text import normalize_line, parse_message_list, parse_ocr_line
from mnm_combat_pvp import annotate_pvp
from mnm_combat_streams import allowed_channel_set, event_allowed
from mnm_paths import data_dir

STATE_PATH = data_dir() / "combat-capture-state.json"
EVENTS_PATH = data_dir() / "combat-events.json"
LIVE_PATH = data_dir() / "combat-live.json"


def resolve_capture_backend(mode: str = "auto") -> str:
    """Return ``memory`` or ``ocr`` for combat capture.

    ``auto`` prefers memory message_blob when configured, else OCR if regions
    exist, else memory heap scan.
    """
    if mode == "ocr":
        return "ocr"
    if mode == "memory":
        return "memory"
    try:
        from client_re.mnmlib.combat_struct import load_struct_config, struct_enabled

        cfg = load_struct_config()
        if struct_enabled(cfg) and cfg.get("layout") == "message_blob":
            return "memory"
    except Exception:
        pass
    try:
        from mnm_paths import load_settings

        settings = load_settings()
        if settings.get("combat_streams") or settings.get("combat_region"):
            return "ocr"
    except Exception:
        pass
    if mode == "auto":
        try:
            from client_re.combat_memory import memory_capture_status

            status = memory_capture_status()
            if status.get("process_running") and status.get("signatures_ready"):
                return "memory"
        except Exception:
            pass
    return "ocr"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _stamp_batch_events(events: list[dict], poll_ts: str, state: dict) -> None:
    """Assign monotonic ``seq`` and sub-second ``ts`` for chronological pairing."""
    seq = int(state.get("event_seq") or 0)
    try:
        base = datetime.fromisoformat(poll_ts)
    except ValueError:
        base = datetime.now(timezone.utc).astimezone()
    for i, ev in enumerate(events):
        seq += 1
        ev["seq"] = seq
        ev["ts"] = (base if i == 0 else base.replace(microsecond=min(999999, base.microsecond + i * 1000))).isoformat()
    state["event_seq"] = seq


def load_state() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"prev_frame_lines": [], "text_hash": ""}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def clear_combat_session() -> list[str]:
    """Delete combat OCR session files and reset live counters to zero."""
    touched: list[str] = []
    for path in (EVENTS_PATH, LIVE_PATH, STATE_PATH):
        if path.is_file():
            path.unlink()
    EVENTS_PATH.write_text("[]", encoding="utf-8")
    touched.append(str(EVENTS_PATH))
    LIVE_PATH.write_text(
        json.dumps(
            {
                "event_count": 0,
                "damage_out": 0,
                "damage_in": 0,
                "heal_out": 0,
                "heal_in": 0,
                "by_kind": {},
                "recent": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    touched.append(str(LIVE_PATH))
    save_state({"prev_frame_lines": [], "text_hash": ""})
    touched.append(str(STATE_PATH))
    return touched


def aggregate_session(events: list[dict]) -> dict:
    """Rolling DPS/HPS style counters from parsed events."""
    dmg_out = dmg_in = heal_out = heal_in = 0
    by_kind: dict[str, int] = defaultdict(int)
    by_outcome: dict[str, int] = defaultdict(int)
    by_channel: dict[str, int] = defaultdict(int)
    pvp_count = pvp_incoming = 0
    start = events[0]["ts"] if events else _now()
    for e in events:
        amt = e.get("amount") or 0
        k = e.get("kind") or "other"
        by_kind[k] += 1
        if e.get("outcome"):
            by_outcome[e["outcome"]] += 1
        if e.get("channel"):
            by_channel[e["channel"]] += 1
        if e.get("pvp"):
            pvp_count += 1
            if e.get("pvp_aggressive") or e.get("pvp_kind") == "incoming":
                pvp_incoming += 1
        pet = e.get("pet")
        direction = e.get("direction")
        if k in ("melee", "ability", "dot", "damage") and amt:
            if direction == "outgoing" or (pet and e.get("actor") == pet):
                dmg_out += amt
            elif direction == "incoming":
                dmg_in += amt
        elif k == "heal" and direction == "outgoing":
            heal_out += amt
        elif k == "heal" and direction == "incoming":
            heal_in += amt
    return {
        "updated_at": _now(),
        "event_count": len(events),
        "damage_out": dmg_out,
        "damage_in": dmg_in,
        "heal_out": heal_out,
        "heal_in": heal_in,
        "by_kind": dict(by_kind),
        "by_outcome": dict(by_outcome),
        "by_channel": dict(sorted(by_channel.items(), key=lambda x: -x[1])[:40]),
        "pvp_event_count": pvp_count,
        "pvp_incoming_count": pvp_incoming,
        "session_start": start,
        "recent": events[-25:],
    }


def _load_events() -> list[dict]:
    if EVENTS_PATH.is_file():
        try:
            return json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _write_session(
    events: list[dict],
    *,
    backend: str | None,
    region: dict | None,
    frame_lines: int,
    capture_source: str | None = None,
) -> None:
    live = aggregate_session(events)
    live["capture_source"] = capture_source or backend or "ocr"
    live["ocr_backend"] = backend or available_backends()[0] if capture_source != "memory" else None
    if region:
        live["region"] = region
    live["frame_lines"] = frame_lines
    LIVE_PATH.write_text(json.dumps(live, indent=2, ensure_ascii=False), encoding="utf-8")


def _refresh_combat_site() -> None:
    """Keep dashboard combat-stats.js in sync with the live session (best-effort)."""
    try:
        from build_combat_site import write_bundle
        from mnm_paths import load_settings, site_dir

        write_bundle(data_dir(), site_dir(), settings=load_settings())
    except Exception:
        pass


def run_watch(
    region: dict,
    *,
    interval: float = 1.5,
    backend: str | None = None,
    window_lock: bool | None = None,
    stream_id: str | None = None,
    allowed_channels: set[str] | None = None,
    pvp_alerter=None,
    stop_event=None,
    on_event=None,
    max_events: int = 50000,
    once: bool = False,
) -> dict:
    """Poll OCR until ``stop_event`` is set (if provided). Returns summary stats."""
    if not available_backends():
        raise RuntimeError("No OCR backend — install requirements-combat.txt")

    state = load_state()
    state_key = f"prev_frame_lines_{stream_id}" if stream_id else "prev_frame_lines"
    dedup_key = f"recent_raws_{stream_id}" if stream_id else "recent_raws"
    prev_frame: list[str] = list(state.get(state_key) or state.get("prev_frame_lines") or [])
    recent_raws: list[str] = list(state.get(dedup_key) or [])
    events = _load_events()

    polls = 0
    parsed = 0
    filtered = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            break
        polls += 1
        ts = _now()
        try:
            im = capture_region(region, window_lock=window_lock)
            frame_lines = ocr_image_lines(im, backend=backend)
        except Exception as exc:
            if on_event:
                on_event({"error": str(exc), "stream_id": stream_id})
            if not once:
                time.sleep(interval)
            if once:
                break
            continue

        text_hash = hashlib.sha256(
            "\n".join(frame_lines).encode("utf-8", errors="replace"),
        ).hexdigest()[:16]
        new_lines = diff_chat_lines(prev_frame, frame_lines)
        prev_frame = list(frame_lines)

        batch = []
        for line in new_lines:
            for ev in parse_ocr_line(line, ts=ts, stream_id=stream_id):
                annotate_pvp(ev)
                if not event_allowed(ev, allowed_channels):
                    filtered += 1
                    continue
                norm = normalize_line(ev["raw"])
                if norm in recent_raws:
                    continue
                recent_raws.append(norm)
                batch.append(ev)
                events.append(ev)
                parsed += 1
                if pvp_alerter is not None:
                    pvp_alerter.maybe_alert(ev)
                if on_event:
                    on_event(ev)
        recent_raws[:] = recent_raws[-40:]

        if batch:
            _stamp_batch_events(batch, ts, state)
            events = events[-max_events:]
            EVENTS_PATH.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
            _write_session(events, backend=backend, region=region, frame_lines=len(frame_lines), capture_source="ocr")
            _refresh_combat_site()

        state["text_hash"] = text_hash
        state[state_key] = [normalize_line(l) for l in frame_lines][-40:]
        state[dedup_key] = recent_raws
        if not stream_id:
            state["prev_frame_lines"] = state[state_key]
            state["recent_raws"] = recent_raws
        state["last_poll"] = ts
        state["last_frame_line_count"] = len(frame_lines)
        state["last_new_lines"] = len(new_lines)
        save_state(state)

        if once:
            break
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval)

    return {
        "polls": polls,
        "parsed_events": parsed,
        "filtered_events": filtered,
        "total_events": len(events),
    }


def run_multi_watch(
    streams: list[dict],
    *,
    interval: float = 1.5,
    backend: str | None = None,
    window_lock: bool | None = None,
    pvp_alerter=None,
    stop_event=None,
    on_event=None,
    max_events: int = 50000,
) -> dict:
    """Poll multiple OCR regions (separate in-game chat windows) in one loop."""
    if not streams:
        raise ValueError("combat_streams is empty")
    if not available_backends():
        raise RuntimeError("No OCR backend — install requirements-combat.txt")

    state = load_state()
    events = _load_events()
    runners: list[dict] = []
    for stream in streams:
        sid = stream.get("id") or stream.get("label") or "stream"
        state_key = f"prev_frame_lines_{sid}"
        dedup_key = f"recent_raws_{sid}"
        runners.append({
            "id": sid,
            "label": stream.get("label") or sid,
            "region": stream["region"],
            "allowed": allowed_channel_set(stream),
            "prev_frame": list(state.get(state_key) or []),
            "recent_raws": list(state.get(dedup_key) or []),
            "state_key": state_key,
            "dedup_key": dedup_key,
        })

    totals = {"polls": 0, "parsed_events": 0, "filtered_events": 0, "streams": {}}
    primary_region = streams[0]["region"]

    while True:
        if stop_event is not None and stop_event.is_set():
            break
        totals["polls"] += 1
        ts = _now()
        batch_any = False
        total_frame_lines = 0
        events_before = len(events)

        for runner in runners:
            sid = runner["id"]
            region = runner["region"]
            prev_frame = runner["prev_frame"]
            recent_raws = runner["recent_raws"]
            stream_parsed = 0
            stream_filtered = 0

            try:
                im = capture_region(region, window_lock=window_lock)
                frame_lines = ocr_image_lines(im, backend=backend)
            except Exception as exc:
                if on_event:
                    on_event({"error": str(exc), "stream_id": sid})
                totals["streams"][sid] = {"error": str(exc)}
                continue

            total_frame_lines += len(frame_lines)
            new_lines = diff_chat_lines(prev_frame, frame_lines)
            runner["prev_frame"] = list(frame_lines)

            for line in new_lines:
                for ev in parse_ocr_line(line, ts=ts, stream_id=sid):
                    annotate_pvp(ev)
                    if not event_allowed(ev, runner["allowed"]):
                        stream_filtered += 1
                        continue
                    norm = normalize_line(ev["raw"])
                    if norm in recent_raws:
                        continue
                    recent_raws.append(norm)
                    events.append(ev)
                    stream_parsed += 1
                    batch_any = True
                    if pvp_alerter is not None:
                        pvp_alerter.maybe_alert(ev)
                    if on_event:
                        on_event(ev)

            recent_raws[:] = recent_raws[-40:]
            runner["recent_raws"] = recent_raws
            totals["parsed_events"] += stream_parsed
            totals["filtered_events"] += stream_filtered
            totals["streams"][sid] = {
                "parsed_events": stream_parsed,
                "filtered_events": stream_filtered,
                "new_lines": len(new_lines),
                "frame_lines": len(frame_lines),
            }

            state[runner["state_key"]] = [normalize_line(l) for l in runner["prev_frame"]][-40:]
            state[runner["dedup_key"]] = recent_raws

        if batch_any:
            _stamp_batch_events(events[events_before:], ts, state)
            events = events[-max_events:]
            EVENTS_PATH.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
            _write_session(
                events,
                backend=backend,
                region=primary_region,
                frame_lines=total_frame_lines,
                capture_source="ocr",
            )
            _refresh_combat_site()

        state["last_poll"] = ts
        state["stream_ids"] = [r["id"] for r in runners]
        save_state(state)

        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval)

    totals["total_events"] = len(events)
    return totals


def run_memory_watch(
    *,
    interval: float = 1.0,
    stream_id: str | None = None,
    allowed_channels: set[str] | None = None,
    pvp_alerter=None,
    stop_event=None,
    on_event=None,
    max_events: int = 50000,
    once: bool = False,
    memory_mode: str | None = None,
) -> dict:
    """Poll mnm.exe memory for combat text lines (Option F)."""
    from client_re.combat_memory import ensure_signatures, poll_combat_hits
    from client_re.mnmlib.combat_struct import load_struct_config

    ensure_signatures()
    cfg = load_struct_config()
    layout = cfg.get("layout")
    state = load_state()
    dedup_key = f"recent_raws_{stream_id}" if stream_id else "recent_raws"
    recent_raws: list[str] = list(state.get(dedup_key) or state.get("recent_raws") or [])
    seen_addrs_key = f"memory_seen_addrs_{stream_id}" if stream_id else "memory_seen_addrs"
    seen_addrs: set[int] = {
        int(x, 16) if isinstance(x, str) else int(x)
        for x in (state.get(seen_addrs_key) or [])
    }
    warmup_done = layout == "message_blob"
    events = _load_events()

    polls = 0
    parsed = 0
    filtered = 0
    last_mode = "text_scan"

    if layout == "message_blob":
        print(
            "Memory watch: chronological message blob tail (matches in-game log order).\n"
            "Run --discover-struct once per game session if capture stops updating.\n",
            file=__import__("sys").stderr,
        )
    else:
        print(
            "Memory watch: heap scan (zone-wide, not the combat UI log).\n"
            "Run --discover-struct for message_blob mode, or use OCR for UI matching.\n",
            file=__import__("sys").stderr,
        )

    while True:
        if stop_event is not None and stop_event.is_set():
            break
        polls += 1
        ts = _now()
        try:
            hits, last_mode = poll_combat_hits(
                mode=memory_mode,
                refresh_cache=(polls == 1 and layout != "message_blob"),
                state=state,
            )
        except Exception as exc:
            if on_event:
                on_event({"error": str(exc), "stream_id": stream_id})
            if once:
                break
            time.sleep(interval)
            continue

        if last_mode == "message_blob":
            new_hits = hits
        elif not warmup_done:
            for addr, _line in hits:
                seen_addrs.add(addr)
            warmup_done = True
            if on_event and polls == 1:
                on_event({
                    "info": f"Baselined {len(hits)} heap lines; streaming new combat only.",
                    "stream_id": stream_id,
                })
            new_hits = []
        else:
            new_hits = [(addr, line) for addr, line in hits if addr not in seen_addrs]
            for addr, _line in new_hits:
                seen_addrs.add(addr)

        batch = []
        for _addr, line in sorted(new_hits, key=lambda x: x[0]):
            for ev in parse_ocr_line(line, ts=ts, stream_id=stream_id):
                ev["source"] = "memory"
                ev["memory_mode"] = last_mode
                annotate_pvp(ev)
                if not event_allowed(ev, allowed_channels):
                    filtered += 1
                    continue
                norm = normalize_line(ev["raw"])
                if norm in recent_raws:
                    continue
                recent_raws.append(norm)
                batch.append(ev)
                events.append(ev)
                parsed += 1
                if pvp_alerter is not None:
                    pvp_alerter.maybe_alert(ev)
                if on_event:
                    on_event(ev)
        recent_raws[:] = recent_raws[-40:]

        if batch:
            _stamp_batch_events(batch, ts, state)
            events = events[-max_events:]
            EVENTS_PATH.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
            _write_session(
                events,
                backend=None,
                region=None,
                frame_lines=len(hits),
                capture_source="memory",
            )
            _refresh_combat_site()

        if len(seen_addrs) > 20000:
            seen_addrs = set(sorted(seen_addrs)[-15000:])

        state[seen_addrs_key] = [hex(a) for a in sorted(seen_addrs)[-15000:]]
        state[dedup_key] = recent_raws
        if not stream_id:
            state["recent_raws"] = recent_raws
        state["last_poll"] = ts
        state["memory_mode"] = last_mode
        state["memory_line_count"] = len(hits)
        state["last_new_lines"] = len(new_hits)
        save_state(state)

        if once:
            break
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval)

    return {
        "polls": polls,
        "parsed_events": parsed,
        "filtered_events": filtered,
        "total_events": len(events),
        "memory_mode": last_mode,
    }


def run_combat_watch(
    region: dict | None = None,
    *,
    capture: str = "auto",
    streams: list[dict] | None = None,
    interval: float = 1.5,
    backend: str | None = None,
    window_lock: bool | None = None,
    stream_id: str | None = None,
    allowed_channels: set[str] | None = None,
    pvp_alerter=None,
    stop_event=None,
    on_event=None,
    max_events: int = 50000,
    once: bool = False,
    memory_mode: str | None = None,
) -> dict:
    """Unified entry: memory-first (Option F) with OCR fallback."""
    backend_name = resolve_capture_backend(capture)
    if backend_name == "memory":
        return run_memory_watch(
            interval=min(interval, 1.0),
            stream_id=stream_id,
            allowed_channels=allowed_channels,
            pvp_alerter=pvp_alerter,
            stop_event=stop_event,
            on_event=on_event,
            max_events=max_events,
            once=once,
            memory_mode=memory_mode,
        )
    if streams:
        return run_multi_watch(
            streams,
            interval=interval,
            backend=backend,
            window_lock=window_lock,
            pvp_alerter=pvp_alerter,
            stop_event=stop_event,
            on_event=on_event,
            max_events=max_events,
        )
    if not region:
        raise ValueError("OCR capture requires region or streams")
    return run_watch(
        region,
        interval=interval,
        backend=backend,
        window_lock=window_lock,
        stream_id=stream_id,
        allowed_channels=allowed_channels,
        pvp_alerter=pvp_alerter,
        stop_event=stop_event,
        on_event=on_event,
        max_events=max_events,
        once=once,
    )


def reparse_state_frame() -> dict:
    """Re-merge and parse the last OCR frame rows stored in combat-capture-state.json."""
    from mnm_combat_ocr import merge_wrapped_ocr_lines

    state = load_state()
    raw = state.get("prev_frame_lines") or []
    merged = merge_wrapped_ocr_lines(raw)
    events = parse_message_list(merged)
    summary = aggregate_session(events)
    summary["merged_lines"] = merged
    summary["raw_row_count"] = len(raw)
    summary["merged_line_count"] = len(merged)
    summary["parsed_from_frame"] = len(events)
    return summary
