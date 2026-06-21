"""Spellblade BiS (no level cap) + purchasability + offer bands.

Pricing reality (from data/ledger-trades.json): the ledger logs the item side and
the coin side of a trade as SEPARATE events, so no coin total maps to a specific
item. Only ~14 trades carry any coin at all, and the LARGEST single coin trade in
the whole dataset is ~4000 copper (40 silver / 4 gold). So we cannot quote real
per-item prices. Instead we tier items by power (score) + rarity and translate to
an OFFER BAND grounded in that observed economy ceiling.
"""

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
STATS = ["str", "sta", "agi", "dex", "int", "wis", "cha"]


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# Spellblade weights (same model as analyze_spellblade.py)
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
RESISTS = [
    "cold_resist",
    "fire_resist",
    "magic_resist",
    "poison_resist",
    "disease_resist",
    "electric_resist",
    "corruption_resist",
    "holy_resist",
]


def score(it):
    s = 0.0
    for k, w in WEIGHTS.items():
        v = it.get(k)
        if isinstance(v, (int, float)):
            s += v * w
    for rk in RESISTS:
        v = it.get(rk)
        if isinstance(v, (int, float)):
            s += v * 0.15
    dmg, delay = it.get("dmg"), it.get("delay")
    if isinstance(dmg, (int, float)) and isinstance(delay, (int, float)) and delay:
        s += (dmg / delay) * 100 * 2.0
    return round(s, 1)


def usable(it):
    c = (it.get("classes") or "").upper().replace(",", " ").split()
    return bool(c) and ("ALL" in c or "SPB" in c)


def slots_of(it):
    return [t for t in (it.get("slot") or "").upper().replace(",", " ").split() if t]


def is_2h(it):
    """A two-handed weapon occupies BOTH primary and secondary slots."""
    h = (it.get("handed") or "").lower()
    if "2" in h or "two" in h:
        return True
    cats = (it.get("categories") or "").lower()
    return "2h " in cats or "two-handed" in cats or "two handed" in cats


def tradeable(it):
    # NODROP cannot be traded/bought at all. ATTUNE/lore-only still tradeable until equipped.
    return not it.get("nodrop")


# Offer band grounded in observed economy: the LARGEST single coin trade in the
# whole ledger is ~4000c (40s). So 30-50s is the realistic ceiling, reserved for
# true named chase weapons. Bands are absolute (by power), not within-slot, and
# are barter guidance for a tiny early-beta economy where most gear moves for 0.
def offer_band(sc):
    if sc >= 130:
        return "30-50s (named chase weapon; top of the economy)"
    if sc >= 80:
        return "20-40s"
    if sc >= 45:
        return "12-25s"
    if sc >= 32:
        return "6-15s"
    if sc >= 22:
        return "3-8s"
    if sc >= 14:
        return "1-4s"
    return "<1s / favor"


def fmt_stats(it):
    parts = []
    for k in STATS + ["hp", "mana", "ac", "haste", "mana_regen"]:
        v = it.get(k)
        if isinstance(v, (int, float)) and v:
            parts.append(f"{k}+{v}")
    if it.get("dmg"):
        parts.append(f"{it['dmg']}/{it.get('delay')}")
    return " ".join(parts)


def is_shield(it):
    return "shield" in (it.get("categories") or "").lower()


# Spellblade CAN dual-wield (confirmed in-game): an off-hand 1H weapon grants
# extra attacks. Off-hand swings fire less often than the main hand, so we count
# the off-hand WEAPON's damage at a reduced effectiveness. Its worn stats still
# apply fully. (Exact rate is in the encrypted client; 0.6 is a leveling-era
# placeholder -- tune when the formula is known.)
OFFHAND_FACTOR = 0.6


def stat_score(it):
    """Score from worn stats/resists only (excludes weapon damage)."""
    s = 0.0
    for k, w in WEIGHTS.items():
        v = it.get(k)
        if isinstance(v, (int, float)):
            s += v * w
    for rk in RESISTS:
        v = it.get(rk)
        if isinstance(v, (int, float)):
            s += v * 0.15
    return s


def dmg_score(it):
    dmg, delay = it.get("dmg"), it.get("delay")
    if isinstance(dmg, (int, float)) and isinstance(delay, (int, float)) and delay:
        return (dmg / delay) * 100 * 2.0
    return 0.0


def weapon_config(items):
    """Slot rules for the primary/secondary pairing.

    CERTAIN: a 2-hander fills BOTH slots (never coexists with an off-hand).
    CONFIRMED in-game: SPB can dual-wield -> a 1H off-hand weapon adds attacks.
    Off-hand damage is discounted by OFFHAND_FACTOR (lower swing rate); off-hand
    worn stats count fully. Shield off-hand contributes AC/stats but no damage.
    """
    prim_1h, two_h, off_shield, off_weapon = [], [], [], []
    for it in items:
        if not usable(it):
            continue
        sl = slots_of(it)
        sc = score(it)
        if sc <= 0:
            continue
        if is_2h(it):
            if "PRIMARY" in sl or "SECONDARY" in sl:  # bows are RANGED, excluded
                two_h.append((sc, it))
            continue
        if "PRIMARY" in sl and it.get("dmg") is not None:
            prim_1h.append((sc, it))
        if "SECONDARY" in sl and it.get("dmg") is not None:
            off_weapon.append((sc, it))
        elif "SECONDARY" in sl and is_shield(it):
            off_shield.append((sc, it))

    def top(lst, n=5):
        out, seen = [], set()
        for sc, it in sorted(lst, key=lambda x: x[0], reverse=True):
            if it["title"] in seen:
                continue
            seen.add(it["title"])
            out.append((sc, it))
            if len(out) >= n:
                break
        return out

    bp = top(prim_1h, 1)
    bsh = top(off_shield, 1)
    b2 = top(two_h, 1)
    prim = bp[0][0] if bp else 0

    # For the dual-wield off-hand, pick the 1H weapon that maximizes
    # (worn stats + discounted damage), not raw full score.
    def offhand_effective(it):
        return stat_score(it) + dmg_score(it) * OFFHAND_FACTOR

    best_dw = max(off_weapon, key=lambda x: offhand_effective(x[1])) if off_weapon else None
    dw_off_val = offhand_effective(best_dw[1]) if best_dw else 0

    a_total = prim + (bsh[0][0] if bsh else 0)  # 1H + shield
    b_total = prim + dw_off_val  # 1H + 1H (dual wield, discounted off-hand)
    c_total = b2[0][0] if b2 else 0  # 2H

    def line(sc, it, indent=12, extra=""):
        tag = "ND" if not tradeable(it) else "T "
        return f"  [{tag}] {' ' * indent}{sc:>6}  {it['title']:<34} {fmt_stats(it)}{extra}"

    print("=" * 92)
    print(
        f"WEAPON CONFIG (SPB dual-wields; off-hand damage @ {OFFHAND_FACTOR:.0%}). 2H = both slots."
    )
    print("=" * 92)
    print(
        f"\n  Config A  1H + SHIELD       total = {a_total:.1f}   (defensive: off-hand = AC, no extra swings)"
    )
    for grp in (bp, bsh):
        for sc, it in grp:
            print(line(sc, it))
    print(
        f"\n  Config B  DUAL-WIELD 1H+1H  total = {b_total:.1f}   (max swings -> max procs; best DPS pipe)"
    )
    for sc, it in bp:
        print(line(sc, it))
    if best_dw:
        print(line(round(dw_off_val, 1), best_dw[1], extra="  (off-hand, discounted)"))
    print(f"\n  Config C  TWO-HANDER        total = {c_total:.1f}   (one big hit, fewest procs)")
    for sc, it in b2:
        print(line(sc, it))

    ranked = sorted(
        [("A 1H+shield", a_total), ("B dual-wield", b_total), ("C two-hander", c_total)],
        key=lambda x: x[1],
        reverse=True,
    )
    print("\n  => DPS ranking (by model): " + " > ".join(f"{n} ({v:.0f})" for n, v in ranked))
    print("     Dual-wield favored for SPB: more swings = more weapon procs feeding")
    print("     the INT spell pipe. 2H wins only if its proc/hit is exceptional.")

    print("\n  Top 1H weapons (main or off-hand for dual-wield):")
    for sc, it in top(prim_1h):
        print(line(sc, it, 0))
    print("\n  Top shields (defensive off-hand):")
    for sc, it in top(off_shield):
        print(line(sc, it, 0))
    print("\n  Top two-handers (each EXCLUDES an off-hand):")
    for sc, it in top(two_h):
        print(line(sc, it, 0))

    return {
        "config_a_1h_shield": round(a_total, 1),
        "config_b_dual_wield": round(b_total, 1),
        "config_c_two_hander": round(c_total, 1),
        "offhand_damage_factor": OFFHAND_FACTOR,
        "dps_ranking": [n for n, _ in ranked],
        "dual_wield": "confirmed in-game (off-hand 1H grants extra attacks)",
        "best_1h_weapons": [{"title": it["title"], "score": sc} for sc, it in top(prim_1h)],
        "best_shield": [{"title": it["title"], "score": sc} for sc, it in top(off_shield)],
        "best_two_handers": [
            {"title": it["title"], "score": sc, "tradeable": tradeable(it)} for sc, it in top(two_h)
        ],
    }


def main():
    items = load("items.json")

    weapons = weapon_config(items)
    print()

    by_slot = defaultdict(list)
    for it in items:
        if not usable(it) or not slots_of(it):
            continue
        sc = score(it)
        if sc <= 0:
            continue
        # Melee weapons (primary/secondary, incl. all 2H) are handled by
        # weapon_config() above, so exclude them from the per-slot listing.
        wslots = set(slots_of(it))
        if ({"PRIMARY", "SECONDARY"} & wslots) and (is_2h(it) or it.get("dmg") is not None):
            continue
        for sl in slots_of(it):
            by_slot[sl].append((sc, it))

    SLOT_ORDER = [
        "WAIST",
        "BACK",
        "WRIST",
        "HEAD",
        "CHEST",
        "HANDS",
        "FEET",
        "NECK",
        "EAR",
        "SHOULDERS",
        "FINGER",
        "LEGS",
        "FACE",
        "ARMS",
        "RANGED",
        "AMMO",
    ]

    out = {}
    print("=" * 92)
    print("SPELLBLADE BiS  —  no level cap.  [T]=tradeable/buyable  [ND]=NODROP must-farm")
    print("=" * 92)
    rows = []
    for sl in [s for s in SLOT_ORDER if s in by_slot] + [s for s in by_slot if s not in SLOT_ORDER]:
        cands = sorted(by_slot[sl], key=lambda x: x[0], reverse=True)
        uniq, seen = [], set()
        for sc, it in cands:
            if it["title"] in seen:
                continue
            seen.add(it["title"])
            uniq.append((sc, it))
        if not uniq:
            continue
        slot_best = uniq[0][0]
        out[sl] = []
        print(f"\n### {sl}  (slot-best score {slot_best})")
        # show best overall + best *buyable* if different
        best_buyable = next((x for x in uniq if tradeable(x[1])), None)
        shown = 0
        for sc, it in uniq:
            if shown >= 4 and not (best_buyable and it is best_buyable[1]):
                continue
            tag = "T " if tradeable(it) else "ND"
            band = offer_band(sc) if tradeable(it) else "— not purchasable —"
            print(f"  [{tag}] {sc:>6}  {it['title']:<36} {fmt_stats(it):<46} {band}")
            out[sl].append(
                {
                    "title": it["title"],
                    "score": sc,
                    "tradeable": tradeable(it),
                    "unique": bool(it.get("unique")),
                    "offer_band": band,
                    "stats": fmt_stats(it),
                }
            )
            shown += 1
        # priority weight = slot-best score, captured for global ordering
        rows.append(
            (
                sl,
                slot_best,
                best_buyable[0] if best_buyable else 0,
                uniq[0][1]["title"],
                tradeable(uniq[0][1]),
            )
        )

    # ---- Global priority order (by upgrade magnitude of the slot's best piece) ----
    print("\n" + "=" * 92)
    print("GLOBAL PRIORITY ORDER (slots ranked by power of their best piece)")
    print("=" * 92)
    for i, (sl, best, _buyable_best, title, t) in enumerate(
        sorted(rows, key=lambda r: r[1], reverse=True), 1
    ):
        note = "buyable" if t else "NODROP-farm"
        print(f"{i:>2}. {sl:<10} best={best:<7} {title:<34} ({note})")

    out["_weapons"] = weapons
    (DATA / "spellblade-market.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nWrote data/spellblade-market.json")


if __name__ == "__main__":
    main()
