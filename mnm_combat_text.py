"""Parse MnM combat chat lines (EQ-style text) into structured events.

Uses structural patterns — amount tails, participant markers (You / YOU / your pet),
and message boundaries — rather than enumerating every melee verb or spell name.

Events include ``outcome`` and inferred ``channel`` (maps to ``chats.json`` categories)
for per-ability analytics, interrupt/resist rates, and multi-window capture.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from mnm_combat_channels import infer_channel

# OCR noise fixes applied during normalization.
_OCR_FIXES: tuple[tuple[str, str], ...] = (
    ("|", "l"),
    ("O points", "0 points"),
    (" ot ", " of "),
    (" tor ", " for "),
    (" ror ", " for "),
    (" pomt ", " point "),
    (" orave ", " grave "),
    (" aamage", " damage"),
    ("soiderling", "spiderling"),
    (" tire beetle", " fire beetle"),
    (" heals vou ", " heals you "),
    ("St0DDed", "Stopped"),
    ("St0D", "Sto"),
    (" dan ", " damage "),
    (" D0ints", " points"),
    ("COMBAT ", ""),
    ("Sto ed attackin", "Stopped attacking"),
    ("Sto ed attacking", "Stopped attacking"),
    ("rottingz", "rotting"),
    (" bv ", " by "),
    ("Mootofs", "Mooto's"),
)

_MESSAGE_SPLIT = re.compile(
    r"(?<=[.!])\s+"
    r"(?=(?:You |Your |A |a |An |The |Guard |Starting |Stopped |[A-Z][a-z]))",
    re.I,
)

_GLUE_INCOMPLETE = re.compile(
    r" for \d+ points? of (?=(?:You |Your |[A-Z][a-z]|a |an |the ))",
)

_GLUE_MID_LINE = re.compile(
    r" for \d+ points? of (?=(?:You |Your |Guard |a |an |the |[A-Z][A-Za-z']+ ))",
)

_GLUE_TAIL_START = re.compile(
    r"^(?:You |Your |Guard |Starting |Stopped |[A-Z][A-Za-z']|a |an |the )",
    re.I,
)

_COMBAT_HEADER = re.compile(r"^COMBAT\s*", re.I)

_RE_DAMAGE = re.compile(
    r"^(?P<prefix>.+?) for (?P<amount>\d+) points? of "
    r"(?P<dtype>.*?)(?:damage|Damage)\s*[.!]?$",
    re.I,
)

_RE_HEAL = re.compile(
    r"^(?P<prefix>.+)\s+heals?\s+(?P<heal_target>you|.+?)\s+for\s+(?P<amount>\d+)"
    r"(?:\s+(?:points?|Health))?\s*[.!]?$",
    re.I,
)

_RE_MISS = re.compile(
    r"^(?P<actor>You|Your pet \S+|\S+(?:\s+\S+)*?) tries? to (?P<verb>\w+)"
    r" (?P<target>.+?), but (?P<result>miss(?:es)?|parr(?:y|ies)|dodge(?:s)?|block(?:s)?)",
    re.I,
)

_RE_MISS_YOU = re.compile(
    r"^You try to (?P<verb>\w+) (?P<target>.+?), but miss!?\.?$",
    re.I,
)

_RE_SLAIN = re.compile(
    r"^(?P<killer>You|Your pet \S+|\S+(?:\s+\S+)*?) have(?:s)? slain (?P<victim>.+?)\s*[.!]?$",
    re.I,
)

_RE_PET_SLAIN = re.compile(
    r"^Your pet (\S+) has slain (.+?)\s*[.!]?$",
    re.I,
)

_RE_SLAIN_BY = re.compile(
    r"^(?P<victim>\S+(?:\s+\S+)*?) has been slain by (?P<killer>.+?)\s*[.!]?$",
    re.I,
)

_RE_XP = re.compile(r"^You have gained (?P<amount>\d+) experience", re.I)
_RE_CAST = re.compile(r"^You begin casting (?P<spell>.+?)\.?$", re.I)
_RE_CAST_INTERRUPT = re.compile(r"^Your casting is interrupted", re.I)
_RE_FIZZLE = re.compile(r"^Your (?P<spell>.+?) fizzles!?\.?$", re.I)
_RE_SPELL_FIZZLE = re.compile(r"^Your spell fizzles!?\.?$", re.I)
_RE_RESISTED_BY = re.compile(
    r"^Your (?P<spell>.+?) was resisted by (?P<target>.+?)\s*[.!]?$",
    re.I,
)
_RE_RESIST_YOU = re.compile(
    r"^(?P<actor>.+?) resisted your (?P<spell>.+?)\s*[.!]?$",
    re.I,
)
_RE_YOU_RESIST = re.compile(r"^You resist (?P<spell>.+?)\s*[.!]?$", re.I)

_RE_STATUS_ATTACK = re.compile(r"^(?P<status>Starting|Stopped) attacking[.!]?$", re.I)
_RE_ABSORB = re.compile(
    r"^(?P<actor>.+?) hits? (?P<target>.+?) but (?:they )?absorb",
    re.I,
)
_RE_ANGRY = re.compile(
    r"^(?P<actor>.+?) looks angry at (?P<target>.+?)\s*[.!]?$",
    re.I,
)
_RE_FAR = re.compile(r"^You try to attack, but you are too far away", re.I)
_RE_FACE = re.compile(r"^You try to attack, but you must face your target", re.I)
_RE_STRUCK = re.compile(
    r"^(?P<target>.+?) is struck by (?P<source>.+?)\s*[.!]?$",
    re.I,
)

_PLAYER_NAME = re.compile(r"^[A-Z][A-Za-z']+$")
_MONSTER_START = re.compile(r"^(?:a |an |the )", re.I)

COMBAT_LINE_PATTERNS: list[tuple[re.Pattern, str, str]] = []


def normalize_line(raw: str) -> str:
    """Collapse OCR whitespace and fix common misreads."""
    text = " ".join(raw.split())
    for old, new in _OCR_FIXES:
        text = text.replace(old, new)
    text = re.sub(r"(\d) \1 points", r"\1 points", text)
    return text.strip()


def split_combat_messages(text: str) -> list[str]:
    """Split OCR blob or pasted log into individual combat messages."""
    text = normalize_line(text)
    text = _COMBAT_HEADER.sub("", text).strip()
    if len(text) < 6:
        return []
    parts = _MESSAGE_SPLIT.split(text)
    messages = [p.strip() for p in parts if len(p.strip()) >= 6]
    return messages if messages else [text]


def split_glued_combat_line(raw: str) -> list[str]:
    """Split OCR rows where two chat messages were merged on one line."""
    line = normalize_line(raw)
    if len(line) < 6:
        return []

    def split_once(text: str) -> list[str]:
        for ending in (
            " points of damage. ",
            " points of damage ",
            " points of Damage. ",
            " points of Damage ",
            " Health. ",
        ):
            if ending in text:
                left, right = text.split(ending, 1)
                if len(left.strip()) >= 6 and len(right.strip()) >= 6:
                    return [left.strip() + ending.strip(), right.strip()]

        m = _GLUE_MID_LINE.search(text)
        if m:
            prefix = text[:m.start()].rstrip()
            tail = text[m.end():].strip()
            if len(prefix) >= 6 and len(tail) >= 6 and _GLUE_TAIL_START.match(tail):
                amt_m = re.search(r"for (\d+) points?", text[m.start():m.end()], re.I)
                n = amt_m.group(1) if amt_m else "1"
                return [f"{prefix} for {n} point of damage.", tail]

        m = _GLUE_INCOMPLETE.search(text)
        if m:
            prefix = text[:m.start()].rstrip()
            tail = text[m.end():].strip()
            if len(prefix) >= 6 and len(tail) >= 6 and _GLUE_TAIL_START.match(tail):
                amt_m = re.search(r"for (\d+) points?", text[m.start():m.end()], re.I)
                n = amt_m.group(1) if amt_m else "1"
                return [f"{prefix} for {n} point of damage.", tail]

        return [text]

    parts = [line]
    for _ in range(8):
        new_parts: list[str] = []
        any_split = False
        for part in parts:
            subs = split_once(part)
            if len(subs) > 1:
                any_split = True
            new_parts.extend(subs)
        parts = new_parts
        if not any_split:
            break
    return parts


def _ts(ts: str | None) -> str:
    return ts or datetime.now(timezone.utc).isoformat()


def _event(
    raw: str,
    ts: str | None,
    kind: str,
    direction: str,
    outcome: str | None = None,
    **fields,
) -> dict:
    ev = {
        "ts": _ts(ts),
        "raw": raw.strip(),
        "kind": kind,
        "direction": direction,
        "outcome": outcome,
        "actor": fields.get("actor"),
        "target": fields.get("target"),
        "verb": fields.get("verb"),
        "ability": fields.get("ability"),
        "amount": fields.get("amount"),
        "source": fields.get("source"),
        "pet": fields.get("pet"),
        "damage_type": fields.get("damage_type"),
        "channel": fields.get("channel"),
        "stream_id": fields.get("stream_id"),
    }
    if not ev["channel"]:
        ev["channel"] = infer_channel(ev)
    return ev


def _parse_heal_actors(prefix: str) -> tuple[str, str | None]:
    p = prefix.strip()
    if p.lower().startswith("your "):
        return "You", p[5:].strip() or None
    m = re.match(r"^(.+?)'s (.+)$", p)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return p, None


def _is_player_name(name: str) -> bool:
    n = name.strip()
    if not n or n in ("You", "YOU"):
        return False
    if _MONSTER_START.match(n):
        return False
    return bool(_PLAYER_NAME.match(n.split()[0]))


def _infer_damage_prefix(prefix: str) -> dict:
    """Classify actor/target/direction from text before ``for N points of … damage``."""
    p = prefix.strip()

    m = re.match(r"^Your pet ([^']+)'s (.+?) hits? (.+)$", p, re.I)
    if m:
        pet = m.group(1).strip()
        return {
            "kind": "ability", "direction": "outgoing", "outcome": "hit",
            "actor": pet, "pet": pet, "ability": m.group(2).strip(),
            "target": m.group(3).strip(), "verb": "hit",
        }

    m = re.match(r"^Your pet (\S+) (\w+) ((?:a |an |the ).+)$", p, re.I)
    if m:
        pet = m.group(1).strip()
        return {
            "kind": "melee", "direction": "outgoing", "outcome": "hit",
            "actor": pet, "pet": pet, "target": m.group(3).strip(),
            "verb": m.group(2).strip(),
        }

    m = re.match(r"^Your pet (\S+) hits? (.+)$", p, re.I)
    if m:
        pet = m.group(1).strip()
        return {
            "kind": "melee", "direction": "outgoing", "outcome": "hit",
            "actor": pet, "pet": pet, "target": m.group(2).strip(), "verb": "hit",
        }

    m = re.match(r"^Your (.+?) hits? (.+)$", p, re.I)
    if m and not m.group(1).strip().lower().startswith("pet "):
        return {
            "kind": "ability", "direction": "outgoing", "outcome": "hit",
            "actor": "You", "ability": m.group(1).strip(),
            "target": m.group(2).strip(), "verb": "hit",
        }

    m = re.match(r"^(.+?)'s (.+?) hits? your pet (.+)$", p, re.I)
    if m:
        pet = m.group(3).strip()
        return {
            "kind": "ability", "direction": "incoming", "outcome": "hit",
            "actor": m.group(1).strip(), "ability": m.group(2).strip(),
            "target": pet, "pet": pet, "verb": "hit",
        }

    m = re.match(r"^(.+?)'s (.+?) hits? YOU$", p, re.I)
    if m:
        return {
            "kind": "ability", "direction": "incoming", "outcome": "hit",
            "actor": m.group(1).strip(), "ability": m.group(2).strip(),
            "target": "You", "verb": "hit",
        }

    m = re.match(r"^(.+?)'s (.+?) hits? (.+)$", p, re.I)
    if m and " your pet " not in p.lower() and not p.endswith("YOU"):
        actor = m.group(1).strip()
        direction = "outgoing" if actor == "You" else "neutral"
        return {
            "kind": "ability", "direction": direction, "outcome": "hit",
            "actor": actor, "ability": m.group(2).strip(),
            "target": m.group(3).strip(), "verb": "hit",
        }

    m = re.match(r"^You (.+?) ((?:a |an |the ).+)$", p, re.I)
    if m:
        return {
            "kind": "melee", "direction": "outgoing", "outcome": "hit",
            "actor": "You", "verb": m.group(1).strip(), "target": m.group(2).strip(),
        }

    m = re.match(r"^(.+?) (\w+) your pet (.+)$", p, re.I)
    if m:
        pet = m.group(3).strip()
        return {
            "kind": "melee", "direction": "incoming", "outcome": "hit",
            "actor": m.group(1).strip(), "verb": m.group(2).strip(),
            "target": pet, "pet": pet,
        }

    m = re.match(r"^(.+?) (\w+) YOU$", p, re.I)
    if m:
        return {
            "kind": "melee", "direction": "incoming", "outcome": "hit",
            "actor": m.group(1).strip(), "verb": m.group(2).strip(), "target": "You",
        }

    m = re.match(r"^(.+?) hits? (.+)$", p, re.I)
    if m:
        actor, target = m.group(1).strip(), m.group(2).strip()
        if _is_player_name(target) and not _MONSTER_START.match(target):
            return {
                "kind": "melee", "direction": "neutral", "outcome": "hit",
                "actor": actor, "target": target, "verb": "hit",
            }
        if _is_player_name(actor):
            return {
                "kind": "melee", "direction": "neutral", "outcome": "hit",
                "actor": actor, "target": target, "verb": "hit",
            }
        return {
            "kind": "melee", "direction": "neutral", "outcome": "hit",
            "actor": actor, "target": target, "verb": "hit",
        }

    m = re.match(r"^((?:a |an |the ).+?) (\w+) ([A-Za-z][A-Za-z']+)$", p, re.I)
    if m and _is_player_name(m.group(3)):
        return {
            "kind": "melee", "direction": "neutral", "outcome": "hit",
            "actor": m.group(1).strip(), "verb": m.group(2).strip(),
            "target": m.group(3).strip(),
        }

    m = re.match(r"^([A-Za-z][A-Za-z']+) (\w+) ((?:a |an |the ).+)$", p)
    if m and m.group(1) not in ("You", "Your"):
        return {
            "kind": "melee", "direction": "neutral", "outcome": "hit",
            "actor": m.group(1).strip(), "verb": m.group(2).strip(),
            "target": m.group(3).strip(),
        }

    m = re.match(r"^([A-Za-z][A-Za-z']+) (\w+) ([A-Za-z][A-Za-z']+)$", p)
    if m and m.group(1) not in ("You", "Your") and _is_player_name(m.group(3)):
        return {
            "kind": "melee", "direction": "neutral", "outcome": "hit",
            "actor": m.group(1).strip(), "verb": m.group(2).strip(),
            "target": m.group(3).strip(),
        }

    return {"kind": "damage", "direction": "neutral", "outcome": "hit", "actor": None, "target": None}


def _parse_structural(line: str, ts: str | None, stream_id: str | None = None) -> dict | None:
    """Match one combat message using structural patterns."""
    extra = {"stream_id": stream_id} if stream_id else {}

    if _RE_FAR.match(line):
        return _event(line, ts, "status", "neutral", outcome="too_far", verb="too_far", **extra)

    if _RE_FACE.match(line):
        return _event(line, ts, "status", "neutral", outcome="face_target", verb="face_target", **extra)

    m = _RE_DAMAGE.match(line)
    if m:
        meta = _infer_damage_prefix(m.group("prefix"))
        dtype = (m.group("dtype") or "").strip() or None
        return _event(
            line, ts, meta.get("kind", "damage"), meta["direction"],
            outcome=meta.get("outcome", "hit"),
            amount=int(m.group("amount")),
            damage_type=dtype,
            actor=meta.get("actor"),
            target=meta.get("target"),
            verb=meta.get("verb"),
            ability=meta.get("ability"),
            pet=meta.get("pet"),
            **extra,
        )

    m = _RE_HEAL.match(line)
    if m:
        actor, ability = _parse_heal_actors(m.group("prefix"))
        ht = m.group("heal_target").strip()
        amount = int(m.group("amount"))
        target = "You" if ht.lower() == "you" else ht
        if actor == "You":
            direction = "outgoing"
        elif target == "You":
            direction = "incoming"
        else:
            direction = "neutral"
        return _event(
            line, ts, "heal", direction, outcome="heal", amount=amount,
            actor=actor, target=target, ability=ability, **extra,
        )

    m = _RE_MISS_YOU.match(line) or _RE_MISS.match(line)
    if m:
        actor = m.groupdict().get("actor") or "You"
        pet = None
        target = m.group("target").strip()
        result = m.groupdict().get("result") or "miss"
        outcome = result.lower().replace("es", "").replace("ies", "y")
        if actor.lower().startswith("your pet "):
            pet = actor[9:].strip()
        elif target.lower().startswith("your pet "):
            pet = target[9:].strip()
            target = pet
        direction = "outgoing" if actor == "You" else "incoming"
        if pet and actor != "You":
            direction = "incoming"
        return _event(
            line, ts, "miss", direction, outcome=outcome,
            actor=actor if actor != "You" else "You",
            pet=pet,
            verb=m.group("verb"),
            target=target if target != "YOU" else "You",
            **extra,
        )

    m = _RE_PET_SLAIN.match(line)
    if m:
        pet = m.group(1).strip()
        return _event(
            line, ts, "death", "outgoing", outcome="slain",
            actor=pet, pet=pet, target=m.group(2).strip(), **extra,
        )

    m = _RE_SLAIN.match(line)
    if m:
        killer = m.group("killer").strip()
        pet = None
        if killer.lower().startswith("your pet "):
            pet = killer[9:].strip()
            actor = pet
        elif killer == "You":
            actor = "You"
        else:
            actor = killer
        direction = "outgoing" if actor == "You" or pet else "neutral"
        return _event(
            line, ts, "death", direction, outcome="slain",
            actor=actor, pet=pet, target=m.group("victim").strip(), **extra,
        )

    m = _RE_SLAIN_BY.match(line)
    if m:
        return _event(
            line, ts, "death", "neutral", outcome="slain",
            target=m.group("victim").strip(), actor=m.group("killer").strip(), **extra,
        )

    m = _RE_XP.match(line)
    if m:
        return _event(line, ts, "experience", "neutral", outcome="gain", amount=int(m.group("amount")), **extra)

    m = _RE_CAST.match(line)
    if m:
        return _event(
            line, ts, "cast", "outgoing", outcome="begin",
            actor="You", ability=m.group("spell").strip(), verb="casting", **extra,
        )

    if _RE_CAST_INTERRUPT.match(line):
        return _event(line, ts, "cast", "outgoing", outcome="interrupted", actor="You", verb="interrupted", **extra)

    m = _RE_SPELL_FIZZLE.match(line) or _RE_FIZZLE.match(line)
    if m:
        spell = m.groupdict().get("spell")
        return _event(
            line, ts, "cast", "outgoing", outcome="fizzle",
            actor="You", ability=(spell or "").strip() or None, verb="fizzle", **extra,
        )

    m = _RE_RESISTED_BY.match(line) or _RE_RESIST_YOU.match(line) or _RE_YOU_RESIST.match(line)
    if m:
        spell = m.groupdict().get("spell", "").strip()
        target = m.groupdict().get("target")
        actor = m.groupdict().get("actor")
        if actor:
            return _event(
                line, ts, "ability", "incoming", outcome="resist",
                actor=actor.strip(), ability=spell, target="You", **extra,
            )
        if target:
            return _event(
                line, ts, "ability", "outgoing", outcome="resist",
                actor="You", ability=spell, target=target.strip(), **extra,
            )
        return _event(
            line, ts, "ability", "incoming", outcome="resist",
            actor="You", ability=spell, **extra,
        )

    m = _RE_STATUS_ATTACK.match(line)
    if m:
        return _event(line, ts, "status", "neutral", outcome=m.group("status").lower(), verb=m.group("status").lower(), **extra)

    m = _RE_ABSORB.match(line)
    if m:
        return _event(
            line, ts, "absorb", "neutral", outcome="absorb",
            actor=m.group("actor").strip(), target=m.group("target").strip(), **extra,
        )

    m = _RE_ANGRY.match(line)
    if m:
        return _event(
            line, ts, "status", "neutral", outcome="angry",
            actor=m.group("actor").strip(), target=m.group("target").strip(), verb="angry", **extra,
        )

    m = _RE_STRUCK.match(line)
    if m:
        return _event(
            line, ts, "ability", "neutral", outcome="hit",
            target=m.group("target").strip(), source=m.group("source").strip(), **extra,
        )

    return None


def parse_line(raw: str, ts: str | None = None, stream_id: str | None = None) -> dict | None:
    """Parse a single combat message (call ``split_glued_combat_line`` for merged OCR)."""
    line = normalize_line(raw)
    if len(line) < 6:
        return None
    return _parse_structural(line, ts, stream_id=stream_id)


def parse_ocr_line(raw: str, ts: str | None = None, stream_id: str | None = None) -> list[dict]:
    """Parse one OCR row, splitting glued messages when needed."""
    events: list[dict] = []
    for part in split_glued_combat_line(raw):
        ev = parse_line(part, ts=ts, stream_id=stream_id)
        if ev:
            events.append(ev)
    return events


def parse_lines(text: str, ts: str | None = None, stream_id: str | None = None) -> list[dict]:
    """Parse all combat messages in OCR text or a pasted log."""
    return parse_message_list(split_combat_messages(text), ts=ts, stream_id=stream_id)


def parse_message_list(
    messages: list[str],
    ts: str | None = None,
    stream_id: str | None = None,
) -> list[dict]:
    """Parse an ordered list of combat chat lines."""
    events: list[dict] = []
    for msg in messages:
        events.extend(parse_ocr_line(msg, ts=ts, stream_id=stream_id))
    return events
