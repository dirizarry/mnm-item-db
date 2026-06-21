"""Compare current client install against the last saved fingerprint."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from client_re.paths import DATA_CLIENT, ROOT, ensure_out
from client_re.signatures import load_signature_cache, signatures_cache_path
from client_re.version import fingerprint

FP_PATH = DATA_CLIENT / "build-fingerprint.json"
HISTORY_DIR = DATA_CLIENT / "history"
SIGNATURE_HISTORY = HISTORY_DIR / "signatures"


def _full_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_previous() -> dict | None:
    if not FP_PATH.is_file():
        return None
    return json.loads(FP_PATH.read_text(encoding="utf-8"))


def diff_fingerprints(old: dict, new: dict) -> dict:
    changes: list[str] = []
    for key in ("game_assembly", "global_metadata"):
        o, n = old.get(key, {}), new.get(key, {})
        if o.get("size") != n.get("size"):
            changes.append(f"{key} size: {o.get('size')} -> {n.get('size')}")
        osha = o.get("sha256") or o.get("sha256_prefix")
        npath = n.get("path")
        nsha = _full_sha(Path(npath)) if npath and Path(npath).is_file() else None
        if osha and nsha and osha[:16] != nsha[:16]:
            changes.append(f"{key} hash changed")
    if old.get("manifest_entries") != new.get("manifest_entries"):
        changes.append(
            f"manifest entries: {old.get('manifest_entries')} -> {new.get('manifest_entries')}"
        )
    oh = set(old.get("manifest_path_hashes") or [])
    nh = set(new.get("manifest_path_hashes") or [])
    if oh != nh:
        changes.append(f"manifest file hashes changed: {len(oh ^ nh)} entries")
    if old.get("unity_version") != new.get("unity_version"):
        changes.append(
            f"unity_version: {old.get('unity_version')} -> {new.get('unity_version')}"
        )
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "patched": bool(changes),
        "changes": changes,
        "previous_generated": old.get("generated"),
        "current": new,
    }


def archive_fingerprint(old: dict) -> Path | None:
    if not old.get("generated"):
        return None
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = (old.get("generated") or "unknown")[:10].replace("-", "")
    ga = old.get("game_assembly", {}).get("sha256_prefix", "unknown")[:8]
    out = HISTORY_DIR / f"fingerprint-{stamp}-{ga}.json"
    out.write_text(json.dumps(old, indent=2), encoding="utf-8")
    archive_signature_cache(old)
    return out


def archive_signature_cache(fp: dict) -> Path | None:
    """Move stale signature cache to history/ when fingerprint changes."""
    cache = load_signature_cache(fp)
    if not cache:
        return None
    path = signatures_cache_path(fp)
    if not path.is_file():
        return None
    SIGNATURE_HISTORY.mkdir(parents=True, exist_ok=True)
    ga = (fp.get("game_assembly") or {}).get("sha256_prefix", "unknown")[:8]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = SIGNATURE_HISTORY / f"signatures-{stamp}-{ga}.json"
    shutil.copy2(path, dest)
    path.unlink(missing_ok=True)
    return dest


def signature_stale_report(fp: dict | None = None) -> dict:
    """Report whether combat memory signatures need re-resolution."""
    from client_re.signatures import verify_signatures

    fp = fp or load_previous() or fingerprint()
    verify = verify_signatures()
    cache_path = signatures_cache_path(fp)
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "cache_path": str(cache_path.relative_to(ROOT)) if cache_path.is_file() else None,
        "stale": verify.get("stale", True),
        "ready": verify.get("ready", False),
        "reasons": verify.get("reasons") or [],
    }


def check_patch(root=None) -> dict:
    ensure_out()
    prev = load_previous()
    curr = fingerprint(root)
    if prev is None:
        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "patched": False,
            "changes": [],
            "note": "No previous fingerprint; saving baseline.",
            "current": curr,
        }
    return diff_fingerprints(prev, curr)
