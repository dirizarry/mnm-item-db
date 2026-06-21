"""Tests for mnm_provenance scoring and dedup tokens."""

from mnm_provenance import (
    client_hid_matches_mob,
    empirical_probability,
    kill_token,
    loot_token,
    score_edge,
)


def test_empirical_saturates():
    low = empirical_probability(1)
    high = empirical_probability(20)
    assert low < high
    assert high > 0.9


def test_score_edge_confirmed():
    edge = score_edge(
        {
            "via_mob": True,
            "via_item": True,
            "via_client": False,
            "via_ledger": True,
            "via_crowd": False,
            "observations": 5,
            "contributors": 2,
        }
    )
    assert edge["status"] == "confirmed"
    assert edge["confidence"] > 0.85
    assert edge["conflict"] is False


def test_score_edge_crowd_candidate():
    edge = score_edge(
        {
            "via_mob": False,
            "via_item": False,
            "via_client": False,
            "via_ledger": False,
            "via_crowd": True,
            "observations": 3,
            "contributors": 2,
        }
    )
    assert edge["status"] == "crowd_candidate"
    assert edge["conflict"] is True


def test_kill_token_stable():
    a = kill_token("betapvp", "mob_hid", "2026-06-01T12:00:00")
    b = kill_token("betapvp", "mob_hid", "2026-06-01T12:00:00.999")
    assert a == b
    assert len(a) == 20


def test_loot_token_instance_id():
    a = loot_token("betapvp", mob_hid="x", item_hid="y", ts="t", instance_id="12345")
    b = loot_token("betapvp", mob_hid="z", item_hid="w", ts="u", instance_id="12345")
    assert a == b
    assert len(a) == 20


def test_client_hid_matches_mob():
    assert client_hid_matches_mob(
        "ip_te_a_bloodynose_hag_cmn_ears_melee_15",
        "a bloodynose hag",
    )
