"""Validate combat lines extracted from process memory (stricter than OCR)."""

from __future__ import annotations

import re

_COLOR_TAG = re.compile(r"^<color=[^>]+>", re.I)
_GARBAGE_MARKERS = (
    "You have no other party members",
    "You have not received any tells",
    "You have unlocked a cantrip",
    "You haven't specified",
    "You are now level {0}",
    "serialization system",
    "XmlAnyElementAttribute",
    "callback allocator",
    "Reference equality is defined",
    "Microsoft SQL Server",
    "Program Files",
)

_VALID_START = re.compile(
    r"^(?:You |Your |Your pet \S+|A |An |a |<color=|[A-Z][\w']+)",
    re.I,
)


def normalize_memory_line(raw: str) -> str:
    text = raw.strip()
    text = _COLOR_TAG.sub("", text).strip()
    text = text.rstrip("#+").strip()
    return text


def is_valid_memory_combat_line(raw: str) -> bool:
    from mnm_combat_text import parse_ocr_line

    text = normalize_memory_line(raw)
    if len(text) < 12 or len(text) > 150:
        return False
    if not _VALID_START.match(text):
        return False
    if any(m in text for m in _GARBAGE_MARKERS):
        return False
    if text.count(".") > 3 and "damage" not in text.lower():
        return False
    events = parse_ocr_line(text)
    if not events:
        return False
    ev = events[0]
    if ev.get("kind") == "death":
        actor = ev.get("actor") or ""
        target = ev.get("target") or ""
        if len(actor) > 40 or len(target) > 50:
            return False
    return not (ev.get("target") and len(ev.get("target", "")) > 60)
