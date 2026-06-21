#!/usr/bin/env python3
"""Aggregate many users' upload payloads into a deduped crowd dataset.

This is the reference implementation of the cross-user dedup rules (PROVENANCE.md).
It reads ``mnm-ledger-upload/v2`` payloads and merges them by UNIONing the hashed
per-observation dedup tokens, so the same party-shared kill/loot reported by
multiple players (or re-uploaded) is counted exactly once.

Outputs:
  data/crowd-drops.json   per (item, mob, zone): distinct observations + contributors
  data/crowd-kills.json   per mob: distinct kills + contributors (drop-rate denominator)
  data/crowd-hardcore.json per (server, character): Magnificent standings

Usage:
    python mnm_crowd_aggregate.py                       # read data/crowd-inbox/*.json
    python mnm_crowd_aggregate.py --inbox path/to/dir
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DEFAULT_INBOX = DATA / "crowd-inbox"
ACCEPTED_SCHEMAS = {"mnm-ledger-upload/v2", "mnm-hardcore-submit/v1"}


def _load_payloads(inbox: Path) -> list[dict]:
    payloads = []
    for path in sorted(inbox.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(obj, dict) and obj.get("schema") in ACCEPTED_SCHEMAS:
            payloads.append(obj)
    return payloads


def aggregate(payloads: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (crowd_drops, crowd_kills, crowd_hardcore) with cross-user dedup applied."""
    # edge -> {meta, tokens:set, installs:set, raw_count:int}
    drops: dict[tuple, dict] = {}
    kills: dict[str, dict] = {}
    hardcore: dict[tuple, dict] = {}

    for p in payloads:
        install = p.get("install_id") or p.get("batch_id") or "anon"

        for d in p.get("loot_confirmations") or []:
            item = d.get("item_name")
            mob = d.get("mob_name")
            zone = d.get("zone")
            if not item or not mob:
                continue
            key = (item.casefold(), mob.casefold(), (zone or "").casefold())
            edge = drops.setdefault(key, {
                "item_name": item,
                "item_hid": d.get("item_hid"),
                "mob_name": mob,
                "zone": zone,
                "tokens": set(),
                "installs": set(),
                "raw_count": 0,
            })
            tokens = d.get("dedup_tokens") or []
            edge["tokens"].update(tokens)
            edge["installs"].add(install)
            # Fall back to raw count when a client predates token emission (v1).
            edge["raw_count"] += int(d.get("count") or 0) if not tokens else 0
            edge["item_hid"] = edge["item_hid"] or d.get("item_hid")

        for m in p.get("top_mobs") or []:
            name = m.get("name")
            if not name:
                continue
            rec = kills.setdefault(name.casefold(), {
                "mob_name": name,
                "tokens": set(),
                "installs": set(),
                "raw_count": 0,
                "zones": set(),
            })
            tokens = m.get("dedup_tokens") or []
            rec["tokens"].update(tokens)
            rec["installs"].add(install)
            rec["raw_count"] += int(m.get("kill_count") or 0) if not tokens else 0
            for z in m.get("zones") or []:
                rec["zones"].add(z)

        for hp in p.get("hardcore_profiles") or []:
            server = hp.get("server") or ""
            character = hp.get("character") or ""
            if not server or not character:
                continue
            key = (server.casefold(), character.casefold())
            rec = hardcore.setdefault(key, {
                "server": server,
                "character": character,
                "level": 0,
                "kills": 0,
                "zone": None,
                "status": "candidate",
                "source": "ledger",
                "committed_at": None,
                "last_seen": None,
                "profile_token": hp.get("profile_token"),
                "installs": set(),
            })
            rec["installs"].add(install)
            level = int(hp.get("level") or 0)
            kills_n = int(hp.get("kills") or 0)
            last_seen = hp.get("last_seen") or ""
            committed_at = hp.get("committed_at") or ""
            if level > rec["level"] or (level == rec["level"] and last_seen > (rec["last_seen"] or "")):
                rec["level"] = level
                rec["kills"] = kills_n
                rec["zone"] = hp.get("zone")
                rec["status"] = hp.get("status") or rec["status"]
                rec["source"] = hp.get("source") or rec["source"]
                rec["committed_at"] = committed_at or rec["committed_at"]
                rec["last_seen"] = last_seen or rec["last_seen"]
                rec["profile_token"] = hp.get("profile_token") or rec["profile_token"]
            elif level == rec["level"] and kills_n > rec["kills"]:
                rec["kills"] = kills_n
                rec["zone"] = hp.get("zone") or rec["zone"]
                rec["last_seen"] = last_seen or rec["last_seen"]

        if p.get("schema") == "mnm-hardcore-submit/v1":
            prof = p.get("profile") or {}
            proof = p.get("proof") or {}
            if not proof.get("hardcore_detected"):
                continue
            server = prof.get("server") or ""
            character = prof.get("character") or ""
            if not server or not character:
                continue
            key = (server.casefold(), character.casefold())
            rec = hardcore.setdefault(key, {
                "server": server,
                "character": character,
                "level": 0,
                "kills": 0,
                "zone": None,
                "status": "magnificent",
                "source": "community",
                "race_class": prof.get("race_class"),
                "committed_at": prof.get("committed_at"),
                "last_seen": prof.get("last_seen") or prof.get("committed_at"),
                "profile_token": prof.get("profile_token"),
                "installs": set(),
            })
            rec["installs"].add(install)
            level = int(prof.get("level") or 0)
            if level >= rec["level"]:
                rec["level"] = level
                rec["zone"] = prof.get("zone") or rec["zone"]
                rec["race_class"] = prof.get("race_class") or rec.get("race_class")
                rec["last_seen"] = prof.get("last_seen") or rec["last_seen"]
                rec["profile_token"] = prof.get("profile_token") or rec["profile_token"]

    crowd_drops = []
    for edge in drops.values():
        observations = len(edge["tokens"]) or edge["raw_count"]
        crowd_drops.append({
            "item_name": edge["item_name"],
            "item_hid": edge["item_hid"],
            "mob_name": edge["mob_name"],
            "zone": edge["zone"],
            "observations": observations,
            "contributors": len(edge["installs"]),
        })
    crowd_drops.sort(key=lambda e: -e["observations"])

    crowd_kills = []
    for rec in kills.values():
        distinct = len(rec["tokens"]) or rec["raw_count"]
        crowd_kills.append({
            "mob_name": rec["mob_name"],
            "kills": distinct,
            "contributors": len(rec["installs"]),
            "zones": sorted(rec["zones"]),
        })
    crowd_kills.sort(key=lambda e: -e["kills"])

    crowd_hardcore = []
    for rec in hardcore.values():
        crowd_hardcore.append({
            "server": rec["server"],
            "character": rec["character"],
            "level": rec["level"],
            "zone": rec["zone"],
            "kills": rec["kills"],
            "status": rec["status"],
            "source": rec.get("source"),
            "race_class": rec.get("race_class"),
            "committed_at": rec["committed_at"],
            "last_seen": rec["last_seen"],
            "profile_token": rec["profile_token"],
            "contributors": len(rec["installs"]),
        })
    crowd_hardcore.sort(
        key=lambda e: (-e["level"], -e["kills"], e.get("committed_at") or "", e.get("character") or "")
    )

    return crowd_drops, crowd_kills, crowd_hardcore


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate crowd upload payloads (deduped)")
    ap.add_argument("--inbox", type=Path, default=DEFAULT_INBOX,
                    help="Directory of mnm-ledger-upload/v2 payload JSON files")
    args = ap.parse_args()

    if not args.inbox.is_dir():
        print(f"Inbox not found: {args.inbox}")
        print("Create it and drop upload payloads in, or point --inbox at a directory.")
        return 1

    payloads = _load_payloads(args.inbox)
    if not payloads:
        print(f"No accepted payloads in {args.inbox}")
        return 1

    crowd_drops, crowd_kills, crowd_hardcore = aggregate(payloads)
    (DATA / "crowd-drops.json").write_text(
        json.dumps(crowd_drops, indent=2, ensure_ascii=False), encoding="utf-8")
    (DATA / "crowd-kills.json").write_text(
        json.dumps(crowd_kills, indent=2, ensure_ascii=False), encoding="utf-8")
    (DATA / "crowd-hardcore.json").write_text(
        json.dumps(crowd_hardcore, indent=2, ensure_ascii=False), encoding="utf-8")

    installs = {p.get("install_id") for p in payloads}
    print(f"Aggregated {len(payloads)} payloads from {len(installs)} installs")
    print(f"  crowd-drops.json: {len(crowd_drops)} deduped drop edges")
    print(f"  crowd-kills.json: {len(crowd_kills)} deduped mob kill totals")
    print(f"  crowd-hardcore.json: {len(crowd_hardcore)} Magnificent standings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
