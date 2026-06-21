#!/usr/bin/env python3
"""Real-time M&M ledger monitor — tails live Character/Social ledgers as you play.

The game rewrites today's Ledger/*.json files on every event (each event already
carries a sub-second f04 timestamp). This watcher polls those files, parses only
*new* events since last seen, and maintains a live play session with rolling
rate stats (kills/hr, coin/hr, loot/hr, level progress). Every observed event is
also stamped with the wall-clock arrival time, so any future event type that ever
ships without f04 still gets an accurate timestamp.

Outputs:
  data/ledger-live.json        live session snapshot (dashboard polls this)
  site/stats/ledger-live.js    window.MNM_LEDGER_LIVE = {...}  (file:// fallback)
  data/.watch-state.json       per-file cursors (so restarts don't replay)

Usage:
    python mnm_ledger_watch.py                 # watch, skip existing backlog
    python mnm_ledger_watch.py --backlog       # seed session with today's events first
    python mnm_ledger_watch.py --interval 1.0  # poll faster
    python mnm_ledger_watch.py --session-gap 20
    python mnm_ledger_watch.py --rebuild       # full re-mine after each idle lull
    python mnm_ledger_watch.py --once          # single catch-up pass, then exit
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mnm_ledger_config import ledger_settings
from mnm_ledger_parse import is_combat_kill, is_ground_loot
from mnm_local import (
    character_context,
    clean_item_name,
    decode_b64_text,
    decode_hid,
    decode_name_token,
    default_locallow,
    ledger_file_kind,
    parse_currency_field,
    parse_ledger_zone,
)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SITE_STATS = ROOT / "site" / "stats"
STATE_PATH = DATA / ".watch-state.json"
LIVE_JSON = DATA / "ledger-live.json"
LIVE_JS = SITE_STATS / "ledger-live.js"

LIVE_SCHEMA = "mnm-ledger-live/v1"


def live_ledger_files(locallow: Path) -> list[Path]:
    """Only the actively-written daily files (Archive snapshots never change)."""
    out: list[Path] = []
    for pat in ("*_Character_*.json", "*_Social_*.json"):
        for path in locallow.rglob(f"Ledger/{pat}"):
            if path.is_file() and "Archive" not in path.parts:
                out.append(path)
    return sorted(out)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


class Session:
    """Rolling stats for the current play session."""

    def __init__(self, gap_minutes: float) -> None:
        self.gap_seconds = gap_minutes * 60
        self.reset()

    def reset(self) -> None:
        self.started_at: str | None = None
        self.last_event_at: str | None = None
        self.kills = 0
        self.loot_events = 0
        self.loot_qty = 0
        self.ground_loot = 0
        self.coin_own_bulk = 0  # corpse bulk I randomly won
        self.coin_others_bulk = 0  # corpse bulk a groupmate won
        self.coin_split_received = 0  # my small split when a mate won
        self.vendor_copper = 0
        self.levelups: list[dict] = []
        self.deaths = 0
        self.kills_by_mob: dict[str, int] = defaultdict(int)
        self.kills_by_zone: dict[str, int] = defaultdict(int)
        self.loot_by_item: dict[str, int] = defaultdict(int)
        self.party_loot_events = 0
        self.current_zone: str | None = None
        self.current_character: str | None = None
        self.current_server: str | None = None
        self.current_level: int | None = None
        self.recent: list[dict] = []
        self.seen: set = set()

    def maybe_roll(self, ts: str | None) -> bool:
        """Start a fresh session if the idle gap since last event is too large."""
        if not ts:
            return False
        now = _parse_ts(ts)
        last = _parse_ts(self.last_event_at)
        if self.started_at and now and last:
            if (now - last).total_seconds() > self.gap_seconds:
                self.reset()
                return True
        return False

    def note(self, ts: str | None) -> None:
        if ts and not self.started_at:
            self.started_at = ts
        if ts:
            self.last_event_at = ts

    def push_recent(self, entry: dict, limit: int = 40) -> None:
        self.recent.append(entry)
        if len(self.recent) > limit:
            self.recent = self.recent[-limit:]

    def active_seconds(self) -> float:
        start = _parse_ts(self.started_at)
        last = _parse_ts(self.last_event_at)
        if start and last:
            return max((last - start).total_seconds(), 0.0)
        return 0.0

    def _per_hour(self, n: int) -> float:
        secs = self.active_seconds()
        return round(n / (secs / 3600), 1) if secs >= 60 else 0.0

    def coin_group_total(self) -> int:
        """All coin the group looted (corpse bulks; bulk-dominated, slightly under
        since other members' splits aren't in my ledger)."""
        return self.coin_own_bulk + self.coin_others_bulk

    def coin_received(self) -> int:
        """My split of the group's loot: bulks I randomly won (d12) plus the small
        splits (d15) I got when a partymate won the bulk."""
        return self.coin_own_bulk + self.coin_split_received

    def snapshot(self, observed_at: str) -> dict:
        top_mobs = sorted(self.kills_by_mob.items(), key=lambda x: -x[1])[:8]
        top_zones = sorted(self.kills_by_zone.items(), key=lambda x: -x[1])[:8]
        top_items = sorted(self.loot_by_item.items(), key=lambda x: -x[1])[:8]
        received = self.coin_received()
        return {
            "schema": LIVE_SCHEMA,
            "observed_at": observed_at,
            "session": {
                "started_at": self.started_at,
                "last_event_at": self.last_event_at,
                "active_seconds": round(self.active_seconds()),
                "character": self.current_character,
                "server": self.current_server,
                "zone": self.current_zone,
                "level": self.current_level,
            },
            "totals": {
                "kills": self.kills,
                "loot_events": self.loot_events,
                "loot_qty": self.loot_qty,
                "ground_loot": self.ground_loot,
                "coin_received": received,
                "coin_group_total": self.coin_group_total(),
                "coin_own_bulk": self.coin_own_bulk,
                "coin_others_bulk": self.coin_others_bulk,
                "coin_split_received": self.coin_split_received,
                "vendor_copper": self.vendor_copper,
                "levelups": len(self.levelups),
                "deaths": self.deaths,
                "party_loot_events": self.party_loot_events,
            },
            "rates_per_hour": {
                "kills": self._per_hour(self.kills),
                "loot_qty": self._per_hour(self.loot_qty),
                "coin": self._per_hour(received + self.vendor_copper),
            },
            "top_mobs": [{"name": n, "kills": k} for n, k in top_mobs],
            "top_zones": [{"zone": z, "kills": k} for z, k in top_zones],
            "top_items": [{"item": i, "qty": q} for i, q in top_items],
            "levelups": self.levelups[-10:],
            "recent": list(reversed(self.recent[-20:])),
        }


def classify_event(ev: dict, ctx: dict, session: Session, observed_at: str) -> bool:
    """Update session from one ledger event. Returns True if it was a tracked event."""
    act = ev.get("f01", "")
    payload = None
    raw_payload = ev.get("f03")
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            payload = None
    ts = ev.get("f04") or observed_at
    _zone_key, zone = parse_ledger_zone(ev.get("f05"))
    char_level = ev.get("f06")
    actor = ev.get("f07")
    ev.get("f09") or ctx.get("character")
    player = ctx.get("character")
    is_own = actor == player or actor is None

    # Same kill/loot is written to both Character and Social ledgers — dedup by content.
    dedup = (act, ts, ev.get("f02"), raw_payload, actor)
    if dedup in session.seen:
        return False
    session.seen.add(dedup)

    session.maybe_roll(ts)
    session.note(ts)
    if zone:
        session.current_zone = zone
    # Only adopt identity/level context from the player's own events, not partymates'.
    if is_own:
        if player:
            session.current_character = player
        if ctx.get("server"):
            session.current_server = ctx["server"]
        if isinstance(char_level, int):
            session.current_level = char_level

    if act == "act_14" and payload:
        mob_name = decode_b64_text(payload.get("d13", "")) or decode_name_token(ev.get("f02", ""))
        mob_hid = decode_hid(payload.get("d14"))
        coin = parse_currency_field(payload.get("d12"))
        copper = coin.get("copper_total") if coin else None
        if is_ground_loot(act, mob_name, mob_hid):
            session.ground_loot += 1
            return True
        if mob_hid == "party_split":
            # Group loot: d11/d12 is the corpse bulk a (random) member won, d15 is my
            # split of the same corpse.
            bulk = parse_currency_field(payload.get("d12"))
            if bulk and "copper_total" in bulk:
                session.coin_others_bulk += bulk["copper_total"]
            share = parse_currency_field(payload.get("d15"))
            if share and "copper_total" in share:
                session.coin_split_received += share["copper_total"]
            return True
        if not is_own:
            return False  # a partymate's corpse recorded in my Social ledger
        if mob_name and is_combat_kill(mob_name, mob_hid, kind=act):
            session.kills += 1
            session.kills_by_mob[mob_name] += 1
            if zone:
                session.kills_by_zone[zone] += 1
            # I randomly won this corpse's bulk (d12); counts toward group total and my split.
            if copper:
                session.coin_own_bulk += copper
            session.push_recent(
                {
                    "at": ts,
                    "kind": "kill",
                    "name": mob_name,
                    "copper": copper,
                    "zone": zone,
                }
            )
            return True
        return False

    if act == "act_18":
        session.ground_loot += 1
        return True

    if act == "act_13" and payload:
        item_name = clean_item_name(payload.get("d04"))
        mob_name = decode_b64_text(payload.get("d02", ""))
        if item_name:
            qty = int(payload.get("d01") or 1)
            if not is_own:
                session.party_loot_events += 1
                return True
            session.loot_events += 1
            session.loot_qty += qty
            session.loot_by_item[item_name] += qty
            session.push_recent(
                {
                    "at": ts,
                    "kind": "loot",
                    "name": item_name,
                    "qty": qty,
                    "from": mob_name,
                    "zone": zone,
                }
            )
            return True

    if act == "act_24" and payload and is_own:
        coin = parse_currency_field(payload.get("d03"))
        if coin and "copper_total" in coin:
            session.vendor_copper += coin["copper_total"]
            return True

    if act == "act_01" and payload and is_own:
        new_lvl = payload.get("d21")
        old_lvl = payload.get("d22")
        if new_lvl is not None and old_lvl == new_lvl - 1:
            entry = {
                "at": ts,
                "character": ev.get("f07") or ctx.get("character"),
                "old_level": old_lvl,
                "new_level": new_lvl,
                "zone": zone,
            }
            session.levelups.append(entry)
            session.push_recent(
                {
                    "at": ts,
                    "kind": "levelup",
                    "name": entry["character"],
                    "level": new_lvl,
                    "zone": zone,
                }
            )
            return True

    return False


def load_state() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"cursors": {}}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def write_live(snapshot: dict) -> None:
    DATA.mkdir(exist_ok=True)
    LIVE_JSON.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    SITE_STATS.mkdir(parents=True, exist_ok=True)
    LIVE_JS.write_text(
        "window.MNM_LEDGER_LIVE = "
        + json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


def _fmt_coin(copper: int) -> str:
    # 100 per tier: 100c = 1s, 100s = 1g, 100g = 1p.
    pp, rem = divmod(copper, 1_000_000)
    gp, rem = divmod(rem, 10_000)
    sp, cp = divmod(rem, 100)
    parts = [
        f"{pp}p" if pp else "",
        f"{gp}g" if gp else "",
        f"{sp}s" if sp else "",
        f"{cp}c" if cp else "",
    ]
    return " ".join(p for p in parts if p) or "0c"


def print_console(snap: dict) -> None:
    sess = snap["session"]
    tot = snap["totals"]
    rates = snap["rates_per_hour"]
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[2J\x1b[H")  # clear screen + home
    else:
        print()
    print("=" * 58)
    print(" M&M LIVE SESSION MONITOR")
    print("=" * 58)
    who = f"{sess.get('character') or '?'}@{sess.get('server') or '?'}"
    print(f" {who}   lvl {sess.get('level') or '?'}   zone: {sess.get('zone') or '?'}")
    print(
        f" active: {_fmt_dur(sess.get('active_seconds') or 0)}   updated {snap['observed_at'][11:19]}"
    )
    print("-" * 58)
    print(
        f" Kills {tot['kills']:<6} ({rates['kills']}/hr)    Loot {tot['loot_qty']:<6} ({rates['loot_qty']}/hr)"
    )
    mine = tot["coin_received"]
    grp = tot.get("coin_group_total", 0)
    share = f"{round(100 * mine / grp)}%" if grp else "—"
    print(
        f" My split {_fmt_coin(mine):<13} ({share} of group {_fmt_coin(grp)})  +vendor {_fmt_coin(tot['vendor_copper'])}"
    )
    print(f" Levelups {tot['levelups']}   Ground loot {tot['ground_loot']}")
    if snap["top_mobs"]:
        print("-" * 58)
        print(" Top mobs this session:")
        for m in snap["top_mobs"][:5]:
            print(f"   {m['kills']:>4}  {m['name']}")
    if snap["recent"]:
        print("-" * 58)
        print(" Recent:")
        for r in snap["recent"][:6]:
            t = (r.get("at") or "")[11:19]
            if r["kind"] == "kill":
                print(
                    f"   {t}  killed {r['name']}"
                    + (f" (+{_fmt_coin(r['copper'])})" if r.get("copper") else "")
                )
            elif r["kind"] == "loot":
                print(f"   {t}  looted {r.get('qty', 1)}x {r['name']}")
            elif r["kind"] == "levelup":
                print(f"   {t}  *** {r['name']} reached level {r['level']} ***")
    print("=" * 58)
    print(" Ctrl+C to stop · dashboard: site/stats/index.html")


def run(
    locallow: Path,
    *,
    interval: float,
    gap_minutes: float,
    backlog: bool,
    once: bool,
    rebuild: bool,
) -> int:
    state = load_state()
    cursors: dict[str, int] = state.get("cursors", {})
    session = Session(gap_minutes)

    first_pass = not cursors
    pending_rebuild = False
    last_change = time.time()

    def process_once() -> int:
        nonlocal pending_rebuild
        observed_at = datetime.now(timezone.utc).astimezone().isoformat()
        batch: list[tuple[str, dict, dict]] = []
        for path in live_ledger_files(locallow):
            key = str(path)
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            events = doc.get("c01") or []
            if not isinstance(events, list):
                continue
            seen = cursors.get(key, 0)
            if len(events) <= seen:
                cursors[key] = len(events)
                continue
            # On the very first run, skip existing backlog unless asked to replay.
            if first_pass and seen == 0 and not backlog:
                cursors[key] = len(events)
                continue
            ctx = character_context(path, locallow)
            ctx["ledger_kind"] = ledger_file_kind(path)
            for ev in events[seen:]:
                batch.append((ev.get("f04") or observed_at, ev, ctx))
            cursors[key] = len(events)
            pending_rebuild = True

        # Process in true chronological order (Character + Social files interleave).
        batch.sort(key=lambda item: item[0])
        new_events = 0
        for _ts, ev, ctx in batch:
            if classify_event(ev, ctx, session, observed_at):
                new_events += 1
        return new_events

    try:
        added = process_once()
        snap = session.snapshot(datetime.now(timezone.utc).astimezone().isoformat())
        write_live(snap)
        save_state({"cursors": cursors})
        if not once:
            print_console(snap)

        if once:
            print(f"Catch-up pass: {added} new tracked events.")
            return 0

        while True:
            time.sleep(interval)
            added = process_once()
            now = time.time()
            if added:
                last_change = now
                snap = session.snapshot(datetime.now(timezone.utc).astimezone().isoformat())
                write_live(snap)
                save_state({"cursors": cursors})
                print_console(snap)
            elif rebuild and pending_rebuild and (now - last_change) > 8:
                pending_rebuild = False
                _trigger_rebuild()
    except KeyboardInterrupt:
        save_state({"cursors": cursors})
        print("\nStopped. Live snapshot saved to data/ledger-live.json")
        return 0


def _trigger_rebuild() -> None:
    try:
        from build_ledger_site import main as build_site
        from mnm_ledger_db import run as extract_run

        cfg = ledger_settings()
        locallow = Path(cfg["locallow"]) if cfg.get("locallow") else default_locallow()
        extract_run(locallow, ledger=True, journal=False)
        build_site()
    except Exception as exc:  # noqa: BLE001 - best-effort background refresh
        print(f"[rebuild skipped: {exc}]")


def main() -> int:
    ap = argparse.ArgumentParser(description="Real-time M&M ledger session monitor")
    ap.add_argument("--path", type=Path, default=None, help="LocalLow Monsters and Memories folder")
    ap.add_argument("--interval", type=float, default=2.0, help="Poll interval seconds (default 2)")
    ap.add_argument(
        "--session-gap", type=float, default=30.0, help="Idle minutes that start a new session"
    )
    ap.add_argument(
        "--backlog", action="store_true", help="Seed session with today's existing events"
    )
    ap.add_argument("--once", action="store_true", help="Single catch-up pass, then exit")
    ap.add_argument(
        "--rebuild", action="store_true", help="Full re-mine of dashboard data after idle lulls"
    )
    args = ap.parse_args()

    cfg = ledger_settings()
    locallow = args.path or (Path(cfg["locallow"]) if cfg.get("locallow") else default_locallow())
    if not locallow.is_dir():
        print(f"LocalLow path not found:\n  {locallow}", file=sys.stderr)
        print("Set MNM_LOCALLOW in config/ledger.env or pass --path", file=sys.stderr)
        return 1

    return run(
        locallow,
        interval=args.interval,
        gap_minutes=args.session_gap,
        backlog=args.backlog,
        once=args.once,
        rebuild=args.rebuild,
    )


if __name__ == "__main__":
    raise SystemExit(main())
