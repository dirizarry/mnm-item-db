"""Persist wiki loot-fix review decisions (rejected / pushed)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
DEFAULT_STATE_PATH = ROOT / "data" / "wiki-fixes" / "loot" / "review-state.json"


def load_state(path: Path | None = None) -> dict:
    path = path or DEFAULT_STATE_PATH
    if not path.is_file():
        return {"rejected": [], "pushed": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "rejected": list(dict.fromkeys(data.get("rejected") or [])),
        "pushed": list(dict.fromkeys(data.get("pushed") or [])),
    }


def save_state(state: dict, path: Path | None = None) -> Path:
    path = path or DEFAULT_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "rejected": list(dict.fromkeys(state.get("rejected") or [])),
        "pushed": list(dict.fromkeys(state.get("pushed") or [])),
    }
    path.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    return path


def add_rejected(ids: list[str], path: Path | None = None) -> dict:
    state = load_state(path)
    for fix_id in ids:
        if fix_id not in state["rejected"]:
            state["rejected"].append(fix_id)
        if fix_id in state["pushed"]:
            state["pushed"].remove(fix_id)
    save_state(state, path)
    return state


def add_pushed(ids: list[str], path: Path | None = None) -> dict:
    state = load_state(path)
    for fix_id in ids:
        if fix_id not in state["pushed"]:
            state["pushed"].append(fix_id)
        if fix_id in state["rejected"]:
            state["rejected"].remove(fix_id)
    save_state(state, path)
    return state


def rejected_ids(path: Path | None = None) -> set[str]:
    return set(load_state(path)["rejected"])


def pushed_ids(path: Path | None = None) -> set[str]:
    return set(load_state(path)["pushed"])
