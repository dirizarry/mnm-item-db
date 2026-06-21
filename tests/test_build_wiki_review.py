"""Tests for build_wiki_review.py review bundle generation."""

from __future__ import annotations

import json
from pathlib import Path

import build_wiki_review as bwr


def test_wiki_page_url():
    url = bwr.wiki_page_url("Cinder Beetle Mandible")
    assert url == "https://monstersandmemories.miraheze.org/wiki/Cinder_Beetle_Mandible"


def test_push_command():
    cmd = bwr.push_command("Test Item", "data/wiki-fixes/loot/item-test.wiki")
    assert "--page" in cmd
    assert '"Test Item"' in cmd
    assert "item-test.wiki" in cmd
    assert "--dry-run" in cmd


def test_make_review_header_basic():
    header = bwr.make_review_header(page="Test Mob", kind="mob", adds=["Item A", "Item B"])
    assert "mnm-review" in header
    assert "Test Mob" in header
    assert "Item A" in header


def test_make_review_header_new_page():
    header = bwr.make_review_header(page="New Item", kind="item", adds=["Mob A"], new_page=True)
    assert "new_page" in header
    # Should be valid JSON inside the header comment
    meta_str = header.split("mnm-review")[1].split("-->")[0].strip()
    meta = json.loads(meta_str)
    assert meta["new_page"] is True


def test_parse_fix_file_with_review_header(tmp_path: Path):
    fix = tmp_path / "mob-test.wiki"
    fix.write_text(
        '<!-- mnm-review {"page": "Test Mob", "kind": "mob", "adds": ["Item"]} -->\n'
        "{{Namedmobpage\n| common_loot =\n* [[Item]]\n}}",
        encoding="utf-8",
    )
    meta, body = bwr.parse_fix_file(fix)
    assert meta is not None
    assert meta["page"] == "Test Mob"
    assert meta["kind"] == "mob"
    assert meta["adds"] == ["Item"]
    assert body.startswith("{{Namedmobpage")
    assert "mnm-review" not in body


def test_parse_fix_file_with_legacy_header(tmp_path: Path):
    fix = tmp_path / "mob-test.wiki"
    fix.write_text(
        "<!-- mnm loot fix: Test Mob adds 2 item -->\n"
        "{{Namedmobpage\n}}",
        encoding="utf-8",
    )
    meta, body = bwr.parse_fix_file(fix)
    assert meta is not None
    assert meta["page"] == "Test Mob"
    assert meta["kind"] == "mob"
    assert body.startswith("{{Namedmobpage")


def test_parse_fix_file_no_header(tmp_path: Path):
    fix = tmp_path / "mob-test.wiki"
    fix.write_text("{{Namedmobpage\n}}", encoding="utf-8")
    meta, body = bwr.parse_fix_file(fix)
    assert meta is None
    assert body == "{{Namedmobpage\n}}"


def test_entry_from_files_mob(tmp_path: Path):
    # Create structure matching expected layout
    fix = tmp_path / "mob-ashira.wiki"
    fix.write_text(
        '<!-- mnm-review {"page": "An ashira warrior", "kind": "mob", "adds": ["Item A"]} -->\n'
        "{{Namedmobpage\n}}",
        encoding="utf-8",
    )
    meta = {"page": "An ashira warrior", "kind": "mob", "adds": ["Item A"]}

    # Mock ROOT for relative path calculation
    import build_wiki_review
    original_root = build_wiki_review.ROOT
    build_wiki_review.ROOT = tmp_path
    try:
        entry = bwr.entry_from_files(
            fix,
            before="{{Namedmobpage\n| common_loot =\n}}",
            after="{{Namedmobpage\n| common_loot =\n* [[Item A]]\n}}",
            meta=meta,
        )
    finally:
        build_wiki_review.ROOT = original_root

    assert entry["id"] == "mob-ashira"
    assert entry["kind"] == "mob"
    assert entry["page"] == "An ashira warrior"
    assert "Item A" in entry["adds"]
    assert "wiki_url" in entry
    assert "push_dry" in entry
    assert "push" in entry
    assert "--dry-run" not in entry["push"]


def test_entry_from_files_item(tmp_path: Path):
    fix = tmp_path / "item-zombie-bone.wiki"
    fix.write_text("{{Itempage\n}}", encoding="utf-8")
    meta = {"page": "Zombie Bone", "kind": "item", "adds": ["a zombie"]}

    import build_wiki_review
    original_root = build_wiki_review.ROOT
    build_wiki_review.ROOT = tmp_path
    try:
        entry = bwr.entry_from_files(
            fix,
            before="old",
            after="new",
            meta=meta,
        )
    finally:
        build_wiki_review.ROOT = original_root

    assert entry["kind"] == "item"
    assert entry["page"] == "Zombie Bone"


def test_entry_from_files_new_page(tmp_path: Path):
    fix = tmp_path / "item-new.wiki"
    fix.write_text("{{Itempage\n}}", encoding="utf-8")
    meta = {"page": "New Item", "kind": "item", "adds": [], "new_page": True}

    import build_wiki_review
    original_root = build_wiki_review.ROOT
    build_wiki_review.ROOT = tmp_path
    try:
        entry = bwr.entry_from_files(fix, before="", after="new", meta=meta)
    finally:
        build_wiki_review.ROOT = original_root

    assert entry["new_page"] is True


def test_write_review_bundle(tmp_path: Path):
    entries = [
        {
            "id": "mob-test",
            "kind": "mob",
            "page": "Test Mob",
            "file": "data/wiki-fixes/loot/mob-test.wiki",
            "adds": ["Item A"],
            "before": "old",
            "after": "new",
            "wiki_url": "https://wiki.example.com/Test_Mob",
            "push_dry": "python push_wiki.py --page Test --dry-run",
            "push": "python push_wiki.py --page Test",
            "new_page": False,
        }
    ]

    out = bwr.write_review_bundle(entries, site_dir=tmp_path, stats={"written": 1})
    assert out == tmp_path / "review-data.js"
    assert out.exists()

    content = out.read_text(encoding="utf-8")
    assert content.startswith("window.MNM_WIKI_REVIEW = ")
    assert "mob-test" in content
    assert '"written":1' in content


def test_write_review_bundle_empty(tmp_path: Path):
    out = bwr.write_review_bundle([], site_dir=tmp_path)
    content = out.read_text(encoding="utf-8")
    data = json.loads(content.replace("window.MNM_WIKI_REVIEW = ", "").rstrip(";\n"))
    assert data["meta"]["count"] == 0
    assert data["fixes"] == []


def test_parse_fix_file_with_new_page_flag(tmp_path: Path):
    fix = tmp_path / "item-new.wiki"
    fix.write_text(
        '<!-- mnm-review {"page": "New Item", "kind": "item", "adds": ["Mob"], "new_page": true} -->\n'
        "{{Itempage\n}}",
        encoding="utf-8",
    )
    meta, body = bwr.parse_fix_file(fix)
    assert meta is not None
    assert meta.get("new_page") is True
