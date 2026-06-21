"""Path + settings resolution for both source-run and PyInstaller-frozen modes.

In source mode the workspace is the repo directory (so the existing pipeline modules,
which use ``ROOT = Path(__file__).parent``, write to ``./data`` as before). When frozen
into an exe, read-only bundled resources live next to the exe (``resource_path``) while
writable state (settings, mined data, site bundle) lives in a per-user workspace under
``%LOCALAPPDATA%\\MnMItemDB`` so the app never tries to write into Program Files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "MnMItemDB"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_path(rel: str = "") -> Path:
    """Absolute path to a bundled read-only resource (works frozen and from source)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent
    return base / rel if rel else base


def workspace_dir() -> Path:
    """Writable working directory for data/, site/, and settings."""
    override = os.environ.get("MNM_WORKSPACE")
    if override:
        ws = Path(override)
    elif is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        ws = Path(base) / APP_NAME
    else:
        ws = Path(__file__).parent
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def data_dir() -> Path:
    d = workspace_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def site_dir() -> Path:
    return workspace_dir() / "site"


def settings_path() -> Path:
    return workspace_dir() / "client-settings.json"


DEFAULT_SETTINGS = {
    "locallow": "",
    "upload_url": "",
    "upload_token": "",
    "share_characters": False,
    "update_url": "https://raw.githubusercontent.com/OWNER/mnm-item-db/main/latest-version.json",
    "auto_check_updates": True,
    # Combat OCR (Option C) — region in screen pixels {left, top, width, height}
    "combat_region": None,
    "combat_ocr_interval": 1.5,
    "combat_ocr_backend": None,
    "combat_window_lock": True,
    "pvp_alert_enabled": True,
    "pvp_alert_sound": True,
    "pvp_alert_sound_path": "",
    "pvp_alert_cooldown": 15,
    # Multi-window OCR: [{ "id", "label", "role", "region", "channels" }]
    "combat_streams": [],
}


def load_settings() -> dict:
    path = settings_path()
    if path.is_file():
        try:
            return {**DEFAULT_SETTINGS, **json.loads(path.read_text(encoding="utf-8"))}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> Path:
    path = settings_path()
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return path


def apply_settings_to_env(settings: dict) -> None:
    """Expose settings to the existing pipeline modules via the MNM_* env vars they read."""
    if settings.get("locallow"):
        os.environ["MNM_LOCALLOW"] = str(settings["locallow"])
    if settings.get("upload_url"):
        os.environ["MNM_UPLOAD_URL"] = str(settings["upload_url"])
    if settings.get("upload_token"):
        os.environ["MNM_UPLOAD_TOKEN"] = str(settings["upload_token"])
    os.environ["MNM_UPLOAD_SHARE_CHARACTERS"] = "1" if settings.get("share_characters") else "0"
