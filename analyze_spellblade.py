"""Spellblade (SPB) deep analysis: stat emphasis + itemization at a target level.

Reads the local normalized dataset (items/base_stats/monsters/drops) and produces
a stat-priority profile plus best-in-slot candidates for a target character level.
No reliance on wiki class pages (the class was reworked); everything here is
derived from data we control: base-stat screenshots, item itemization, and the
mob/zone level of each item's drop source.
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"

TARGET_LEVEL = 25
LEVEL_BAND = (TARGET_LEVEL - 10, TARGET_LEVEL + 5)  # obtainable window for a L25 char

STATS = ["str", "sta", "agi", "dex", "int", "wis", "cha"]


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def main():
    items = load("items.json")
    base = load("base_stats.json")
    monsters = load("monsters.json")
    drops = load("drops.json")

    # ---- 1. Base-stat emphasis for Spellblade ----
    spb_base = [b for b in base if b.get("class") == "Spellblade"]
    print("=" * 70)
    print(f"SPELLBLADE BASE STATS  ({len(spb_base)} race samples)")
    print("=" * 70)
    cur_avg = {s: statistics.mean(b["current"][s] for b in spb_base) for s in STATS}
    max_avg = {s: statistics.mean(b["max"][s] for b in spb_base) for s in STATS}
    print(f"{'stat':<5}{'avg start':>10}{'avg max':>10}{'headroom':>10}")
    for s in STATS:
        print(
            f"{s.upper():<5}{cur_avg[s]:>10.1f}{max_avg[s]:>10.1f}{max_avg[s] - cur_avg[s]:>10.1f}"
        )
    ranked_max = sorted(STATS, key=lambda s: max_avg[s], reverse=True)
    print("\nStat priority by max ceiling:", " > ".join(s.upper() for s in ranked_max))

    # ---- 2. Build mob level lookup ----
    mob_level = {}
    for m in monsters:
        lo, hi = m.get("level_min"), m.get("level_max")
        lvls = [x for x in (lo, hi) if isinstance(x, (int, float))]
        if lvls:
            mob_level[m["title"].lower()] = (min(lvls), max(lvls))

    # item_title -> list of (mob_lo, mob_hi, zone)
    item_sources = defaultdict(list)
    for d in drops:
        it = d.get("item_title")
        mob = (d.get("mob_title") or "").lower()
        if not it:
            continue
        lv = mob_level.get(mob)
        if lv:
            item_sources[it].append((lv[0], lv[1], d.get("zone")))

    # ---- 3. SPB-usable items ----
    def usable_by_spb(it):
        c = (it.get("classes") or "").upper()
        if not c:
            return False
        if "ALL" in c.split():
            return True
        return "SPB" in c.replace(",", " ").split()

    def item_min_level(title):
        srcs = item_sources.get(title, [])
        if not srcs:
            return None
        return min(s[0] for s in srcs)

    # Spellblade stat weights (derived from base-stat emphasis + hybrid role):
    # INT drives spell damage/mana pool; DEX drives melee accuracy/weapon skill;
    # STA = survivability; mana/hp = direct pools; AC = mitigation.
    WEIGHTS = {
        "int": 3.0,
        "dex": 2.0,
        "sta": 1.5,
        "str": 1.0,
        "agi": 0.5,
        "wis": 0.3,
        "cha": 0.2,
        "hp": 0.25,
        "mana": 0.25,
        "ac": 0.4,
        "hp_regen": 1.0,
        "mana_regen": 2.0,
        "haste": 4.0,
    }
    RESIST_W = 0.15

    def score(it):
        s = 0.0
        for k, w in WEIGHTS.items():
            v = it.get(k)
            if isinstance(v, (int, float)):
                s += v * w
        for rk in (
            "cold_resist",
            "fire_resist",
            "magic_resist",
            "poison_resist",
            "disease_resist",
            "electric_resist",
            "corruption_resist",
            "holy_resist",
        ):
            v = it.get(rk)
            if isinstance(v, (int, float)):
                s += v * RESIST_W
        # weapon DPS bonus: ratio*scale; reward magic weapons (can hit incorporeal)
        dmg, delay = it.get("dmg"), it.get("delay")
        if isinstance(dmg, (int, float)) and isinstance(delay, (int, float)) and delay:
            s += (dmg / delay) * 100 * 2.0
        return round(s, 1)

    # slot tokenization (an item may list multiple slots)
    def slots_of(it):
        sl = (it.get("slot") or "").upper().replace(",", " ")
        return [t for t in sl.split() if t]

    spb_items = []
    for it in items:
        if not usable_by_spb(it):
            continue
        if not slots_of(it):
            continue
        if it.get("format") != "structured":
            # freeform may still have stats; keep if it has any stat value
            if not any(isinstance(it.get(k), (int, float)) for k in WEIGHTS):
                continue
        spb_items.append(it)

    print(f"\nTotal SPB-usable items with a slot: {len(spb_items)}")

    # ---- 3b. Itemization fingerprint (dev design intent) ----
    # Restrict to SPB-flagged armor/jewelry (exclude ALL-class & weapons) so we
    # see what the devs deliberately put on *Spellblade* gear.
    def spb_specific(it):
        c = (it.get("classes") or "").upper().replace(",", " ").split()
        return "SPB" in c and "ALL" not in c

    armor = [it for it in spb_items if spb_specific(it) and not (it.get("dmg") and it.get("delay"))]
    print("\n" + "=" * 70)
    print(f"ITEMIZATION FINGERPRINT  ({len(armor)} SPB-tagged armor/jewelry pieces)")
    print("(how often each stat appears + average magnitude when present)")
    print("=" * 70)
    fp = {}
    for k in STATS + ["hp", "mana", "ac", "haste", "mana_regen", "hp_regen"]:
        vals = [it[k] for it in armor if isinstance(it.get(k), (int, float)) and it[k]]
        if vals:
            fp[k] = (len(vals), len(vals) / len(armor) * 100, statistics.mean(vals))
    print(f"{'stat':<11}{'#items':>7}{'freq%':>8}{'avg val':>9}")
    for k, (n, pct, avg) in sorted(fp.items(), key=lambda x: x[1][1], reverse=True):
        print(f"{k:<11}{n:>7}{pct:>7.0f}%{avg:>9.1f}")

    # ---- 4. Best-in-slot at target level ----
    by_slot = defaultdict(list)
    for it in spb_items:
        sc = score(it)
        if sc <= 0:
            continue
        mlv = item_min_level(it["title"])
        # availability: unknown source OR source within/under the obtainable window
        obtainable = (mlv is None) or (mlv <= LEVEL_BAND[1])
        if not obtainable:
            continue
        for sl in slots_of(it):
            by_slot[sl].append((sc, mlv, it))

    SLOT_ORDER = [
        "HEAD",
        "FACE",
        "EAR",
        "NECK",
        "SHOULDERS",
        "BACK",
        "CHEST",
        "ARMS",
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
    ]

    print("\n" + "=" * 70)
    print(f"BEST-IN-SLOT CANDIDATES (obtainable by ~L{TARGET_LEVEL})")
    print("=" * 70)

    def fmt_stats(it):
        parts = []
        for k in STATS + ["hp", "mana", "ac", "haste", "mana_regen", "hp_regen"]:
            v = it.get(k)
            if isinstance(v, (int, float)) and v:
                parts.append(f"{k}+{v}")
        if it.get("dmg"):
            parts.append(f"{it['dmg']}/{it.get('delay')}")
        if it.get("magic"):
            parts.append("magic")
        return " ".join(parts)

    report = {
        "base_stats": {"current_avg": cur_avg, "max_avg": max_avg, "priority": ranked_max},
        "slots": {},
    }

    seen_slots = [s for s in SLOT_ORDER if s in by_slot] + [
        s for s in by_slot if s not in SLOT_ORDER
    ]
    for sl in seen_slots:
        cands = sorted(by_slot[sl], key=lambda x: x[0], reverse=True)
        # dedupe by item title
        uniq, names = [], set()
        for c in cands:
            t = c[2]["title"]
            if t in names:
                continue
            names.add(t)
            uniq.append(c)
        print(f"\n### {sl}")
        report["slots"][sl] = []
        for sc, mlv, it in uniq[:5]:
            lvtag = f"~L{mlv}" if mlv is not None else "L?"
            src = item_sources.get(it["title"], [])
            zone = src[0][2] if src else (it.get("dropsfrom") or "?")
            print(f"  {sc:>6}  [{lvtag:>5}] {it['title']:<34} {fmt_stats(it)}  <{zone}>")
            report["slots"][sl].append(
                {
                    "title": it["title"],
                    "score": sc,
                    "min_source_level": mlv,
                    "stats": fmt_stats(it),
                    "zone": zone,
                }
            )

    (DATA / "spellblade-analysis.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print("\nWrote data/spellblade-analysis.json")


if __name__ == "__main__":
    main()
