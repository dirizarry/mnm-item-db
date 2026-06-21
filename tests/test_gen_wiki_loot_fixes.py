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


# --- Title matching tests ---


def test_wiki_title_key_normalizes_spaces_hyphens():
    assert gwl.wiki_title_key("Low-Quality Jackal Pelt") == gwl.wiki_title_key("Low Quality Jackal Pelt")
    assert gwl.wiki_title_key("Fire_Beetle") == gwl.wiki_title_key("Fire Beetle")


def test_title_matches_case_insensitive():
    assert gwl.title_matches("a jackal pup", "A Jackal Pup")
    assert gwl.title_matches("CINDER BEETLE", "cinder beetle")


# --- parse_dropsfrom_sections tests ---


def test_parse_dropsfrom_sections_basic():
    text = """[[Shaded Dunes]]
* [[a stumbling zombie]]
* [[a walking skeleton]]
[[Night Harbor]]
* [[a dock rat]]"""
    preamble, sections = gwl.parse_dropsfrom_sections(text)
    assert preamble == []
    assert len(sections) == 2
    assert sections[0][0] == "Shaded Dunes"
    assert sections[0][1] == ["a stumbling zombie", "a walking skeleton"]
    assert sections[1][0] == "Night Harbor"
    assert sections[1][1] == ["a dock rat"]


def test_parse_dropsfrom_sections_with_preamble():
    text = """This item drops from:
[[Shaded Dunes]]
* [[a zombie]]"""
    preamble, sections = gwl.parse_dropsfrom_sections(text)
    assert preamble == ["This item drops from:"]
    assert len(sections) == 1


def test_parse_dropsfrom_sections_no_zone():
    text = """* [[a random mob]]
* [[another mob]]"""
    preamble, sections = gwl.parse_dropsfrom_sections(text)
    assert len(sections) == 1
    assert sections[0][0] is None  # no zone header
    assert sections[0][1] == ["a random mob", "another mob"]


# --- fix_mob_page tests ---


FULL_MOB_PAGE = """{{Namedmobpage
| name = An ashira warrior
| level = 10-12
| common_loot =
* [[Ashira Warrior Pelt]]

| factions =
}}

== Description ==
A fierce warrior of the Ashira tribe."""


def test_fix_mob_page_adds_item():
    result = gwl.fix_mob_page(FULL_MOB_PAGE, "Ashira Blade")
    assert result is not None
    assert "* [[Ashira Blade]]" in result
    # Should preserve the rest of the page
    assert "== Description ==" in result
    assert "A fierce warrior" in result


def test_fix_mob_page_returns_none_for_existing_item():
    result = gwl.fix_mob_page(FULL_MOB_PAGE, "Ashira Warrior Pelt")
    assert result is None


def test_fix_mob_page_returns_none_without_namedmobpage():
    text = "Just some text without a mob template"
    result = gwl.fix_mob_page(text, "Some Item")
    assert result is None


# --- fix_item_page tests ---


FULL_ITEM_PAGE = """{{ItemBox
| name = Zombie Bone
| slot = None
}}

{{Itempage
|dropsfrom =
[[Shaded Dunes]]
* [[a stumbling zombie]]
|recipes =
}}

== Description ==
A bone from a zombie."""


def test_fix_item_page_adds_mob():
    result = gwl.fix_item_page(FULL_ITEM_PAGE, "a walking skeleton", "Tomb of the Forgotten")
    assert result is not None
    assert "* [[a walking skeleton]]" in result
    assert "[[Tomb of the Forgotten]]" in result
    # Should preserve the rest of the page
    assert "== Description ==" in result


def test_fix_item_page_returns_none_for_existing_mob():
    result = gwl.fix_item_page(FULL_ITEM_PAGE, "a stumbling zombie", "Shaded Dunes")
    assert result is None


def test_fix_item_page_returns_none_without_itempage():
    text = "Just some text without an item template"
    result = gwl.fix_item_page(text, "a mob", "Some Zone")
    assert result is None


def test_fix_item_page_adds_mob_to_existing_zone():
    result = gwl.fix_item_page(FULL_ITEM_PAGE, "a risen corpse", "Shaded Dunes")
    assert result is not None
    assert "* [[a risen corpse]]" in result
    # Should add under existing Shaded Dunes, not create new zone header
    assert result.count("[[Shaded Dunes]]") == 1


# --- edge_needs_item_fix tests ---


def test_edge_needs_item_fix_false_when_via_item():
    edge = {"item_title": "Sword", "mob_title": "Goblin", "via_item": True, "via_ledger": True}
    assert gwl.edge_needs_item_fix(edge, {}) is False


def test_edge_needs_item_fix_false_when_item_already_lists_mob():
    edge = {
        "item_title": "Zombie Bone",
        "mob_title": "a stumbling zombie",
        "via_item": False,
        "via_ledger": True,
    }
    items_index = {
        "Zombie Bone": {
            "title": "Zombie Bone",
            "drops_mobs": ["a stumbling zombie"],
        }
    }
    assert gwl.edge_needs_item_fix(edge, items_index) is False


def test_edge_needs_item_fix_true_for_new_drop():
    edge = {
        "item_title": "Zombie Bone",
        "mob_title": "a walking corpse",
        "via_item": False,
        "via_crowd": True,
    }
    items_index = {
        "Zombie Bone": {
            "title": "Zombie Bone",
            "drops_mobs": ["a stumbling zombie"],
        }
    }
    assert gwl.edge_needs_item_fix(edge, items_index) is True


# --- format_dropsfrom_block tests ---


def test_format_dropsfrom_block():
    sections = [
        ["Shaded Dunes", ["a stumbling zombie", "a walking skeleton"]],
        ["Night Harbor", ["a dock rat"]],
    ]
    result = gwl.format_dropsfrom_block([], sections)
    assert "[[Shaded Dunes]]" in result
    assert "* [[a stumbling zombie]]" in result
    assert "[[Night Harbor]]" in result
