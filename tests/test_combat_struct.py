"""Unit tests for IL2CPP combat struct decoder (fixture-driven)."""

from __future__ import annotations

from client_re.mnmlib.combat_struct import load_struct_config, struct_enabled


def test_struct_enabled_false_without_enabled_flag():
    """A config with enabled=False should return struct_enabled=False."""
    cfg = {"enabled": False}
    assert struct_enabled(cfg) is False


def test_struct_enabled_true_with_message_blob_hints():
    """When layout=message_blob and holder_ptr_hint exists, struct is enabled."""
    cfg = {
        "enabled": True,
        "layout": "message_blob",
        "message_blob": {"holder_ptr_hint": 12345},
    }
    assert struct_enabled(cfg) is True


def test_struct_enabled_false_without_message_blob_hints():
    """When layout=message_blob but no holder_ptr_hint, struct is disabled."""
    cfg = {
        "enabled": True,
        "layout": "message_blob",
        "message_blob": {},
    }
    assert struct_enabled(cfg) is False


def test_struct_enabled_il2cpp_list_requires_offsets():
    """Default il2cpp_list layout requires both text_offset and list_offset."""
    cfg = {
        "enabled": True,
        "layout": "il2cpp_list",
        "entry": {"text_offset": None},
        "queue": {"list_offset": None},
    }
    assert struct_enabled(cfg) is False

    cfg["entry"]["text_offset"] = 0x18
    cfg["queue"]["list_offset"] = 0x20
    assert struct_enabled(cfg) is True


def test_load_struct_config_returns_dict():
    """load_struct_config returns the actual config file contents."""
    cfg = load_struct_config()
    assert isinstance(cfg, dict)
    assert "version" in cfg or "enabled" in cfg
