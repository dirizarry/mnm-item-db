"""Tests for build_relations.py drop graph and zone building."""

from __future__ import annotations

import build_relations as br


class TestNormKey:
    """Tests for title normalization."""

    def test_casefold(self):
        assert br.norm_key("Cinder Beetle") == br.norm_key("cinder beetle")
        assert br.norm_key("A JACKAL PUP") == br.norm_key("a jackal pup")

    def test_strips_whitespace(self):
        assert br.norm_key("  Sword  ") == br.norm_key("Sword")
        assert br.norm_key("\tShield\n") == br.norm_key("Shield")


class TestCanonicalTitles:
    """Tests for building canonical title maps."""

    def test_items_canonical(self):
        items = [
            {"title": "Cinder Beetle Mandible", "name": "cinder beetle mandible"},
            {"title": "Fire Beetle Carapace"},
        ]
        mobs = [{"title": "A Jackal Pup"}]
        item_canon, mob_canon = br.canonical_titles(items, mobs)

        assert br.resolve_item("cinder beetle mandible", item_canon) == "Cinder Beetle Mandible"
        assert br.resolve_item("FIRE BEETLE CARAPACE", item_canon) == "Fire Beetle Carapace"
        assert br.resolve_item("nonexistent", item_canon) is None

    def test_mobs_canonical(self):
        items = []
        mobs = [{"title": "A Jackal Pup"}, {"title": "Desert Bat"}]
        item_canon, mob_canon = br.canonical_titles(items, mobs)

        assert br.resolve_mob("a jackal pup", mob_canon) == "A Jackal Pup"
        assert br.resolve_mob("DESERT BAT", mob_canon) == "Desert Bat"


class TestBuildDrops:
    """Tests for the core build_drops() function."""

    def test_basic_mob_loot(self):
        """Mobs with loot fields create drop edges."""
        items = [{"title": "Pelt"}]
        mobs = [
            {
                "title": "A Jackal Pup",
                "zone": "Night Harbor",
                "common_loot": ["Pelt"],
            }
        ]
        drops = br.build_drops(items, mobs)

        assert len(drops) == 1
        d = drops[0]
        assert d["item_title"] == "Pelt"
        assert d["mob_title"] == "A Jackal Pup"
        assert d["zone"] == "Night Harbor"
        assert d["via_mob"] is True
        assert d["via_item"] is False
        assert d["loot_kind"] == "common"

    def test_item_dropsfrom(self):
        """Items with drops_mobs field create drop edges."""
        items = [
            {
                "title": "Spiderling Eye",
                "drops_mobs": ["A Spiderling"],
                "drops_zones": ["Night Harbor"],
            }
        ]
        mobs = [{"title": "A Spiderling", "zone": "Night Harbor"}]
        drops = br.build_drops(items, mobs)

        assert len(drops) == 1
        d = drops[0]
        assert d["item_title"] == "Spiderling Eye"
        assert d["mob_title"] == "A Spiderling"
        assert d["via_item"] is True
        assert d["via_mob"] is False

    def test_both_sources_corroborated(self):
        """When both mob and item pages list the drop with same zone, it's corroborated."""
        items = [
            {
                "title": "Pelt",
                "drops_mobs": ["A Jackal Pup"],
                "drops_zones": ["Night Harbor"],
            }
        ]
        mobs = [{"title": "A Jackal Pup", "zone": "Night Harbor", "common_loot": ["Pelt"]}]
        drops = br.build_drops(items, mobs)

        # Should be merged into 1 edge since zone matches
        assert len(drops) == 1
        d = drops[0]
        assert d["via_mob"] is True
        assert d["via_item"] is True
        # wiki_corroborated = both wiki sources agree, but no empirical observation
        assert d["status"] == "wiki_corroborated"
        assert d["confidence"] > 0.7

    def test_wiki_plus_ledger_confirmed(self):
        """Wiki sources + ledger observation = confirmed."""
        items = [
            {
                "title": "Pelt",
                "drops_mobs": ["A Jackal Pup"],
                "drops_zones": ["Night Harbor"],
            }
        ]
        mobs = [{"title": "A Jackal Pup", "zone": "Night Harbor", "common_loot": ["Pelt"]}]
        ledger = [
            {
                "item_name": "pelt",
                "mob_name": "a jackal pup",
                "zone": "Night Harbor",
                "count": 3,
            }
        ]
        drops = br.build_drops(items, mobs, ledger_drops=ledger)

        assert len(drops) == 1
        d = drops[0]
        assert d["via_mob"] is True
        assert d["via_item"] is True
        assert d["via_ledger"] is True
        assert d["status"] == "confirmed"
        assert d["confidence"] > 0.85

    def test_ledger_drops_merged(self):
        """Ledger drops are merged with wiki data."""
        items = [{"title": "Pelt"}]
        mobs = [{"title": "A Jackal Pup", "zone": "Night Harbor"}]
        ledger = [
            {
                "item_name": "pelt",  # lowercase to test canonicalization
                "mob_name": "a jackal pup",
                "zone": "Night Harbor",
                "count": 5,
                "sources": ["user1"],
            }
        ]
        drops = br.build_drops(items, mobs, ledger_drops=ledger)

        assert len(drops) == 1
        d = drops[0]
        assert d["item_title"] == "Pelt"  # canonicalized
        assert d["mob_title"] == "A Jackal Pup"  # canonicalized
        assert d["via_ledger"] is True
        assert d["observations"] == 5

    def test_crowd_drops_merged(self):
        """Crowd drops are merged with wiki data."""
        items = [{"title": "Rare Drop"}]
        mobs = [{"title": "A Boss Mob"}]
        crowd = [
            {
                "item_title": "Rare Drop",
                "mob_title": "A Boss Mob",
                "zone": "Dungeon",
                "observations": 10,
                "contributors": 3,
            }
        ]
        drops = br.build_drops(items, mobs, crowd_drops=crowd)

        assert len(drops) == 1
        d = drops[0]
        assert d["via_crowd"] is True
        assert d["observations"] == 10
        assert d["contributors"] == 3

    def test_unique_loot_kind_precedence(self):
        """Unique loot takes precedence over common."""
        items = [{"title": "Rare Ring", "drops_mobs": ["A Boss"]}]
        mobs = [
            {
                "title": "A Boss",
                "unique_loot": ["Rare Ring"],
                "common_loot": ["Rare Ring"],
            }
        ]
        drops = br.build_drops(items, mobs)

        assert len(drops) == 1
        assert drops[0]["loot_kind"] == "unique"

    def test_empty_inputs(self):
        """Empty inputs produce no drops."""
        drops = br.build_drops([], [])
        assert drops == []

    def test_no_match_for_unknown_item(self):
        """Unknown items in mob loot don't create edges if item doesn't exist."""
        items = []
        mobs = [{"title": "A Mob", "common_loot": ["Unknown Item"]}]
        drops = br.build_drops(items, mobs)
        # The mob lists an item that doesn't exist in items, so resolve_item returns None
        # and the add() function early-returns
        assert len(drops) == 0


class TestBuildZones:
    """Tests for zone index building."""

    def test_zones_from_mobs(self):
        mobs = [
            {"title": "Mob A", "zone": "Zone Alpha"},
            {"title": "Mob B", "zone": "Zone Alpha"},
            {"title": "Mob C", "zone": "Zone Beta"},
        ]
        drops = []
        zones = br.build_zones(mobs, drops)

        zone_names = {z["name"] for z in zones}
        assert "Zone Alpha" in zone_names
        assert "Zone Beta" in zone_names

        alpha = next(z for z in zones if z["name"] == "Zone Alpha")
        assert alpha["mob_count"] == 2

    def test_zones_from_drops(self):
        mobs = []
        drops = [
            {"item_title": "Item", "mob_title": "Mob", "zone": "Drop Zone"},
            {"item_title": "Item2", "mob_title": "Mob2", "zone": "Drop Zone"},
        ]
        zones = br.build_zones(mobs, drops)

        assert len(zones) == 1
        assert zones[0]["name"] == "Drop Zone"
        assert zones[0]["drop_count"] == 2


class TestLoadJson:
    """Tests for load_json helper."""

    def test_nonexistent_file(self, tmp_path):
        result = br.load_json(tmp_path / "nonexistent.json")
        assert result == []

    def test_valid_json_file(self, tmp_path):
        import json

        path = tmp_path / "test.json"
        path.write_text(json.dumps([{"a": 1}, {"b": 2}]), encoding="utf-8")
        result = br.load_json(path)
        assert result == [{"a": 1}, {"b": 2}]
