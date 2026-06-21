"""Minimal wiki page stubs for loot fixes when a page does not exist yet."""

from __future__ import annotations

import re

from mnm_zones import normalize_zone_name


def item_link_id(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def stub_namedmob_page(title: str, zones: list[str]) -> str:
    zone_vals = []
    seen: set[str] = set()
    for z in zones:
        nz = normalize_zone_name(z) if z else None
        if not nz:
            continue
        fold = nz.casefold()
        if fold not in seen:
            seen.add(fold)
            zone_vals.append(nz)
    zone_param = ", ".join(zone_vals)
    return (
        "{{Namedmobpage\n\n"
        f"| imagefilename     = {title}.png\n"
        "| width             = 300px\n"
        f"| caption           = {title}\n\n"
        "| race              = \n"
        "| class             = \n"
        "| level             = \n"
        "| agro_radius       = \n"
        "| run_speed         = \n\n"
        f"| zone              = {zone_param}\n"
        "| respawn_time      = \n\n"
        "| AC                = \n"
        "| HP                = \n"
        "| HP_regen          = \n"
        "| mana_regen        = \n\n"
        "| attacks_per_round = \n"
        "| attack_speed      = \n"
        "| damage_per_hit    = \n"
        "| special           = \n\n"
        "| location          = \n"
        "| description       = \n\n"
        "| known_loot =\n\n"
        "| common_loot =\n\n"
        "| factions = \n\n"
        "| opposing_factions = \n\n"
        "| related_quests = \n\n"
        "}}"
    )


def stub_item_page(title: str, item_rec: dict | None = None) -> str:
    rec = item_rec or {}
    icon_id = rec.get("icon_id") or ""
    weight = rec.get("weight")
    weight_s = str(weight) if weight is not None else ""
    size = rec.get("size") or "SMALL"
    link_id = item_link_id(rec.get("name") or title) if rec else ""
    box = (
        "{{ItemBox\n"
        f"| item_name     = {title}\n"
    )
    if link_id:
        box += f"| item_link_id  = {link_id}\n"
    box += (
        f"| icon_id       = {icon_id}\n"
        f"| weight        = {weight_s}\n"
        f"| size          = {size}\n"
        "| item_stats    = \n"
        "}}\n\n"
        "{{Itempage\n"
        "|dropsfrom = \n\n"
        "|relatedquests =\n\n"
        "}}\n\n"
        "[[Category:Inventory Items]]"
    )
    return box
