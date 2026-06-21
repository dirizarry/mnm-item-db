"""Tests for gen_wiki_loot_fixes insertion and duplicate detection."""

from __future__ import annotations

import gen_wiki_loot_fixes as gwl

ASHIRA_BOX = """
| known_loot =

| common_loot =
* [[Ashira Warrior Pelt]]
* [[Ashira Warrior Bracer]]
* [[Ashira Warrior Necklace]]

| factions =
"""


ZOMBIE_ITEM_BOX = """
|dropsfrom =
[[Shaded Dunes]]
* [[a stumbling zombie]]
|recipes =
"""


def test_mob_loot_skips_item_already_in_common_loot():
    assert gwl.append_mob_loot(ASHIRA_BOX, "Ashira Warrior Pelt") is None


def test_mob_loot_appends_new_item_to_common_loot():
    out = gwl.append_mob_loot(ASHIRA_BOX, "Ashira Tail")
    assert out is not None
    assert "* [[Ashira Tail]]" in out
    assert out.count("* [[Ashira Warrior Pelt]]") == 1


def test_mob_loot_preserves_following_params():
    box = """| common_loot =

| factions =

| opposing_factions =
"""
    out = gwl.append_mob_loot(box, "Ashira Tail")
    assert out is not None
    assert "| factions =" in out
    assert "| opposing_factions =" in out


def test_dropsfrom_inserts_under_matching_zone_at_end():
    out = gwl.append_dropsfrom(
        ZOMBIE_ITEM_BOX,
        "A risen zombie",
        "Tomb of the Last Wyrmsbane",
    )
    assert out is not None
    p = gwl.parse_params(out)
    block = p["dropsfrom"]
    dunes_idx = block.index("[[Shaded Dunes]]")
    stumble_idx = block.index("* [[a stumbling zombie]]")
    tomb_idx = block.index("[[Tomb of the Last Wyrmsbane]]")
    risen_idx = block.index("* [[A risen zombie]]")
    assert dunes_idx < stumble_idx < tomb_idx < risen_idx


def test_dropsfrom_skips_existing_mob():
    assert gwl.append_dropsfrom(ZOMBIE_ITEM_BOX, "a stumbling zombie", "Shaded Dunes") is None


def test_mob_loot_skips_hyphenated_title_variant():
    box = """
| common_loot =
* [[Low Quality Jackal Pelt]]
* [[Raw Jackal Meat]]

| factions =
"""
    assert gwl.append_mob_loot(box, "Low-Quality Jackal Pelt") is None


def test_edge_needs_mob_fix_false_for_hyphen_variant_in_monsters_json():
    edge = {
        "item_title": "Low-Quality Jackal Pelt",
        "mob_title": "A jackal pup",
        "via_mob": False,
        "via_ledger": True,
    }
    mobs_index = {
        "A jackal pup": {
            "title": "A jackal pup",
            "common_loot": ["Low Quality Jackal Pelt"],
        }
    }
    assert gwl.edge_needs_mob_fix(edge, mobs_index) is False


def test_edge_needs_mob_fix_false_when_monsters_json_lists_item():
    edge = {
        "item_title": "Ashira Warrior Pelt",
        "mob_title": "An ashira warrior",
        "via_mob": False,
        "via_ledger": True,
    }
    mobs_index = {
        "An ashira warrior": {
            "title": "An ashira warrior",
            "common_loot": ["Ashira Warrior Pelt"],
        }
    }
    assert gwl.edge_needs_mob_fix(edge, mobs_index) is False
