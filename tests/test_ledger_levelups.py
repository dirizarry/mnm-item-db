"""Level-up extraction from Character + Social ledgers."""

from __future__ import annotations

import json

from mnm_ledger_db import extract_ledger, new_state


def test_character_ledger_own_levelups(tmp_path):
    locallow = tmp_path / "betapvp" / "Onelife" / "Ledger"
    locallow.mkdir(parents=True)
    (locallow / "Onelife_Character_2026-06-19.json").write_text(
        json.dumps(
            {
                "c01": [
                    {
                        "f01": "act_01",
                        "f02": "2",
                        "f03": '{"d21":2,"d22":1,"d23":""}',
                        "f04": "2026-06-19T11:58:48-05:00",
                        "f05": "zone_bmlnaHRoYXJib3I=",
                        "f06": 2,
                        "f07": "Onelife",
                        "f09": "Onelife",
                    },
                    {
                        "f01": "act_01",
                        "f02": "3",
                        "f03": '{"d21":3,"d22":2,"d23":""}',
                        "f04": "2026-06-19T12:38:38-05:00",
                        "f05": "zone_bmlnaHRoYXJib3I=",
                        "f06": 3,
                        "f07": "Onelife",
                        "f09": "Onelife",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    state = new_state()
    extract_ledger(locallow / "Onelife_Character_2026-06-19.json", tmp_path, state)
    own = [lu for lu in state["levelups"] if lu["character"] == "Onelife"]
    assert len(own) == 2
    assert own[0]["old_level"] == 1 and own[0]["new_level"] == 2
    assert own[1]["old_level"] == 2 and own[1]["new_level"] == 3


def test_social_ledger_party_levelup_still_captured(tmp_path):
    locallow = tmp_path / "betapvp" / "Onelife" / "Ledger"
    locallow.mkdir(parents=True)
    (locallow / "Onelife_Social_2026-06-19.json").write_text(
        json.dumps(
            {
                "c01": [
                    {
                        "f01": "act_01",
                        "f02": "2",
                        "f03": '{"d21":2,"d22":1,"d23":""}',
                        "f04": "2026-06-19T19:45:55-05:00",
                        "f05": "zone_bmlnaHRoYXJib3I=",
                        "f06": 2,
                        "f07": "Glimz",
                        "f09": "Onelife",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    state = new_state()
    extract_ledger(locallow / "Onelife_Social_2026-06-19.json", tmp_path, state)
    assert len(state["levelups"]) == 1
    assert state["levelups"][0]["character"] == "Glimz"
    assert state["levelups"][0]["observer"] == "Onelife"
