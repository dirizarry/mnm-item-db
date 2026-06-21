"""Shared MediaWiki API helpers for M&M crawlers."""

from __future__ import annotations

import html
import re
import time

import requests

API = "https://monstersandmemories.miraheze.org/w/api.php"
USER_AGENT = "MnMItemDB/0.2 (personal fan project; contact via wiki user page)"


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def category_members(s: requests.Session, category: str, limit: int | None = None) -> list[str]:
    titles: list[str] = []
    cont: str | None = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmlimit": "500",
            "cmtype": "page",
            "format": "json",
        }
        if cont:
            params["cmcontinue"] = cont
        data = s.get(API, params=params, timeout=60).json()
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont or (limit and len(titles) >= limit):
            break
    return titles[:limit] if limit else titles


def fetch_contents(s: requests.Session, titles: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i : i + 50]
        data = s.get(
            API,
            params={
                "action": "query",
                "titles": "|".join(batch),
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
            },
            timeout=60,
        ).json()
        pages = data.get("query", {}).get("pages", {})
        for p in pages.values():
            title = p.get("title", "")
            revs = p.get("revisions")
            if revs:
                slot = revs[0].get("slots", {}).get("main", {})
                out[title] = slot.get("*", "")
            else:
                out[title] = ""
        for norm in data.get("query", {}).get("normalized", []):
            if norm["to"] in out:
                out[norm["from"]] = out[norm["to"]]
        time.sleep(0.2)
    return out


def parse_params(box: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for chunk in re.split(r"\n\s*\|", box):
        if "=" not in chunk:
            continue
        key, _, val = chunk.partition("=")
        key = key.strip().lstrip("|").strip().lower()
        if re.fullmatch(r"[a-z0-9_]+", key or ""):
            params[key] = val.strip()
    return params


def strip_markup(raw: str | None) -> str:
    if not raw:
        return ""
    s = re.sub(r"<br\s*/?>", " ", raw, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def wiki_links(raw: str | None) -> list[str]:
    if not raw:
        return []
    return list(dict.fromkeys(m.strip() for m in re.findall(r"\[\[([^\]|]+)", raw) if m.strip()))


def parse_level(raw: str | None) -> tuple[int | None, int | None]:
    if not raw:
        return None, None
    s = strip_markup(raw)
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if not nums:
        return None, None
    if len(nums) == 1:
        return nums[0], nums[0]
    return min(nums), max(nums)
