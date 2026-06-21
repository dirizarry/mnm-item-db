"""Zone name normalization for M&M wiki extraction."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mnm_wiki import strip_markup, wiki_links

ROOT = Path(__file__).parent
REGISTRY_PATH = ROOT / "data" / "zone_canonical.json"

_REGISTRY: dict | None = None


def _load_registry() -> dict:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return _REGISTRY


def canonical_zones() -> set[str]:
    return set(_load_registry()["canonical"])


def zone_aliases() -> dict[str, str]:
    reg = _load_registry()
    out = dict(reg.get("aliases", {}))
    for name in reg["canonical"]:
        out.setdefault(name, name)
    return out


def non_zone_terms() -> set[str]:
    reg = _load_registry()
    terms = set(reg.get("non_zones", []))
    terms |= {z.casefold() for z in terms}
    return terms


def _alias_lookup() -> dict[str, str]:
    aliases = zone_aliases()
    lookup: dict[str, str] = {}
    for raw, canon in aliases.items():
        lookup[raw] = canon
        lookup[raw.casefold()] = canon
    for name in canonical_zones():
        lookup[name.casefold()] = name
    return lookup


def normalize_zone_name(name: str | None) -> str | None:
    """Return a canonical zone name, or None if empty."""
    if not name:
        return None
    s = strip_markup(name).replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    if s.casefold() == "unknown":
        return "Unknown"
    ledger = ledger_zone_keys()
    if s.casefold() in ledger:
        s = ledger[s.casefold()]
    lookup = _alias_lookup()
    return lookup.get(s) or lookup.get(s.casefold()) or s


def _split_zone_parts(raw: str) -> list[str]:
    s = strip_markup(raw)
    parts: list[str] = []
    for chunk in re.split(r"\s*/\s*", s):
        for part in chunk.split(","):
            part = part.strip()
            if part:
                parts.append(part)
    return parts or [s] if s else []


def parse_zone_field(raw: str | None) -> list[str]:
    """Parse a wiki zone field (possibly multi-zone) into normalized names."""
    if not raw or not strip_markup(raw):
        return []
    out: list[str] = []
    for part in _split_zone_parts(raw):
        links = wiki_links(part) if "[[" in part else [part]
        for link in links:
            nz = normalize_zone_name(link)
            if nz and nz not in out:
                out.append(nz)
    return out


def is_known_zone(name: str) -> bool:
    nz = normalize_zone_name(name)
    return nz is not None and nz in canonical_zones()


def _looks_like_mob(name: str) -> bool:
    s = strip_markup(name).strip()
    if re.match(r"^(a|an)\s+", s, re.IGNORECASE):
        return True
    if name.startswith("File:"):
        return True
    return False


def sanitize_item_drops(
    zones: list[str],
    mobs: list[str],
    mob_canon: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Move misclassified mob names out of drops_zones; normalize survivors."""
    mob_canon = mob_canon or {}
    canon = canonical_zones()
    non_terms = non_zone_terms()
    out_zones: list[str] = []
    out_mobs = list(mobs)

    def add_mob(name: str) -> None:
        resolved = mob_canon.get(name.strip().casefold(), name.strip())
        if resolved not in out_mobs:
            out_mobs.append(resolved)

    for raw in zones:
        if not raw or raw.startswith("File:"):
            continue
        if raw.casefold() in non_terms or raw in non_terms:
            continue
        nz = normalize_zone_name(raw)
        if not nz:
            continue
        if nz in canon:
            if nz not in out_zones:
                out_zones.append(nz)
            continue
        if mob_canon.get(raw.strip().casefold()) or _looks_like_mob(raw):
            add_mob(raw)
            continue
        if raw.strip().casefold() in mob_canon:
            add_mob(raw)
            continue
        # Named NPC / quest giver misfiled as zone — route to mobs.
        add_mob(raw)

    return out_zones, out_mobs


def normalize_mob_record(mob: dict) -> dict:
    """Set zones[] and primary zone from raw zone / zones fields."""
    raw = mob.get("zone")
    existing = mob.get("zones")
    if existing and isinstance(existing, list):
        zones = []
        for z in existing:
            nz = normalize_zone_name(z)
            if nz and nz not in zones:
                zones.append(nz)
    elif raw:
        zones = parse_zone_field(raw)
    else:
        zones = []

    mob["zones"] = zones
    mob["zone"] = zones[0] if zones else None
    return mob


def normalize_item_drops(rec: dict, mob_canon: dict[str, str] | None = None) -> dict:
    zones = rec.get("drops_zones") or []
    mobs = rec.get("drops_mobs") or []
    if zones or mobs:
        rec["drops_zones"], rec["drops_mobs"] = sanitize_item_drops(zones, mobs, mob_canon)
    return rec


def load_mob_canon(path: Path | None = None) -> dict[str, str]:
    path = path or ROOT / "data" / "monsters.json"
    if not path.is_file():
        return {}
    mobs = json.loads(path.read_text(encoding="utf-8"))
    canon: dict[str, str] = {}
    for m in mobs:
        t = m.get("title") or m.get("name") or ""
        if t:
            canon[t.strip().casefold()] = t
        if m.get("name"):
            canon.setdefault(m["name"].strip().casefold(), t or m["name"])
    return canon


def format_zone_param(zones: list[str]) -> str:
    if not zones:
        return ""
    if len(zones) == 1:
        return zones[0]
    return ", ".join(zones)


def mob_needs_zone_fix(raw_zone: str | None, zones: list[str]) -> bool:
    if not raw_zone or not zones:
        return False
    if "[[" in raw_zone or "_" in raw_zone:
        return True
    if " / " in raw_zone:
        return True
    expected = format_zone_param(zones)
    return strip_markup(raw_zone) != expected


def mob_zone_entries(mob: dict) -> list[str]:
    """All normalized zones for indexing (prefers zones[], falls back to zone)."""
    zones = mob.get("zones")
    if zones:
        return [z for z in zones if z]
    z = mob.get("zone")
    return parse_zone_field(z) if z else []


def ledger_zone_keys() -> dict[str, str]:
    reg = _load_registry()
    keys = reg.get("ledger_keys", {})
    return {k.casefold(): v for k, v in keys.items()}


def discover_alias_candidates(mobs: list[dict]) -> dict[str, str]:
    """Map raw mob zone strings to canonical names for registry updates."""
    candidates: dict[str, str] = {}
    for m in mobs:
        raw = m.get("zone")
        if not raw:
            continue
        norm = parse_zone_field(raw)
        if not norm:
            continue
        primary = norm[0]
        plain = raw.strip()
        if plain == primary:
            continue
        if parse_zone_field(plain) == norm:
            candidates.setdefault(plain, primary)
    return candidates


def persist_normalized_data(
    items_path: Path,
    mobs_path: Path,
    *,
    backup: bool = False,
) -> tuple[list[dict], list[dict], dict]:
    """Normalize monsters + items and write back to JSON."""
    import shutil
    from datetime import date

    items = json.loads(items_path.read_text(encoding="utf-8"))
    mobs = json.loads(mobs_path.read_text(encoding="utf-8"))
    mob_canon = load_mob_canon(mobs_path)

    item_queue: list[str] = []
    for it in items:
        z0 = list(it.get("drops_zones") or [])
        m0 = list(it.get("drops_mobs") or [])
        z1, m1 = sanitize_item_drops(z0, m0, mob_canon)
        if z0 != z1 or m0 != m1:
            item_queue.append(it["title"])

    mob_queue: list[dict] = []
    for m in mobs:
        raw = m.get("zone")
        zones = parse_zone_field(raw)
        if mob_needs_zone_fix(raw, zones):
            mob_queue.append({"title": m["title"], "zones": zones})

    for m in mobs:
        normalize_mob_record(m)
    for it in items:
        normalize_item_drops(it, mob_canon)

    queue_path = items_path.parent / "zones-wiki-queue.json"
    queue_path.write_text(
        json.dumps({"items": item_queue, "mobs": mob_queue}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    audit = write_zone_audit(mobs, items, items_path.parent / "zones-audit.txt")

    if backup:
        today = date.today().isoformat()
        for path, rows in ((items_path, items), (mobs_path, mobs)):
            if path.is_file():
                bak = path.with_suffix(f"{path.suffix}.bak-{today}")
                shutil.copy2(path, bak)
    items_path.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mobs_path.write_text(json.dumps(mobs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return items, mobs, audit


def write_zone_audit(
    mobs: list[dict],
    items: list[dict],
    path: Path,
) -> dict:
    """Write human-readable audit; return summary stats."""
    canon = canonical_zones()
    mob_zone_raw: dict[str, list[str]] = {}
    for m in mobs:
        raw = m.get("_zone_raw") or m.get("zone")
        if raw and parse_zone_field(raw) != mob_zone_entries(m):
            mob_zone_raw[m["title"]] = [raw, mob_zone_entries(m)]

    item_mob_as_zone: list[tuple[str, str]] = []
    unknown_zones = 0
    for it in items:
        for z in it.get("drops_zones") or []:
            if z == "Unknown":
                unknown_zones += 1
            elif z not in canon:
                item_mob_as_zone.append((it["title"], z))

    zone_counts: dict[str, int] = {}
    for m in mobs:
        for z in mob_zone_entries(m):
            zone_counts[z] = zone_counts.get(z, 0) + 1

    lines = [
        "Zone normalization audit",
        f"Canonical zones: {len(canon)}",
        f"Zones with mobs: {len(zone_counts)}",
        f"Mobs indexed: {sum(zone_counts.values())}",
        f"Item drops with Unknown zone: {unknown_zones}",
        f"Item drops_zones not in canonical: {len(item_mob_as_zone)}",
        "",
        "=== Mob counts by zone ===",
    ]
    for z, n in sorted(zone_counts.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"  {n:4}  {z}")

    if item_mob_as_zone:
        lines += ["", "=== drops_zones still not canonical (review) ==="]
        for title, z in sorted(set(item_mob_as_zone))[:50]:
            lines.append(f"  {z!r}  ({title})")
        if len(set(item_mob_as_zone)) > 50:
            lines.append(f"  ... and {len(set(item_mob_as_zone)) - 50} more")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "canonical": len(canon),
        "zones_with_mobs": len(zone_counts),
        "unknown_item_drops": unknown_zones,
        "noncanonical_item_zones": len(set(item_mob_as_zone)),
    }
