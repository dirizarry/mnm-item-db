#!/usr/bin/env python3
"""Re-runnable probe for on-disk combat/damage/healing data (Option B).

The architecture decision in COMBAT-CAPTURE.md is based on a one-time spike. Game
patches could add a chat/combat log to disk at any time, which would flip Option B
from "not viable" to "trivial text parser". Run this after game updates to re-check.

Usage:
    python mnm_combat_probe.py
    python mnm_combat_probe.py --path "D:\\...\\Monsters and Memories"
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from mnm_local import default_locallow, iter_ledger_files

# Phrases that would indicate combat/damage/heal *text* is being written to disk.
# Kept deliberately specific so NPC quest dialogue (journal files) does not match.
COMBAT_TEXT = re.compile(
    r"points of damage|hits? you for \d+|you hit .* for \d+|for \d+ points of|"
    r"\bslashes\b .* for \d+|\bcrushes\b .* for \d+|\bpierces\b .* for \d+|"
    r"you have gained \d+ experience|gained a level|"
    r"\bheals?\b .* for \d+ (points|hit)|"
    r'CombatHit(Mine|Victim|Other)"\s*:\s*"[^"]*\d',
    re.IGNORECASE,
)

# Directories that hold NPC quest dialogue, not combat — excluded to avoid false positives.
SKIP_DIR_PARTS = {"journal"}

# Ledger action codes we already understand (none are combat).
KNOWN_ACTS = {
    "act_01": "level-up",
    "act_02": "zone-enter/session (no payload; self actor)",
    "act_11": "item-touch",
    "act_12": "item-touch",
    "act_13": "loot",
    "act_14": "corpse/coin",
    "act_15": "item-touch",
    "act_16": "trade",
    "act_18": "ground-loot",
    "act_20": "trade",
    "act_24": "vendor",
    "act_27": "item-touch",
    "act_31": "party-create",
    "act_32": "party-join",
    "act_33": "party-disband",
    "act_34": "party-leave",
    "act_35": "party-leader",
}


def scan_text_files(locallow: Path) -> list[tuple[str, str]]:
    """Return (relative_path, sample_line) for files that contain combat text."""
    hits: list[tuple[str, str]] = []
    for path in locallow.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".dat", ".bin", ".dll", ".so"}:
            continue
        # chats.json is channel *config*, not messages — skip the known false positive.
        if path.name == "chats.json":
            continue
        # journal/* holds NPC quest dialogue ("X says ..."), never combat text.
        if SKIP_DIR_PARTS & {p.lower() for p in path.parts}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = COMBAT_TEXT.search(text)
        if m:
            line = text[max(0, m.start() - 20) : m.start() + 120].replace("\n", " ")
            hits.append((str(path.relative_to(locallow)), line.strip()))
    return hits


def scan_ledger_acts(locallow: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in iter_ledger_files(locallow):
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for code in re.findall(r'"f01"\s*:\s*"([^"]+)"', raw):
            counts[code] = counts.get(code, 0) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe for on-disk combat/damage data")
    ap.add_argument("--path", type=Path, default=None, help="LocalLow Monsters and Memories folder")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = ap.parse_args()

    locallow = args.path or default_locallow()
    if not locallow.is_dir():
        print(f"LocalLow path not found: {locallow}")
        return 1

    text_hits = scan_text_files(locallow)
    acts = scan_ledger_acts(locallow)
    unknown_acts = sorted(a for a in acts if a not in KNOWN_ACTS)
    combat_log_present = bool(text_hits)

    result = {
        "locallow": str(locallow),
        "combat_text_on_disk": combat_log_present,
        "text_hits": text_hits[:20],
        "ledger_action_codes": dict(sorted(acts.items(), key=lambda kv: -kv[1])),
        "unknown_action_codes": unknown_acts,
        "decision": (
            "Combat text now on disk — Option B viable; build a text parser."
            if combat_log_present
            else "No on-disk combat text — Option A only (see COMBAT-CAPTURE.md)."
        ),
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"LocalLow: {locallow}")
    print(f"Combat text on disk: {'YES' if combat_log_present else 'no'}")
    if text_hits:
        print("  Candidate files:")
        for rel, line in text_hits[:20]:
            print(f"    {rel}: {line[:100]}")
    print(f"Ledger action codes seen: {', '.join(sorted(acts)) or '(none)'}")
    if unknown_acts:
        print(f"  NEW/unknown codes (investigate for combat!): {', '.join(unknown_acts)}")
    print(f"\nDecision: {result['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
