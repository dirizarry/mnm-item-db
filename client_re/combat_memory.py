"""Read-only combat event harvest from mnm.exe process memory (Option F)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from client_re.mnmlib.combat_struct import harvest_structured_queue, load_struct_config, struct_enabled
from client_re.process_io import find_process, open_process, close_process, iter_region_data
from client_re.signatures import load_signature_cache, resolve_signatures, verify_signatures

# Combat line templates — aligned with mnm_combat_text.py
_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("damage", re.compile(
        r"(?:^You |^Your |^[A-Za-z][\w']+(?:'s | )|^[Aa]n? )"
        r".+ for \d+ points? of .*(?:damage|Damage)\s*[.!]?$",
        re.I,
    )),
    ("heal", re.compile(
        r"(?:^You |^Your |^[A-Za-z][\w']+(?:'s | ))"
        r".+\s+heals?\s+.+\s+for\s+\d+(?:\s+(?:points?|Health))?\s*[.!]?$",
        re.I,
    )),
    ("miss", re.compile(
        r"(?:^You |^Your pet \S+|^[Aa]n? |[A-Za-z])"
        r".+ try(?:s)? to .+, but (?:miss(?:es)?|parr(?:y|ies)|dodge(?:s)?|block(?:s)?)",
        re.I,
    )),
    ("slain", re.compile(
        r"(?:^You |^Your pet \S+|^[A-Za-z])"
        r".+(?:have slain|has slain|has been slain by)",
        re.I,
    )),
    ("cast", re.compile(r"^You begin casting .+\.?$", re.I)),
    ("experience", re.compile(r".+ gain(?:s)? experience", re.I)),
)


def memory_capture_status(install=None) -> dict:
    """Report whether memory harvest can run for the current install."""
    verify = verify_signatures(install)
    cfg = load_struct_config()
    pid = find_process()
    structured = struct_enabled(cfg)
    layout = cfg.get("layout", "il2cpp_list")
    live_structured = structured and layout in ("il2cpp_list", "message_blob")
    text_ok = pid is not None
    return {
        "process_running": pid is not None,
        "pid": pid,
        "signatures_ready": text_ok or verify.get("ready", False),
        "signatures_stale": verify.get("stale", True) if live_structured else False,
        "stale_reasons": verify.get("reasons") or [],
        "structured_enabled": structured,
        "structured_layout": layout if structured else None,
        "recommended_mode": (
            "message_blob" if layout == "message_blob"
            else ("text_scan" if layout == "inline_buffer" else ("structured" if structured else "text_scan"))
        ),
        "live_capture_note": (
            "message_blob reads the chronological combat record tail (no OCR)."
            if layout == "message_blob"
            else (
                "inline_buffer is a session snapshot; prefer message_blob or text_scan."
                if layout == "inline_buffer"
                else None
            )
        ),
    }


def _extract_strings(data: bytes, min_len: int = 12, max_len: int = 512) -> list[str]:
    """Pull candidate UTF-8 and UTF-16LE strings from a memory region."""
    found: list[str] = []
    # UTF-8 runs
    for m in re.finditer(rb"[\x20-\x7e]{%d,%d}" % (min_len, max_len), data):
        try:
            found.append(m.group().decode("ascii"))
        except UnicodeDecodeError:
            pass
    # UTF-16LE (printable ASCII chars)
    for m in re.finditer(
        (rb"(?:[\x20-\x7e]\x00){%d,%d}" % (min_len, max_len // 2)),
        data,
    ):
        try:
            s = m.group().decode("utf-16-le")
            if len(s) >= min_len:
                found.append(s)
        except UnicodeDecodeError:
            pass
    return found


def _line_from_needle_match(data: bytes, idx: int, needle: bytes) -> tuple[int, str] | None:
    lo = idx
    while lo > 0 and lo > idx - 160:
        ch = data[lo - 1]
        if ch in (0, 10, 13):
            break
        if ch < 0x20 and ch not in (9,):
            break
        lo -= 1
    hi = idx + len(needle)
    while hi < len(data) and hi < idx + 220:
        ch = data[hi]
        if ch in (0, 10, 13):
            break
        if ch < 0x20 and ch not in (9,):
            break
        hi += 1
    chunk = data[lo:hi]
    for decode in (
        lambda b: b.decode("utf-8", errors="ignore"),
        lambda b: b.decode("utf-16-le", errors="ignore"),
    ):
        try:
            text = decode(chunk).strip(" \x00\r\n\t.&!")
        except Exception:
            continue
        for end in (".", "!", "?"):
            pos = text.find(end)
            if pos > 10:
                text = text[: pos + 1]
                break
        if 12 <= len(text) <= 200:
            return lo, text
    return None


def _extract_combat_needles(data: bytes) -> list[str]:
    return [text for _, text in _extract_combat_needles_at(0, data)]


def _extract_combat_needles_at(base: int, data: bytes) -> list[tuple[int, str]]:
    """Find EQ-style combat substrings; return (absolute_address, line)."""
    needles = (
        b"points of damage",
        b"points of Damage",
        b"point of damage",
        b"points of Magic Damage",
        b"points of Fire Damage",
        b"points of Cold Damage",
        b"points of Electric Damage",
        b"heals you for",
        b"heals YOU for",
        b" Health.",
        b"have slain",
        b"has been slain by",
        b"but miss",
        b"but misses",
        b"begin casting",
        b"spell fizzles",
        b"casting is interrupted",
    )
    hits: list[tuple[int, str]] = []
    seen_addr: set[int] = set()
    for needle in needles:
        start = 0
        while True:
            idx = data.find(needle, start)
            if idx < 0:
                break
            start = idx + 1
            parsed = _line_from_needle_match(data, idx, needle)
            if not parsed:
                continue
            lo, text = parsed
            addr = base + lo
            if addr in seen_addr:
                continue
            seen_addr.add(addr)
            hits.append((addr, text))
    return hits


def scan_region_for_combat_hits(base: int, data: bytes) -> list[tuple[int, str]]:
    from client_re.combat_validate import is_valid_memory_combat_line, normalize_memory_line

    hits: list[tuple[int, str]] = []
    seen_addr: set[int] = set()

    for m in re.finditer(rb"[\x20-\x7e]{15,220}", data):
        addr = base + m.start()
        if addr in seen_addr:
            continue
        norm = normalize_memory_line(m.group().decode("ascii", errors="ignore").strip())
        if not is_valid_memory_combat_line(norm):
            continue
        seen_addr.add(addr)
        hits.append((addr, norm))

    for addr, raw in _extract_combat_needles_at(base, data):
        if addr in seen_addr:
            continue
        norm = normalize_memory_line(raw.strip())
        if not is_valid_memory_combat_line(norm):
            continue
        seen_addr.add(addr)
        hits.append((addr, norm))

    return hits


def scan_region_for_combat_lines(data: bytes) -> list[str]:
    return [text for _, text in scan_region_for_combat_hits(0, data)]


def scan_process_combat_hits(
    pid: int | None = None,
    *,
    max_regions: int | None = None,
    heap_only: bool = True,
    max_bytes: int = 256_000_000,
    use_cache: bool = True,
    refresh_cache: bool = False,
) -> list[tuple[int, str]]:
    from client_re.combat_regions import iter_cached_region_data, load_region_cache, refresh_region_cache

    pid = pid or find_process()
    if not pid:
        raise RuntimeError("mnm.exe is not running")
    handle = open_process(pid)
    hits: list[tuple[int, str]] = []
    seen_addr: set[int] = set()
    if refresh_cache or not use_cache:
        refresh_region_cache(pid)
    cache = load_region_cache() if use_cache else {"regions": []}
    if use_cache and not cache.get("regions"):
        refresh_region_cache(pid)
        cache = load_region_cache()
    try:
        count = 0
        region_iter = iter_cached_region_data(handle, cache) if cache.get("regions") else iter_region_data(
            handle, heap_only=heap_only, max_bytes=max_bytes
        )
        for base, data in region_iter:
            for addr, line in scan_region_for_combat_hits(base, data):
                if addr in seen_addr:
                    continue
                seen_addr.add(addr)
                hits.append((addr, line))
            count += 1
            if max_regions is not None and count >= max_regions:
                break
    finally:
        close_process(handle)
    hits.sort(key=lambda x: x[0])
    return hits


def scan_process_text(
    pid: int | None = None,
    *,
    max_regions: int | None = None,
    heap_only: bool = True,
    max_bytes: int = 256_000_000,
    use_cache: bool = True,
) -> list[str]:
    return [line for _, line in scan_process_combat_hits(
        pid,
        max_regions=max_regions,
        heap_only=heap_only,
        max_bytes=max_bytes,
        use_cache=use_cache,
    )]


def harvest_structured(pid: int | None = None, queue_root: int | None = None) -> list[dict]:
    cfg = load_struct_config()
    if not struct_enabled(cfg):
        return []
    pid = pid or find_process()
    if not pid:
        return []
    if queue_root is None:
        queue_root = cfg.get("queue", {}).get("root_address")
    if cfg.get("layout") not in ("inline_buffer", "message_blob"):
        if queue_root is None and not cfg.get("queue", {}).get("list_ptr_hint"):
            return []
    handle = open_process(pid)
    try:
        root = queue_root or cfg.get("queue", {}).get("root_address")
        return harvest_structured_queue(handle, root, cfg)
    finally:
        close_process(handle)


def poll_combat_hits(
    *,
    pid: int | None = None,
    mode: str | None = None,
    max_regions: int | None = None,
    refresh_cache: bool = False,
    state: dict | None = None,
) -> tuple[list[tuple[int, str]], str]:
    """Return (address, line) hits and the capture mode used."""
    status = memory_capture_status()
    pid = pid or status.get("pid")
    if not pid:
        raise RuntimeError("mnm.exe is not running")

    cfg = load_struct_config()
    layout = cfg.get("layout", "il2cpp_list")

    if layout == "message_blob" and struct_enabled(cfg) and mode != "text_scan":
        from client_re.combat_record import poll_blob_tail

        handle = open_process(pid)
        try:
            hits, _view = poll_blob_tail(handle, cfg, state or {})
            return hits, "message_blob"
        finally:
            close_process(handle)

    use_structured = mode == "structured" or (
        mode != "text_scan" and status.get("structured_enabled")
    )
    if use_structured and layout == "inline_buffer" and mode != "structured":
        use_structured = False
    if use_structured and status.get("structured_enabled"):
        rows = harvest_structured(pid=pid)
        hits = [(0, r["raw"]) for r in rows if r.get("raw")]
        return hits, "structured"

    hits = scan_process_combat_hits(
        pid, max_regions=max_regions, refresh_cache=refresh_cache,
    )
    return hits, "text_scan"


def poll_combat_lines(
    *,
    pid: int | None = None,
    mode: str | None = None,
    max_regions: int | None = None,
) -> tuple[list[str], str]:
    """Return combat text lines and the mode used."""
    hits, mode_used = poll_combat_hits(
        pid=pid, mode=mode, max_regions=max_regions,
    )
    return [line for _, line in hits], mode_used


def ensure_signatures(install=None) -> dict:
    verify = verify_signatures(install)
    if verify.get("stale") or not verify.get("cache"):
        return resolve_signatures(install)
    return verify["cache"]
