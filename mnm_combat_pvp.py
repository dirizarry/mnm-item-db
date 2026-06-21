"""Detect incoming player aggression from OCR combat events and trigger alerts.

Alerts fire when a **player** (not NPC/monster) damages or aggressively acts on
you or your pet — matching in-game filters like Detrimental Me / Players.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from mnm_combat_channels import describe_channel

_PLAYER_TOKEN = re.compile(r"^[A-Z][A-Za-z']{2,}$")
_NPC_PREFIXES = ("guard ", "a ", "an ", "the ", "your pet ")

# Combat kinds that can represent incoming player aggression.
_AGGRESSIVE_KINDS = frozenset({
    "melee", "ability", "damage", "miss", "dot", "absorb",
})


def is_player_name(name: str | None) -> bool:
    """True for PC names (Mooto, Past), false for monsters and guards."""
    if not name or name in ("You", "YOU"):
        return False
    n = name.strip()
    low = n.lower()
    if any(low.startswith(p) for p in _NPC_PREFIXES):
        return False
    token = n.split()[0]
    return bool(_PLAYER_TOKEN.match(token))


def _targets_you_or_pet(event: dict) -> bool:
    target = (event.get("target") or "").strip()
    if target in ("You", "YOU"):
        return True
    low = target.lower()
    if low.startswith("your pet "):
        return True
    pet = event.get("pet")
    if pet and event.get("direction") == "incoming" and target == pet:
        return True
    return False


def classify_pvp(event: dict) -> str | None:
    """Return ``incoming``, ``outgoing``, or ``witness`` if event is PvP-related."""
    channel = event.get("channel") or ""
    actor = event.get("actor")
    target = event.get("target")
    direction = event.get("direction") or ""

    if channel.endswith("OtherPlayer"):
        if direction == "incoming" or target == "You" or _targets_you_or_pet(event):
            return "incoming"
        if direction == "outgoing" or actor == "You":
            return "outgoing"
        return "witness"

    if direction == "incoming" and is_player_name(actor):
        return "incoming"

    if direction == "outgoing" and is_player_name(target):
        return "outgoing"

    if channel.endswith("Victim") and is_player_name(actor):
        return "incoming"

    if is_player_name(actor) and is_player_name(target):
        return "witness"

    if direction == "neutral" and is_player_name(actor) and _targets_you_or_pet(event):
        return "incoming"

    if direction == "neutral" and (is_player_name(actor) or is_player_name(target)):
        if is_player_name(actor) and actor != "You":
            if _targets_you_or_pet(event):
                return "incoming"
            if is_player_name(target):
                return "witness"
        if is_player_name(target) and target != "You" and actor == "You":
            return "outgoing"

    return None


def is_incoming_player_aggression(event: dict) -> bool:
    """True when a player damages or aggressively acts on you or your pet."""
    if event.get("direction") == "outgoing":
        return False
    if not is_player_name(event.get("actor")):
        return False
    if not _targets_you_or_pet(event):
        if event.get("direction") != "incoming":
            return False
    kind = event.get("kind") or ""
    if kind in _AGGRESSIVE_KINDS:
        return True
    if kind == "status" and event.get("verb") == "angry" and event.get("target") == "You":
        return True
    if kind == "ability" and event.get("outcome") == "resist" and event.get("direction") == "incoming":
        return True
    return False


def annotate_pvp(event: dict) -> dict:
    """Add ``pvp``, ``pvp_kind``, and ``pvp_aggressive`` fields."""
    kind = classify_pvp(event)
    event["pvp"] = kind is not None
    event["pvp_kind"] = kind
    event["pvp_aggressive"] = is_incoming_player_aggression(event)
    ch = event.get("channel")
    if ch:
        meta = describe_channel(ch)
        event["channel_perspective"] = meta.get("perspective")
    return event


def should_alert_pvp(event: dict, settings: dict) -> bool:
    if not settings.get("pvp_alert_enabled", True):
        return False
    return bool(event.get("pvp_aggressive"))


def play_alert_sound(settings: dict) -> None:
    """Play configured alert sound (client should call this on the UI thread)."""
    if not settings.get("pvp_alert_sound", True):
        return
    custom = (settings.get("pvp_alert_sound_path") or "").strip()
    if custom and Path(custom).is_file():
        try:
            import winsound
            winsound.PlaySound(custom, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except (OSError, RuntimeError):
            pass
    try:
        import sys
        if sys.platform == "win32":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except OSError:
        pass


class PvpAlerter:
    """Rate-limited incoming-PvP alerts; sound handled via ``on_alert`` callback."""

    def __init__(
        self,
        settings: dict,
        on_alert: Callable[[dict, str, str], None] | None = None,
        cooldown_sec: float | None = None,
    ) -> None:
        self.settings = settings
        self.on_alert = on_alert
        self.cooldown_sec = float(
            cooldown_sec if cooldown_sec is not None
            else settings.get("pvp_alert_cooldown", 15)
        )
        self._last_alert = 0.0

    def maybe_alert(self, event: dict) -> bool:
        if not should_alert_pvp(event, self.settings):
            return False
        now = time.monotonic()
        if now - self._last_alert < self.cooldown_sec:
            return False
        self._last_alert = now
        actor = event.get("actor") or "Unknown player"
        raw = event.get("raw") or ""
        title = "Player attacking you"
        msg = f"{actor}: {raw[:140]}"
        if self.on_alert:
            self.on_alert(event, title, msg)
        else:
            play_alert_sound(self.settings)
        return True
