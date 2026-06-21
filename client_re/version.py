"""Build fingerprint for the installed game client."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from client_re.paths import (
    bundles_dir,
    game_assembly,
    game_db_path,
    il2cpp_metadata,
    install_root,
)


def _sha256(path: Path, max_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        if max_bytes is None:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        else:
            h.update(f.read(max_bytes))
    return h.hexdigest()


def read_client_manifest(root: Path | None = None) -> list[dict]:
    """Parse the client's download manifest (``game.db`` next to mnm.exe)."""
    db = game_db_path(root)
    if not db.is_file():
        return []
    con = sqlite3.connect(db)
    try:
        row = con.execute("SELECT json FROM manifest LIMIT 1").fetchone()
    finally:
        con.close()
    if not row:
        return []
    doc = json.loads(row[0])
    return doc.get("manifest") or []


def fingerprint(root: Path | None = None) -> dict:
    root = install_root(root)
    manifest = read_client_manifest(root)
    [e.get("path", "") for e in manifest if e.get("path")]
    ga = game_assembly(root)
    meta = il2cpp_metadata(root)
    bdir = bundles_dir(root)

    bundle_files = sorted(bdir.glob("*.bundle")) if bdir.is_dir() else []
    fp = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "install_root": str(root),
        "manifest_entries": len(manifest),
        "bundle_files_on_disk": len(bundle_files),
        "game_assembly": {
            "path": str(ga),
            "size": ga.stat().st_size if ga.is_file() else None,
            "sha256_prefix": _sha256(ga, 1 << 20) if ga.is_file() else None,
        },
        "global_metadata": {
            "path": str(meta),
            "size": meta.stat().st_size if meta.is_file() else None,
            "sha256": _sha256(meta) if meta.is_file() else None,
        },
        "manifest_path_hashes": sorted(
            {e.get("file_hash") for e in manifest if e.get("file_hash")}
        ),
    }
    # Unity version from first bundle
    if bundle_files:
        from client_re.mnm_bundle import read_file

        try:
            _, hdr = read_file(bundle_files[0])
            fp["unity_version"] = hdr.get("unity_version")
        except (OSError, ValueError):
            pass
    return fp


def write_fingerprint(out: Path, root: Path | None = None) -> dict:
    fp = fingerprint(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fp, indent=2), encoding="utf-8")
    return fp
