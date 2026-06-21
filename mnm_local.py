"""Shared helpers for mining Monsters & Memories client-side logs."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).parent
REGISTRY_PATH = ROOT / "data" / "zone_canonical.json"

_DEFAULT_LOCALLOW = (
    Path(os.environ.get("LOCALAPPDATA", "")).parent
    / "LocalLow"
    / "Niche Worlds Cult"
    / "Monsters and Memories"
)


def default_locallow() -> Path:
    override = os.environ.get("MNM_LOCALLOW")
    if override:
        return Path(override)
    return _DEFAULT_LOCALLOW


def ledger_zone_keys() -> dict[str, str]:
    reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    keys = reg.get("ledger_keys", {})
    return {k.casefold(): v for k, v in keys.items()}


def decode_b64_text(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return base64.b64decode(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        try:
            return base64.b64decode(raw).decode("latin-1")
        except (ValueError, UnicodeDecodeError):
            return None


def decode_name_token(token: str) -> str | None:
    """Decode f02 values like ``name_S2F0eQ==`` or plain display names."""
    if not token:
        return None
    if token.startswith("name_"):
        return decode_b64_text(token[5:])
    if token.startswith("ref_"):
        return None
    return token.strip() or None


def parse_ledger_zone(raw: str | None) -> tuple[str | None, str | None]:
    """Return (zone_key, canonical_zone_name) from ledger f05."""
    if not raw:
        return None, None
    if not raw.startswith("zone_"):
        return None, None
    key = decode_b64_text(raw[5:])
    if not key:
        return None, None
    keys = ledger_zone_keys()
    canon = keys.get(key, key)
    from mnm_zones import normalize_zone_name

    return key, normalize_zone_name(canon)


def clean_item_name(raw: str | None) -> str | None:
    """Strip the ``<instance_id>|`` prefix the ledger puts on unique item drops."""
    if not raw:
        return None
    text = raw
    if "|" in text:
        head, _, tail = text.partition("|")
        if head.strip().lstrip("-").isdigit():
            text = tail
    return text.strip() or None


def parse_event_payload(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def decode_hid(raw: str | None) -> str | None:
    """Decode mob/item internal ids (plain or base64)."""
    if not raw:
        return None
    if re.fullmatch(r"[\w_]+", raw):
        return raw
    return decode_b64_text(raw) or raw


def coins_to_copper(pp: int, gp: int, sp: int, cp: int) -> int:
    """Convert coin tiers to total copper. 100 per tier: 100c=1s, 100s=1g, 100g=1p."""
    return (pp * 1_000_000) + (gp * 10_000) + (sp * 100) + cp


def parse_currency_field(raw: str | None) -> dict[str, int] | None:
    """Parse ``MCwwLDAsMjI=`` -> pp/gp/sp/cp or human vendor price strings."""
    if not raw:
        return None
    text = decode_b64_text(raw) or raw
    if "," in text and all(p.strip().lstrip("-").isdigit() for p in text.split(",")):
        pp, gp, sp, cp = (int(x) for x in text.split(",", 3))
        return {"pp": pp, "gp": gp, "sp": sp, "cp": cp, "copper_total": coins_to_copper(pp, gp, sp, cp)}
    m = re.search(
        r"(-?\d+)\s*platinum.*?(-?\d+)\s*gold.*?(-?\d+)\s*silver.*?(-?\d+)\s*copper",
        text,
        re.IGNORECASE,
    )
    if m:
        pp, gp, sp, cp = (int(x) for x in m.groups())
        return {"pp": pp, "gp": gp, "sp": sp, "cp": cp, "copper_total": coins_to_copper(pp, gp, sp, cp), "label": text}
    return {"label": text}


def day_from_ts(ts: str | None) -> str | None:
    if not ts:
        return None
    return ts[:10] if len(ts) >= 10 else None


def iter_ledger_files(locallow: Path) -> list[Path]:
    """Daily Character/Social ledgers plus rolled Archive snapshots."""
    patterns = (
        "Ledger/*_Character_*.json",
        "Ledger/*_Social_*.json",
        "Ledger/Archive/*.json",
    )
    seen: set[Path] = set()
    out: list[Path] = []
    for pat in patterns:
        for path in sorted(locallow.rglob(pat)):
            if path.is_file() and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def ledger_file_kind(path: Path) -> str:
    name = path.name.lower()
    if "archive" in path.parts:
        return "archive"
    if "_social_" in name:
        return "social"
    return "character"


def character_context(path: Path, locallow: Path) -> dict[str, str]:
    """Infer server + character from ``.../<server>/<char>/Ledger/file.json``."""
    rel = path.relative_to(locallow)
    parts = rel.parts
    server = parts[0] if len(parts) > 2 else ""
    character = parts[1] if len(parts) > 2 else ""
    return {"server": server, "character": character, "rel": str(rel)}


JOURNAL_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}): (.+?) says (.+)$"
)
