"""Read MnM per-character chat window layout + channel routing from LocalLow.

The game stores:
  <server>/<character>/chats.json   — which message categories route to which windows
  <server>/<character>/windows.json — Unity UI anchors, size, scale per window id

The built-in ``combat`` window id typically receives Combat*/Ability*/Buff*/Death*
channels — ideal for OCR capture of damage/healing without social chat noise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

COMBAT_WINDOW_ID = "combat"

# Message categories we care about for damage/healing meters.
COMBAT_CHANNEL_PREFIXES = (
    "Combat",
    "Ability",
    "DamageShield",
    "Buff",
    "Death",
    "LOS",
    "Experience",
)


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def parse_resolution(text: str | None) -> tuple[int, int] | None:
    """``3840 x 1080`` -> (3840, 1080)."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*[x×]\s*(\d+)", str(text), re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def load_game_settings(locallow: Path) -> dict:
    return _load_json(locallow / "settings.json") or {}


def find_character_dirs(locallow: Path) -> list[Path]:
    """Return character dirs that have Ledger (most recently touched first)."""
    out: list[tuple[float, Path]] = []
    if not locallow.is_dir():
        return []
    for server in locallow.iterdir():
        if not server.is_dir():
            continue
        for char in server.iterdir():
            if not char.is_dir():
                continue
            if (char / "Ledger").is_dir():
                try:
                    mtime = max(p.stat().st_mtime for p in char.rglob("*") if p.is_file())
                except (OSError, ValueError):
                    mtime = 0.0
                out.append((mtime, char))
    out.sort(key=lambda t: -t[0])
    return [p for _, p in out]


def pick_character_dir(
    locallow: Path, server: str | None = None, character: str | None = None
) -> Path | None:
    if server and character:
        p = locallow / server / character
        return p if p.is_dir() else None
    dirs = find_character_dirs(locallow)
    return dirs[0] if dirs else None


def channels_for_window(chats: dict, window_id: str) -> list[str]:
    routed = []
    for name, targets in (chats.get("channels") or {}).items():
        if window_id in (targets or []):
            routed.append(name)
    return sorted(routed)


def combat_channels(chats: dict) -> list[str]:
    """Channels routed to the combat window."""
    return channels_for_window(chats, COMBAT_WINDOW_ID)


def is_combat_channel(name: str) -> bool:
    return any(name.startswith(p) for p in COMBAT_CHANNEL_PREFIXES)


def window_entry(windows: dict, identifier: str) -> dict | None:
    for row in windows.get("SaveData") or []:
        if row.get("identifier") == identifier:
            return row
    return None


def estimate_region(
    windows: dict,
    settings: dict,
    window_id: str = COMBAT_WINDOW_ID,
) -> dict | None:
    """Rough screen pixel bbox for a chat window (bottom-right anchored combat pane).

    Unity canvas scaling is approximate — always allow manual calibration override.
    Returns ``{left, top, width, height, source}``.
    """
    entry = window_entry(windows, window_id)
    if not entry:
        return None
    res = parse_resolution(settings.get("GameSettingDisplayResolution"))
    if not res:
        return None
    screen_w, screen_h = res
    ui_scale = float(settings.get("GameSettingUIScale") or 1.0)

    size = entry.get("sizeDelta") or {}
    w = int(float(size.get("x") or 0) * ui_scale)
    h = int(float(size.get("y") or 0) * ui_scale)
    if w < 80 or h < 40:
        return None

    anchor_max = entry.get("anchorMax") or {}
    ax = float(anchor_max.get("x") or 0)
    ay = float(anchor_max.get("y") or 0)

    # Bottom-right anchored combat window (anchor x=1, y=0): extends left/up from corner.
    if ax >= 0.99 and ay <= 0.01:
        left = max(0, screen_w - w)
        top = max(0, screen_h - h)
    else:
        # Fallback: use position + size (less reliable).
        pos = entry.get("position") or {}
        left = int(float(pos.get("x") or 0))
        top = int(float(pos.get("y") or 0))

    return {
        "left": left,
        "top": top,
        "width": min(w, screen_w - left),
        "height": min(h, screen_h - top),
        "source": f"windows.json:{window_id}",
        "screen_width": screen_w,
        "screen_height": screen_h,
    }


def load_layout(locallow: Path, char_dir: Path | None = None) -> dict:
    """Combined chats + windows + suggested region for one character."""
    char_dir = char_dir or pick_character_dir(locallow)
    if not char_dir:
        return {"error": "no character directory found"}
    chats = _load_json(char_dir / "chats.json") or {}
    windows = _load_json(char_dir / "windows.json") or {}
    settings = load_game_settings(locallow)
    combat_routed = combat_channels(chats)
    combat_only = [c for c in combat_routed if is_combat_channel(c)]
    region = estimate_region(windows, settings, COMBAT_WINDOW_ID)
    return {
        "character": char_dir.name,
        "server": char_dir.parent.name,
        "path": str(char_dir),
        "identifiers": chats.get("identifiers") or [],
        "combat_channel_count": len(combat_routed),
        "combat_meter_channels": combat_only,
        "combat_region_estimate": region,
        "chat_font_size": settings.get("GameSettingChatFontSize"),
        "ui_scale": settings.get("GameSettingUIScale"),
        "resolution": settings.get("GameSettingDisplayResolution"),
    }


def setup_recommendations(layout: dict) -> list[str]:
    """Human-readable tips for OCR-friendly combat window configuration."""
    from mnm_combat_channels import OCR_PRESETS

    tips = [
        "Right-click the combat chat window → Combat > to open filter flyouts (see data/combat-filter-ui.json).",
        "Use a dedicated combat chat window (built-in id: combat) — route Combat/Ability/Buff/Death there.",
        "Meter preset: "
        + "; ".join(OCR_PRESETS["meter"]["steps"][:2])
        + " (full list in Combat setup…).",
        "PvP preset: enable Mine + Players under Melee Hits/Misses and Detrimental spell toggles.",
        "Increase chat font size (/chatfontsize or Settings) — larger text improves OCR accuracy.",
        "Use high-contrast colors (bright damage on dark background); avoid neon-on-neon.",
        "Lock the combat window position and do not collapse it while capture runs.",
        "Keep the combat window on your primary monitor; ultrawide layouts need manual region calibration.",
        "Route social chat (Say/Tell/Party) to other windows so combat OCR sees less noise.",
    ]
    if layout.get("combat_channel_count", 0) < 20:
        tips.append(
            "Few channels route to combat — open in-game chat filters and enable combat/damage/heal categories."
        )
    if not layout.get("combat_region_estimate"):
        tips.append(
            "Could not estimate window position — use Calibrate in the client or pass --region."
        )
    return tips
