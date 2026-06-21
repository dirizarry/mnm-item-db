"""Tests for Option F combat memory harvest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from client_re.combat_memory import scan_region_for_combat_lines
from client_re.signatures import load_signature_template, scan_file_string
from client_re.mnmlib.types import generate_types_catalog, scan_metadata_types
from mnm_combat_text import parse_message_list
from mnm_combat_watch import resolve_capture_backend

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "combat_memory" / "heap_sample.bin"


def test_scan_region_finds_combat_lines():
    data = FIXTURE.read_bytes()
    lines = scan_region_for_combat_lines(data)
    assert len(lines) >= 4
    assert any("points of damage" in ln for ln in lines)
    assert any("slain" in ln.lower() for ln in lines)


def test_parse_memory_lines_match_ocr_schema():
    data = FIXTURE.read_bytes()
    lines = scan_region_for_combat_lines(data)
    events = parse_message_list(lines)
    kinds = {e.get("kind") for e in events}
    assert "melee" in kinds or "combat" in kinds or any(e.get("amount") for e in events)


def test_mnmlib_types_catalog():
    doc = scan_metadata_types()
    assert doc["combat_type_count"] > 0
    assert "ChatMessageData" in doc["priority_hits"]


def test_signature_template_loads():
    tpl = load_signature_template()
    assert tpl.get("version") == 1
    assert any(p.get("id") == "consider_string" for p in tpl.get("patterns", []))


def test_consider_string_in_game_assembly_if_installed():
    try:
        from client_re.paths import game_assembly

        ga = game_assembly()
    except FileNotFoundError:
        pytest.skip("game not installed")
    hits = scan_file_string(ga, "Consider")
    assert hits, "Consider anchor should exist in GameAssembly.dll"


def test_resolve_capture_backend_defaults():
    assert resolve_capture_backend("ocr") == "ocr"
    assert resolve_capture_backend("memory") == "memory"
