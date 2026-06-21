"""Resolve GameAssembly.dll anchors via pattern / string scan (MacroQuest-style)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from client_re.paths import DATA_CLIENT, ROOT, ensure_out, game_assembly, install_root
from client_re.process_io import (
    close_process,
    find_module,
    find_process,
    open_process,
)

MNMLIB_DIR = Path(__file__).resolve().parent / "mnmlib"
SIGNATURES_TEMPLATE = MNMLIB_DIR / "signatures.json"


def _fingerprint_id(fp: dict | None = None) -> str:
    fp = fp or {}
    ga = fp.get("game_assembly") or {}
    prefix = ga.get("sha256_prefix") or "unknown"
    size = ga.get("size") or 0
    return hashlib.sha256(f"{prefix}:{size}".encode()).hexdigest()[:16]


def signatures_cache_path(fp: dict | None = None) -> Path:
    fid = _fingerprint_id(fp)
    return ensure_out() / f"signatures-{fid}.json"


def load_signature_template() -> dict:
    if SIGNATURES_TEMPLATE.is_file():
        return json.loads(SIGNATURES_TEMPLATE.read_text(encoding="utf-8"))
    return {"version": 1, "patterns": []}


def load_signature_cache(fp: dict | None = None) -> dict | None:
    path = signatures_cache_path(fp)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_bytes(data: bytes, pattern: str) -> list[int]:
    """Scan for space-separated hex pattern with ?? wildcards."""
    parts = pattern.strip().split()
    if not parts:
        return []
    hits: list[int] = []
    step = len(parts)
    for i in range(len(data) - step):
        ok = True
        for j, p in enumerate(parts):
            if p == "??":
                continue
            if data[i + j] != int(p, 16):
                ok = False
                break
        if ok:
            hits.append(i)
    return hits


def scan_file_pattern(path: Path, pattern: str, limit: int = 5) -> list[int]:
    data = path.read_bytes()
    return _scan_bytes(data, pattern)[:limit]


def scan_file_string(path: Path, needle: str, encoding: str = "ascii") -> list[int]:
    data = path.read_bytes()
    if encoding == "utf-16-le":
        blob = needle.encode("utf-16-le")
    else:
        blob = needle.encode("ascii")
    hits: list[int] = []
    start = 0
    while True:
        idx = data.find(blob, start)
        if idx < 0:
            break
        hits.append(idx)
        start = idx + 1
        if len(hits) >= 20:
            break
    return hits


def resolve_signatures(
    install=None,
    *,
    pid: int | None = None,
    write_cache: bool = True,
) -> dict:
    """Resolve signature template against on-disk DLL and optional live process."""
    root = install_root(install) if install else None
    try:
        ga_path = game_assembly(root) if root else game_assembly()
    except FileNotFoundError:
        ga_path = None

    fp_doc = None
    fp_path = DATA_CLIENT / "build-fingerprint.json"
    if fp_path.is_file():
        fp_doc = json.loads(fp_path.read_text(encoding="utf-8"))

    template = load_signature_template()
    result: dict = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "fingerprint_id": _fingerprint_id(fp_doc),
        "game_assembly": str(ga_path) if ga_path else None,
        "pid": pid or find_process(),
        "resolved": [],
        "errors": [],
        "ready": False,
    }

    file_data = ga_path.read_bytes() if ga_path and ga_path.is_file() else None
    runtime_mod = None
    handle = None
    if result["pid"]:
        try:
            handle = open_process(result["pid"])
            runtime_mod = find_module(result["pid"], "GameAssembly.dll")
        except OSError as exc:
            result["errors"].append(str(exc))

    try:
        for pat in template.get("patterns") or []:
            entry = {"id": pat.get("id"), "kind": pat.get("kind")}
            kind = pat.get("kind")
            if kind == "string" and file_data is not None:
                needle = pat.get("needle", "")
                enc = pat.get("encoding", "ascii")
                file_offsets = scan_file_string(ga_path, needle, enc)
                entry["file_offsets"] = file_offsets
                entry["file_hits"] = len(file_offsets)
                if runtime_mod and file_offsets:
                    base = runtime_mod["base"]
                    entry["runtime_addresses"] = [base + off for off in file_offsets[:5]]
                if file_offsets:
                    entry["ok"] = True
                else:
                    entry["ok"] = False
                    entry["error"] = f"String {needle!r} not found in GameAssembly.dll"
            elif kind == "code" and file_data is not None:
                pattern = pat.get("pattern", "")
                offs = scan_file_pattern(ga_path, pattern)
                entry["file_offsets"] = offs
                entry["file_hits"] = len(offs)
                if runtime_mod and offs:
                    entry["runtime_addresses"] = [runtime_mod["base"] + o for o in offs[:5]]
                entry["ok"] = bool(offs)
            elif kind in ("metadata_string", "memory_text"):
                entry["ok"] = True
                entry["note"] = pat.get("note")
            else:
                entry["ok"] = False
                entry["error"] = "Unsupported or missing scan target"
            result["resolved"].append(entry)

        structured = template.get("structured_queue") or {}
        result["structured_enabled"] = bool(structured.get("enabled"))
        result["ready"] = (
            any(e.get("ok") for e in result["resolved"] if e.get("kind") == "string")
            or not result["structured_enabled"]
        )
    finally:
        if handle:
            close_process(handle)

    if write_cache:
        cache_path = signatures_cache_path(fp_doc)
        cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        result["cache_path"] = str(cache_path.relative_to(ROOT))

    return result


def verify_signatures(install=None) -> dict:
    """Verify cached signatures still match the installed client."""
    fp_path = DATA_CLIENT / "build-fingerprint.json"
    fp_doc = json.loads(fp_path.read_text(encoding="utf-8")) if fp_path.is_file() else {}
    cache = load_signature_cache(fp_doc)
    fresh = resolve_signatures(install, write_cache=False)

    stale = False
    reasons: list[str] = []
    if cache is None:
        stale = True
        reasons.append("No signature cache for current fingerprint")
    elif cache.get("fingerprint_id") != fresh.get("fingerprint_id"):
        stale = True
        reasons.append("Fingerprint changed since cache was built")
    else:
        for old, new in zip(cache.get("resolved") or [], fresh.get("resolved") or [], strict=False):
            if old.get("file_hits") != new.get("file_hits"):
                stale = True
                reasons.append(f"Pattern {old.get('id')}: file hit count changed")

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "stale": stale,
        "reasons": reasons,
        "cache": cache,
        "current": fresh,
        "ready": fresh.get("ready") and not stale,
    }


def resolve_runtime_address(signature_id: str, install=None) -> int | None:
    fp_path = DATA_CLIENT / "build-fingerprint.json"
    fp_doc = json.loads(fp_path.read_text(encoding="utf-8")) if fp_path.is_file() else {}
    cache = load_signature_cache(fp_doc)
    if not cache:
        cache = resolve_signatures(install)
    for entry in cache.get("resolved") or []:
        if entry.get("id") == signature_id and entry.get("runtime_addresses"):
            return entry["runtime_addresses"][0]
    pid = find_process()
    if not pid:
        return None
    handle = open_process(pid)
    try:
        fresh = resolve_signatures(install, pid=pid, write_cache=True)
        for entry in fresh.get("resolved") or []:
            if entry.get("id") == signature_id and entry.get("runtime_addresses"):
                return entry["runtime_addresses"][0]
    finally:
        close_process(handle)
    return None
