#!/usr/bin/env python3
"""Push wiki page edits to the M&M wiki via MediaWiki API.

Requires env:
  MNM_WIKI_USER       — bot or user name
  MNM_WIKI_BOT_PASSWORD — bot password (preferred) OR MNM_WIKI_PASS for login

Usage:
  python push_wiki.py --page "Cinder Beetle Mandible" --file data/wiki-fixes/cinder-beetle-mandible.wiki
  python push_wiki.py --page "Cinder Beetle Mandible" --file ... --dry-run
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys
from pathlib import Path

import requests

from build_wiki_review import parse_fix_file

API = "https://monstersandmemories.miraheze.org/w/api.php"
USER_AGENT = "MnMWikiPush/1.2 (mnm-item-db; item corrections)"
DEFAULT_CREDS = Path.home() / ".mnm-wiki" / "wiki-credentials.env"
DEFAULT_LOOT_SUMMARY = "Add missing loot drops (mnm-item-db)"


class WikiPushError(Exception):
    pass


def load_credentials() -> None:
    """Load WIKI_USERNAME / WIKI_PASSWORD from env file if not already set."""
    if os.environ.get("MNM_WIKI_USER") or os.environ.get("WIKI_USERNAME"):
        return
    path = Path(os.environ.get("MNM_WIKI_CREDENTIALS", DEFAULT_CREDS))
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k == "WIKI_USERNAME" and not os.environ.get("MNM_WIKI_USER"):
            os.environ["MNM_WIKI_USER"] = v
        elif k == "WIKI_PASSWORD" and not os.environ.get("MNM_WIKI_BOT_PASSWORD"):
            os.environ["MNM_WIKI_BOT_PASSWORD"] = v


def wiki_user() -> str:
    return os.environ.get("MNM_WIKI_USER") or os.environ.get("WIKI_USERNAME") or ""


def wiki_password() -> str:
    return (
        os.environ.get("MNM_WIKI_BOT_PASSWORD")
        or os.environ.get("MNM_WIKI_PASS")
        or os.environ.get("WIKI_PASSWORD")
        or ""
    )


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def credentials_configured() -> bool:
    load_credentials()
    return bool(wiki_user() and wiki_password())


def read_fix_wikitext(path: Path) -> str:
    _meta, body = parse_fix_file(path)
    return body


def wiki_page_url(title: str) -> str:
    return f"https://monstersandmemories.miraheze.org/wiki/{title.replace(' ', '_')}"


def unified_diff(old: str, new: str, *, fromfile: str, tofile: str) -> list[str]:
    return list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )


def dry_run_fix(page: str, file: Path) -> dict:
    text = read_fix_wikitext(file)
    s = session()
    revid, old = fetch_page(s, page)
    diff = unified_diff(old, text, fromfile="current", tofile="proposed")
    return {
        "ok": True,
        "page": page,
        "revid": revid,
        "changed": old.strip() != text.strip(),
        "diff": diff,
        "url": wiki_page_url(page),
    }


def push_fix(page: str, file: Path, summary: str) -> dict:
    if not credentials_configured():
        raise WikiPushError(
            "Wiki credentials not configured (~/.mnm-wiki/wiki-credentials.env)"
        )
    text = read_fix_wikitext(file)
    s = session()
    login(s)
    push_page(s, page, text, summary)
    return {"ok": True, "page": page, "url": wiki_page_url(page)}


def login(s: requests.Session) -> None:
    user = wiki_user()
    if not user:
        raise WikiPushError(
            "Set MNM_WIKI_USER or WIKI_USERNAME (or ~/.mnm-wiki/wiki-credentials.env)."
        )
    token = s.get(API, params={"action": "query", "meta": "tokens", "type": "login", "format": "json"}).json()
    ltoken = token["query"]["tokens"]["logintoken"]
    pw = wiki_password()
    if not pw:
        raise WikiPushError("Set MNM_WIKI_BOT_PASSWORD, MNM_WIKI_PASS, or WIKI_PASSWORD.")
    r = s.post(API, data={
        "action": "login", "lgname": user, "lgpassword": pw,
        "lgtoken": ltoken, "format": "json",
    }).json()
    if r.get("login", {}).get("result") != "Success":
        raise WikiPushError(f"Login failed: {r}")


def fetch_page(s: requests.Session, title: str) -> tuple[int | None, str]:
    r = s.get(API, params={
        "action": "query", "prop": "revisions", "rvprop": "content|ids",
        "titles": title, "format": "json",
    }).json()
    page = next(iter(r["query"]["pages"].values()))
    if "missing" in page:
        return None, ""
    rev = page["revisions"][0]
    return rev["revid"], rev.get("*", "")


def push_page(s: requests.Session, title: str, text: str, summary: str) -> None:
    token = s.get(API, params={"action": "query", "meta": "tokens", "type": "csrf", "format": "json"}).json()
    csrf = token["query"]["tokens"]["csrftoken"]
    _, old = fetch_page(s, title)
    r = s.post(API, data={
        "action": "edit",
        "title": title,
        "text": text,
        "summary": summary,
        "token": csrf,
        "format": "json",
    }).json()
    if "error" in r:
        raise WikiPushError(f"Edit failed: {r['error']}")
    print(f"Published: {wiki_page_url(title)}")
    if old and old.strip() != text.strip():
        for line in unified_diff(old, text, fromfile="wiki", tofile="fix"):
            print(line)


def main() -> None:
    load_credentials()
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--summary", default=DEFAULT_LOOT_SUMMARY)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        if args.dry_run:
            out = dry_run_fix(args.page, args.file)
            print(f"Page: {out['page']} (rev {out['revid']})")
            for line in out["diff"]:
                print(line)
            return
        push_fix(args.page, args.file, args.summary)
    except WikiPushError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
