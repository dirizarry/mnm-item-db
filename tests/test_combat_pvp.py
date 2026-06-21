"""Tests for PvP aggression detection."""

from mnm_combat_pvp import annotate_pvp, is_incoming_player_aggression, should_alert_pvp


def test_player_hits_you():
    ev = annotate_pvp({
        "raw": "Past slashes YOU for 12 points of damage.",
        "kind": "melee",
        "direction": "incoming",
        "actor": "Past",
        "target": "You",
    })
    assert ev["pvp_aggressive"]
    assert should_alert_pvp(ev, {"pvp_alert_enabled": True})


def test_monster_hits_you_not_pvp():
    ev = annotate_pvp({
        "raw": "a desert bat bites YOU for 1 point of damage.",
        "kind": "melee",
        "direction": "incoming",
        "actor": "a desert bat",
        "target": "You",
    })
    assert not ev["pvp_aggressive"]


def test_player_hits_pet():
    ev = annotate_pvp({
        "raw": "Past crushes your pet Zanobab for 3 points of damage.",
        "kind": "melee",
        "direction": "incoming",
        "actor": "Past",
        "target": "Zanobab",
        "pet": "Zanobab",
    })
    assert ev["pvp_aggressive"]


def test_player_miss_you():
    ev = annotate_pvp({
        "raw": "Enchante tries to punch YOU, but misses!",
        "kind": "miss",
        "direction": "incoming",
        "actor": "Enchante",
        "target": "You",
        "verb": "punch",
    })
    assert is_incoming_player_aggression(ev)


def test_pet_outgoing_not_aggressive():
    ev = annotate_pvp({
        "raw": "Your pet Zanobab slashes a spiderling for 2 points of damage.",
        "kind": "melee",
        "direction": "outgoing",
        "actor": "Zanobab",
        "target": "a spiderling",
        "pet": "Zanobab",
        "channel": "CombatHitPet",
    })
    assert not ev["pvp_aggressive"]
