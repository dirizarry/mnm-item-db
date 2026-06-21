"""Catalog Unity assets and Addressable bundles in the game install."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from client_re.mnm_bundle import is_unity_bundle, load_unity_env
from client_re.paths import bundles_dir, install_root
from client_re.version import read_client_manifest


def _classify_path(rel: str) -> str:
    low = rel.replace("\\", "/").lower()
    if "/globalitems" in low:
        return "global_items_models"
    if "/globalraces" in low:
        return "global_races"
    if "/globalstructures" in low:
        return "global_structures"
    if "/globalprops" in low:
        return "global_props"
    if "/globaltextures" in low:
        return "global_textures"
    if "/globalshaders" in low:
        return "global_shaders"
    if "defaultlocalgroup" in low:
        return "default_local_group"
    if "contentupdate" in low:
        return "content_update"
    if "/zone_" in low:
        return "zone"
    if low.endswith(".bundle"):
        return "bundle_other"
    if low.endswith(".assets"):
        return "assets"
    if low.endswith(".dll"):
        return "binary"
    return "other"


def scan_unity_file(path: Path) -> dict:
    row: dict = {
        "path": str(path),
        "name": path.name,
        "size": path.stat().st_size,
        "category": _classify_path(path.name),
        "parseable": False,
        "object_types": {},
        "mono_behaviour_count": 0,
        "text_asset_count": 0,
        "error": None,
    }
    if not is_unity_bundle(path) and path.suffix.lower() not in {".assets", ".resource"}:
        return row
    try:
        env, hdr = load_unity_env(path)
        row["parseable"] = True
        row["mnm_offset"] = hdr.get("mnm_offset")
        row["unity_version"] = hdr.get("unity_version")
        types: dict[str, int] = {}
        mb = 0
        ta = 0
        for obj in env.objects:
            t = obj.type.name
            types[t] = types.get(t, 0) + 1
            if t == "MonoBehaviour":
                mb += 1
            elif t == "TextAsset":
                ta += 1
        row["object_types"] = dict(sorted(types.items(), key=lambda x: -x[1]))
        row["object_count"] = sum(types.values())
        row["mono_behaviour_count"] = mb
        row["text_asset_count"] = ta
    except Exception as exc:  # noqa: BLE001 — catalog must continue on bad files
        row["error"] = str(exc)
    return row


def catalog(root: Path | None = None) -> dict:
    root = install_root(root)
    manifest = read_client_manifest(root)
    manifest_paths = []
    for entry in manifest:
        rel = (entry.get("path") or "").lstrip("/").replace("/", "\\")
        if not rel:
            continue
        full = root / rel
        manifest_paths.append(
            {
                "manifest_path": entry.get("path"),
                "file_hash": entry.get("file_hash"),
                "on_disk": full.is_file(),
                "size": full.stat().st_size if full.is_file() else None,
                "category": _classify_path(rel),
            }
        )

    scanned: list[dict] = []
    # Priority bundles + core assets
    candidates: list[Path] = []
    bdir = bundles_dir(root)
    if bdir.is_dir():
        candidates.extend(sorted(bdir.glob("*.bundle")))
    data_dir = root / "mnm_Data"
    for name in ("resources.assets", "sharedassets0.assets", "globalgamemanagers.assets"):
        p = data_dir / name
        if p.is_file():
            candidates.append(p)

    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        scanned.append(scan_unity_file(path))

    scanned.sort(key=lambda r: (-r.get("mono_behaviour_count", 0), -r.get("size", 0)))

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "install_root": str(root),
        "manifest_summary": {
            "entries": len(manifest_paths),
            "on_disk": sum(1 for m in manifest_paths if m["on_disk"]),
        },
        "manifest_paths": manifest_paths,
        "scanned_files": scanned,
    }


def write_catalog(out: Path, root: Path | None = None) -> dict:
    doc = catalog(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
