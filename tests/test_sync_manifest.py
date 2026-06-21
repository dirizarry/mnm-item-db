"""Tests for sync_manifest orchestration."""

from pathlib import Path
from unittest import mock

import sync_manifest as sm


def test_sync_report_structure():
    report = sm.SyncReport(started_at="2026-01-01T00:00:00Z")
    report.add(sm.StepResult("test", "ok", "done", {"n": 1}))
    d = report.to_dict()
    assert d["steps"][0]["name"] == "test"
    assert d["steps"][0]["changes"]["n"] == 1


def test_aggregate_crowd_skips_empty_inbox(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "crowd-inbox").mkdir()
    step = sm.aggregate_crowd(data)
    assert step.status == "skipped"


def test_build_relations_skips_without_items(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    step = sm.build_relations(data)
    assert step.status == "skipped"


def test_run_sync_minimal(tmp_path: Path, monkeypatch):
    """Ledger extract skipped path with empty locallow structure."""
    locallow = tmp_path / "logs"
    locallow.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    site = tmp_path / "site"
    site.mkdir()

    fake_stats = {
        "files": 0, "events": 0, "kills": 0, "drops": 0,
        "skipped": True, "install_id": "abc", "characters": [], "servers": [],
    }

    with mock.patch.object(sm, "detect_game_patch", return_value=sm.StepResult("game_patch", "ok", "", {"patched": False})):
        with mock.patch.object(sm, "extract_ledger", return_value=sm.StepResult("ledger_extract", "ok", "", {"stats": fake_stats})):
            with mock.patch.object(sm, "build_relations", return_value=sm.StepResult("relations", "skipped", "no items")):
                with mock.patch.object(sm, "build_site_bundles", return_value=sm.StepResult("site_bundles", "ok", "")):
                    with mock.patch.object(sm, "package_upload", return_value=sm.StepResult("upload", "skipped", "")):
                        report = sm.run_sync(locallow=locallow, data_dir=data, site_dir=site, upload=False)
    assert report.summary["failed"] == 0
    assert any(s.name == "ledger_extract" for s in report.steps)
