"""Tests for combat chat line parsing (real session samples)."""

from mnm_combat_text import parse_line, parse_ocr_line, split_glued_combat_line


def test_you_crush():
    ev = parse_line("You crush a desert bat for 1 point of damage.")
    assert ev["kind"] == "melee"
    assert ev["direction"] == "outgoing"
    assert ev["actor"] == "You"
    assert ev["amount"] == 1
    assert ev["outcome"] == "hit"
    assert ev["channel"] == "CombatHitMine"


def test_pet_slash():
    ev = parse_line("Your pet Zanobab slashes a jackal pup for 5 points of damage.")
    assert ev["kind"] == "melee"
    assert ev["direction"] == "outgoing"
    assert ev["pet"] == "Zanobab"
    assert ev["amount"] == 5
    assert ev["channel"] == "CombatHitPet"


def test_other_player_crush():
    ev = parse_line("Mooto crushes a desert bat for 8 points of damage.")
    assert ev["actor"] == "Mooto"
    assert ev["direction"] == "neutral"
    assert ev["amount"] == 8


def test_heal_possessive_ability():
    ev = parse_line("Mooto's Minor Heal heals Mooto for 11 Health.")
    assert ev["kind"] == "heal"
    assert ev["actor"] == "Mooto"
    assert ev["ability"] == "Minor Heal"
    assert ev["target"] == "Mooto"
    assert ev["amount"] == 11


def test_life_drain():
    ev = parse_line("Your Life Drain hits a spiderling for 4 points of Corruption Damage.")
    assert ev["kind"] == "ability"
    assert ev["direction"] == "outgoing"
    assert ev["ability"] == "Life Drain"
    assert ev["damage_type"] == "Corruption"
    assert ev["channel"] == "AbilityHitDetrimentMine"


def test_life_drain_heal():
    ev = parse_line("Your Life Drain heals you for 4 Health.")
    assert ev["kind"] == "heal"
    assert ev["ability"] == "Life Drain"
    assert ev["target"] == "You"
    assert ev["amount"] == 4


def test_glued_line_split():
    glued = (
        "Your pet Zanobab slashes a desert bat for 5 points of "
        "You crush a desert bat for 12 points of damage."
    )
    parts = split_glued_combat_line(glued)
    assert len(parts) == 2
    events = parse_ocr_line(glued)
    assert len(events) == 2
    assert events[0]["pet"] == "Zanobab"
    assert events[0]["amount"] == 5
    assert events[1]["actor"] == "You"
    assert events[1]["amount"] == 12


def test_glued_pet_and_incoming():
    glued = (
        "Your pet Zanobab slashes a spiderling for 1 point of "
        "a spiderling hits YOU for 1 point of damage."
    )
    events = parse_ocr_line(glued)
    assert len(events) == 2
    assert events[0]["channel"] == "CombatHitPet"
    assert events[1]["channel"] == "CombatHitVictim"


def test_glued_party_combat():
    glued = (
        "Enchante punches a spiderling for 1 point of "
        "Past slashes a spiderling for 1 point of damage."
    )
    events = parse_ocr_line(glued)
    assert len(events) == 2
    assert events[0]["actor"] == "Enchante"
    assert events[1]["actor"] == "Past"


def test_ocr_soiderling_and_vou():
    ev = parse_line("a soiderling hits YOU for 2 points of damage.")
    assert "spiderling" in ev["actor"]
    ev2 = parse_line("Your Life Drain heals vou for 4 Health")
    assert ev2["target"] == "You"


def test_kick_incoming():
    ev = parse_line("a snake's Kick hits YOU for 1 point of damage!")
    assert ev["direction"] == "incoming"
    assert ev["ability"] == "Kick"
    assert ev["target"] == "You"


def test_cast_and_interrupt():
    ev = parse_line("You begin casting Life Drain.")
    assert ev["kind"] == "cast"
    assert ev["outcome"] == "begin"
    ev2 = parse_line("Your casting is interrupted!")
    assert ev2["outcome"] == "interrupted"


def test_pet_targeted():
    ev = parse_line("a rotting skeleton crushes your pet Zanobab for 1 point of damage.")
    assert ev["direction"] == "incoming"
    assert ev["pet"] == "Zanobab"
    assert ev["channel"] == "CombatHitPet"


def test_player_vs_player():
    ev = parse_line("a large rat bites Mooto for 2 points of damage.")
    assert ev["actor"] == "a large rat"
    assert ev["target"] == "Mooto"
    assert ev["direction"] == "neutral"
