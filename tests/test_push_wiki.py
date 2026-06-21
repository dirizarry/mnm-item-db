"""Tests for push_wiki.py wiki push functionality."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import push_wiki


@pytest.fixture
def clean_env(monkeypatch):
    """Clear wiki-related env vars for isolated tests."""
    for key in [
        "MNM_WIKI_USER",
        "MNM_WIKI_BOT_PASSWORD",
        "MNM_WIKI_PASS",
        "WIKI_USERNAME",
        "WIKI_PASSWORD",
        "MNM_WIKI_CREDENTIALS",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_wiki_page_url():
    url = push_wiki.wiki_page_url("Cinder Beetle Mandible")
    assert url == "https://monstersandmemories.miraheze.org/wiki/Cinder_Beetle_Mandible"


def test_wiki_page_url_already_underscored():
    url = push_wiki.wiki_page_url("Fire_Beetle")
    assert url == "https://monstersandmemories.miraheze.org/wiki/Fire_Beetle"


def test_unified_diff_shows_changes():
    old = "line one\nline two\nline three"
    new = "line one\nline modified\nline three"
    diff = push_wiki.unified_diff(old, new, fromfile="old", tofile="new")
    assert any("-line two" in line for line in diff)
    assert any("+line modified" in line for line in diff)


def test_unified_diff_empty_for_identical():
    text = "same\ncontent"
    diff = push_wiki.unified_diff(text, text, fromfile="a", tofile="b")
    # unified_diff returns empty when files are identical
    assert list(diff) == []


def test_credentials_configured_false_when_empty(clean_env):
    # Point to nonexistent file
    os.environ["MNM_WIKI_CREDENTIALS"] = "/nonexistent/path.env"
    assert push_wiki.credentials_configured() is False


def test_credentials_configured_true_with_env_vars(clean_env, monkeypatch):
    monkeypatch.setenv("MNM_WIKI_USER", "testuser")
    monkeypatch.setenv("MNM_WIKI_BOT_PASSWORD", "testpass")
    assert push_wiki.credentials_configured() is True


def test_load_credentials_from_file(clean_env, tmp_path: Path):
    creds = tmp_path / "wiki-credentials.env"
    creds.write_text(
        "# Comment line\n"
        "WIKI_USERNAME=fileuser\n"
        'WIKI_PASSWORD="filepass"\n',
        encoding="utf-8",
    )
    os.environ["MNM_WIKI_CREDENTIALS"] = str(creds)
    push_wiki.load_credentials()
    assert os.environ.get("MNM_WIKI_USER") == "fileuser"
    assert os.environ.get("MNM_WIKI_BOT_PASSWORD") == "filepass"


def test_load_credentials_env_takes_precedence(clean_env, tmp_path: Path, monkeypatch):
    """Env vars already set should not be overwritten by file."""
    monkeypatch.setenv("MNM_WIKI_USER", "envuser")
    creds = tmp_path / "wiki-credentials.env"
    creds.write_text("WIKI_USERNAME=fileuser\n", encoding="utf-8")
    os.environ["MNM_WIKI_CREDENTIALS"] = str(creds)
    push_wiki.load_credentials()
    assert os.environ.get("MNM_WIKI_USER") == "envuser"


def test_wiki_user_checks_multiple_env_vars(clean_env, monkeypatch):
    monkeypatch.setenv("WIKI_USERNAME", "fallbackuser")
    assert push_wiki.wiki_user() == "fallbackuser"
    monkeypatch.setenv("MNM_WIKI_USER", "primaryuser")
    assert push_wiki.wiki_user() == "primaryuser"


def test_wiki_password_checks_multiple_env_vars(clean_env, monkeypatch):
    monkeypatch.setenv("WIKI_PASSWORD", "fallbackpass")
    assert push_wiki.wiki_password() == "fallbackpass"
    monkeypatch.setenv("MNM_WIKI_PASS", "middlepass")
    assert push_wiki.wiki_password() == "middlepass"
    monkeypatch.setenv("MNM_WIKI_BOT_PASSWORD", "primarypass")
    assert push_wiki.wiki_password() == "primarypass"


def test_read_fix_wikitext_strips_header(tmp_path: Path):
    fix = tmp_path / "mob-test.wiki"
    fix.write_text(
        '<!-- mnm-review {"page": "Test Mob", "kind": "mob", "adds": ["Item"]} -->\n'
        "{{Namedmobpage\n| common_loot =\n* [[Item]]\n}}",
        encoding="utf-8",
    )
    body = push_wiki.read_fix_wikitext(fix)
    assert body.startswith("{{Namedmobpage")
    assert "mnm-review" not in body


def test_session_has_user_agent():
    sess = push_wiki.session()
    assert "MnMWikiPush" in sess.headers.get("User-Agent", "")


def test_push_fix_raises_without_credentials(clean_env, tmp_path: Path):
    os.environ["MNM_WIKI_CREDENTIALS"] = "/nonexistent/path.env"
    fix = tmp_path / "mob-test.wiki"
    fix.write_text(
        '<!-- mnm-review {"page": "Test", "kind": "mob", "adds": []} -->\n{{x}}',
        encoding="utf-8",
    )
    with pytest.raises(push_wiki.WikiPushError, match="credentials"):
        push_wiki.push_fix("Test Page", fix, "summary")


def test_login_raises_without_user(clean_env):
    sess = MagicMock()
    with pytest.raises(push_wiki.WikiPushError, match="MNM_WIKI_USER"):
        push_wiki.login(sess)


def test_login_raises_without_password(clean_env, monkeypatch):
    monkeypatch.setenv("MNM_WIKI_USER", "testuser")
    sess = MagicMock()
    sess.get.return_value.json.return_value = {
        "query": {"tokens": {"logintoken": "faketoken"}}
    }
    with pytest.raises(push_wiki.WikiPushError, match="PASSWORD"):
        push_wiki.login(sess)


def test_login_success(clean_env, monkeypatch):
    monkeypatch.setenv("MNM_WIKI_USER", "testuser")
    monkeypatch.setenv("MNM_WIKI_BOT_PASSWORD", "testpass")
    sess = MagicMock()
    sess.get.return_value.json.return_value = {
        "query": {"tokens": {"logintoken": "tok123"}}
    }
    sess.post.return_value.json.return_value = {"login": {"result": "Success"}}
    # Should not raise
    push_wiki.login(sess)
    sess.post.assert_called_once()


def test_login_failure_raises(clean_env, monkeypatch):
    monkeypatch.setenv("MNM_WIKI_USER", "testuser")
    monkeypatch.setenv("MNM_WIKI_BOT_PASSWORD", "wrongpass")
    sess = MagicMock()
    sess.get.return_value.json.return_value = {
        "query": {"tokens": {"logintoken": "tok123"}}
    }
    sess.post.return_value.json.return_value = {
        "login": {"result": "Failed", "reason": "bad password"}
    }
    with pytest.raises(push_wiki.WikiPushError, match="Login failed"):
        push_wiki.login(sess)


def test_fetch_page_returns_content():
    sess = MagicMock()
    sess.get.return_value.json.return_value = {
        "query": {
            "pages": {
                "12345": {
                    "pageid": 12345,
                    "title": "Test Page",
                    "revisions": [{"revid": 999, "*": "page content here"}],
                }
            }
        }
    }
    revid, content = push_wiki.fetch_page(sess, "Test Page")
    assert revid == 999
    assert content == "page content here"


def test_fetch_page_missing_returns_none():
    sess = MagicMock()
    sess.get.return_value.json.return_value = {
        "query": {"pages": {"-1": {"missing": True, "title": "Missing"}}}
    }
    revid, content = push_wiki.fetch_page(sess, "Missing")
    assert revid is None
    assert content == ""


@patch("push_wiki.session")
def test_dry_run_fix_returns_diff(mock_session, tmp_path: Path):
    mock_sess = MagicMock()
    mock_session.return_value = mock_sess
    mock_sess.get.return_value.json.return_value = {
        "query": {
            "pages": {
                "1": {
                    "revisions": [{"revid": 100, "*": "old content"}]
                }
            }
        }
    }
    fix = tmp_path / "item-test.wiki"
    fix.write_text(
        '<!-- mnm-review {"page": "Test", "kind": "item", "adds": []} -->\nnew content',
        encoding="utf-8",
    )
    result = push_wiki.dry_run_fix("Test", fix)
    assert result["ok"] is True
    assert result["page"] == "Test"
    assert result["revid"] == 100
    assert result["changed"] is True
    assert any("-old content" in line for line in result["diff"])
    assert any("+new content" in line for line in result["diff"])


def test_push_page_raises_on_error(clean_env, monkeypatch):
    monkeypatch.setenv("MNM_WIKI_USER", "testuser")
    monkeypatch.setenv("MNM_WIKI_BOT_PASSWORD", "testpass")
    sess = MagicMock()
    # First get: csrf token
    # Second get: fetch_page for diff
    sess.get.return_value.json.side_effect = [
        {"query": {"tokens": {"csrftoken": "csrf123"}}},
        {"query": {"pages": {"1": {"revisions": [{"revid": 1, "*": "old"}]}}}},
    ]
    sess.post.return_value.json.return_value = {
        "error": {"code": "protectedpage", "info": "Page is protected"}
    }
    with pytest.raises(push_wiki.WikiPushError, match="Edit failed"):
        push_wiki.push_page(sess, "Protected Page", "new text", "summary")
