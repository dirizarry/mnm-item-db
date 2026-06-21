"""Tests for memory combat line validation."""

from client_re.combat_validate import is_valid_memory_combat_line, normalize_memory_line


def test_normalize_strips_color():
    raw = "<color=#FFFF00>Your Electric Infusion hits a rat for 20 point of damage."
    assert normalize_memory_line(raw).startswith("Your Electric")


def test_rejects_ui_template_glue():
    raw = (
        "to consent.You have no other party members to deny."
        "You have slain You have unlocked a cantrip!"
    )
    assert not is_valid_memory_combat_line(raw)


def test_accepts_real_slain_line():
    assert is_valid_memory_combat_line("a feisty fishwife has been slain by Handy!")


def test_accepts_real_damage_line():
    assert is_valid_memory_combat_line(
        "a mercenary magus's Lavaburst hits a dockworker for 126 point of damage."
    )
