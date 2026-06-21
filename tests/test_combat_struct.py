"""Unit tests for IL2CPP combat struct decoder (fixture-driven)."""

from __future__ import annotations

import json
from pathlib import Path

from client_re.mnmlib.combat_struct import load_struct_config, struct_enabled

ROOT = Path(__file__).resolve().parent.parent


def test_struct_disabled_by_default():
    cfg = load_struct_config()
    assert cfg.get("enabled") is False
    assert struct_enabled(cfg) is False


def test_struct_enabled_requires_offsets():
    cfg = json.loads((ROOT / "client_re" / "mnmlib" / "combat_struct.json").read_text(encoding="utf-8"))
    cfg["enabled"] = True
    assert struct_enabled(cfg) is False
    cfg["entry"]["text_offset"] = 0x18
    cfg["queue"]["list_offset"] = 0x20
    assert struct_enabled(cfg) is True
