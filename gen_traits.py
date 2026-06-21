#!/usr/bin/env python3
"""Fetch Template:Traits from the wiki and emit site/traits.js for the planner.

Parses the five sections (Class Specific, Racial Combat Abilities, Major Combat,
Minor Combat, Major Non-Combat, Minor Non-Combat) into structured rows, and
attaches passive stat/resist bonuses for the known stat-line traits so the
planner can total them.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import requests

API = "https://monstersandmemories.miraheze.org/w/api.php"
UA = "MnMItemDB/0.1 (planner trait sync)"
SITE = Path(__file__).parent / "site"

SECTIONS = [
    ("class", "== Class Specific Traits =="),
    ("racial", "== Racial Combat Abilities =="),
    ("major_combat", "== Major Combat Traits =="),
    ("minor_combat", "== Minor Combat Traits =="),
    ("major_noncombat", "== Major Non-Combat Traits =="),
    ("minor_noncombat", "== Minor Non-Combat Traits =="),
]

# Passive bonuses the planner can sum, keyed by trait name.
STAT_BONUS = {
    "Strong": {"str": 10},
    "Tough": {"sta": 10},
    "Agile": {"agi": 10},
    "Dexterous": {"dex": 10},
    "Intelligent": {"int": 10},
    "Wise": {"wis": 10},
    "Charismatic": {"cha": 10},
    "Cold Resistant": {"cold_resist": 10},
    "Fire Resistant": {"fire_resist": 10},
    "Magic Resistant": {"magic_resist": 10},
    "Poison Resistant": {"poison_resist": 10},
    "Disease Resistant": {"disease_resist": 10},
    "Electric Resistant": {"electric_resist": 10},
    "Corruption Resistant": {"corruption_resist": 10},
    "Holy Resistant": {"holy_resist": 10},
    "Slippery": {},
    "Tenacity": {},
}


def strip_markup(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]|]+)\]\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_template() -> str:
    r = requests.get(
        API,
        params={
            "action": "query",
            "titles": "Template:Traits",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "format": "json",
        },
        headers={"User-Agent": UA},
        timeout=60,
    )
    return next(iter(r.json()["query"]["pages"].values()))["revisions"][0]["slots"]["main"]["*"]


def parse_rows(section_text: str) -> list[dict]:
    rows: list[dict] = []
    for line in section_text.splitlines():
        if (
            not line.startswith("|")
            or line.startswith("|-")
            or "!!" in line
            or line.strip() == "|}"
        ):
            continue
        cells = [strip_markup(c) for c in line.lstrip("|").split("||")]
        if len(cells) < 4:
            continue
        name, race, cls, desc = cells[0], cells[1], cells[2], cells[3]
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "race": race,
                "classes": cls,
                "desc": desc,
                "bonus": STAT_BONUS.get(name, {}),
            }
        )
    return rows


def main() -> int:
    text = fetch_template()
    bounds = []
    for key, header in SECTIONS:
        idx = text.find(header)
        bounds.append((key, header, idx))
    out: dict[str, list[dict]] = {}
    for i, (key, header, idx) in enumerate(bounds):
        if idx < 0:
            out[key] = []
            continue
        end = len(text)
        for _, _, nidx in bounds[i + 1 :]:
            if nidx > idx:
                end = nidx
                break
        out[key] = parse_rows(text[idx + len(header) : end])

    SITE.mkdir(exist_ok=True)
    js = "window.MNM_TRAITS = " + json.dumps(out, ensure_ascii=False, indent=0) + ";\n"
    (SITE / "traits.js").write_text(js, encoding="utf-8")
    counts = {k: len(v) for k, v in out.items()}
    print("Wrote site/traits.js", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
