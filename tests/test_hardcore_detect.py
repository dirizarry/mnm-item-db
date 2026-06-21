"""Tests for Magnificent (hardcore) character detection."""

from __future__ import annotations

from mnm_hardcore_detect import (
    build_hardcore_profiles,
    classify_journal,
    parse_journal_file,
    profile_token,
)


def test_player_commit_is_magnificent():
    lines = [
        {"at": "2026-06-19 11:41:10", "speaker": "Onelife", "text": "I want to be hardcore."},
        {"at": "2026-06-19 11:41:13", "speaker": "Magnificent Malkiyah", "text": "Walk the hardcore path!"},
    ]
    status, at = classify_journal(lines, character="Onelife", server="betapvp")
    assert status == "magnificent"
    assert at == "2026-06-19 11:41:10"


def test_npc_confirm_is_magnificent():
    lines = [
        {"at": "2026-06-19 12:00:00", "speaker": "Magnificent Malkiyah", "text": "Your soul has committed. You are magnificent now."},
    ]
    status, at = classify_journal(lines, character="Onelife", server="betapvp")
    assert status == "magnificent"
    assert at == "2026-06-19 12:00:00"


def test_betapvp_malkiyah_without_commit_is_candidate():
    lines = [
        {"at": "2026-06-19 11:38:41", "speaker": "Magnificent Malkiyah", "text": "If that doesn't deter you, say I want to be hardcore."},
    ]
    status, at = classify_journal(lines, character="Onelife", server="betapvp")
    assert status == "candidate"
    assert at == "2026-06-19 11:38:41"


def test_malkiyah_rejection_is_not_listed():
    lines = [
        {"at": "2026-06-19 11:38:41", "speaker": "Magnificent Malkiyah", "text": "Only we, the magnificent few... and it's too late for you!"},
    ]
    status, _ = classify_journal(lines, character="Dhomina", server="betapvp")
    assert status == "rejected"


def test_non_betapvp_without_commit_is_none():
    lines = [
        {"at": "2026-06-19 11:38:41", "speaker": "Magnificent Malkiyah", "text": "Only we, the magnificent few..."},
    ]
    status, _ = classify_journal(lines, character="Dhom", server="haradrel")
    assert status == "none"


def test_profile_token_stable():
    a = profile_token("betapvp", "Onelife", "2026-06-19 11:41:10", None)
    b = profile_token("betapvp", "Onelife", "2026-06-19 11:41:10", None)
    assert a == b
    assert len(a) == 20


def test_build_profiles_from_fixture(tmp_path):
    journal_dir = tmp_path / "betapvp" / "Onelife" / "journal"
    journal_dir.mkdir(parents=True)
    (journal_dir / "Magnificent Malkiyah").write_text(
        "2026-06-19 11:38:41: Magnificent Malkiyah says Only we, the magnificent few, get to live the hardcore life.\n",
        encoding="utf-8",
    )
    kills = [
        {
            "at": "2026-06-19T11:53:23-05:00",
            "character": "Onelife",
            "server": "betapvp",
            "character_level": 1,
            "zone": "Night Harbor",
        },
        {
            "at": "2026-06-19T15:01:33-05:00",
            "character": "Onelife",
            "server": "betapvp",
            "character_level": 4,
            "zone": "Night Harbor",
        },
    ]
    profiles = build_hardcore_profiles(tmp_path, kills, [])
    assert len(profiles) == 1
    p = profiles[0]
    assert p["character"] == "Onelife"
    assert p["server"] == "betapvp"
    assert p["status"] == "candidate"
    assert p["level"] == 4
    assert p["kills"] == 2


def test_parse_journal_file(tmp_path):
    path = tmp_path / "journal.txt"
    path.write_text(
        "2026-06-19 11:41:10: Onelife says I want to be hardcore.\n",
        encoding="utf-8",
    )
    lines = parse_journal_file(path)
    assert len(lines) == 1
    assert lines[0]["speaker"] == "Onelife"
