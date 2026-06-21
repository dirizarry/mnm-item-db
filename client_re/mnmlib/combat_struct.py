"""Decode combat message objects from process memory (IL2CPP layout)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from client_re.process_io import read_i32, read_memory, read_ptr, read_utf8_string

MNMLIB_DIR = Path(__file__).resolve().parent
STRUCT_PATH = MNMLIB_DIR / "combat_struct.json"


def load_struct_config(path: Path | None = None) -> dict:
    path = path or STRUCT_PATH
    if not path.is_file():
        return {"enabled": False}
    return json.loads(path.read_text(encoding="utf-8"))


def struct_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg or load_struct_config()
    if not cfg.get("enabled"):
        return False
    layout = cfg.get("layout", "il2cpp_list")
    if layout == "message_blob":
        mb = cfg.get("message_blob") or {}
        return bool(mb.get("holder_ptr_hint"))
    if layout == "inline_buffer":
        buf = cfg.get("buffer") or {}
        return bool(buf.get("holder_ptr_hint") or buf.get("buffer_ptr_hint"))
    entry = cfg.get("entry") or {}
    queue = cfg.get("queue") or {}
    has_text = entry.get("text_offset") is not None
    has_queue = queue.get("list_offset") is not None or queue.get("list_ptr_hint")
    return bool(has_text and has_queue)


def read_il2cpp_list(handle, list_ptr: int, max_items: int = 256, cfg: dict | None = None) -> list[int]:
    """Return object pointers from IL2CPP List<T> (x64)."""
    if not list_ptr:
        return []
    queue = (cfg or load_struct_config()).get("queue") or {}
    items_off = int(queue.get("list_items_offset") or 0x10)
    size_off = int(queue.get("list_size_offset") or 0x18)
    array_off = int(queue.get("array_data_offset") or 0x20)
    items_arr = read_ptr(handle, list_ptr + items_off)
    size = read_i32(handle, list_ptr + size_off) or 0
    size = min(size, max_items)
    if not items_arr or size <= 0:
        return []
    raw = read_memory(handle, items_arr + array_off, size * 8)
    if not raw or len(raw) < size * 8:
        return []
    return list(struct.unpack_from(f"<{size}Q", raw, 0))


def decode_entry(handle, entry_ptr: int, cfg: dict) -> dict | None:
    entry_cfg = cfg.get("entry") or {}
    text_off = entry_cfg.get("text_offset")
    if text_off is None:
        return None
    text_ptr = read_ptr(handle, entry_ptr + text_off)
    text = read_utf8_string(handle, text_ptr or 0)
    if not text or len(text) < 4:
        return None
    out: dict = {"raw": text, "source": "memory_structured"}
    ch_off = entry_cfg.get("channel_offset")
    if ch_off is not None:
        if entry_cfg.get("channel_is_string", True):
            ch_ptr = read_ptr(handle, entry_ptr + ch_off)
            ch = read_utf8_string(handle, ch_ptr or 0)
            if ch:
                out["channel"] = ch
        else:
            ch_val = read_i32(handle, entry_ptr + ch_off)
            if ch_val is not None:
                out["channel_id"] = ch_val
    return out


def harvest_inline_buffer(handle, cfg: dict | None = None) -> list[dict]:
    """Read formatted combat lines from a discovered inline text buffer."""
    from client_re.combat_memory import scan_region_for_combat_lines

    cfg = cfg or load_struct_config()
    buf_cfg = cfg.get("buffer") or {}
    holder = buf_cfg.get("holder_ptr_hint")
    buf_ptr = buf_cfg.get("buffer_ptr_hint")
    if holder:
        holder = int(holder)
        data_off = int(buf_cfg.get("data_offset") or 0)
        cap_off = int(buf_cfg.get("capacity_offset") or 32)
        buf_ptr = read_ptr(handle, holder + data_off) or buf_ptr
        capacity = read_i32(handle, holder + cap_off) or 8192
    else:
        capacity = int(buf_cfg.get("capacity") or 8192)
    if not buf_ptr:
        return []
    capacity = max(512, min(int(capacity), 65536))
    data = read_memory(handle, int(buf_ptr), capacity)
    if not data:
        return []
    return [
        {"raw": line, "source": "memory_structured"}
        for line in scan_region_for_combat_lines(data)
    ]


def harvest_structured_queue(handle, queue_root: int | None, cfg: dict | None = None) -> list[dict]:
    """Read all entries from configured combat message queue."""
    cfg = cfg or load_struct_config()
    if not struct_enabled(cfg):
        return []
    if cfg.get("layout") == "message_blob":
        from client_re.combat_record import read_blob_records, read_blob_view

        mb = cfg.get("message_blob") or {}
        holder = int(mb.get("holder_ptr_hint") or 0)
        view = read_blob_view(handle, holder)
        if not view:
            return []
        return [
            {"raw": text, "source": "memory_structured", "blob_offset": addr - view.blob_ptr}
            for addr, text in read_blob_records(handle, view)
        ]
    if cfg.get("layout") == "inline_buffer":
        return harvest_inline_buffer(handle, cfg)
    queue = cfg.get("queue") or {}
    list_ptr = queue.get("list_ptr_hint")
    if queue_root and queue.get("list_offset") is not None:
        list_ptr = read_ptr(handle, queue_root + queue["list_offset"]) or list_ptr
    if not list_ptr:
        return []
    max_items = int(queue.get("max_items") or 256)
    text_off = int(cfg.get("entry", {}).get("text_offset") or 0x18)
    entries: list[dict] = []
    for obj_ptr in read_il2cpp_list(handle, list_ptr, max_items, cfg):
        if not obj_ptr:
            continue
        row = decode_entry(handle, obj_ptr, cfg)
        if not row:
            # fallback with discovered offset only
            text = _decode_entry_text_simple(handle, obj_ptr, text_off)
            if text:
                row = {"raw": text, "source": "memory_structured"}
        if row:
            entries.append(row)
    return entries


def _decode_entry_text_simple(handle, entry_ptr: int, text_offset: int) -> str | None:
    from client_re.combat_validate import is_valid_memory_combat_line, normalize_memory_line

    text_ptr = read_ptr(handle, entry_ptr + text_offset)
    text = read_utf8_string(handle, text_ptr or 0)
    if not text:
        return None
    text = normalize_memory_line(text)
    if not is_valid_memory_combat_line(text):
        return None
    return text
