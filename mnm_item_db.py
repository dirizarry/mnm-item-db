#!/usr/bin/env python3
"""Extract Monsters and Memories item data from the wiki into a normalized DB.

Parses every {{ItemBox}} (both the structured-param dialect and the freeform
``item_stats = ...<br>`` dialect) into one schema, then writes items.json,
items.db (SQLite) and a coverage report.

Usage:
    python mnm_item_db.py --pilot 200      # validate parser on a sample
    python mnm_item_db.py --all            # full crawl of Category:Items
    python mnm_item_db.py --category "Category:Weapon"
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import time
from pathlib import Path

import requests

from mnm_zones import load_mob_canon, normalize_item_drops

# Canonical vocab for cleaning leaked markup / typos out of parsed fields.
CLASS_CODES = {
    "ARC",
    "BRD",
    "BST",
    "CLR",
    "DRU",
    "ELE",
    "ENC",
    "FTR",
    "INQ",
    "MNK",
    "NEC",
    "PAL",
    "RNG",
    "ROG",
    "SHD",
    "SHM",
    "SPB",
    "WIZ",
}
CLASS_ALIAS = {"ENCH": "ENC", "ELEM": "ELE", "MKN": "MNK", "MNL": "MNK", "WAR": "FTR"}

RACE_CODES = {
    "ALL",
    "HUM",
    "DWF",
    "GNM",
    "GOB",
    "HFL",
    "HIE",
    "OGR",
    "TRL",
    "ELF",
    "DDF",
    "DEF",
    "DGN",
    "LIZ",
}

SLOT_CANON = {
    "HEAD",
    "FACE",
    "EAR",
    "NECK",
    "SHOULDERS",
    "CHEST",
    "ARMS",
    "BACK",
    "WRIST",
    "HANDS",
    "FINGER",
    "WAIST",
    "LEGS",
    "FEET",
    "PRIMARY",
    "SECONDARY",
    "RANGED",
    "AMMO",
}
SLOT_ALIAS = {
    "CHES": "CHEST",
    "SECONDAY": "SECONDARY",
    "SECONDARY,": "SECONDARY",
    "WAISTE": "WAIST",
    "RANGE": "RANGED",
    "EARS": "EAR",
    "WRISTS": "WRIST",
    "FINGERS": "FINGER",
    "SHOULDER": "SHOULDERS",
    "BODY": "CHEST",
    "HEADS": "HEAD",
}
HANDED_2H = {"TWO", "2H", "2HS", "2HB", "TWOHAND", "TWOHANDED"}
HANDED_1H = {"ONE", "1H", "1HS", "1HB", "ONEHAND"}

API = "https://monstersandmemories.miraheze.org/w/api.php"
USER_AGENT = "MnMItemDB/0.1 (personal fan project; contact via wiki user page)"
OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

# Resist param -> readable name
RESIST_FIELDS = {
    "cr": "cold_resist",
    "fr": "fire_resist",
    "mr": "magic_resist",
    "pr": "poison_resist",
    "dr": "disease_resist",
    "er": "electric_resist",
    "cor": "corruption_resist",
    "hr": "holy_resist",
}

# Numeric stat params shared by both dialects
STAT_FIELDS = [
    "ac",
    "dmg",
    "delay",
    "str",
    "sta",
    "agi",
    "dex",
    "int",
    "wis",
    "cha",
    "hp",
    "mana",
    "hp_regen",
    "mana_regen",
    "haste",
    "ranged_haste",
    "spell_haste",
    "weight",
]

FLAG_WORDS = {
    "MAGIC": "magic",
    "LORE": "lore",
    "UNIQUE": "unique",
    "NO DROP": "nodrop",
    "NODROP": "nodrop",
    "NO RENT": "norent",
    "NORENT": "norent",
    "NO ZONE": "nozone",
    "TEMPORARY": "temporary",
    "ATTUNEABLE": "attuneable",
}

ACQ_FIELDS = [
    "source_types",
    "drops_zones",
    "drops_mobs",
    "crafted",
    "tradeskills",
    "components",
    "quests",
    "vendor_value",
]
# Fields that hold lists/objects (JSON-encoded when written to SQLite).
COMPLEX_FIELDS = {
    "drops_zones",
    "drops_mobs",
    "tradeskills",
    "components",
    "quests",
    "source_types",
}

ALL_COLUMNS = (
    [
        "title",
        "name",
        "slot",
        "handed",
        "skill",
        "size",
        "classes",
        "races",
        "effect",
        "icon_id",
        "dropsfrom",
        "categories",
        "format",
        "raw_len",
    ]
    + STAT_FIELDS
    + list(RESIST_FIELDS.values())
    + ["magic", "lore", "unique", "nodrop", "norent", "nozone", "temporary", "attuneable"]
    + ACQ_FIELDS
)

TRADESKILLS = {
    "Blacksmithing",
    "Tailoring",
    "Leatherworking",
    "Jewelcrafting",
    "Pottery",
    "Woodworking",
    "Alchemy",
    "Brewing",
    "Cooking",
    "Fletching",
    "Smelting",
    "Tinkering",
    "Spellcrafting",
    "Carpentry",
    "Masonry",
    "Poison Making",
    "Research",
    "Baking",
    "Enchanting",
}

_MOB_CANON: dict[str, str] = {}


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def category_members(s: requests.Session, category: str, limit: int | None) -> list[str]:
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
    return titles


def fetch_contents(s: requests.Session, titles: list[str]) -> dict[str, str]:
    """Batch-fetch page wikitext (up to 50 titles per request)."""
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
        # normalize any title mapping (redirects/normalization)
        for norm in data.get("query", {}).get("normalized", []):
            if norm["to"] in out:
                out[norm["from"]] = out[norm["to"]]
        time.sleep(0.2)
    return out


def extract_itembox(text: str) -> str | None:
    m = re.search(r"\{\{ItemBox(.*?)\n\}\}", text, re.DOTALL | re.IGNORECASE)
    if not m:
        m = re.search(r"\{\{ItemBox(.*?)\}\}", text, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def extract_itempage(text: str) -> str | None:
    """Return the body of the {{Itempage ...}} template (acquisition info)."""
    idx = text.lower().find("{{itempage")
    if idx < 0:
        return None
    i = idx + len("{{itempage")
    depth = 2  # we're already inside the opening {{
    out = []
    while i < len(text) and depth > 0:
        if text[i : i + 2] == "{{":
            depth += 2
            out.append("{{")
            i += 2
            continue
        if text[i : i + 2] == "}}":
            depth -= 2
            if depth <= 0:
                break
            out.append("}}")
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def parse_acquisition(text: str, rec: dict) -> None:
    body = extract_itempage(text)
    params = parse_params(body) if body else {}
    source_types: list[str] = []

    # --- drops ---
    drops_raw = params.get("dropsfrom", "")
    zones: list[str] = []
    mobs: list[str] = []
    if drops_raw and "not dropped" not in drops_raw.lower():
        for line in drops_raw.splitlines():
            links = re.findall(r"\[\[([^\]|]+)", line)
            if not links:
                continue
            if line.lstrip().startswith("*"):
                mobs += links
            else:
                zones += links
    zones = list(dict.fromkeys(zones))
    mobs = list(dict.fromkeys(mobs))
    if zones or mobs:
        source_types.append("dropped")
        rec["drops_zones"] = zones
        rec["drops_mobs"] = mobs

    # --- crafted ---
    craft_raw = "\n".join(filter(None, [params.get("playercrafted", ""), params.get("notes", "")]))
    is_crafted = (
        bool(params.get("playercrafted")) and "not crafted by players" not in craft_raw.lower()
    )
    # fallback: notes describing a recipe
    if not is_crafted and re.search(r"recipe is", params.get("notes", ""), re.IGNORECASE):
        is_crafted = True
    if is_crafted:
        source_types.append("crafted")
        rec["crafted"] = True
        skills = [s for s in TRADESKILLS if re.search(rf"\[\[{re.escape(s)}", craft_raw)]
        if skills:
            rec["tradeskills"] = list(dict.fromkeys(skills))
        # Skip the recipe's own Yield line and any self-reference so the crafted
        # item isn't listed as its own ingredient.
        self_names = {n for n in (rec.get("name"), rec.get("title")) if n}
        comps = []
        for line in craft_raw.splitlines():
            if re.search(r"yield", line, re.IGNORECASE):
                continue
            for qty, name in re.findall(r"x?\s*(\d+)\s*\[\[([^\]|]+)", line):
                nm = name.strip()
                if nm in TRADESKILLS or nm in self_names:
                    continue
                if not any(c["name"] == nm for c in comps):
                    comps.append({"qty": int(qty), "name": nm})
        if comps:
            rec["components"] = comps

    # --- quests ---
    quests_raw = params.get("relatedquests", "")
    if quests_raw and "no related quests" not in quests_raw.lower():
        q = list(dict.fromkeys(re.findall(r"\[\[([^\]|]+)", quests_raw)))
        if q:
            source_types.append("quest")
            rec["quests"] = q

    # --- vendor ---
    mv = params.get("merchant_value")
    if mv:
        rec["vendor_value"] = strip_markup(mv)

    # --- starter (from categories/notes) ---
    if re.search(r"starting racial|starter", text, re.IGNORECASE):
        source_types.append("starter")

    rec["source_types"] = source_types or ["unknown"]


def parse_params(box: str) -> dict[str, str]:
    """Parse top-level |key = value pairs from an ItemBox body."""
    params: dict[str, str] = {}
    # split on newline-pipe to avoid splitting inline || in tables
    for chunk in re.split(r"\n\s*\|", box):
        if "=" not in chunk:
            continue
        key, _, val = chunk.partition("=")
        key = key.strip().lstrip("|").strip().lower()
        if re.fullmatch(r"[a-z_]+", key or ""):
            params[key] = val.strip()
    return params


def strip_markup(raw: str | None) -> str:
    """Remove <br>/HTML tags, decode entities, collapse whitespace."""
    if not raw:
        return ""
    s = re.sub(r"<br\s*/?>", " ", raw, flags=re.IGNORECASE)
    # Remove other tags WITHOUT inserting a space: the wiki styles item names as
    # F<span class="item-title-sm">rightwoven</span> -> must rejoin to "Frightwoven".
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def clean_name(raw: str) -> str:
    return strip_markup(raw)


def norm_classes(raw: str | None) -> str | None:
    toks = re.split(r"[\s,/]+", strip_markup(raw).upper())
    out: list[str] = []
    for t in toks:
        t = CLASS_ALIAS.get(t, t)
        if t in CLASS_CODES and t not in out:
            out.append(t)
    if not out and "ALL" in {t.upper() for t in toks}:
        return "ALL"
    return " ".join(out) or None


def norm_races(raw: str | None) -> str | None:
    toks = re.split(r"[\s,/]+", strip_markup(raw).upper())
    out: list[str] = []
    for t in toks:
        if t in RACE_CODES and t not in out:
            out.append(t)
    return " ".join(out) or None


def norm_slot(raw: str | None) -> tuple[str | None, str | None]:
    """Return (clean slot string, handedness or None)."""
    toks = re.split(r"[\s,/]+", strip_markup(raw).upper())
    out: list[str] = []
    handed: str | None = None
    for t in toks:
        if t in HANDED_2H:
            handed = "2H"
            continue
        if t in HANDED_1H:
            handed = "1H"
            continue
        t = SLOT_ALIAS.get(t, t)
        if t in SLOT_CANON and t not in out:
            out.append(t)
    return (" ".join(out) or None), handed


def num(val: str | None) -> float | int | None:
    if not val:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", val)
    if not m:
        return None
    f = float(m.group())
    return int(f) if f.is_integer() else f


def parse_freeform(stats: str, rec: dict) -> None:
    """Parse the 'MAGIC<br>Slot: HEAD<br>AC: 21<br>...' dialect."""
    text = re.sub(r"<br\s*/?>", "\n", stats, flags=re.IGNORECASE)
    # Flat version (<br>/tags -> spaces) for single-line list fields like Class/Race
    flat = strip_markup(stats)
    upper = text.upper()
    for word, flag in FLAG_WORDS.items():
        if re.search(rf"(?<![A-Z]){re.escape(word)}(?![A-Z])", upper):
            rec[flag] = True

    def grab(label: str) -> str | None:
        m = re.search(rf"{label}\s*:\s*([^\n<]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def grab_flat(label: str, stop_labels: list[str]) -> str | None:
        # capture from "Label:" up to the next known label in the flattened blob
        stop = "|".join(stop_labels)
        m = re.search(rf"{label}\s*:\s*(.+?)(?:\s+(?:{stop})\s*:|$)", flat, re.IGNORECASE)
        return m.group(1).strip() if m else None

    rec.setdefault("slot", grab("Slot"))
    rec.setdefault("size", grab("Size"))
    rec.setdefault("skill", grab("Skill") or grab("Type"))
    cls = grab_flat("Class", ["Race", "Slot", "Size", "Weight", "Skill"])
    if cls:
        rec.setdefault("classes", cls)
    race = grab_flat("Race", ["Class", "Slot", "Size", "Weight", "Skill"])
    if race:
        rec.setdefault("races", race)
    for label, field in [
        ("AC", "ac"),
        ("DMG", "dmg"),
        ("Dmg", "dmg"),
        ("Delay", "delay"),
        ("Dly", "delay"),
        ("STR", "str"),
        ("STA", "sta"),
        ("AGI", "agi"),
        ("DEX", "dex"),
        ("INT", "int"),
        ("WIS", "wis"),
        ("CHA", "cha"),
        ("HP", "hp"),
        ("MANA", "mana"),
        ("Weight", "weight"),
        ("WT", "weight"),
    ]:
        if rec.get(field) is None:
            v = grab(label)
            if v is not None:
                rec[field] = num(v)
    for label, field in [
        ("Cold", "cold_resist"),
        ("Fire", "fire_resist"),
        ("Magic", "magic_resist"),
        ("Poison", "poison_resist"),
        ("Disease", "disease_resist"),
        ("Electric", "electric_resist"),
    ]:
        if rec.get(field) is None:
            v = grab(label + " Resist") or grab(label + " Res")
            if v is not None:
                rec[field] = num(v)


def parse_item(title: str, text: str) -> dict:
    rec: dict = {"title": title, "raw_len": len(text)}
    box = extract_itembox(text)
    if box is None:
        rec["format"] = "no_itembox"
        return rec
    params = parse_params(box)
    rec["name"] = clean_name(params.get("item_name", title))
    rec["icon_id"] = params.get("icon_id") or None

    structured_keys = {"slot", "dmg", "ac", "str", "sta", "int", "wis", "delay"}
    is_structured = bool(structured_keys & params.keys())
    rec["format"] = "structured" if is_structured else "freeform"

    # structured params
    for f in STAT_FIELDS:
        if f in params:
            rec[f] = num(params[f])
    for pk, field in RESIST_FIELDS.items():
        if pk in params:
            rec[field] = num(params[pk])
    for f in ["slot", "handed", "skill", "size", "effect"]:
        if params.get(f):
            rec[f] = params[f].strip()
    if params.get("class"):
        rec["classes"] = params["class"].strip()
    if params.get("race"):
        rec["races"] = params["race"].strip()
    for flag in ["magic", "lore", "unique", "nodrop", "norent", "nozone"]:
        if params.get(flag, "").strip().upper() in {"TRUE", "YES", "1", "X"}:
            rec[flag] = True

    # freeform blob (fills anything still missing)
    if params.get("item_stats"):
        parse_freeform(params["item_stats"], rec)

    # drops-from (from {{Itempage|dropsfrom=...}})
    dm = re.search(r"dropsfrom\s*=(.*?)(?:\n\s*\||\}\})", text, re.DOTALL | re.IGNORECASE)
    if dm:
        drops = re.findall(r"\[\[([^\]|]+)", dm.group(1))
        if drops:
            rec["dropsfrom"] = "; ".join(dict.fromkeys(drops))

    # categories
    cats = re.findall(r"\[\[Category:([^\]]+)\]\]", text)
    if cats:
        rec["categories"] = "; ".join(cats)

    # acquisition (drops / crafted / quest / vendor)
    parse_acquisition(text, rec)
    normalize_item_drops(rec, _MOB_CANON)

    # ---- finalize: clean leaked markup / typos out of text fields ----
    rec["name"] = strip_markup(rec.get("name") or "") or title
    rec["classes"] = norm_classes(rec.get("classes"))
    rec["races"] = norm_races(rec.get("races"))
    slot, handed = norm_slot(rec.get("slot"))
    rec["slot"] = slot
    if handed and not rec.get("handed"):
        rec["handed"] = handed
    elif rec.get("handed"):
        rec["handed"] = strip_markup(rec["handed"]) or None
    for f in ("skill", "size", "effect"):
        if rec.get(f):
            rec[f] = strip_markup(rec[f]) or None

    return rec


def normalize_row(rec: dict) -> dict:
    row = {}
    for col in ALL_COLUMNS:
        v = rec.get(col)
        if col in COMPLEX_FIELDS and v is not None:
            v = json.dumps(v, ensure_ascii=False)
        row[col] = v
    return row


def write_outputs(rows: list[dict], tag: str) -> tuple[Path, Path, Path]:
    json_path = OUT_DIR / f"items{tag}.json"
    db_path = OUT_DIR / f"items{tag}.db"
    report_path = OUT_DIR / f"items{tag}-report.txt"

    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    cols_def = ", ".join(f'"{c}"' for c in ALL_COLUMNS)
    conn.execute(f"CREATE TABLE items ({cols_def})")
    placeholders = ", ".join("?" for _ in ALL_COLUMNS)
    conn.executemany(
        f"INSERT INTO items VALUES ({placeholders})",
        [tuple(normalize_row(r)[c] for c in ALL_COLUMNS) for r in rows],
    )
    conn.commit()

    total = len(rows)
    equippable = sum(1 for r in rows if r.get("slot"))
    structured = sum(1 for r in rows if r.get("format") == "structured")
    freeform = sum(1 for r in rows if r.get("format") == "freeform")
    no_box = sum(1 for r in rows if r.get("format") == "no_itembox")
    field_fill = {c: sum(1 for r in rows if r.get(c) not in (None, "", False)) for c in ALL_COLUMNS}
    lines = [
        f"Monsters and Memories item extraction report ({tag or 'full'})",
        f"Total items: {total}",
        f"Equippable (has slot): {equippable}",
        f"Format: structured={structured}  freeform={freeform}  no_itembox={no_box}",
        "",
        "Field fill rate (non-empty / total):",
    ]
    for c in ALL_COLUMNS:
        pct = (field_fill[c] / total * 100) if total else 0
        lines.append(f"  {c:18} {field_fill[c]:4}/{total}  {pct:5.1f}%")
    # parse-quality flags
    suspect = [r["title"] for r in rows if r.get("format") != "no_itembox" and not r.get("name")]
    lines.append("")
    lines.append(f"Items missing parsed name: {len(suspect)}")
    for t in suspect[:20]:
        lines.append(f"  - {t}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    conn.close()
    return json_path, db_path, report_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", type=int, metavar="N", help="Sample N items and parse")
    g.add_argument("--all", action="store_true", help="Crawl all of Category:Items")
    ap.add_argument("--category", default="Category:Items", help="Source category")
    ap.add_argument("--seed", type=int, default=7, help="Sample seed for --pilot")
    args = ap.parse_args()

    global _MOB_CANON
    _MOB_CANON = load_mob_canon()
    if _MOB_CANON:
        print(f"Loaded {len(_MOB_CANON)} mob names for drops_zones validation")

    s = session()
    print(f"Listing members of {args.category} ...")
    pool = category_members(s, args.category, None if args.all else max(args.pilot * 5, 500))
    print(f"  {len(pool)} pages")

    if args.all:
        titles = pool
        tag = ""
    else:
        import random

        random.seed(args.seed)
        titles = random.sample(pool, min(args.pilot, len(pool)))
        tag = "-pilot"

    print(f"Fetching {len(titles)} item pages ...")
    contents = fetch_contents(s, titles)

    rows = [parse_item(t, contents.get(t, "")) for t in titles]
    json_path, db_path, report_path = write_outputs(rows, tag)

    equippable = sum(1 for r in rows if r.get("slot"))
    print(f"\nParsed {len(rows)} items ({equippable} equippable).")
    print(f"  {json_path.name}")
    print(f"  {db_path.name}")
    print(f"  {report_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
