#!/usr/bin/env python3
"""Mine item/mob/play analytics from local M&M client logs (Ledger + journal).

Scans daily Character/Social ledgers and Ledger/Archive snapshots under:
  %LOCALAPPDATA%\\..\\LocalLow\\Niche Worlds Cult\\Monsters and Memories\\
    <server>/<character>/Ledger/*.json
    <server>/<character>/journal/<npc>

Usage:
    python mnm_ledger_db.py
    python mnm_ledger_db.py --path "D:\\..."
    python mnm_ledger_db.py --journal-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from mnm_hardcore_detect import build_hardcore_profiles
from mnm_ledger_parse import is_combat_kill, is_ground_loot
from mnm_provenance import kill_token, loot_token
from mnm_local import (
    character_context,
    clean_item_name,
    day_from_ts,
    decode_b64_text,
    decode_hid,
    decode_name_token,
    default_locallow,
    iter_ledger_files,
    ledger_file_kind,
    parse_currency_field,
    parse_event_payload,
    parse_ledger_zone,
    JOURNAL_LINE,
)

ROOT = Path(__file__).parent
OUT = ROOT / "data"
MANIFEST_SCHEMA = "mnm-ledger-manifest/v1"

PARTY_ACTS = {
    "act_31": "PartyCreate",
    "act_32": "PartyJoin",
    "act_33": "PartyDisband",
    "act_34": "PartyLeave",
    "act_35": "PartyLeaderChange",
}
TRADE_ACTS = {"act_16", "act_20"}
ITEM_ACTS = {"act_11", "act_12", "act_13", "act_15", "act_24", "act_27"}


def _instance_id(raw_d04: str | None) -> str | None:
    """Pull the globally-unique ``<instance_id>|`` prefix off a unique-item drop."""
    if not raw_d04 or "|" not in raw_d04:
        return None
    head = raw_d04.split("|", 1)[0].strip()
    return head if head.lstrip("-").isdigit() else None


def _bump_time(rec: dict, ts: str | None) -> None:
    if not ts:
        return
    if not rec.get("first_seen") or ts < rec["first_seen"]:
        rec["first_seen"] = ts
    if not rec.get("last_seen") or ts > rec["last_seen"]:
        rec["last_seen"] = ts


def _note_source(rec: dict, ctx: dict) -> None:
    key = f"{ctx['server']}|{ctx['character']}"
    sources = rec.setdefault("sources", {})
    sources[key] = sources.get(key, 0) + 1


def _serialize_sources(sources: dict) -> list[dict]:
    return [
        {"server": k.split("|", 1)[0], "character": k.split("|", 1)[1], "events": n}
        for k, n in sorted(sources.items())
    ]


def _write_json(path: Path, rows) -> None:
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def extract_ledger(path: Path, locallow: Path, state: dict) -> None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        state["errors"].append(str(path))
        return

    ctx = character_context(path, locallow)
    ctx["ledger_kind"] = ledger_file_kind(path)
    state["files_scanned"] += 1
    events = doc.get("c01") or []
    if not isinstance(events, list):
        return

    for ev in events:
        act = ev.get("f01", "")
        payload = parse_event_payload(ev.get("f03"))
        zone_key, zone = parse_ledger_zone(ev.get("f05"))
        ts = ev.get("f04")
        day = day_from_ts(ts)
        char_level = ev.get("f06")
        looter = ev.get("f07") or ctx["character"]
        owner = ev.get("f09") or ctx["character"]
        state["events_total"] += 1

        if act == "act_14" and payload:
            mob_name = decode_b64_text(payload.get("d13", "")) or decode_name_token(ev.get("f02", ""))
            mob_hid = decode_hid(payload.get("d14"))
            coin = parse_currency_field(payload.get("d12"))
            copper = coin.get("copper_total") if coin else None
            coin_key = (ctx["server"], ctx["character"])

            is_own = looter == ctx["character"]
            if mob_hid == "party_split":
                # Group loot. d11/d12 is the corpse "bulk" that went to a (random)
                # member; d15 is OUR split of the same corpse. We never see the other
                # members' splits, so group total is bulk-dominated and slightly under.
                split_key = (ts, looter, mob_name, payload.get("d12"), payload.get("d15"))
                if split_key not in state["coin_seen"]:
                    state["coin_seen"].add(split_key)
                    bulk = parse_currency_field(payload.get("d12"))
                    bulk_c = bulk["copper_total"] if bulk and "copper_total" in bulk else 0
                    share = parse_currency_field(payload.get("d15"))
                    mine_c = share["copper_total"] if share and "copper_total" in share else 0
                    state["coin"][coin_key]["others_bulk"] += bulk_c
                    state["coin"][coin_key]["split_received"] += mine_c
                    if bulk_c or mine_c:
                        state["coin_events"].append({
                            "at": ts,
                            "character": ctx["character"],
                            "server": ctx["server"],
                            "bulk": bulk_c,
                            "mine": mine_c,
                        })
            if is_ground_loot(act, mob_name, mob_hid):
                state["ground_loot"] += 1
            elif is_own and mob_name and is_combat_kill(mob_name, mob_hid, kind=act):
                mob_cf = mob_name.casefold()
                dedup_key = (ts, mob_cf, zone or "", ctx["server"], ctx["character"])
                if dedup_key in state["kill_seen"]:
                    continue
                state["kill_seen"].add(dedup_key)
                mob = state["mobs"].setdefault(mob_cf, {
                    "name": mob_name,
                    "mob_hid": mob_hid,
                    "copper_min": None,
                    "copper_max": None,
                    "copper_total": 0,
                    "zones": set(),
                    "kill_count": 0,
                    "sources": {},
                    "tokens": set(),
                })
                if mob_hid and not mob.get("mob_hid"):
                    mob["mob_hid"] = mob_hid
                if copper is not None:
                    mob["copper_total"] += copper
                    if mob["copper_min"] is None or copper < mob["copper_min"]:
                        mob["copper_min"] = copper
                    if mob["copper_max"] is None or copper > mob["copper_max"]:
                        mob["copper_max"] = copper
                if zone:
                    mob["zones"].add(zone)
                mob["kill_count"] += 1
                mob["tokens"].add(kill_token(ctx["server"], mob_hid or mob_cf, ts))
                _bump_time(mob, ts)
                _note_source(mob, ctx)

                # We won the corpse bulk ourselves (d12). Counts toward both the group
                # total and our split.
                if copper:
                    state["coin"][coin_key]["own_bulk"] += copper
                    state["coin_events"].append({
                        "at": ts,
                        "character": ctx["character"],
                        "server": ctx["server"],
                        "bulk": copper,
                        "mine": copper,
                    })

                state["mob_kills"][mob_cf] += 1
                if zone:
                    state["mob_kills_zone"][(mob_cf, zone)] += 1

                heat_key = (zone or "?", day or "?", ctx["server"], ctx["character"])
                state["kill_heatmap"][heat_key] += 1

                state["kills"].append({
                    "at": ts,
                    "day": day,
                    "mob_name": mob_name,
                    "mob_hid": mob_hid,
                    "zone": zone,
                    "zone_key": zone_key,
                    "character_level": char_level,
                    "character": ctx["character"],
                    "server": ctx["server"],
                    "ledger_kind": ctx["ledger_kind"],
                    "copper": copper,
                })

        if act == "act_18":
            state["ground_loot"] += 1

        if act in ITEM_ACTS and payload:
            item_name = clean_item_name(payload.get("d04")) or decode_name_token(ev.get("f02", ""))
            item_hid = payload.get("d05") or None
            if item_name:
                item = state["items"].setdefault(item_hid or item_name.casefold(), {
                    "name": item_name,
                    "item_hid": item_hid,
                    "count": 0,
                    "zones": set(),
                    "sources": {},
                })
                if item_hid and not item.get("item_hid"):
                    item["item_hid"] = item_hid
                qty = int(payload.get("d01") or 1)
                item["count"] += qty
                if zone:
                    item["zones"].add(zone)
                _bump_time(item, ts)
                _note_source(item, ctx)

        if act == "act_13" and payload:
            raw_d04 = payload.get("d04")
            item_name = clean_item_name(raw_d04)
            item_hid = payload.get("d05") or None
            mob_name = decode_b64_text(payload.get("d02", ""))
            instance_id = _instance_id(raw_d04)
            if item_name and mob_name:
                mob_cf = mob_name.casefold()
                qty = int(payload.get("d01") or 1)
                own_loot = looter == ctx["character"]
                loot_dedup = (ts, item_name.casefold(), mob_cf, looter)
                duped = loot_dedup in state["loot_seen"]
                if not duped:
                    state["loot_seen"].add(loot_dedup)

                # Drop-rate knowledge tied to *my own* kills (denominator = own kills).
                if own_loot and not duped:
                    key = (item_name.casefold(), mob_cf, zone or "")
                    drop = state["drops"].setdefault(key, {
                        "item_name": item_name,
                        "item_hid": item_hid,
                        "mob_name": mob_name,
                        "zone": zone,
                        "zone_key": zone_key,
                        "count": 0,
                        "sources": {},
                        "tokens": set(),
                    })
                    if item_hid and not drop.get("item_hid"):
                        drop["item_hid"] = item_hid
                    drop["count"] += qty
                    # Cross-user/idempotent dedup identity for this loot observation.
                    drop["tokens"].add(
                        loot_token(ctx["server"], item_hid, mob_cf, ts, instance_id)
                    )
                    _bump_time(drop, ts)
                    _note_source(drop, ctx)

                    loot_key = (mob_cf, zone or "")
                    bucket = state["loot_by_mob"].setdefault(loot_key, defaultdict(int))
                    bucket[item_name.casefold()] += qty
                    state["loot_item_names"][(mob_cf, zone or "", item_name.casefold())] = item_name

                if not duped:
                    state["loot"].append({
                        "at": ts,
                        "day": day,
                        "item_name": item_name,
                        "item_hid": item_hid,
                        "mob_name": mob_name,
                        "qty": qty,
                        "zone": zone,
                        "zone_key": zone_key,
                        "looter": looter,
                        "owner": owner,
                        "character": ctx["character"],
                        "server": ctx["server"],
                        "ledger_kind": ctx["ledger_kind"],
                        "own": own_loot,
                        "party_loot": looter != owner,
                    })

        if act == "act_24" and payload:
            item_name = clean_item_name(payload.get("d04")) or decode_name_token(ev.get("f02", ""))
            if item_name:
                coin = parse_currency_field(payload.get("d03"))
                key = (item_name.casefold(), payload.get("d05") or "")
                rec = state["vendor_prices"].setdefault(key, {
                    "item_name": item_name,
                    "item_hid": payload.get("d05") or None,
                    "sell_count": 0,
                    "min_copper": None,
                    "max_copper": None,
                    "zones": set(),
                })
                rec["sell_count"] += int(payload.get("d01") or 1)
                if zone:
                    rec["zones"].add(zone)
                if coin and "copper_total" in coin:
                    ct = coin["copper_total"]
                    rec["min_copper"] = ct if rec["min_copper"] is None else min(rec["min_copper"], ct)
                    rec["max_copper"] = ct if rec["max_copper"] is None else max(rec["max_copper"], ct)
                    rec["last_price"] = coin
                    vkey = (ts, item_name.casefold(), ct)
                    if vkey not in state["loot_seen"]:
                        state["loot_seen"].add(vkey)
                        state["coin"][(ctx["server"], ctx["character"])]["vendor"] += ct

        if act == "act_01" and payload:
            new_lvl = payload.get("d21")
            old_lvl = payload.get("d22")
            if new_lvl is not None and old_lvl == new_lvl - 1:
                who = ev.get("f07") or decode_name_token(ev.get("f02", ""))
                # Character ledgers hold your own level-ups; Social/Archive hold party sightings.
                if ctx["ledger_kind"] == "character" and who != ctx["character"]:
                    pass
                elif ctx["ledger_kind"] in {"social", "archive", "character"}:
                    lu_key = (ts, ctx["server"], who, old_lvl, new_lvl)
                    if lu_key not in state["levelup_seen"]:
                        state["levelup_seen"].add(lu_key)
                        state["levelups"].append({
                            "at": ts,
                            "day": day,
                            "character": who,
                            "observer": ctx["character"],
                            "server": ctx["server"],
                            "new_level": new_lvl,
                            "old_level": old_lvl,
                            "zone": zone,
                        })

        if act in TRADE_ACTS and payload:
            partner = decode_name_token(ev.get("f02", "")) or payload.get("partner")
            summary = decode_b64_text(payload.get("summary", "")) or payload.get("summary")
            coin = parse_currency_field(payload.get("currency"))
            state["trades"].append({
                "at": ts,
                "day": day,
                "character": ctx["character"],
                "server": ctx["server"],
                "partner": partner,
                "summary": summary,
                "item_count": payload.get("itemCount"),
                "items": payload.get("items") or [],
                "currency": coin,
                "zone": zone,
                "act": act,
            })

        if act in PARTY_ACTS and payload:
            state["party"].append({
                "at": ts,
                "day": day,
                "character": ctx["character"],
                "server": ctx["server"],
                "action": PARTY_ACTS[act],
                "detail": decode_b64_text(payload.get("d63", "")) or payload.get("d63"),
                "ref": payload.get("d64"),
                "zone": zone,
                "character_level": char_level,
            })

        if act in TRADE_ACTS and payload:
            for it in payload.get("items") or []:
                item_name = it.get("name")
                item_hid = it.get("hid")
                if not item_name:
                    continue
                item = state["items"].setdefault(item_hid or item_name.casefold(), {
                    "name": item_name,
                    "item_hid": item_hid,
                    "count": 0,
                    "zones": set(),
                    "sources": {},
                })
                item["count"] += 1
                if zone:
                    item["zones"].add(zone)
                _bump_time(item, ts)
                _note_source(item, ctx)


def extract_journal(path: Path, locallow: Path, state: dict) -> None:
    rel = path.relative_to(locallow)
    server, character = rel.parts[0], rel.parts[1]

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        state["errors"].append(str(path))
        return

    lines = []
    for raw in text.splitlines():
        m = JOURNAL_LINE.match(raw.strip())
        if m:
            lines.append({"at": m.group(1), "speaker": m.group(2), "text": m.group(3)})

    if not lines:
        return

    npc = path.name
    key = npc.casefold()
    rec = state["journal"].setdefault(key, {
        "npc": npc,
        "line_count": 0,
        "characters": set(),
        "servers": set(),
        "first_seen": None,
        "last_seen": None,
        "sample": [],
    })
    rec["line_count"] += len(lines)
    rec["characters"].add(character)
    rec["servers"].add(server)
    first, last = lines[-1]["at"], lines[0]["at"]
    if not rec["first_seen"] or first < rec["first_seen"]:
        rec["first_seen"] = first
    if not rec["last_seen"] or last > rec["last_seen"]:
        rec["last_seen"] = last
    if len(rec["sample"]) < 3:
        rec["sample"].extend(lines[: 3 - len(rec["sample"])])


def build_drop_rates(state: dict) -> list[dict]:
    rows = []
    for (mob_cf, zone), items in sorted(state["loot_by_mob"].items()):
        kills = state["mob_kills_zone"].get((mob_cf, zone)) or state["mob_kills"].get(mob_cf, 0)
        mob_name = next(
            (d["mob_name"] for d in state["drops"].values() if d["mob_name"].casefold() == mob_cf),
            mob_cf,
        )
        mob_rec = state["mobs"].get(mob_cf, {})
        loot_rows = []
        total_loots = sum(items.values())
        for item_cf, count in sorted(items.items(), key=lambda x: -x[1]):
            item_name = state["loot_item_names"].get((mob_cf, zone, item_cf), item_cf)
            rate = round(count / kills, 4) if kills else None
            loot_rows.append({
                "item_name": item_name,
                "loot_count": count,
                "drop_rate": rate,
                "pct": round(100 * count / total_loots, 1) if total_loots else None,
            })
        rows.append({
            "mob_name": mob_name,
            "zone": zone or None,
            "kills": kills,
            "loot_events": total_loots,
            "loots_per_kill": round(total_loots / kills, 3) if kills else None,
            "items": loot_rows,
            "mob_copper_avg": (
                round(mob_rec.get("copper_total", 0) / mob_rec["kill_count"], 1)
                if mob_rec.get("kill_count")
                else None
            ),
        })
    return sorted(rows, key=lambda r: (-r["kills"], r["mob_name"]))


def build_kill_heatmap(state: dict) -> list[dict]:
    rows = []
    for (zone, day, server, character), kills in sorted(
        state["kill_heatmap"].items(), key=lambda x: (-x[1], x[0])
    ):
        rows.append({
            "zone": zone,
            "day": day,
            "server": server,
            "character": character,
            "kills": kills,
        })
    return rows


def serialize_mobs(mobs: dict) -> list[dict]:
    out = []
    for rec in sorted(mobs.values(), key=lambda r: r["name"].casefold()):
        kc = rec["kill_count"] or 1
        row = {
            "name": rec["name"],
            "mob_hid": rec.get("mob_hid"),
            "kill_count": rec["kill_count"],
            "copper_min": rec.get("copper_min"),
            "copper_max": rec.get("copper_max"),
            "copper_avg": round(rec.get("copper_total", 0) / kc, 1),
            "zones": sorted(rec["zones"]),
            "first_seen": rec.get("first_seen"),
            "last_seen": rec.get("last_seen"),
            "sources": _serialize_sources(rec["sources"]),
            "dedup_tokens": sorted(rec.get("tokens", ())),
        }
        out.append(row)
    return out


def serialize_items(items: dict) -> list[dict]:
    out = []
    for rec in sorted(items.values(), key=lambda r: r["name"].casefold()):
        out.append({
            "name": rec["name"],
            "item_hid": rec.get("item_hid"),
            "count": rec["count"],
            "zones": sorted(rec["zones"]),
            "first_seen": rec.get("first_seen"),
            "last_seen": rec.get("last_seen"),
            "sources": _serialize_sources(rec["sources"]),
        })
    return out


def serialize_drops(drops: dict) -> list[dict]:
    out = []
    for rec in sorted(drops.values(), key=lambda r: (r["item_name"], r["mob_name"])):
        row = dict(rec)
        row["sources"] = _serialize_sources(row.pop("sources"))
        row["dedup_tokens"] = sorted(row.pop("tokens", ()))
        out.append(row)
    return out


def serialize_coin(coin: dict) -> list[dict]:
    out = []
    for (server, character), c in sorted(coin.items()):
        own_bulk = c.get("own_bulk", 0)          # corpse bulk I randomly won
        others_bulk = c.get("others_bulk", 0)    # corpse bulk a groupmate won
        split_received = c.get("split_received", 0)  # my small split when a mate won
        vendor = c.get("vendor", 0)
        group_total = own_bulk + others_bulk     # all coin the group looted (bulk-dominated)
        my_split = own_bulk + split_received      # my cut of that total
        out.append({
            "server": server,
            "character": character,
            "own_bulk": own_bulk,
            "others_bulk": others_bulk,
            "split_received": split_received,
            "group_total": group_total,
            "my_split": my_split,
            "my_share": round(my_split / group_total, 4) if group_total else 0,
            "vendor": vendor,
        })
    return sorted(out, key=lambda r: -r["my_split"])


def serialize_vendor(vendor_prices: dict) -> list[dict]:
    out = []
    for rec in sorted(vendor_prices.values(), key=lambda r: r["item_name"].casefold()):
        row = dict(rec)
        row["zones"] = sorted(row.pop("zones"))
        out.append(row)
    return out


def serialize_journal(journal: dict) -> list[dict]:
    out = []
    for rec in sorted(journal.values(), key=lambda r: r["npc"].casefold()):
        out.append({
            "npc": rec["npc"],
            "line_count": rec["line_count"],
            "characters": sorted(rec["characters"]),
            "servers": sorted(rec["servers"]),
            "first_seen": rec["first_seen"],
            "last_seen": rec["last_seen"],
            "sample": rec["sample"],
        })
    return out


def write_report(
    path: Path,
    locallow: Path,
    state: dict,
    *,
    drops: list,
    items: list,
    mobs: list,
    journal: list,
    drop_rates: list,
    heatmap: list,
    levelups: list,
    trades: list,
    party: list,
    vendor: list,
) -> None:
    lines = [
        "M&M local log extraction report",
        f"Scanned: {locallow}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Ledger files: {state['files_scanned']:,}",
        f"Ledger events: {state['events_total']:,}",
        f"Combat kills (act_14): {len(state['kills']):,}",
        f"Ground loot (act_18): {state['ground_loot']:,}",
        f"Loot events (act_13): {len(state['loot']):,}",
        f"Loot link buckets: {len(drops):,}",
        f"Drop-rate mob buckets: {len(drop_rates):,}",
        f"Heatmap cells: {len(heatmap):,}",
        f"Distinct items: {len(items):,}",
        f"Distinct mobs: {len(mobs):,}",
        f"Level-ups (act_01): {len(levelups):,}",
        f"Trades: {len(trades):,}",
        f"Party events: {len(party):,}",
        f"Vendor prices: {len(vendor):,}",
        f"Journal NPCs: {len(journal):,}",
        f"Parse errors: {len(state['errors'])}",
        "",
        "=== Top loot links ===",
    ]
    for d in sorted(drops, key=lambda x: -x["count"])[:20]:
        z = d.get("zone") or "?"
        lines.append(f"  {d['count']:4}x  {d['item_name']}  <-  {d['mob_name']}  ({z})")

    lines += ["", "=== Top drop rates (by kills) ==="]
    for r in sorted(drop_rates, key=lambda x: -x["kills"])[:15]:
        top = r["items"][0] if r["items"] else {}
        lines.append(
            f"  {r['kills']:4} kills  {r['mob_name']}  "
            f"top={top.get('item_name','?')} @{top.get('drop_rate','?')}/kill"
        )

    lines += ["", "=== Kill heatmap (top cells) ==="]
    for h in heatmap[:15]:
        lines.append(f"  {h['kills']:4}  {h['day']}  {h['zone']}  ({h['character']}@{h['server']})")

    lines += ["", "=== Recent level-ups ==="]
    for lu in sorted(levelups, key=lambda x: x["at"])[-10:]:
        lines.append(f"  {lu['at'][:16]}  {lu['character']}  {lu['old_level']} -> {lu['new_level']}  ({lu.get('zone') or '?'})")

    lines += ["", "=== Top journal NPCs ==="]
    for j in sorted(journal, key=lambda x: -x["line_count"])[:10]:
        lines.append(f"  {j['line_count']:4} lines  {j['npc']}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_file_index(locallow: Path, *, ledger: bool = True, journal: bool = True) -> dict[str, dict]:
    """Fingerprint ledger + journal files for incremental skip detection."""
    index: dict[str, dict] = {}
    if ledger:
        for path in iter_ledger_files(locallow):
            rel = str(path.relative_to(locallow))
            st = path.stat()
            index[rel] = {"mtime": int(st.st_mtime), "size": st.st_size}
    if journal:
        for path in sorted(locallow.rglob("journal/*")):
            if path.is_file():
                rel = str(path.relative_to(locallow))
                st = path.stat()
                index[rel] = {"mtime": int(st.st_mtime), "size": st.st_size}
    return index


def _load_previous_index(manifest_path: Path) -> dict[str, dict] | None:
    if not manifest_path.is_file():
        return None
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    idx = doc.get("file_index")
    return idx if isinstance(idx, dict) else None


def write_manifest(
    path: Path,
    locallow: Path,
    stats: dict,
    *,
    characters: list[str],
    servers: list[str],
    install_id: str,
    file_index: dict[str, dict] | None = None,
) -> None:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "locallow": str(locallow),
        "install_id": install_id,
        "characters": sorted(characters),
        "servers": sorted(servers),
        "stats": stats,
        "file_index": file_index or build_file_index(locallow),
        "outputs": [
            "ledger-drops.json",
            "ledger-drop-rates.json",
            "ledger-kills.json",
            "ledger-loot.json",
            "ledger-coin.json",
            "ledger-kill-heatmap.json",
            "ledger-mobs.json",
            "ledger-items.json",
            "ledger-vendor-prices.json",
            "ledger-levelups.json",
            "ledger-trades.json",
            "ledger-party.json",
            "ledger-journal.json",
            "ledger-hardcore.json",
            "ledger-report.txt",
        ],
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _collect_scope(locallow: Path) -> tuple[list[str], list[str]]:
    chars: set[str] = set()
    servers: set[str] = set()
    for path in iter_ledger_files(locallow):
        ctx = character_context(path, locallow)
        if ctx["character"]:
            chars.add(ctx["character"])
        if ctx["server"]:
            servers.add(ctx["server"])
    for path in locallow.rglob("journal/*"):
        if path.is_file():
            rel = path.relative_to(locallow)
            if len(rel.parts) >= 2:
                servers.add(rel.parts[0])
                chars.add(rel.parts[1])
    return sorted(chars), sorted(servers)


def new_state() -> dict:
    return {
        "events_total": 0,
        "files_scanned": 0,
        "errors": [],
        "ground_loot": 0,
        "items": {},
        "mobs": {},
        "drops": {},
        "journal": {},
        "kills": [],
        "kill_seen": set(),
        "loot": [],
        "loot_seen": set(),
        "coin": defaultdict(lambda: {"own_bulk": 0, "others_bulk": 0, "split_received": 0, "vendor": 0}),
        "coin_seen": set(),
        "coin_events": [],
        "kill_heatmap": defaultdict(int),
        "mob_kills": defaultdict(int),
        "mob_kills_zone": defaultdict(int),
        "loot_by_mob": {},
        "loot_item_names": {},
        "vendor_prices": {},
        "levelups": [],
        "levelup_seen": set(),
        "trades": [],
        "party": [],
    }


def run(
    locallow: Path,
    *,
    ledger: bool = True,
    journal: bool = True,
    incremental: bool = False,
    force: bool = False,
) -> dict:
    if not locallow.is_dir():
        raise SystemExit(f"LocalLow path not found: {locallow}")

    manifest_path = OUT / "ledger-manifest.json"
    current_index = build_file_index(locallow, ledger=ledger, journal=journal)
    if incremental and not force:
        previous_index = _load_previous_index(manifest_path)
        if previous_index and previous_index == current_index:
            try:
                prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                prev = {}
            stats = prev.get("stats") or {}
            return {
                **stats,
                "locallow": str(locallow),
                "install_id": prev.get("install_id"),
                "characters": prev.get("characters", []),
                "servers": prev.get("servers", []),
                "skipped": True,
            }

    state = new_state()

    if ledger:
        for path in iter_ledger_files(locallow):
            extract_ledger(path, locallow, state)

    if journal:
        for path in sorted(locallow.rglob("journal/*")):
            if path.is_file():
                extract_journal(path, locallow, state)

    items = serialize_items(state["items"])
    mobs = serialize_mobs(state["mobs"])
    drops = serialize_drops(state["drops"])
    journal_rows = serialize_journal(state["journal"])
    drop_rates = build_drop_rates(state)
    heatmap = build_kill_heatmap(state)
    vendor = serialize_vendor(state["vendor_prices"])
    levelups = sorted(state["levelups"], key=lambda r: r["at"])
    trades = sorted(state["trades"], key=lambda r: r["at"])
    party = sorted(state["party"], key=lambda r: r["at"])

    OUT.mkdir(exist_ok=True)
    if ledger:
        _write_json(OUT / "ledger-items.json", items)
        _write_json(OUT / "ledger-mobs.json", mobs)
        _write_json(OUT / "ledger-drops.json", drops)
        _write_json(OUT / "ledger-drop-rates.json", drop_rates)
        _write_json(OUT / "ledger-kill-heatmap.json", heatmap)
        _write_json(OUT / "ledger-kills.json", state["kills"])
        _write_json(OUT / "ledger-loot.json", state["loot"])
        _write_json(OUT / "ledger-coin.json", serialize_coin(state["coin"]))
        _write_json(OUT / "ledger-coin-events.json", sorted(state["coin_events"], key=lambda r: r["at"]))
        _write_json(OUT / "ledger-vendor-prices.json", vendor)
        _write_json(OUT / "ledger-levelups.json", levelups)
        _write_json(OUT / "ledger-trades.json", trades)
        _write_json(OUT / "ledger-party.json", party)
    if journal:
        _write_json(OUT / "ledger-journal.json", journal_rows)

    hardcore_profiles = build_hardcore_profiles(locallow, state["kills"], levelups)
    if ledger or journal:
        _write_json(OUT / "ledger-hardcore.json", hardcore_profiles)

    write_report(
        OUT / "ledger-report.txt",
        locallow,
        state,
        drops=drops,
        items=items,
        mobs=mobs,
        journal=journal_rows,
        drop_rates=drop_rates,
        heatmap=heatmap,
        levelups=levelups,
        trades=trades,
        party=party,
        vendor=vendor,
    )

    stats = {
        "files": state["files_scanned"],
        "events": state["events_total"],
        "drops": len(drops),
        "drop_rates": len(drop_rates),
        "heatmap": len(heatmap),
        "kills": len(state["kills"]),
        "loot_events": len(state["loot"]),
        "ground_loot": state["ground_loot"],
        "items": len(items),
        "mobs": len(mobs),
        "levelups": len(levelups),
        "trades": len(trades),
        "party": len(party),
        "vendor": len(vendor),
        "journal_npcs": len(journal_rows),
        "hardcore_n": len(hardcore_profiles),
        "errors": len(state["errors"]),
    }

    install_id = hashlib.sha256(str(locallow).casefold().encode()).hexdigest()[:16]
    characters, servers = _collect_scope(locallow)
    write_manifest(
        manifest_path,
        locallow,
        stats,
        characters=characters,
        servers=servers,
        install_id=install_id,
        file_index=current_index,
    )

    return {
        **stats,
        "locallow": str(locallow),
        "install_id": install_id,
        "characters": characters,
        "servers": servers,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract M&M client ledger + journal analytics")
    ap.add_argument("--path", type=Path, default=None, help="LocalLow Monsters and Memories folder")
    ap.add_argument("--ledger-only", action="store_true")
    ap.add_argument("--journal-only", action="store_true")
    args = ap.parse_args()

    locallow = args.path or default_locallow()
    ledger = not args.journal_only
    journal = not args.ledger_only
    stats = run(locallow, ledger=ledger, journal=journal)

    print(f"Scanned {locallow}")
    if ledger:
        print(f"  {stats['files']:,} ledger files, {stats['events']:,} events")
        print(f"  kills={stats['kills']:,}  drops={stats['drops']:,}  drop_rates={stats['drop_rates']:,}")
        print(f"  heatmap={stats['heatmap']:,}  levelups={stats['levelups']:,}  trades={stats['trades']:,}")
        print(f"  party={stats['party']:,}  vendor={stats['vendor']:,}  mobs={stats['mobs']:,}")
    if journal:
        print(f"  journal NPCs={stats['journal_npcs']:,}")
    if stats.get("hardcore_n"):
        print(f"  hardcore profiles={stats['hardcore_n']:,}")
    if stats["errors"]:
        print(f"  {stats['errors']} files failed to parse")
    print("  data/ledger-*.json + ledger-manifest.json + ledger-report.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
