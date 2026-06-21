"""build_combat_site bundles live session totals for the dashboard."""

from pathlib import Path

from build_combat_site import build_bundle, _live_totals


def test_live_totals_from_flat_live_json():
    live = {"damage_out": 100, "damage_in": 5, "event_count": 42, "by_kind": {"melee": 10}}
    totals = _live_totals(live)
    assert totals["damage_out"] == 100
    assert totals["event_count"] == 42


def test_build_bundle_includes_stream_breakdown(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    events = [
        {"ts": "t1", "kind": "melee", "direction": "outgoing", "amount": 10, "stream_id": "a"},
        {"ts": "t2", "kind": "melee", "direction": "incoming", "amount": 3, "stream_id": "b"},
    ]
    (data / "combat-events.json").write_text(__import__("json").dumps(events), encoding="utf-8")
    (data / "combat-live.json").write_text(
        '{"damage_out":10,"damage_in":3,"event_count":2}', encoding="utf-8"
    )
    settings = {"combat_streams": [{"id": "a", "label": "Meter"}, {"id": "b", "label": "Casts"}]}
    bundle = build_bundle(data, settings=settings)
    assert bundle["meta"]["event_count"] == 2
    assert bundle["totals"]["damage_out"] == 10
    assert bundle["by_stream"]["a"]["events"] == 1
    assert bundle["by_stream"]["b"]["label"] == "Casts"
