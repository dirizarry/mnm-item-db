"""Combat OCR stream config and channel filtering."""

from mnm_combat_streams import (
    channels_from_filter_paths,
    event_allowed,
    filter_paths_from_channels,
    iter_filter_leaves,
    normalize_stream,
)
from mnm_combat_channels import build_filter_menu, infer_channel


def test_iter_filter_leaves_melee_hits_me():
    paths = {p for p, _l, _c in iter_filter_leaves()}
    assert "melee:Hits:Me" in paths
    assert "melee:Hits:Mine" in paths


def test_channels_from_filter_paths_melee_hits_me():
    chs = channels_from_filter_paths(["melee:Hits:Me", "melee:Hits:Players"])
    assert chs == ["CombatHitMine", "CombatHitOtherPlayer"]


def test_filter_paths_cover_meter_subset():
    from mnm_combat_channels import ROLE_CHANNELS

    meter = set(ROLE_CHANNELS["meter"])
    paths = filter_paths_from_channels(meter)
    back = set(channels_from_filter_paths(paths))
    assert "CombatHitMine" in back
    assert "AbilityHitBenefitMine" in back
    assert back <= meter


def test_normalize_stream_from_filter_paths():
    raw = {
        "id": "a",
        "label": "Meter",
        "window_id": "combat",
        "region": {"left": 1, "top": 2, "width": 100, "height": 200},
        "filter_paths": ["melee:Hits:Me", "melee:Misses:Me"],
    }
    norm = normalize_stream(raw)
    assert norm is not None
    assert "CombatHitMine" in norm["channels"]
    assert "CombatMissMine" in norm["channels"]


def test_event_allowed_respects_channel_filter():
    ev = {
        "kind": "melee",
        "direction": "outgoing",
        "actor": "You",
        "target": "a rat",
        "amount": 12,
        "channel": "CombatHitMine",
    }
    assert event_allowed(ev, {"CombatHitMine"})
    assert not event_allowed(ev, {"CombatHitVictim"})


def test_event_allowed_ability_status_interrupt():
    ev = {"kind": "cast", "outcome": "interrupted", "channel": None}
    assert event_allowed(ev, {"AbilityStatus"})


def test_infer_channel_matches_filter_leaf():
    menu = build_filter_menu()
    for path_id, _label, chs in iter_filter_leaves(menu):
        if not chs or len(chs) != 1:
            continue
        if not chs[0].startswith("CombatHit"):
            continue
        # CombatHitMine — outgoing melee from you
        ev = {
            "kind": "melee",
            "direction": "outgoing",
            "actor": "You",
            "target": "mob",
            "amount": 5,
            "outcome": "hit",
        }
        assert infer_channel(ev) == chs[0]
        break
