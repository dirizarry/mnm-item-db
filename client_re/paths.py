"""Locate the M&M game install and output directories."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_CLIENT = ROOT / "data" / "client"
DUMPS_DIR = Path(__file__).resolve().parent / "dumps"

_DEFAULT_INSTALL = Path(os.environ.get("LOCALAPPDATA", "")) / "Monsters & Memories" / "mnm"


def default_install() -> Path:
    override = os.environ.get("MNM_INSTALL")
    if override:
        return Path(override)
    return _DEFAULT_INSTALL


def install_root(path: Path | None = None) -> Path:
    root = path or default_install()
    if not root.is_dir():
        raise FileNotFoundError(
            f"Game install not found at {root}. "
            "Set MNM_INSTALL to your mnm folder (contains mnm.exe)."
        )
    return root


def game_db_path(root: Path | None = None) -> Path:
    return install_root(root) / "game.db"


def bundles_dir(root: Path | None = None) -> Path:
    return install_root(root) / "mnm_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"


def il2cpp_metadata(root: Path | None = None) -> Path:
    return install_root(root) / "mnm_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat"


def game_assembly(root: Path | None = None) -> Path:
    return install_root(root) / "GameAssembly.dll"


def ensure_out() -> Path:
    DATA_CLIENT.mkdir(parents=True, exist_ok=True)
    return DATA_CLIENT


def ensure_dumps() -> Path:
    DUMPS_DIR.mkdir(parents=True, exist_ok=True)
    return DUMPS_DIR
