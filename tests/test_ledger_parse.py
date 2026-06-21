"""Tests for mnm_ledger_parse combat kill and ground loot detection."""

from __future__ import annotations

from mnm_ledger_parse import (
    CORPSE_HID,
    GROUND_HIDS,
    PARTY_SPLIT_HID,
    is_combat_kill,
    is_ground_loot,
)


class TestIsCombatKill:
    """Tests for is_combat_kill() function."""

    def test_real_kill_with_corpse_hid(self):
        """A real mob kill has act_14 + npc_corpse hid + valid mob name."""
        assert is_combat_kill("a jackal pup", CORPSE_HID, kind="act_14") is True

    def test_rejects_non_act14(self):
        """Non-act_14 events are not combat kills."""
        assert is_combat_kill("a jackal pup", CORPSE_HID, kind="act_13") is False
        assert is_combat_kill("a jackal pup", CORPSE_HID, kind="act_18") is False

    def test_rejects_party_split(self):
        """Party split events are coin distributions, not kills."""
        assert is_combat_kill("a jackal pup", PARTY_SPLIT_HID, kind="act_14") is False

    def test_rejects_ground_as_mob_name(self):
        """'ground' as mob name indicates ground loot, not a kill."""
        assert is_combat_kill("ground", CORPSE_HID, kind="act_14") is False
        assert is_combat_kill("Ground", CORPSE_HID, kind="act_14") is False
        assert is_combat_kill("GROUND", CORPSE_HID, kind="act_14") is False

    def test_rejects_empty_mob_name(self):
        """Empty mob names are not valid kills."""
        assert is_combat_kill("", CORPSE_HID, kind="act_14") is False
        assert is_combat_kill(None, CORPSE_HID, kind="act_14") is False
        assert is_combat_kill("  ", CORPSE_HID, kind="act_14") is False

    def test_rejects_drop_action_hid(self):
        """drop_action hid is ground loot, not a kill."""
        assert is_combat_kill("a jackal pup", "drop_action", kind="act_14") is False

    def test_accepts_various_mob_names(self):
        """Various valid mob names should be accepted."""
        assert is_combat_kill("a desert bat", CORPSE_HID, kind="act_14") is True
        assert is_combat_kill("A Large Rat", CORPSE_HID, kind="act_14") is True
        assert is_combat_kill("Bloodynose Hag", CORPSE_HID, kind="act_14") is True


class TestIsGroundLoot:
    """Tests for is_ground_loot() function."""

    def test_act18_is_ground_loot(self):
        """act_18 events are always ground loot."""
        assert is_ground_loot("act_18", "a jackal pup", CORPSE_HID) is True
        assert is_ground_loot("act_18", None, None) is True

    def test_ground_mob_name_is_ground_loot(self):
        """mob_name='ground' indicates ground loot."""
        assert is_ground_loot("act_14", "ground", CORPSE_HID) is True
        assert is_ground_loot("act_14", "Ground", CORPSE_HID) is True
        assert is_ground_loot("act_14", "GROUND", None) is True

    def test_drop_action_hid_is_ground_loot(self):
        """drop_action hid indicates ground loot."""
        assert is_ground_loot("act_14", "a jackal pup", "drop_action") is True

    def test_normal_kill_not_ground_loot(self):
        """Normal mob kills are not ground loot."""
        assert is_ground_loot("act_14", "a jackal pup", CORPSE_HID) is False
        assert is_ground_loot("act_13", "a desert bat", CORPSE_HID) is False


class TestConstants:
    """Verify expected constant values for ledger parsing."""

    def test_corpse_hid_value(self):
        assert CORPSE_HID == "npc_corpse"

    def test_party_split_hid_value(self):
        assert PARTY_SPLIT_HID == "party_split"

    def test_ground_hids_contains_drop_action(self):
        assert "drop_action" in GROUND_HIDS
