"""Runtime discovery of combat message memory layout from live mnm.exe memory."""

from __future__ import annotations

import json
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from client_re.combat_memory import scan_region_for_combat_lines
from client_re.combat_regions import discover_regions, save_region_cache
from client_re.combat_validate import is_valid_memory_combat_line, normalize_memory_line
from client_re.mnmlib.combat_struct import STRUCT_PATH, load_struct_config, struct_enabled
from client_re.process_io import (
    MEM_PRIVATE,
    close_process,
    find_process,
    iter_regions,
    open_process,
    read_i32,
    read_memory,
    read_ptr,
    read_utf8_string,
)

LIST_LAYOUTS = (
    (0x10, 0x18, 0x20),  # standard IL2CPP List + Array
    (0x18, 0x20, 0x20),
    (0x10, 0x1C, 0x20),
)

TEXT_OFFSETS = (0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40, 0x48)
CAPACITY_OFFSETS = (0x10, 0x18, 0x20, 0x28, 0x30, 0x32, 0x38)


def _decode_entry_text(handle, entry_ptr: int, text_offset: int) -> str | None:
    sp = read_ptr(handle, entry_ptr + text_offset)
    if not sp:
        return None
    text = read_utf8_string(handle, sp)
    if text:
        text = normalize_memory_line(text)
        if is_valid_memory_combat_line(text):
            return text
    return None


def _read_list_entries_layout(
    handle,
    list_ptr: int,
    text_offset: int,
    items_off: int,
    size_off: int,
    array_data_off: int,
    max_items: int = 256,
) -> list[str]:
    items_arr = read_ptr(handle, list_ptr + items_off)
    size = read_i32(handle, list_ptr + size_off) or 0
    if not items_arr or size <= 0:
        return []
    size = min(size, max_items)
    raw = read_memory(handle, items_arr + array_data_off, size * 8)
    if not raw or len(raw) < size * 8:
        return []
    texts: list[str] = []
    for ep in struct.unpack_from(f"<{size}Q", raw, 0):
        if not ep:
            continue
        t = _decode_entry_text(handle, ep, text_offset)
        if t:
            texts.append(t)
    return texts


def _score_list_at(handle, list_ptr: int) -> tuple[int, int, int, tuple, list[str]] | None:
    best = None
    for items_off, size_off, array_off in LIST_LAYOUTS:
        items_arr = read_ptr(handle, list_ptr + items_off)
        size = read_i32(handle, list_ptr + size_off) or 0
        if not items_arr or not (3 <= size <= 400):
            continue
        for text_off in TEXT_OFFSETS:
            texts = _read_list_entries_layout(
                handle, list_ptr, text_off, items_off, size_off, array_off,
                max_items=min(size, 120),
            )
            if len(texts) >= 3:
                score = len(texts)
                layout = (items_off, size_off, array_off)
                if best is None or score > best[0]:
                    best = (score, text_off, size, layout, texts)
    if not best:
        return None
    score, text_off, size, layout, texts = best
    return score, size, text_off, layout, texts


def _collect_combat_line_addrs(handle, regions: list[dict]) -> list[tuple[int, str]]:
    from client_re.combat_memory import _extract_combat_needles

    lines: list[tuple[int, str]] = []
    seen: set[str] = set()
    for reg in regions:
        data = read_memory(handle, reg["base"], reg["size"])
        if not data:
            continue
        for raw in _extract_combat_needles(data):
            text = normalize_memory_line(raw)
            if not is_valid_memory_combat_line(text) or text in seen:
                continue
            needle = raw.encode("ascii", errors="ignore")
            idx = data.find(needle)
            if idx < 0:
                idx = data.find(text.encode("ascii", errors="ignore"))
            if idx < 0:
                continue
            seen.add(text)
            lines.append((reg["base"] + idx, text))
    return lines


def _count_il2cpp_string_ptrs(handle, regions: list[dict]) -> int:
    from client_re.combat_regions import COMBAT_MARKERS

    string_ptrs: set[int] = set()
    for reg in regions:
        data = read_memory(handle, reg["base"], min(reg["size"], 2_000_000))
        if not data:
            continue
        for marker in COMBAT_MARKERS:
            needle = marker.decode("ascii", errors="ignore").encode("utf-16-le")
            idx = 0
            while True:
                hit = data.find(needle, idx)
                if hit < 0:
                    break
                for delta in (0x14, 0x18, 0x10, 0x1C):
                    sb = reg["base"] + hit - delta
                    text = read_utf8_string(handle, sb)
                    if text and is_valid_memory_combat_line(normalize_memory_line(text)):
                        string_ptrs.add(sb)
                idx = hit + 2
    return len(string_ptrs)


def _diagnose_storage(handle, regions: list[dict]) -> dict:
    lines = _collect_combat_line_addrs(handle, regions)
    il2cpp_strings = _count_il2cpp_string_ptrs(handle, regions)
    storage = "unknown"
    if lines and il2cpp_strings == 0:
        storage = "inline_utf8_buffer"
    elif il2cpp_strings > 0:
        storage = "il2cpp_string"
    you_lines = [text for _, text in lines if text.startswith("You ") or text.startswith("Your ")]
    return {
        "valid_combat_lines": len(lines),
        "your_combat_lines": len(you_lines),
        "il2cpp_string_objects": il2cpp_strings,
        "storage_hint": storage,
        "sample_lines": [text for _, text in lines[:6]],
        "your_recent_lines": you_lines[:6],
        "note": (
            "sample_lines are stale heap strings from the whole session/zone — "
            "not necessarily your current fight. Discovery uses message_blob holders instead."
        ),
    }


def _discover_il2cpp_list(handle, regions: list[dict]) -> dict | None:
    candidates: list[tuple] = []
    for reg in regions:
        base = reg["base"]
        size = reg["size"]
        data = read_memory(handle, base, size)
        if not data:
            continue
        limit = min(len(data), 400_000)
        for off in range(0, limit - 0x20, 8):
            list_ptr = base + off
            scored = _score_list_at(handle, list_ptr)
            if scored:
                candidates.append((*scored, list_ptr))
    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], -x[1]))
    score, list_size, text_off, layout, texts, list_ptr = candidates[0]
    items_off, size_off, array_off = layout

    list_offset = 0x18
    root_ptr = None
    needle = struct.pack("<Q", list_ptr)
    for reg in regions:
        data = read_memory(handle, reg["base"], min(reg["size"], 200_000))
        if not data:
            continue
        idx = 0
        while True:
            hit = data.find(needle, idx)
            if hit < 0:
                break
            idx = hit + 8
            for loff in (0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40):
                root = reg["base"] + hit - loff
                if read_ptr(handle, root + loff) == list_ptr:
                    root_ptr = root
                    list_offset = loff
                    break
            if root_ptr:
                break
        if root_ptr:
            break

    return {
        "success": True,
        "generated": datetime.now(timezone.utc).isoformat(),
        "layout": "il2cpp_list",
        "text_offset": text_off,
        "list_items_offset": items_off,
        "list_size_offset": size_off,
        "array_data_offset": array_off,
        "list_offset": list_offset,
        "list_ptr": list_ptr,
        "root_ptr": root_ptr,
        "list_size": list_size,
        "score": score,
        "sample_texts": texts[:12],
        "confidence": "high" if score >= 8 else "medium",
    }


def _discover_inline_buffer(handle, regions: list[dict]) -> dict | None:
    lines = _collect_combat_line_addrs(handle, regions)
    if len(lines) < 2:
        return None

    pages = Counter(addr & ~0xFFF for addr, _ in lines)
    buffer_base = pages.most_common(1)[0][0]
    page_lines = [(addr, text) for addr, text in lines if (addr & ~0xFFF) == buffer_base]
    if len(page_lines) < 2:
        return None

    needle = struct.pack("<Q", buffer_base)
    best: tuple[int, int, int, int, list[str]] | None = None

    for base, size, _protect, typ in iter_regions(handle):
        if typ != MEM_PRIVATE or size > 8_000_000 or size < 4096:
            continue
        data = read_memory(handle, base, size)
        if not data:
            continue
        idx = 0
        while True:
            hit = data.find(needle, idx)
            if hit < 0:
                break
            idx = hit + 8
            holder = base + hit
            if read_ptr(handle, holder) != buffer_base:
                continue
            for cap_off in CAPACITY_OFFSETS:
                capacity = read_i32(handle, holder + cap_off) or 0
                if not (256 <= capacity <= 65536):
                    continue
                buf_data = read_memory(handle, buffer_base, capacity)
                if not buf_data:
                    continue
                texts = scan_region_for_combat_lines(buf_data)
                if len(texts) < 2:
                    continue
                score = len(texts)
                if best is None or score > best[0]:
                    best = (score, holder, buffer_base, cap_off, texts)

    if not best:
        return None

    score, holder_ptr, buf_ptr, cap_off, texts = best
    return {
        "success": True,
        "generated": datetime.now(timezone.utc).isoformat(),
        "layout": "inline_buffer",
        "holder_ptr": holder_ptr,
        "buffer_ptr": buf_ptr,
        "data_offset": 0,
        "capacity_offset": cap_off,
        "capacity": read_i32(handle, holder_ptr + cap_off),
        "score": score,
        "sample_texts": texts[:12],
        "confidence": "high" if score >= 6 else "medium",
        "note": (
            "MnM stores formatted combat lines in a native UTF-8 buffer, not "
            "IL2CPP List<System.String>. Re-run discover after restarting the game."
        ),
    }


def discover_struct(pid: int | None = None) -> dict:
    pid = pid or find_process()
    if not pid:
        return {"success": False, "error": "mnm.exe is not running"}

    regions = discover_regions(pid)
    save_region_cache(regions)
    if not regions:
        return {
            "success": False,
            "error": "No combat strings in memory — fight in a busy zone, then retry",
            "pid": pid,
        }

    handle = open_process(pid)
    try:
        diag = _diagnose_storage(handle, regions)
        doc = None
        if diag.get("storage_hint") != "inline_utf8_buffer":
            doc = _discover_il2cpp_list(handle, regions)
        if doc is None:
            from client_re.combat_record import discover_message_blob_holder

            blob_doc = discover_message_blob_holder(handle, regions)
            if blob_doc:
                doc = {
                    "success": True,
                    "generated": datetime.now(timezone.utc).isoformat(),
                    **blob_doc,
                    "note": (
                        "Chronological combat records in a native message blob "
                        "(used-length tail). Re-run discover after restarting the game."
                    ),
                }
        if doc is None:
            doc = _discover_inline_buffer(handle, regions)
        if doc is None:
            hint = diag.get("storage_hint")
            if hint == "inline_utf8_buffer" and diag.get("valid_combat_lines", 0) >= 2:
                err = (
                    "Could not locate an active message_blob holder. Fight in your current "
                    "pull (need hits landing in chat), then retry discover. Heap samples like "
                    "old party members are normal stale RAM — they are not used for capture."
                )
            elif diag.get("valid_combat_lines", 0) < 2:
                err = "Too few combat lines in memory — keep fighting, then retry discover."
            else:
                err = (
                    "Combat text found but layout is unknown — metadata decrypt/Ghidra "
                    "is required for IL2CPP List<ChatMessageEntry> discovery."
                )
            return {
                "success": False,
                "error": err,
                "regions_scanned": len(regions),
                "pid": pid,
                "diagnostics": diag,
            }

        doc["pid"] = pid
        doc["regions_scanned"] = len(regions)
        doc["diagnostics"] = diag
        return doc
    finally:
        close_process(handle)


def apply_discovery(doc: dict, path: Path | None = None) -> Path:
    path = path or STRUCT_PATH
    cfg = load_struct_config(path)
    cfg["enabled"] = True
    cfg["layout"] = doc.get("layout", "il2cpp_list")
    cfg["discovered"] = doc.get("generated")
    if doc.get("note"):
        cfg["discovery_note"] = doc["note"]

    if cfg["layout"] == "message_blob":
        cfg["message_blob"] = {
            "holder_ptr_hint": doc["holder_ptr"],
            "blob_ptr_hint": doc.get("blob_ptr"),
            "data_offset": doc.get("data_offset", 0),
            "used_offset": doc.get("used_offset", 4),
            "capacity_offset": doc.get("capacity_offset", 0x20),
            "capacity": doc.get("capacity"),
        }
    elif cfg["layout"] == "inline_buffer":
        cfg["buffer"] = {
            "holder_ptr_hint": doc["holder_ptr"],
            "buffer_ptr_hint": doc.get("buffer_ptr"),
            "data_offset": doc.get("data_offset", 0),
            "capacity_offset": doc.get("capacity_offset", 32),
            "capacity": doc.get("capacity"),
        }
    else:
        cfg["queue"]["list_offset"] = doc.get("list_offset", 0x18)
        cfg["queue"]["list_items_offset"] = doc.get("list_items_offset", 0x10)
        cfg["queue"]["list_size_offset"] = doc.get("list_size_offset", 0x18)
        cfg["queue"]["array_data_offset"] = doc.get("array_data_offset", 0x20)
        cfg["queue"]["list_ptr_hint"] = doc["list_ptr"]
        if doc.get("root_ptr"):
            cfg["queue"]["root_address"] = doc["root_ptr"]
        cfg["entry"]["text_offset"] = doc["text_offset"]
        cfg["entry"]["channel_offset"] = None
        cfg["entry"]["channel_is_string"] = True

    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return path


def discover_and_apply(pid: int | None = None) -> dict:
    doc = discover_struct(pid)
    if doc.get("success"):
        doc["config_path"] = str(apply_discovery(doc))
        doc["structured_enabled"] = struct_enabled(load_struct_config())
    return doc


if __name__ == "__main__":
    import sys

    print(json.dumps(discover_and_apply(), indent=2))
    raise SystemExit(0 if struct_enabled() else 1)
