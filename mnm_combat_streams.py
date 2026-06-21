"""Multi-region combat OCR stream configuration.

Each stream binds a screen region to an in-game chat window id and the same
Combat > filter toggles the player enables for that window in ``chats.json``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

from mnm_chat_windows import channels_for_window, load_layout, pick_character_dir
from mnm_combat_channels import OCR_PRESETS, ROLE_CHANNELS, build_filter_menu, infer_channel


def new_stream_id() -> str:
    return uuid.uuid4().hex[:8]


def import_window_channels(locallow: Path, window_id: str) -> list[str]:
    """Channels routed to ``window_id`` in the active character's chats.json."""
    char_dir = pick_character_dir(locallow)
    if not char_dir:
        return []
    chats_path = char_dir / "chats.json"
    if not chats_path.is_file():
        return []
    try:
        chats = json.loads(chats_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return channels_for_window(chats, window_id)


def channels_for_role(role: str) -> list[str]:
    return list(ROLE_CHANNELS.get(role) or ())


def channels_for_preset(preset_key: str) -> list[str]:
    meta = OCR_PRESETS.get(preset_key) or {}
    role = meta.get("role")
    if role:
        return channels_for_role(role)
    return []


def iter_filter_leaves(menu: dict | None = None) -> Iterator[tuple[str, str, list[str]]]:
    """Yield ``(path_id, label, channel_ids)`` for every in-game filter leaf."""
    menu = menu or build_filter_menu()

    death = menu.get("Death") or {}
    for target, chs in (death.get("channels_by_target") or {}).items():
        if chs:
            yield f"death:{target}", f"Death → {target}", list(chs)

    pet = menu.get("Pet") or {}
    if pet.get("channels"):
        yield "pet", "Pet", list(pet["channels"])

    los = menu.get("Line of Sight") or {}
    if los.get("channels"):
        yield "los", "Line of Sight", list(los["channels"])

    for outcome, entry in (menu.get("Melee") or {}).get("outcomes", {}).items():
        targets = entry.get("targets")
        chs = entry.get("channels") or []
        if targets and chs:
            fam = (
                "CombatHit" if outcome == "Hits" else "CombatMiss" if outcome == "Misses" else None
            )
            if fam:
                from mnm_combat_channels import UI_TARGET_SUFFIX

                for target in targets:
                    suf = UI_TARGET_SUFFIX.get(target)
                    if suf:
                        yield (
                            f"melee:{outcome}:{target}",
                            f"Melee → {outcome} → {target}",
                            [f"{fam}{suf}"],
                        )
        elif chs:
            yield f"melee:{outcome}", f"Melee → {outcome}", list(chs)

    for outcome, entry in (menu.get("Ability") or {}).get("outcomes", {}).items():
        targets = entry.get("targets")
        chs = entry.get("channels") or []
        if outcome == "Hit" and targets:
            from mnm_combat_channels import UI_TARGET_SUFFIX

            for target in targets:
                leaf_chs = [
                    f"AbilityHit{det}{UI_TARGET_SUFFIX[target]}"
                    for det in ("Benefit", "Detriment")
                    if UI_TARGET_SUFFIX.get(target)
                ]
                yield (
                    f"ability:{outcome}:{target}",
                    f"Ability → {outcome} → {target}",
                    leaf_chs,
                )
        elif targets and chs:
            from mnm_combat_channels import UI_TARGET_SUFFIX

            fam = {
                "Miss": "AbilityMiss",
                "Resist": "AbilityResist",
            }.get(outcome)
            if fam:
                for target in targets:
                    suf = UI_TARGET_SUFFIX.get(target)
                    if suf:
                        yield (
                            f"ability:{outcome}:{target}",
                            f"Ability → {outcome} → {target}",
                            [f"{fam}{suf}"],
                        )
        elif chs:
            yield f"ability:{outcome}", f"Ability → {outcome}", list(chs)

    for phase, phase_entry in (menu.get("Spell") or {}).get("phases", {}).items():
        for align, align_entry in (phase_entry.get("alignments") or {}).items():
            targets = align_entry.get("targets") or []
            chs = align_entry.get("channels") or []
            if not targets or not chs:
                continue
            from mnm_combat_channels import BUFF_UI_SUFFIX

            for target in targets:
                suf = BUFF_UI_SUFFIX.get((align, target))
                if suf:
                    yield (
                        f"spell:{phase}:{align}:{target}",
                        f"Spell → {phase} → {align} → {target}",
                        [f"Buff{phase}{suf}"],
                    )

    spell_resist = menu.get("Spell", {}).get("Resist")
    if isinstance(spell_resist, dict):
        for align, align_entry in (spell_resist.get("alignments") or {}).items():
            targets = align_entry.get("targets") or []
            chs = align_entry.get("channels") or []
            if targets and chs:
                from mnm_combat_channels import UI_TARGET_SUFFIX

                for target in targets:
                    suf = UI_TARGET_SUFFIX.get(target)
                    if suf:
                        yield (
                            f"spell:resist:{align}:{target}",
                            f"Spell → Resist → {align} → {target}",
                            [f"AbilityResist{suf}"],
                        )


def channels_from_filter_paths(paths: set[str] | list[str], menu: dict | None = None) -> list[str]:
    """Union of channel ids enabled by filter leaf path ids."""
    wanted = set(paths)
    out: set[str] = set()
    for path_id, _label, chs in iter_filter_leaves(menu):
        if path_id in wanted:
            out.update(chs)
    return sorted(out)


def filter_paths_from_channels(
    channels: set[str] | list[str], menu: dict | None = None
) -> set[str]:
    """Best-effort reverse map: which filter leaves cover the given channels."""
    ch_set = set(channels)
    paths: set[str] = set()
    for path_id, _label, leaf_chs in iter_filter_leaves(menu):
        if leaf_chs and all(c in ch_set for c in leaf_chs):
            paths.add(path_id)
    return paths


def normalize_stream(raw: dict) -> dict | None:
    """Validate and fill defaults on a combat_streams[] entry."""
    if not isinstance(raw, dict):
        return None
    region = raw.get("region")
    if not isinstance(region, dict):
        return None
    if not region.get("width") or not region.get("height"):
        return None
    sid = str(raw.get("id") or raw.get("label") or new_stream_id())
    label = str(raw.get("label") or sid)
    window_id = str(raw.get("window_id") or "combat")
    role = raw.get("role")
    channels = list(raw.get("channels") or [])
    filter_paths = list(raw.get("filter_paths") or [])
    if filter_paths and not channels:
        channels = channels_from_filter_paths(filter_paths)
    return {
        "id": sid,
        "label": label,
        "window_id": window_id,
        "role": role,
        "region": dict(region),
        "channels": channels,
        "filter_paths": filter_paths,
    }


def resolve_capture_streams(settings: dict, locallow: Path | None = None) -> list[dict]:
    """Return ready-to-capture streams from settings (legacy region → single stream)."""
    configured = settings.get("combat_streams") or []
    streams: list[dict] = []
    for raw in configured:
        norm = normalize_stream(raw)
        if norm:
            if locallow and not norm["channels"]:
                norm["channels"] = import_window_channels(locallow, norm["window_id"])
            streams.append(norm)
    if streams:
        return streams

    region = settings.get("combat_region")
    if isinstance(region, dict) and region.get("width") and region.get("height"):
        channels: list[str] = []
        if locallow:
            channels = import_window_channels(locallow, "combat")
        return [
            {
                "id": "default",
                "label": "Combat",
                "window_id": "combat",
                "role": "meter",
                "region": dict(region),
                "channels": channels,
                "filter_paths": [],
            }
        ]

    if locallow:
        layout = load_layout(locallow)
        est = layout.get("combat_region_estimate")
        if est:
            return [
                {
                    "id": "default",
                    "label": "Combat",
                    "window_id": "combat",
                    "role": "meter",
                    "region": dict(est),
                    "channels": layout.get("combat_meter_channels") or [],
                    "filter_paths": [],
                }
            ]
    return []


def allowed_channel_set(stream: dict) -> set[str] | None:
    """``None`` means accept all parsed events (no filter)."""
    chs = stream.get("channels") or []
    if not chs:
        return None
    return set(chs)


def event_allowed(event: dict, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    ch = event.get("channel") or infer_channel(event)
    if ch and ch in allowed:
        return True
    # Cast lifecycle lines often land on AbilityStatus without a clean channel match.
    return bool("AbilityStatus" in allowed and event.get("outcome") in ("interrupted", "fizzle"))


def stream_summary(streams: list[dict]) -> str:
    if not streams:
        return "no streams"
    parts = []
    for s in streams:
        ch_count = len(s.get("channels") or [])
        filt = f", {ch_count} filters" if ch_count else ", all channels"
        r = s["region"]
        parts.append(
            f"{s.get('label')} ({s.get('window_id')}) "
            f"{r['left']},{r['top']} {r['width']}×{r['height']}{filt}"
        )
    return "; ".join(parts)
