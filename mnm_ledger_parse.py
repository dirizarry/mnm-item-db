"""Ledger event classification — mob kills vs ground loot vs party coin splits.

Key finding from the data: on act_14 corpse events the ``d11`` field is *not* a
mob level — it is exactly the copper that dropped (d11 == copper in 100% of
corpse events, and a single mob shows a wide spread of d11 values). So we never
treat d11 as a level. A real kill is an ``npc_corpse`` event; ``party_split``
events are group coin-distribution records, not kills.
"""

from __future__ import annotations

CORPSE_HID = "npc_corpse"
PARTY_SPLIT_HID = "party_split"
GROUND_HIDS = {"drop_action"}


def is_combat_kill(mob_name: str | None, mob_hid: str | None, *, kind: str = "act_14") -> bool:
    """True only for real mob kills (a corpse). Excludes coin splits and ground loot."""
    if kind != "act_14":
        return False
    if mob_hid != CORPSE_HID:
        return False
    name = (mob_name or "").strip()
    return not (not name or name.lower() == "ground")


def is_ground_loot(kind: str, mob_name: str | None, mob_hid: str | None) -> bool:
    return kind == "act_18" or (mob_name or "").lower() == "ground" or mob_hid in GROUND_HIDS
