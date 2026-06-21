#!/usr/bin/env python3
"""Convert data/base_stats.json (race/class base stats from creation screenshots)
into site/base_stats.js keyed by "RACECODE|CLASSCODE" for the planner."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "data" / "base_stats.json"
OUT = ROOT / "site" / "base_stats.js"

RACE = {
    "deep dwarf": "DDF",
    "deep elf": "DEF",
    "deep gnome": "DGN",
    "dwarf": "DWF",
    "gnome": "GNM",
    "goblin": "GOB",
    "halfling": "HFL",
    "high elf": "HIE",
    "human": "HUM",
    "ogre": "OGR",
    "troll": "TRL",
    "wood elf": "ELF",
}
CLS = {
    "archer": "ARC",
    "bard": "BRD",
    "beastmaster": "BST",
    "cleric": "CLR",
    "druid": "DRU",
    "elementalist": "ELE",
    "enchanter": "ENC",
    "fighter": "FTR",
    "inquisitor": "INQ",
    "monk": "MNK",
    "necromancer": "NEC",
    "paladin": "PAL",
    "ranger": "RNG",
    "rogue": "ROG",
    "shadowknight": "SHD",
    "shadow knight": "SHD",
    "shaman": "SHM",
    "spellblade": "SPB",
    "wizard": "WIZ",
}


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"Missing {SRC} — run the extraction subagent first.")
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    table: dict[str, dict] = {}
    skipped = []
    for r in rows:
        rc = RACE.get(str(r.get("race", "")).strip().lower())
        cc = CLS.get(str(r.get("class", "")).strip().lower())
        if not rc or not cc:
            skipped.append(r.get("source"))
            continue
        table[f"{rc}|{cc}"] = {
            "points": r.get("points", 0),
            "current": r.get("current", {}),
            "max": r.get("max", {}),
        }
    OUT.write_text(
        "window.MNM_BASESTATS = " + json.dumps(table, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT.name} with {len(table)} race/class combos.")
    if skipped:
        print(f"Skipped {len(skipped)} unmapped rows: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
