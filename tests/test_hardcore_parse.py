"""Tests for character-select screenshot OCR parsing."""

from __future__ import annotations

from mnm_hardcore_parse import parse_char_select_text, profile_token


SAMPLE_OCR = """
Beta Server PvP
Onidifs (4 Gnome Necromancer)
Current Zone: Night Harbor
Hardcore
Enter World
"""


def test_parse_hardcore_character_select():
    parsed = parse_char_select_text(SAMPLE_OCR)
    assert parsed["character"] == "Onidifs"
    assert parsed["level"] == 4
    assert parsed["race_class"] == "Gnome Necromancer"
    assert parsed["zone"] == "Night Harbor"
    assert parsed["server"] == "betapvp"
    assert parsed["hardcore_detected"] is True
    assert parsed["parse_ok"] is True


def test_pvp_in_server_name_is_not_hardcore():
    parsed = parse_char_select_text("Beta Server PvP\nFoo (1 Human Warrior)\nCurrent Zone: X")
    assert parsed["hardcore_detected"] is False
    assert parsed["parse_ok"] is False


def test_profile_token_stable():
    a = profile_token("betapvp", "Onidifs", "2026-06-19T12:00:00")
    b = profile_token("betapvp", "Onidifs", "2026-06-19T12:00:00")
    assert a == b
    assert len(a) == 20
