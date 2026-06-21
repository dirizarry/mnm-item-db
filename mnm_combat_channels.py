"""MnM chat channel catalog for combat OCR analytics.

Channel ids come from per-character ``chats.json`` (106 categories in v3.1).
Each in-game chat window routes a subset of these; OCR regions can be bound to
a window id + expected channel set for richer event tagging.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Window roles for multi-region capture (user-defined chat windows in chats.json).
WINDOW_ROLES = {
    "meter": "Primary damage/heal meter (Combat + Ability hits/misses)",
    "casts": "Casting, interrupts, resists, fizzles (Ability* + Action)",
    "buffs": "Buff apply/fade/tick",
    "deaths": "Death + experience",
    "pvp": "Incoming player aggression (hits on you / your pet from players)",
    "social": "Say/Tell/Party (usually excluded from combat OCR)",
    "misc": "LOS, Consider, Loot, Status",
}

# Map channel id prefix families to analytics categories.
FAMILY_META: dict[str, dict] = {
    "CombatHit": {"category": "combat", "subcategory": "hit", "damage": True},
    "CombatMiss": {"category": "combat", "subcategory": "miss", "damage": False},
    "AbilityHitBenefit": {"category": "ability", "subcategory": "hit", "benefit": True, "damage": True},
    "AbilityHitDetriment": {"category": "ability", "subcategory": "hit", "benefit": False, "damage": True},
    "AbilityMiss": {"category": "ability", "subcategory": "miss"},
    "AbilityResist": {"category": "ability", "subcategory": "resist"},
    "Ability": {"category": "ability", "subcategory": "cast"},
    "AbilityStatus": {"category": "ability", "subcategory": "status"},
    "DamageShieldHit": {"category": "damage_shield", "subcategory": "hit", "damage": True},
    "BuffApplyBenefit": {"category": "buff", "subcategory": "apply", "benefit": True},
    "BuffApplyDetriment": {"category": "buff", "subcategory": "apply", "benefit": False},
    "BuffFadeBenefit": {"category": "buff", "subcategory": "fade", "benefit": True},
    "BuffFadeDetriment": {"category": "buff", "subcategory": "fade", "benefit": False},
    "BuffTickBenefit": {"category": "buff", "subcategory": "tick", "benefit": True},
    "BuffTickDetriment": {"category": "buff", "subcategory": "tick", "benefit": False},
    "Death": {"category": "death", "subcategory": "kill"},
    "DeathMe": {"category": "death", "subcategory": "death_me"},
    "Experience": {"category": "experience", "subcategory": "gain"},
    "LOS": {"category": "los", "subcategory": "blocked"},
    "Action": {"category": "action", "subcategory": "misc"},
    "Skill": {"category": "skill", "subcategory": "misc"},
    "Status": {"category": "status", "subcategory": "misc"},
}

SUFFIX_META = {
    "Mine": {"perspective": "mine", "actor": "you"},
    "Pet": {"perspective": "pet", "actor": "pet"},
    "Victim": {"perspective": "victim", "actor": "you"},
    "OtherPlayer": {"perspective": "other_player"},
    "Other": {"perspective": "other"},
}

# Recommended channel sets per capture window role.
ROLE_CHANNELS: dict[str, tuple[str, ...]] = {
    "meter": (
        "CombatHitMine", "CombatHitVictim", "CombatHitPet", "CombatHitOther", "CombatHitOtherPlayer",
        "CombatMissMine", "CombatMissVictim", "CombatMissPet", "CombatMissOther", "CombatMissOtherPlayer",
        "AbilityHitBenefitMine", "AbilityHitBenefitVictim", "AbilityHitBenefitPet",
        "AbilityHitBenefitOther", "AbilityHitBenefitOtherPlayer",
        "AbilityHitDetrimentMine", "AbilityHitDetrimentVictim", "AbilityHitDetrimentPet",
        "AbilityHitDetrimentOther", "AbilityHitDetrimentOtherPlayer",
        "AbilityMissMine", "AbilityMissVictim", "AbilityMissPet", "AbilityMissOther", "AbilityMissOtherPlayer",
        "DamageShieldHitMine", "DamageShieldHitVictim", "DamageShieldHitOther", "DamageShieldHitOtherPlayer",
    ),
    "casts": (
        "AbilityMine", "AbilityOther", "AbilityOtherPlayer", "AbilityPet",
        "AbilityResistMine", "AbilityResistVictim", "AbilityResistPet", "AbilityResistOther", "AbilityResistOtherPlayer",
        "AbilityStatus", "Action",
    ),
    "buffs": tuple(
        f"Buff{kind}{suffix}"
        for kind in ("Apply", "Fade", "Tick")
        for suffix in ("BenefitMine", "BenefitVictim", "BenefitOther", "BenefitOtherPlayer",
                       "DetrimentMine", "DetrimentVictim", "DetrimentOther", "DetrimentOtherPlayer")
    ),
    "deaths": ("DeathMine", "DeathMe", "DeathOther", "DeathOtherPlayer", "Experience"),
    "pvp": (
        "CombatHitVictim", "CombatHitOtherPlayer",
        "CombatMissVictim", "CombatMissOtherPlayer",
        "AbilityHitDetrimentVictim", "AbilityHitDetrimentOtherPlayer",
        "AbilityMissVictim", "AbilityMissOtherPlayer",
        "AbilityResistVictim", "AbilityResistOtherPlayer",
        "DamageShieldHitVictim", "DamageShieldHitOtherPlayer",
        "BuffApplyDetrimentVictim", "BuffApplyDetrimentOtherPlayer",
        "BuffTickDetrimentVictim", "BuffTickDetrimentOtherPlayer",
        "DeathMe", "DeathOtherPlayer",
    ),
    "misc": ("LOS", "Status", "Loot", "ConsiderRED", "ConsiderYELLOW", "ConsiderWHITE",
             "ConsiderBLUE", "ConsiderGREEN", "ConsiderGREY", "ConsiderLIGHTBLUE", "ConsiderLIGHTGREEN"),
}

# In-game Combat filter menu labels → chats.json channel suffix (Mine/Victim/Pet/Other/OtherPlayer).
UI_TARGET_SUFFIX: dict[str, str] = {
    "Me": "Mine",
    "My": "Mine",
    "Mine": "Victim",
    "Pet": "Pet",
    "Pets": "Pet",
    "NPCs": "Other",
    "Others": "Other",
    "Co-Players": "Other",
    "Group": "Other",
    "Players": "OtherPlayer",
}

# Spell Apply/Fade/Tick toggles use Beneficial/Detrimental × target (not the generic suffix map).
BUFF_UI_SUFFIX: dict[tuple[str, str], str] = {
    ("Beneficial", "Me"): "BenefitMine",
    ("Beneficial", "NPCs"): "BenefitOther",
    ("Beneficial", "Players"): "BenefitOtherPlayer",
    ("Beneficial", "Pets"): "BenefitVictim",
    ("Detrimental", "Me"): "DetrimentVictim",
    ("Detrimental", "NPCs"): "DetrimentOther",
    ("Detrimental", "Players"): "DetrimentOtherPlayer",
    ("Detrimental", "Pets"): "DetrimentVictim",
}

DEATH_UI_CHANNELS: dict[str, tuple[str, ...]] = {
    "Me": ("DeathMine", "DeathMe"),
    "Pet": (),
    "NPCs": ("DeathOther",),
    "Players": ("DeathOtherPlayer",),
}

# OCR capture presets — map to in-game filter paths and ROLE_CHANNELS sets.
OCR_PRESETS: dict[str, dict] = {
    "meter": {
        "label": "DPS / HPS meter (primary combat window)",
        "role": "meter",
        "window_id": "combat",
        "steps": [
            "Combat → Melee → Hits: Me, Pet, NPCs, Players",
            "Combat → Melee → Misses: Me, Pet, NPCs, Players",
            "Combat → Ability → Hit / Miss: Me, NPCs, Players",
            "Combat → Spell → Tick: all Beneficial + Detrimental toggles",
        ],
    },
    "casts": {
        "label": "Casts, resists, interrupts, fizzles",
        "role": "casts",
        "window_id": "combat2",
        "steps": [
            "Open a second chat window (or route to combat2)",
            "Combat → Ability → Resist: Me, NPCs, Players",
            "Enable AbilityStatus (interrupts/fizzles) via casts filter group",
        ],
    },
    "buffs": {
        "label": "Buff apply, fade, tick",
        "role": "buffs",
        "window_id": "combat3",
        "steps": [
            "Combat → Spell → Apply / Fade / Tick",
            "Enable all Beneficial + Detrimental toggles (Me, NPCs, Players)",
        ],
    },
    "deaths": {
        "label": "Deaths and experience",
        "role": "deaths",
        "window_id": "combat",
        "steps": [
            "Combat → Death: Me, NPCs, Players",
            "Route Experience channel to this window",
        ],
    },
    "pvp": {
        "label": "PvP incoming aggression alerts",
        "role": "pvp",
        "window_id": "combat",
        "steps": [
            "Combat → Melee → Hits/Misses: Mine (hits on you), Players",
            "Combat → Ability → Hit/Miss/Resist: Me, Players",
            "Combat → Spell → Apply/Tick Detrimental: Me, Players",
            "Combat → Death → Players",
        ],
    },
    "misc": {
        "label": "LOS, consider, loot noise",
        "role": "misc",
        "window_id": "combat",
        "steps": [
            "Combat → Line of Sight",
            "Optional: route Consider / Loot to a separate window",
        ],
    },
}


def channel_family(channel_id: str) -> str:
    for suffix in ("Mine", "OtherPlayer", "Other", "Victim", "Pet"):
        if channel_id.endswith(suffix):
            return channel_id[:-len(suffix)]
    return channel_id


def channel_suffix(channel_id: str) -> str | None:
    for suffix in ("OtherPlayer", "Mine", "Victim", "Pet", "Other"):
        if channel_id.endswith(suffix):
            return suffix
    return None


def describe_channel(channel_id: str) -> dict:
    fam = channel_family(channel_id)
    suf = channel_suffix(channel_id)
    meta = dict(FAMILY_META.get(fam, {"category": "unknown", "subcategory": fam}))
    if suf and suf in SUFFIX_META:
        meta.update(SUFFIX_META[suf])
    meta["channel"] = channel_id
    meta["family"] = fam
    meta["suffix"] = suf
    return meta


def infer_channel(event: dict) -> str | None:
    """Best-effort map from parsed event back to a chats.json channel id."""
    kind = event.get("kind") or ""
    direction = event.get("direction") or ""
    actor = event.get("actor") or ""
    target = event.get("target") or ""
    pet = event.get("pet")
    outcome = event.get("outcome") or ""
    ability = event.get("ability")

    def persp() -> str:
        if pet or (actor and actor != "You" and event.get("kind") in ("melee", "ability", "miss") and direction == "outgoing"):
            if pet:
                return "Pet"
        if actor == "You" or (direction == "outgoing" and not pet):
            return "Mine"
        if target == "You" or direction == "incoming":
            return "Victim"
        if actor and actor != "You" and re.match(r"^[A-Z]", actor):
            return "OtherPlayer"
        return "Other"

    p = persp()

    if kind == "experience":
        return "Experience"
    if kind == "death":
        if actor == "You":
            return "DeathMine"
        if target == "You":
            return "DeathMe"
        if p == "OtherPlayer":
            return "DeathOtherPlayer"
        return "DeathOther"
    if kind == "cast":
        if outcome in ("interrupted", "fizzle"):
            return "AbilityStatus"
        return f"Ability{p}" if p in ("Mine", "Pet", "Other", "OtherPlayer") else "AbilityMine"
    if outcome == "resist":
        return f"AbilityResist{p}"
    if kind in ("melee", "damage") or (kind == "ability" and not ability):
        hit = outcome not in ("miss", "parry", "dodge", "block")
        fam = "CombatHit" if hit else "CombatMiss"
        return f"{fam}{p}"
    if kind in ("ability", "heal", "absorb", "dot"):
        if outcome in ("miss", "parry", "dodge", "block"):
            return f"AbilityMiss{p}"
        if kind == "heal" or (ability and "heal" in (ability or "").lower()):
            det = "Benefit"
        elif direction == "outgoing" and target and target not in ("You",):
            det = "Detriment"
        elif direction == "incoming":
            det = "Detriment"
        else:
            det = "Benefit"
        if kind == "damage_shield" or "shield" in (event.get("raw") or "").lower():
            return f"DamageShieldHit{p}"
        return f"AbilityHit{det}{p}"
    if kind == "buff":
        return f"BuffApplyBenefit{p}"  # refined later with apply/fade
    if kind == "status" and "los" in (event.get("raw") or "").lower():
        return "LOS"
    return None


def load_channels_from_chats(chats_path: Path) -> list[str]:
    data = json.loads(chats_path.read_text(encoding="utf-8"))
    return sorted((data.get("channels") or {}).keys())


def _channels_for_hit_family(family: str, targets: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for label in targets:
        suf = UI_TARGET_SUFFIX.get(label)
        if suf:
            out.append(f"{family}{suf}")
    return out


def _channels_for_buff_phase(phase: str, alignment: str, targets: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for label in targets:
        suf = BUFF_UI_SUFFIX.get((alignment, label))
        if suf:
            out.append(f"Buff{phase}{suf}")
    return out


def build_filter_menu() -> dict:
    """In-game Combat submenu tree (from ShareX screenshots, 2026-06-19)."""
    hit_targets = ("Me", "Mine", "Pet", "NPCs", "Players")
    ability_targets = ("Me", "NPCs", "Players")
    buff_targets = ("Me", "NPCs", "Players")
    spell_alignments = ("Beneficial", "Detrimental")

    melee_outcomes = (
        "Hits", "Misses", "Dodges", "Parries", "Ripostes", "Blocks",
        "Absorbs", "Reflects", "Invulnerable",
    )
    ability_outcomes = ("Hit", "Miss", "Resist", "Interrupts", "Fizzles")
    spell_phases = ("Apply", "Fade", "Tick")

    menu: dict = {
        "Death": {
            "targets": list(DEATH_UI_CHANNELS.keys()),
            "channels_by_target": {k: list(v) for k, v in DEATH_UI_CHANNELS.items()},
        },
        "Pet": {"toggle": True, "channels": ["Pet"]},
        "Line of Sight": {"toggle": True, "channels": ["LOS"]},
        "Melee": {
            "outcomes": {},
        },
        "Ability": {"outcomes": {}},
        "Spell": {"phases": {}},
    }

    for outcome in melee_outcomes:
        fam = "CombatHit" if outcome == "Hits" else "CombatMiss" if outcome == "Misses" else None
        if fam:
            menu["Melee"]["outcomes"][outcome] = {
                "targets": list(hit_targets),
                "channels": _channels_for_hit_family(fam, hit_targets),
            }
        else:
            menu["Melee"]["outcomes"][outcome] = {
                "note": "Mitigation outcome — parsed from hit lines (absorb/parry/dodge/block)",
                "channels": [],
            }

    for outcome in ability_outcomes:
        if outcome == "Hit":
            chs = []
            for det in ("Benefit", "Detriment"):
                for label in ability_targets:
                    suf = UI_TARGET_SUFFIX[label]
                    chs.append(f"AbilityHit{det}{suf}")
            menu["Ability"]["outcomes"][outcome] = {
                "targets": list(ability_targets),
                "channels": chs,
            }
        elif outcome == "Miss":
            menu["Ability"]["outcomes"][outcome] = {
                "targets": list(ability_targets),
                "channels": _channels_for_hit_family("AbilityMiss", ability_targets),
            }
        elif outcome == "Resist":
            menu["Ability"]["outcomes"][outcome] = {
                "targets": list(ability_targets),
                "channels": _channels_for_hit_family("AbilityResist", ability_targets),
            }
        else:
            menu["Ability"]["outcomes"][outcome] = {
                "note": "Cast lifecycle — AbilityStatus channel",
                "channels": ["AbilityStatus"],
            }

    for phase in spell_phases:
        phase_entry: dict = {"alignments": {}}
        for align in spell_alignments:
            phase_entry["alignments"][align] = {
                "targets": list(buff_targets),
                "channels": _channels_for_buff_phase(phase, align, buff_targets),
            }
        menu["Spell"]["phases"][phase] = phase_entry

    menu["Spell"]["Resist"] = {
        "note": "Spell resist flyout — maps to AbilityResist* channels",
        "alignments": {
            align: {
                "targets": list(hit_targets),
                "channels": _channels_for_hit_family("AbilityResist", hit_targets),
            }
            for align in ("Beneficial", "Detriment", "Misc")
        },
    }

    return menu


def export_filter_ui() -> dict:
    screenshots = [
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_1OLuI4SLno.jpg",
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_3XUnnh83dk.jpg",
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_de4bPvwNYV.jpg",
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_pTAvNH91Nl.jpg",
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_4kDcOH7csC.jpg",
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_EuowaYxVIW.jpg",
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_qhudRZ741e.jpg",
        "C:\\Users\\84dan\\Documents\\ShareX\\Screenshots\\2026-06\\mnm_Vk9q7ggBG0.jpg",
    ]
    presets = {}
    for key, meta in OCR_PRESETS.items():
        role = meta["role"]
        presets[key] = {
            **meta,
            "channels": list(ROLE_CHANNELS.get(role, ())),
            "channel_count": len(ROLE_CHANNELS.get(role, ())),
        }
    return {
        "version": 1,
        "ui_path": "Right-click chat window → Combat >",
        "source_screenshots": screenshots,
        "label_maps": {
            "target_suffix": UI_TARGET_SUFFIX,
            "buff_suffix": {f"{a}|{t}": s for (a, t), s in BUFF_UI_SUFFIX.items()},
            "suffix_meta": SUFFIX_META,
        },
        "menu": build_filter_menu(),
        "presets": presets,
        "roles": {role: list(chs) for role, chs in ROLE_CHANNELS.items()},
    }


def write_filter_ui(path: Path) -> dict:
    doc = export_filter_ui()
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def export_catalog(channels: list[str]) -> dict:
    return {
        "version": 1,
        "channel_count": len(channels),
        "channels": {c: describe_channel(c) for c in channels},
        "roles": {role: list(chs) for role, chs in ROLE_CHANNELS.items()},
        "filter_ui_ref": "combat-filter-ui.json",
    }
