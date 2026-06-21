"""Generate mnmlib type catalog from IL2CPP metadata / dump.cs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from client_re.paths import ensure_dumps, il2cpp_metadata

MNMLIB_DIR = Path(__file__).resolve().parent
TYPES_PATH = MNMLIB_DIR / "types.json"

COMBAT_TYPE_KEYWORDS = (
    "Chat",
    "Combat",
    "Message",
    "AbilityHit",
    "AbilityMiss",
    "Damage",
    "Heal",
    "Buff",
    "Consider",
    "Spawn",
    "Log",
    "Channel",
    "MudView",
    "PersistedMessage",
)

PRIORITY_COMBAT_TYPES = (
    "ChatLibrary",
    "ChatMessage",
    "ChatMessageData",
    "ChatMessageEntry",
    "ChatMessageMudView",
    "ChatMessagePersistence",
    "PersistedMessageData",
    "ChatMessageWithTarget",
    "ChatMessageControls",
    "ChatMessageFading",
    "LogMessages",
    "ChatFilterDescriptions",
    "ChatFiltersSettingsSection",
    "MudChatHandler",
    "Consider",
    "BuffCommandQueueItem",
    "CmdDamageLogs",
    "CmdCombatReport",
)


def combat_type_keywords() -> tuple[str, ...]:
    return COMBAT_TYPE_KEYWORDS


def types_catalog_path() -> Path:
    return TYPES_PATH


def _extract_metadata_identifiers(data: bytes) -> set[str]:
    return {
        m.group().decode("ascii", "ignore")
        for m in re.finditer(rb"[A-Za-z_][A-Za-z0-9_]{4,80}", data)
    }


def _classify_type(name: str) -> list[str]:
    tags: list[str] = []
    for kw in COMBAT_TYPE_KEYWORDS:
        if kw in name:
            tags.append(kw.lower())
    if name in PRIORITY_COMBAT_TYPES:
        tags.append("priority")
    return sorted(set(tags))


def scan_metadata_types(meta_path: Path | None = None) -> dict:
    meta_path = meta_path or il2cpp_metadata()
    data = meta_path.read_bytes()
    names = _extract_metadata_identifiers(data)
    combat_types = sorted(
        n for n in names if any(kw in n for kw in COMBAT_TYPE_KEYWORDS) and n[0].isupper()
    )
    priority = [n for n in PRIORITY_COMBAT_TYPES if n in names]
    return {
        "metadata_path": str(meta_path),
        "metadata_size": len(data),
        "combat_type_count": len(combat_types),
        "priority_hits": priority,
        "combat_types": [{"name": n, "tags": _classify_type(n)} for n in combat_types],
    }


def scan_dump_cs_types(dump_path: Path | None = None) -> list[dict]:
    dump_path = dump_path or (ensure_dumps() / "il2cpp" / "dump.cs")
    if not dump_path.is_file():
        return []
    text = dump_path.read_text(encoding="utf-8", errors="replace")
    found: list[dict] = []
    for type_name in PRIORITY_COMBAT_TYPES:
        pat = re.compile(
            rf"public (?:class|struct|enum) {re.escape(type_name)}\b.*?",
            re.MULTILINE,
        )
        if pat.search(text):
            found.append({"name": type_name, "source": "dump.cs"})
    # Broader combat-related classes
    for m in re.finditer(
        r"public (?:class|struct|enum) ([A-Za-z_][A-Za-z0-9_]*(?:Chat|Combat|Message)[A-Za-z0-9_]*)\b",
        text,
    ):
        name = m.group(1)
        if name not in {t["name"] for t in found}:
            found.append({"name": name, "source": "dump.cs"})
    return found


def generate_types_catalog(
    *,
    meta_path: Path | None = None,
    dump_path: Path | None = None,
    out: Path | None = None,
) -> dict:
    out = out or TYPES_PATH
    meta = scan_metadata_types(meta_path)
    dump_types = scan_dump_cs_types(dump_path)
    doc = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "metadata": meta,
        "dump_cs_types": dump_types,
        "dump_cs_available": bool(dump_types),
        "notes": (
            "Combat channel ids (CombatHitMine, …) live in per-character chats.json, "
            "not as plaintext in GameAssembly.dll. Chat pipeline types are in metadata "
            "string heap; full field layouts require Il2CppDumper + Ghidra."
        ),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def load_types_catalog(path: Path | None = None) -> dict:
    path = path or TYPES_PATH
    if not path.is_file():
        return generate_types_catalog(out=path)
    return json.loads(path.read_text(encoding="utf-8"))
