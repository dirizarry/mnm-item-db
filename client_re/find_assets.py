"""Rank MonoBehaviour assets by serialized size — locate master data tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from client_re.mnm_bundle import load_unity_env
from client_re.paths import bundles_dir, install_root


def _mono_candidates(path: Path, top: int) -> list[dict]:
    env, hdr = load_unity_env(path)
    rows: list[dict] = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        raw = obj.get_raw_data()
        name = ""
        class_name = ""
        try:
            data = obj.read()
            name = getattr(data, "m_Name", "") or ""
            if data.m_Script:
                script = data.m_Script.read()
                class_name = getattr(script, "m_ClassName", "") or ""
        except Exception:
            pass
        rows.append({
            "path_id": obj.path_id,
            "size": len(raw),
            "name": name,
            "script_class": class_name,
        })
    rows.sort(key=lambda r: -r["size"])
    return rows[:top]


def find_candidates(root: Path | None = None, top_per_file: int = 25) -> dict:
    root = install_root(root)
    bdir = bundles_dir(root)
    targets: list[Path] = []
    if bdir.is_dir():
        for pattern in (
            "defaultlocalgroup_*.bundle",
            "contentupdate_*.bundle",
            "globalstructures_*.bundle",
        ):
            targets.extend(sorted(bdir.glob(pattern)))

    files_out: list[dict] = []
    all_large: list[dict] = []

    for path in targets:
        entry: dict = {
            "file": path.name,
            "path": str(path),
            "size": path.stat().st_size,
            "candidates": [],
            "error": None,
        }
        try:
            cands = _mono_candidates(path, top_per_file)
            entry["candidates"] = cands
            for c in cands:
                all_large.append({**c, "file": path.name})
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)
        files_out.append(entry)

    all_large.sort(key=lambda r: -r["size"])

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "install_root": str(root),
        "files": files_out,
        "top_overall": all_large[:50],
        "notes": [
            "Large MonoBehaviours in defaultlocalgroup/contentupdate are likely Odin-serialized game tables.",
            "script_class is often empty under IL2CPP until TypeTree / Il2CppDumper mapping exists.",
        ],
    }


def write_candidates(out: Path, root: Path | None = None) -> dict:
    doc = find_candidates(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
