"""Dump IL2CPP-related blobs from a running mnm.exe process."""

from __future__ import annotations

import json
import struct
from datetime import datetime, timezone
from pathlib import Path

from client_re.paths import DUMPS_DIR, ensure_dumps, il2cpp_metadata
from client_re.process_io import (
    PROCESS_NAME,
    close_process,
    find_process,
    iter_regions,
    open_process,
    read_memory,
)

IL2CPP_MAGIC = 0xFAB11BAF

PRIORITY_TYPES = (
    "ClientItemRecord",
    "ItemRecord",
    "ItemInformation",
    "GlobalItemModelDataList",
    "ItemModelData",
    "ItemModelConfiguration",
    "LootTable",
    "RecipeRecord",
    "RecipeComponent",
    "ZoneRecord",
    "ZoneInfo",
    "Consider",
)


def find_il2cpp_magic(handle) -> list[dict]:
    magic = struct.pack("<I", IL2CPP_MAGIC)
    hits: list[dict] = []
    for base, size, protect, _typ in iter_regions(handle):
        if size > 80_000_000:
            continue
        data = read_memory(handle, base, size)
        if not data:
            continue
        off = 0
        while True:
            idx = data.find(magic, off)
            if idx < 0:
                break
            hits.append(
                {
                    "address": base + idx,
                    "region_base": base,
                    "region_size": size,
                    "protect": protect,
                }
            )
            off = idx + 4
            if len(hits) >= 10:
                return hits
    return hits


def find_metadata_blob(handle, expected_size: int) -> list[dict]:
    """Unity 6000 may keep an encrypted metadata mirror (~same size as on-disk file)."""
    lo = int(expected_size * 0.98)
    hi = int(expected_size * 1.02)
    hits: list[dict] = []
    for base, size, protect, _typ in iter_regions(handle):
        if not (lo <= size <= hi):
            continue
        head = read_memory(handle, base, 64)
        if not head:
            continue
        magic = struct.unpack_from("<I", head, 0)[0]
        hits.append(
            {
                "address": base,
                "size": size,
                "magic_hex": f"{magic:08x}",
                "head_hex": head[:16].hex(),
                "protect": protect,
                "il2cpp_magic": magic == IL2CPP_MAGIC,
            }
        )
    return hits


def count_type_strings(handle) -> dict[str, int]:
    needles = [t.encode("ascii") for t in PRIORITY_TYPES]
    counts = dict.fromkeys(PRIORITY_TYPES, 0)
    for base, size, _protect, _typ in iter_regions(handle):
        if size > 50_000_000:
            continue
        data = read_memory(handle, base, size)
        if not data:
            continue
        for name, needle in zip(PRIORITY_TYPES, needles, strict=False):
            counts[name] += data.count(needle)
    return counts


def dump_at_address(pid: int, address: int, size: int, out: Path) -> Path:
    handle = open_process(pid)
    try:
        data = read_memory(handle, address, size)
        if not data or len(data) < 64:
            raise OSError(f"ReadProcessMemory failed at {address:#x}")
        out.write_bytes(data)
    finally:
        close_process(handle)
    return out


def dump_metadata(
    out: Path | None = None,
    pid: int | None = None,
    size: int | None = None,
) -> dict:
    ensure_dumps()
    enc_path = il2cpp_metadata()
    expected_size = size or (enc_path.stat().st_size if enc_path.is_file() else 20_400_000)
    on_disk_head = enc_path.read_bytes()[:16].hex() if enc_path.is_file() else None

    if pid is None:
        pid = find_process()

    result: dict = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "pid": pid,
        "encrypted_size": expected_size,
        "on_disk_head": on_disk_head,
        "ran": False,
        "error": None,
    }
    if pid is None:
        result["error"] = f"{PROCESS_NAME} is not running."
        return result

    handle = open_process(pid)
    try:
        magic_hits = find_il2cpp_magic(handle)
        blob_hits = find_metadata_blob(handle, expected_size)
        type_counts = count_type_strings(handle)
        result["il2cpp_magic_hits"] = magic_hits
        result["metadata_blob_hits"] = blob_hits
        result["runtime_type_string_counts"] = type_counts
    finally:
        close_process(handle)

    if magic_hits:
        hit = magic_hits[0]
        out = out or (DUMPS_DIR / "il2cpp" / "global-metadata.decrypted.dat")
        out.parent.mkdir(parents=True, exist_ok=True)
        dump_at_address(pid, hit["address"], expected_size, out)
        result["ran"] = True
        result["output"] = str(out)
        result["address"] = hit["address"]
        result["magic_ok"] = True
        result["source"] = "il2cpp_magic"
        return result

    if blob_hits:
        hit = blob_hits[0]
        out = out or (DUMPS_DIR / "il2cpp" / "global-metadata.from-memory.dat")
        out.parent.mkdir(parents=True, exist_ok=True)
        dump_at_address(pid, hit["address"], hit["size"], out)
        result["ran"] = True
        result["output"] = str(out)
        result["address"] = hit["address"]
        result["magic_ok"] = False
        result["source"] = "encrypted_mirror"
        result["note"] = (
            "Metadata mirror found in memory but header is NOT 0xFAB11BAF — "
            "still encrypted/obfuscated (Unity 6000)."
        )
        from client_re.decrypt_metadata import decrypt_metadata_file

        decrypt_report = decrypt_metadata_file(src=out, allow_partial=True)
        result["decrypt"] = decrypt_report
        if decrypt_report.get("success"):
            result["magic_ok"] = True
            result["output"] = decrypt_report["output"]
            result["note"] = "Decrypted metadata written from memory mirror."
        elif decrypt_report.get("partial"):
            result["output"] = decrypt_report["output"]
            result["note"] = decrypt_report.get("warning", result["note"])
        return result

    result["error"] = "No IL2CPP metadata magic or size-matched metadata blob in process memory."
    return result


def write_dump_report(out: Path) -> dict:
    doc = dump_metadata()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
