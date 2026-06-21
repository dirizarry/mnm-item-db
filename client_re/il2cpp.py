"""IL2CPP dump helpers and symbol extraction from global-metadata.dat."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from client_re.paths import DUMPS_DIR, ensure_dumps, game_assembly, il2cpp_metadata, install_root

COMBAT_PRIORITY_TYPES = (
    "ChatLibrary",
    "ChatMessage",
    "ChatMessageData",
    "ChatMessageEntry",
    "ChatMessageMudView",
    "PersistedMessageData",
    "MudChatHandler",
    "LogMessages",
    "Consider",
    "BuffCommandQueueItem",
)

PRIORITY_TYPES = (
    "ClientItemRecord",
    "ItemRecord",
    "ItemInformation",
    "ItemInformationRequest",
    "ItemInformationRequestResult",
    "GlobalItemModelDataList",
    "ItemModelData",
    "ItemModelConfiguration",
    "LootTable",
    "RecipeRecord",
    "RecipeComponent",
    "ZoneRecord",
    "ZoneInfo",
    "Consider",
    "NpcHID",
    "NpcHid",
    "NpcCommandPacket",
)


def metadata_header_valid(meta_path: Path) -> bool:
    """True when global-metadata.dat has a parseable IL2CPP v39 header."""
    import struct

    from client_re.decrypt_metadata import _quick_validate_v39_header

    data = meta_path.read_bytes()[:512]
    if len(data) < 380:
        return False
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == 0xFAB11BAF:
        return _quick_validate_v39_header(data)
    return False


def _dumper_exe() -> Path | None:
    env = os.environ.get("MNM_IL2CPP_DUMPER")
    if env:
        p = Path(env)
        return p if p.is_file() else None
    for candidate in (
        DUMPS_DIR / "c01ns" / "Il2CppDumper.exe",
        DUMPS_DIR
        / "Il2CppDumper-src"
        / "Il2CppDumper"
        / "bin"
        / "Release"
        / "net8.0"
        / "Il2CppDumper.exe",
        DUMPS_DIR / "Il2CppDumper" / "Il2CppDumper.exe",
        Path("Il2CppDumper.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


def _dumper_cwd(exe: Path) -> Path:
    return exe.parent


def _metadata_for_dump(root: Path | None = None) -> Path:
    """Prefer decrypted dump; fall back to on-disk file."""
    dec = ensure_dumps() / "il2cpp" / "global-metadata.decrypted.dat"
    if dec.is_file() and dec.stat().st_size > 1024:
        head = dec.read_bytes()[:8]
        if head[:4] == b"\xaf\x1b\xb1\xfa":
            return dec
    for name in ("global-metadata.from-memory.dat",):
        p = ensure_dumps() / "il2cpp" / name
        if p.is_file() and p.stat().st_size > 1024:
            return p
    return il2cpp_metadata(root)


def extract_metadata_symbols(meta_path: Path | None = None) -> dict:
    meta_path = meta_path or il2cpp_metadata()
    data = meta_path.read_bytes()
    # C#-ish identifiers from metadata string heap
    names = {
        m.group().decode("ascii", "ignore")
        for m in re.finditer(rb"[A-Za-z_][A-Za-z0-9_]{4,80}", data)
    }
    priority = sorted(n for n in PRIORITY_TYPES if n in names)
    item_related = sorted(
        n
        for n in names
        if any(
            k in n
            for k in (
                "Item",
                "Loot",
                "Recipe",
                "Npc",
                "Mob",
                "Zone",
                "Consider",
                "Spawn",
                "Chat",
                "Combat",
                "Message",
            )
        )
        and n[0].isupper()
    )
    combat_hits = sorted(n for n in COMBAT_PRIORITY_TYPES if n in names)
    return {
        "metadata_path": str(meta_path),
        "metadata_size": meta_path.stat().st_size,
        "metadata_header_valid": metadata_header_valid(meta_path),
        "priority_hits": priority,
        "combat_priority_hits": combat_hits,
        "related_symbols": item_related[:200],
        "related_symbol_count": len(item_related),
    }


def run_il2cpp_dumper(root: Path | None = None, out_dir: Path | None = None) -> dict:
    root = install_root(root)
    out_dir = out_dir or (ensure_dumps() / "il2cpp")
    out_dir.mkdir(parents=True, exist_ok=True)
    exe = _dumper_exe()
    ga = game_assembly(root)
    meta = _metadata_for_dump(root)

    result: dict = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "dumper": str(exe) if exe else None,
        "metadata": str(meta),
        "metadata_decrypted": meta.name.endswith(".decrypted.dat"),
        "metadata_header_valid": metadata_header_valid(meta),
        "output_dir": str(out_dir),
        "ran": False,
        "error": None,
    }

    if not result["metadata_header_valid"]:
        result["error"] = (
            "global-metadata.dat header is still encrypted/obfuscated — Il2CppDumper requires "
            "a valid v39 header. Run Ghidra trace (see client_re/METADATA-CRYPTO.md) or "
            "python mnm_client_db.py --dump-metadata with mnm.exe running."
        )
        return result

    if not exe:
        result["error"] = (
            "Il2CppDumper not found. Download from "
            "https://github.com/Perfare/Il2CppDumper and set MNM_IL2CPP_DUMPER "
            "to Il2CppDumper.exe, or place it in client_re/dumps/Il2CppDumper/"
        )
        return result

    dump_cs = out_dir / "dump.cs"
    if dump_cs.is_file() and not os.environ.get("MNM_IL2CPP_FORCE"):
        result["skipped"] = True
        result["dump_cs"] = str(dump_cs)
        return result

    try:
        proc = subprocess.run(
            [str(exe), str(ga), str(meta), str(out_dir)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            cwd=str(_dumper_cwd(exe)),
        )
        result["ran"] = True
        result["returncode"] = proc.returncode
        result["stdout"] = proc.stdout[-4000:] if proc.stdout else ""
        result["stderr"] = proc.stderr[-4000:] if proc.stderr else ""
        if proc.returncode != 0:
            result["error"] = f"Il2CppDumper exited {proc.returncode}"
    except subprocess.TimeoutExpired:
        result["error"] = "Il2CppDumper timed out after 300s"
    except OSError as exc:
        result["error"] = str(exc)

    if (out_dir / "dump.cs").is_file():
        result["dump_cs"] = str(out_dir / "dump.cs")
    return result


def parse_dump_cs(dump_path: Path) -> list[dict]:
    if not dump_path.is_file():
        return []
    text = dump_path.read_text(encoding="utf-8", errors="replace")
    blocks: list[dict] = []
    for type_name in PRIORITY_TYPES:
        pat = re.compile(
            rf"(public (?:class|struct|enum) {re.escape(type_name)}\b.*?)(?=^public |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        m = pat.search(text)
        if m:
            body = m.group(1).strip()
            blocks.append(
                {
                    "type": type_name,
                    "lines": len(body.splitlines()),
                    "preview": "\n".join(body.splitlines()[:40]),
                }
            )
    return blocks


def il2cpp_report(root: Path | None = None, try_memory_dump: bool = True) -> dict:
    root = install_root(root)
    out_dir = ensure_dumps() / "il2cpp"
    symbols = extract_metadata_symbols()
    memory_dump: dict | None = None
    if try_memory_dump:
        from client_re.dump_metadata import dump_metadata

        memory_dump = dump_metadata()
    dump_result = run_il2cpp_dumper(root, out_dir)
    types: list[dict] = []
    dump_cs = out_dir / "dump.cs"
    if dump_cs.is_file():
        types = parse_dump_cs(dump_cs)
    from client_re.mnmlib.types import generate_types_catalog

    mnmlib = generate_types_catalog(dump_path=dump_cs if dump_cs.is_file() else None)
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "install_root": str(root),
        "symbols": symbols,
        "memory_dump": memory_dump,
        "dumper": dump_result,
        "parsed_types": types,
        "mnmlib_types": {
            "path": str(mnmlib.get("metadata", {}).get("metadata_path", "")),
            "combat_type_count": mnmlib["metadata"]["combat_type_count"],
            "priority_hits": mnmlib["metadata"]["priority_hits"],
            "dump_cs_available": mnmlib["dump_cs_available"],
        },
    }


def write_il2cpp_report(out: Path, root: Path | None = None) -> dict:
    doc = il2cpp_report(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
