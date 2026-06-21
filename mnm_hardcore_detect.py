"""Detect Hardcore / Magnificent character status from journal + ledger kills.

In-game, committed characters show a **Hardcore** tag on the character select screen
(name, level, race/class, zone) and **Magnificent** in server announcements on level-up
or death. That flag is server-side — not written to LocalLow — so community members
submit a character-select screenshot via the Magnificent Hall submit page.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from mnm_local import JOURNAL_LINE

MALKIYAH_NPC = "Magnificent Malkiyah"
PLAYER_COMMIT_RE = re.compile(r"\bi\s+want\s+to\s+be\s+hardcore\b", re.I)
NPC_CONFIRM_PHRASES = (
    "your soul has committed",
    "you are now magnificent",
    "you have achieved magnificence",
    "welcome, magnificent one",
    "you are magnificent now",
)
NPC_REJECTION_PHRASES = (
    "too late for you",
    "it's too late",
    "it is too late",
)


def parse_journal_file(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = []
    for raw in text.splitlines():
        m = JOURNAL_LINE.match(raw.strip())
        if m:
            lines.append({"at": m.group(1), "speaker": m.group(2), "text": m.group(3)})
    return lines


def _npc_confirms(text: str) -> bool:
    low = text.casefold()
    return any(phrase in low for phrase in NPC_CONFIRM_PHRASES)


def _npc_rejects(text: str) -> bool:
    low = text.casefold()
    return any(phrase in low for phrase in NPC_REJECTION_PHRASES)


def classify_journal(
    lines: list[dict],
    *,
    character: str,
    server: str,
) -> tuple[str, str | None]:
    if not lines:
        return "none", None

    committed_at: str | None = None
    rejected_at: str | None = None

    for line in lines:
        text = line.get("text") or ""
        speaker = line.get("speaker") or ""
        at = line.get("at")
        if speaker == character and PLAYER_COMMIT_RE.search(text):
            return "magnificent", at
        if speaker != character and _npc_rejects(text):
            rejected_at = at
        if speaker != character and _npc_confirms(text):
            committed_at = at

    if committed_at:
        return "magnificent", committed_at
    if rejected_at:
        return "rejected", rejected_at

    if server.casefold() == "betapvp":
        last_at = max((ln.get("at") for ln in lines if ln.get("at")), default=None)
        return "candidate", last_at

    return "none", None


def profile_token(server: str, character: str, committed_at: str | None, first_seen: str | None) -> str:
    anchor = committed_at or first_seen or ""
    raw = f"{server}|{character}|{anchor}".casefold()
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _kill_stats(kills: list[dict]) -> dict:
    if not kills:
        return {
            "level": 0,
            "zone": None,
            "kills": 0,
            "first_seen": None,
            "last_seen": None,
            "fresh_rebirth": False,
        }
    sorted_kills = sorted(kills, key=lambda k: k.get("at") or "")
    levels = [int(k.get("character_level") or 0) for k in kills]
    latest = sorted_kills[-1]
    first = sorted_kills[0]
    return {
        "level": max(levels) if levels else 0,
        "zone": latest.get("zone"),
        "kills": len(kills),
        "first_seen": first.get("at"),
        "last_seen": latest.get("at"),
        "fresh_rebirth": int(first.get("character_level") or 0) == 1,
    }


def build_hardcore_profiles(
    locallow: Path,
    kills: list[dict],
    levelups: list[dict],
) -> list[dict]:
    """Build profiles for characters on this machine with Malkiyah journal activity."""
    by_char: dict[tuple[str, str], list[dict]] = {}
    for k in kills:
        server = k.get("server") or ""
        character = k.get("character") or ""
        if not server or not character:
            continue
        by_char.setdefault((server, character), []).append(k)

    profiles: list[dict] = []

    for path in sorted(locallow.rglob("journal/*")):
        if not path.is_file() or path.name != MALKIYAH_NPC:
            continue
        rel = path.relative_to(locallow)
        if len(rel.parts) < 3:
            continue
        server, character = rel.parts[0], rel.parts[1]
        key = (server, character)

        lines = parse_journal_file(path)
        status, committed_at = classify_journal(lines, character=character, server=server)
        if status in {"none", "rejected"}:
            continue

        stats = _kill_stats(by_char.get(key, []))
        if status == "candidate" and not stats["fresh_rebirth"]:
            continue

        lu_count = sum(
            1 for lu in levelups
            if lu.get("server") == server and lu.get("character") == character
        )
        if not committed_at:
            committed_at = stats["first_seen"]

        profiles.append({
            "server": server,
            "character": character,
            "status": status,
            "source": "journal",
            "level": stats["level"],
            "zone": stats["zone"],
            "kills": stats["kills"],
            "committed_at": committed_at,
            "first_seen": stats["first_seen"],
            "last_seen": stats["last_seen"],
            "levelups": lu_count,
            "profile_token": profile_token(server, character, committed_at, stats["first_seen"]),
        })

    profiles.sort(key=lambda p: (-p["level"], -p["kills"], p.get("committed_at") or ""))
    return profiles
