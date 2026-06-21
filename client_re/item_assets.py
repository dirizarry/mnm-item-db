"""Extract client-side item assets (icon sprites + equipment models) from bundles.

Monsters & Memories ships no item/monster *stat* tables on disk (those are
server-driven, captured via the ledger). What it does ship:

- **Icon sprites** in ``defaultlocalgroup`` (clean keys like ``boots_steel_equipment``)
- **Equipment models** in ``globalitems`` (mesh names like ``WeatheredLeatherB_Helm_HumanF_Base``)

This module catalogs both and (optionally) exports the icon PNGs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from client_re.mnm_bundle import load_unity_env
from client_re.paths import bundles_dir, install_root

# GameObject names in globalitems that are rig/bone/helper nodes, not item models.
_BONE_RE = re.compile(r"^(DEF_|MCH_|ORG_|CTRL_|IK_|root\b|Bip\d|Armature)", re.IGNORECASE)
_RIG_SUFFIX = ("_Rig", "_rig")

# Sprites that are clearly ability/class UI, not item icons.
_ABILITY_PREFIXES = ("Ability_", "Debuff_", "Buff_")
_CLASS_NAMES = (
    "Druid",
    "Wizard",
    "Spellblade",
    "Shaman",
    "Archer",
    "Cleric",
    "Paladin",
    "Necromancer",
    "Enchanter",
    "Monk",
    "Rogue",
    "Warrior",
    "Bard",
    "Ranger",
)


def _looks_like_ability(name: str) -> bool:
    if name.startswith(_ABILITY_PREFIXES):
        return True
    return any(name.startswith(c + "_") for c in _CLASS_NAMES)


def _looks_like_bone(name: str) -> bool:
    return bool(_BONE_RE.match(name)) or name.endswith(_RIG_SUFFIX)


def _first(bdir: Path, glob: str) -> Path | None:
    matches = sorted(bdir.glob(glob))
    return matches[0] if matches else None


def extract_sprites(path: Path, export_dir: Path | None = None) -> list[dict]:
    env, _ = load_unity_env(path)
    rows: list[dict] = []
    seen: set[str] = set()
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        name = getattr(data, "m_Name", "") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        row = {
            "name": name,
            "kind": "ability_ui" if _looks_like_ability(name) else "icon",
            "source": path.name,
        }
        if export_dir is not None and row["kind"] == "icon":
            try:
                img = data.image
                export_dir.mkdir(parents=True, exist_ok=True)
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
                out = export_dir / f"{safe}.png"
                img.save(out)
                row["png"] = out.name
            except Exception as exc:  # noqa: BLE001
                row["export_error"] = str(exc)
        rows.append(row)
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def extract_item_models(path: Path) -> list[dict]:
    env, _ = load_unity_env(path)
    names: set[str] = set()
    for obj in env.objects:
        if obj.type.name != "GameObject":
            continue
        try:
            name = obj.read().m_Name or ""
        except Exception:
            continue
        if not name or _looks_like_bone(name):
            continue
        names.add(name)
    return [{"model": n} for n in sorted(names, key=str.lower)]


_CATEGORY_SUFFIXES = {
    "weapon",
    "food",
    "container",
    "tool",
    "cloth",
    "equipment",
    "material",
    "idol",
    "drink",
    "potion",
    "armor",
    "ammo",
    "misc",
    "key",
    "quest",
}
_WIKI_ITEMS = Path(__file__).resolve().parent.parent / "data" / "items.json"


def _tokens_from_icon(name: str) -> list[str]:
    parts = [p for p in re.split(r"[_\s]+", name.lower()) if p]
    # drop trailing category token(s) and trailing numeric variant tokens
    while parts and (parts[-1] in _CATEGORY_SUFFIXES or parts[-1].isdigit() or len(parts[-1]) == 1):
        parts.pop()
    return parts


def _wiki_token_index() -> list[tuple[set[str], str]]:
    if not _WIKI_ITEMS.is_file():
        return []
    items = json.loads(_WIKI_ITEMS.read_text(encoding="utf-8"))
    idx: list[tuple[set[str], str]] = []
    for it in items:
        title = it.get("title") or it.get("name")
        if not title:
            continue
        toks = {t for t in re.split(r"[^a-z0-9]+", title.lower()) if len(t) > 2}
        if toks:
            idx.append((toks, title))
    return idx


def crosswalk_icons_to_wiki(icons: list[dict]) -> list[dict]:
    """Fuzzy, token-based match of client icon keys to wiki item titles.

    Inherently approximate and many-to-many (multiple items reuse one icon).
    """
    wiki = _wiki_token_index()
    out: list[dict] = []
    for ic in icons:
        toks = set(_tokens_from_icon(ic["name"]))
        if not toks:
            continue
        matches: list[tuple[float, str]] = []
        for wtoks, title in wiki:
            common = toks & wtoks
            if not common:
                continue
            score = len(common) / len(toks | wtoks)
            if score >= 0.5:
                matches.append((round(score, 3), title))
        matches.sort(reverse=True)
        if matches:
            out.append(
                {
                    "icon": ic["name"],
                    "tokens": sorted(toks),
                    "wiki_matches": [{"title": t, "score": s} for s, t in matches[:5]],
                }
            )
    return out


def build_item_assets(root: Path | None = None, export_icons: bool = False) -> dict:
    root = install_root(root)
    bdir = bundles_dir(root)
    icon_dir = (
        (Path(__file__).resolve().parent.parent / "data" / "client" / "icons")
        if export_icons
        else None
    )

    sprites: list[dict] = []
    for glob in (
        "defaultlocalgroup_*.bundle",
        "globalstructures_*.bundle",
        "contentupdate_*.bundle",
    ):
        p = _first(bdir, glob)
        if p:
            sprites.extend(extract_sprites(p, icon_dir))

    models: list[dict] = []
    gi = _first(bdir, "globalitems_*.bundle")
    if gi:
        models = extract_item_models(gi)

    icons = [s for s in sprites if s["kind"] == "icon"]
    abilities = [s for s in sprites if s["kind"] == "ability_ui"]
    wiki_crosswalk = crosswalk_icons_to_wiki(icons)
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "install_root": str(root),
        "counts": {
            "icon_sprites": len(icons),
            "ability_sprites": len(abilities),
            "item_models": len(models),
            "icons_matched_to_wiki": len(wiki_crosswalk),
        },
        "icons": icons,
        "ability_sprites": abilities,
        "item_models": models,
        "wiki_crosswalk": wiki_crosswalk,
        "notes": [
            "Item/monster STAT data is not shipped on disk (server-driven; use the ledger).",
            "Icons are UI sprites; names resemble internal item keys.",
            "Item models are equipment meshes from globalitems (rig/bone nodes filtered out).",
            "wiki_crosswalk is fuzzy token matching (many-to-many); treat scores as hints.",
        ],
    }


def write_item_assets(out: Path, root: Path | None = None, export_icons: bool = False) -> dict:
    doc = build_item_assets(root, export_icons)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
