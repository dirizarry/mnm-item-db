"""Parse MnM structured combat message blobs from process memory (chronological)."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from client_re.combat_validate import is_valid_memory_combat_line, normalize_memory_line
from client_re.process_io import MEM_PRIVATE, iter_regions, read_i32, read_memory, read_ptr

# Formatted combat text embedded in native message records (UTF-8).
_RECORD_TEXT = re.compile(
    rb"(?:You |Your |Your pet \S+|[A-Za-z][\w']+(?:'s | ))"
    rb"[^\x00\r\n]{8,180}?"
    rb"(?:points? of (?:\w+ )*(?:damage|Damage)|Health|slain|miss(?:es)?|casting|fizzles|interrupted|resisted)"
    rb"[^\x00\r\n]{0,24}[.!?]",
)

_HOLDER_USED_OFFSETS = (0x4, 0x14)
_HOLDER_CAPACITY_OFFSETS = (0x20, 0x18, 0x28, 0x32)
_HOLDER_DATA_OFFSETS = (0x0, 0x10)


@dataclass
class MessageBlobView:
    holder_ptr: int
    blob_ptr: int
    used: int
    capacity: int
    data_offset: int = 0
    used_offset: int = 4
    capacity_offset: int = 0x20


def parse_blob_records(data: bytes, blob_base: int = 0, *, start: int = 0) -> list[tuple[int, str]]:
    """Return (absolute_offset, line) in blob byte order."""
    hits: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    chunk = data[start:]
    for m in _RECORD_TEXT.finditer(chunk):
        raw = m.group().decode("utf-8", errors="ignore").strip()
        text = normalize_memory_line(raw)
        if not is_valid_memory_combat_line(text):
            continue
        addr = blob_base + start + m.start()
        key = (addr, text)
        if key in seen:
            continue
        seen.add(key)
        hits.append((addr, text))
    hits.sort(key=lambda x: x[0])
    return hits


def read_blob_view(handle, holder_ptr: int) -> MessageBlobView | None:
    if not holder_ptr:
        return None
    blob_ptr = None
    data_off = 0
    for doff in _HOLDER_DATA_OFFSETS:
        p = read_ptr(handle, holder_ptr + doff)
        if p and p > 0x10000:
            blob_ptr = p
            data_off = doff
            break
    if not blob_ptr:
        return None

    used = 0
    used_off = 4
    for uoff in _HOLDER_USED_OFFSETS:
        v = read_i32(handle, holder_ptr + uoff) or 0
        if 16 <= v <= 65536:
            used = v
            used_off = uoff
            break

    capacity = 0
    cap_off = 0x20
    for coff in _HOLDER_CAPACITY_OFFSETS:
        v = read_i32(handle, holder_ptr + coff) or 0
        if v >= used and 256 <= v <= 65536 and v >= capacity:
            capacity = v
            cap_off = coff
    if capacity <= 0:
        capacity = max(used, 512)
    if used <= 0:
        used = capacity

    return MessageBlobView(
        holder_ptr=holder_ptr,
        blob_ptr=blob_ptr,
        used=min(used, capacity),
        capacity=capacity,
        data_offset=data_off,
        used_offset=used_off,
        capacity_offset=cap_off,
    )


def read_blob_records(handle, view: MessageBlobView) -> list[tuple[int, str]]:
    data = read_memory(handle, view.blob_ptr, view.used)
    if not data:
        return []
    return parse_blob_records(data, view.blob_ptr)


def _score_blob_holder(
    handle, holder_ptr: int, *, full: bool = True
) -> tuple[int, MessageBlobView, list[str]] | None:
    view = read_blob_view(handle, holder_ptr)
    if not view or view.used < 16:
        return None
    peek = read_memory(handle, view.blob_ptr, min(view.used, 384))
    if not peek or not _RECORD_TEXT.search(peek):
        return None
    if not full:
        return 1, view, []
    records = read_blob_records(handle, view)
    if not records:
        return None
    texts = [t for _, t in records]
    you_hits = sum(1 for t in texts if t.startswith("You ") or t.startswith("Your "))
    score = len(records) * 10 + you_hits * 25
    if view.used <= 4096:
        score += 5
    if len(records) >= 2:
        score += 20
    return score, view, texts


def _find_holders_for_blob_ptr(handle, blob_ptr: int) -> list[int]:
    needle = struct.pack("<Q", blob_ptr)
    holders: list[int] = []
    for base, size, _prot, typ in iter_regions(handle):
        if typ != MEM_PRIVATE or size > 4_000_000 or size < 64:
            continue
        data = read_memory(handle, base, min(size, 2_000_000))
        if not data:
            continue
        idx = 0
        while True:
            hit = data.find(needle, idx)
            if hit < 0:
                break
            idx = hit + 8
            holder = base + hit
            if read_ptr(handle, holder) != blob_ptr:
                continue
            holders.append(holder)
    return holders


def _scan_holder_candidates(
    handle, *, max_regions: int = 32
) -> tuple[int, MessageBlobView, list[str]] | None:
    """Scan heap for native message-blob holder structs."""
    best: tuple[int, MessageBlobView, list[str]] | None = None
    seen_holders: set[int] = set()
    scanned = 0

    for base, size, _prot, typ in iter_regions(handle):
        if typ != MEM_PRIVATE or size > 512_000 or size < 256:
            continue
        scanned += 1
        if scanned > max_regions:
            break
        data = read_memory(handle, base, size)
        if not data:
            continue
        for off in range(0, len(data) - 0x48, 16):
            holder = base + off
            if holder in seen_holders:
                continue
            blob_ptr = struct.unpack_from("<Q", data, off)[0]
            if blob_ptr < 0x10000:
                continue
            used = struct.unpack_from("<i", data, off + 4)[0]
            if not (16 <= used <= 8192):
                continue
            cap = struct.unpack_from("<i", data, off + 0x20)[0]
            if cap < used or cap > 65536:
                continue
            seen_holders.add(holder)
            if not _score_blob_holder(handle, holder, full=False):
                continue
            scored = _score_blob_holder(handle, holder, full=True)
            if not scored:
                continue
            score, view, texts = scored
            if best is None or score > best[0]:
                best = (score, view, texts)
    return best


def discover_message_blob_holder(handle, regions: list[dict]) -> dict | None:
    """Find holder → structured message blob with chronological combat records."""
    from client_re.discover_combat_struct import _collect_combat_line_addrs

    best: tuple[int, MessageBlobView, list[str]] | None = None
    lines = _collect_combat_line_addrs(handle, regions)

    blob_bases: set[int] = set()
    page_addrs: dict[int, list[int]] = {}
    for addr, text in lines:
        page = addr & ~0xFFF
        page_addrs.setdefault(page, []).append(addr)
        if text.startswith("You ") or text.startswith("Your "):
            blob_bases.add(addr & ~0xFF)
            blob_bases.add(page)
    for page, addrs in page_addrs.items():
        if len(addrs) >= 2 and addrs[-1] - addrs[0] <= 8192:
            blob_bases.add(page)
            blob_bases.add(min(addrs) & ~0xFF)

    for blob_ptr in blob_bases:
        for holder in _find_holders_for_blob_ptr(handle, blob_ptr):
            scored = _score_blob_holder(handle, holder)
            if not scored:
                continue
            score, view, texts = scored
            if best is None or score > best[0]:
                best = (score, view, texts)

    if best is None:
        best = _scan_holder_candidates(handle)

    if not best:
        return None

    score, view, texts = best
    return {
        "layout": "message_blob",
        "holder_ptr": view.holder_ptr,
        "blob_ptr": view.blob_ptr,
        "data_offset": view.data_offset,
        "used_offset": view.used_offset,
        "capacity_offset": view.capacity_offset,
        "capacity": view.capacity,
        "score": score,
        "sample_texts": texts[:12],
    }


def poll_blob_tail(
    handle,
    cfg: dict,
    state: dict,
) -> tuple[list[tuple[int, str]], MessageBlobView | None]:
    """Return newly appended (offset, line) pairs since the last poll."""
    blob_cfg = cfg.get("message_blob") or cfg.get("buffer") or {}
    holder = int(blob_cfg.get("holder_ptr_hint") or 0)
    view = read_blob_view(handle, holder) if holder else None

    if view is None or read_memory(handle, view.blob_ptr, 16) is None:
        from client_re.combat_regions import discover_regions
        from client_re.process_io import find_process

        rediscovered = discover_message_blob_holder(handle, discover_regions(find_process()))
        if rediscovered:
            holder = int(rediscovered["holder_ptr"])
            view = read_blob_view(handle, holder)
        if view is None or read_memory(handle, view.blob_ptr, 16) is None:
            return [], view

    key = f"{view.blob_ptr:x}"
    st = state.setdefault("message_blob_poll", {})
    prev_used = int(st.get(key, {}).get("used") or 0)
    prev_tail = int(st.get(key, {}).get("tail_offset") or 0)

    records = read_blob_records(handle, view)
    if not records:
        st[key] = {"used": view.used, "tail_offset": 0, "holder": view.holder_ptr}
        return [], view

    if view.used < prev_used or view.blob_ptr != int(
        st.get(key, {}).get("blob_ptr") or view.blob_ptr
    ):
        prev_tail = 0
        prev_used = 0

    if prev_tail == 0 and prev_used == 0:
        last_off = records[-1][0] - view.blob_ptr + 64
        st[key] = {
            "used": view.used,
            "tail_offset": min(last_off, view.used),
            "blob_ptr": view.blob_ptr,
            "holder": view.holder_ptr,
        }
        return [], view

    new: list[tuple[int, str]] = []
    for addr, text in records:
        off = addr - view.blob_ptr
        if off >= prev_tail - 32:
            new.append((addr, text))

    if new:
        last_off = new[-1][0] - view.blob_ptr + len(new[-1][1]) + 32
    else:
        last_off = prev_tail
    st[key] = {
        "used": view.used,
        "tail_offset": min(last_off, view.capacity),
        "blob_ptr": view.blob_ptr,
        "holder": view.holder_ptr,
    }
    return new, view
