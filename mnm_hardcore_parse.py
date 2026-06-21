"""Parse character-select screenshot OCR text for Hardcore standings."""

from __future__ import annotations

import hashlib
import re

CHAR_LINE_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z'-]{1,23})\s*\(\s*(?P<level>\d{1,2})\s+(?P<race_class>.+?)\s*\)",
    re.I,
)
ZONE_RE = re.compile(r"Current\s+Zone\s*:\s*(.+)", re.I)
SERVER_MAP = (
    (re.compile(r"beta\s*server\s*pvp", re.I), "betapvp"),
    (re.compile(r"\bbetapvp\b", re.I), "betapvp"),
    (re.compile(r"\bharadrel\b", re.I), "haradrel"),
)


def parse_char_select_text(text: str) -> dict:
    """Extract character-select fields from OCR/plain text."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    blob = "\n".join(lines)

    hardcore = bool(re.search(r"(?<![A-Za-z])Hardcore(?![A-Za-z])", blob))
    name = level = race_class = zone = server = None

    for line in lines:
        m = CHAR_LINE_RE.search(line)
        if m and not name:
            name = m.group("name").strip()
            level = int(m.group("level"))
            race_class = m.group("race_class").strip()
        zm = ZONE_RE.search(line)
        if zm:
            zone = zm.group(1).strip()

    for pat, shard in SERVER_MAP:
        if pat.search(blob):
            server = shard
            break
    if not server:
        server = "betapvp"

    return {
        "character": name,
        "level": level,
        "race_class": race_class,
        "zone": zone,
        "server": server,
        "hardcore_detected": hardcore,
        "parse_ok": bool(name and level and hardcore),
    }


def profile_token(server: str, character: str, anchor: str) -> str:
    raw = f"{server}|{character}|{anchor}".casefold()
    return hashlib.sha256(raw.encode()).hexdigest()[:20]
