"""Tests for wiki page stub templates."""

from __future__ import annotations

import wiki_page_stubs as stubs


def test_stub_namedmob_page_includes_zone_and_template():
    text = stubs.stub_namedmob_page("a goon", ["Night Harbor"])
    assert "{{Namedmobpage" in text
    assert "Night Harbor" in text
    assert "| common_loot =" in text


def test_stub_item_page_minimal():
    text = stubs.stub_item_page("Spiderling Eye")
    assert "{{ItemBox" in text
    assert "Spiderling Eye" in text
    assert "{{Itempage" in text
    assert "|dropsfrom =" in text
