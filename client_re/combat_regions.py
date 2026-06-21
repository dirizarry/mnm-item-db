"""Cache heap regions that contain combat strings for fast incremental scans."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from client_re.paths import DATA_CLIENT, ensure_out
from client_re.process_io import MEM_PRIVATE, close_process, find_process, iter_regions, open_process, read_memory

CACHE_PATH = DATA_CLIENT / "combat-memory-regions.json"

COMBAT_MARKERS = (
    b"points of damage",
    b"points of Damage",
    b"point of damage",
    b"have slain",
    b"has been slain by",
    b"heals you for",
    b"heals YOU for",
    b"bites YOU for",
)


def load_region_cache() -> dict:
    if CACHE_PATH.is_file():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"regions": [], "generated": None}


def save_region_cache(regions: list[dict]) -> Path:
    ensure_out()
    doc = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "regions": regions,
    }
    CACHE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return CACHE_PATH


def discover_regions(pid: int | None = None) -> list[dict]:
    pid = pid or find_process()
    if not pid:
        return []
    handle = open_process(pid)
    found: list[dict] = []
    try:
        for base, size, protect, typ in iter_regions(handle):
            if typ != MEM_PRIVATE or size > 16_000_000 or size < 4096:
                continue
            head = read_memory(handle, base, min(size, 256 * 1024))
            if not head:
                continue
            if not any(m in head for m in COMBAT_MARKERS):
                full = read_memory(handle, base, size)
                if not full or not any(m in full for m in COMBAT_MARKERS):
                    continue
            found.append({"base": base, "size": size, "protect": protect})
    finally:
        close_process(handle)
    return found


def refresh_region_cache(pid: int | None = None) -> dict:
    regions = discover_regions(pid)
    save_region_cache(regions)
    return {"region_count": len(regions), "path": str(CACHE_PATH)}


def iter_cached_region_data(handle, cache: dict | None = None):
    cache = cache or load_region_cache()
    regions = cache.get("regions") or []
    if not regions:
        yield from ()
        return
    for reg in regions:
        base = reg["base"]
        size = reg["size"]
        data = read_memory(handle, base, size)
        if data:
            yield base, data
