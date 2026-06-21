"""Tests for wiki review push API helpers."""

from __future__ import annotations

from pathlib import Path

import push_wiki
import wiki_review_server as wrs
import wiki_review_state as wrstate


def test_read_fix_wikitext_strips_review_header(tmp_path: Path):
    fix = tmp_path / "mob-test.wiki"
    fix.write_text(
        '<!-- mnm-review {"page": "Test Mob", "kind": "mob", "adds": ["Item"]} -->\n'
        "{{Namedmobpage\n| common_loot =\n* [[Item]]\n}}",
        encoding="utf-8",
    )
    body = push_wiki.read_fix_wikitext(fix)
    assert body.startswith("{{Namedmobpage")
    assert "mnm-review" not in body


def test_resolve_fix_path_rejects_traversal(tmp_path: Path):
    loot = tmp_path / "data" / "wiki-fixes" / "loot"
    loot.mkdir(parents=True)
    (loot / "mob-safe.wiki").write_text("x", encoding="utf-8")
    try:
        wrs.resolve_fix_path(tmp_path, "../secrets")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_resolve_fix_path_finds_loot_fix(tmp_path: Path):
    loot = tmp_path / "data" / "wiki-fixes" / "loot"
    loot.mkdir(parents=True)
    path = loot / "mob-a-jackal-pup.wiki"
    path.write_text("{{x}}", encoding="utf-8")
    resolved = wrs.resolve_fix_path(tmp_path, "mob-a-jackal-pup")
    assert resolved == path.resolve()


def test_review_state_reject_and_push(tmp_path: Path):
    state_path = tmp_path / "review-state.json"
    wrstate.add_rejected(["mob-a"], path=state_path)
    state = wrstate.load_state(state_path)
    assert state["rejected"] == ["mob-a"]
    wrstate.add_pushed(["mob-a"], path=state_path)
    state = wrstate.load_state(state_path)
    assert state["pushed"] == ["mob-a"]
    assert state["rejected"] == []
