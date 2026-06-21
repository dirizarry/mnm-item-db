import json
from collections import Counter
from pathlib import Path

from mnm_combat_text import parse_line

events = json.loads(Path("data/combat-events.json").read_text(encoding="utf-8"))
start = "2026-06-19T16:17:52"
sess = [e for e in events if e["ts"] >= start]
print(f"Session events: {len(sess)} (total {len(events)})")
print("kinds:", dict(Counter(e["kind"] for e in sess)))

json_ocr = [
    e
    for e in sess
    if '"' in e.get("raw", "") or "kind" in e.get("raw", "") and ":" in e.get("raw", "")
]
print(f"json-ish OCR lines: {len(json_ocr)}")

for e in sess:
    amt = e.get("amount") or 0
out = sum(
    e.get("amount") or 0
    for e in sess
    if e["kind"] in ("melee", "ability", "dot") and e.get("direction") == "outgoing"
)
inn = sum(
    e.get("amount") or 0
    for e in sess
    if e["kind"] in ("melee", "ability", "dot") and e.get("direction") == "incoming"
)
neutral = sum(e.get("amount") or 0 for e in sess if e["kind"] == "damage")
heal = sum(e.get("amount") or 0 for e in sess if e["kind"] == "heal")
print(f"stored totals: out={out} in={inn} neutral_damage={neutral} heal={heal}")

# Re-parse session
reparsed = [parse_line(e["raw"]) for e in sess]
reparsed = [p for p in reparsed if p]
r_out = sum(
    p.get("amount") or 0
    for p in reparsed
    if p["kind"] in ("melee", "ability", "dot") and p.get("direction") == "outgoing"
)
r_in = sum(
    p.get("amount") or 0
    for p in reparsed
    if p["kind"] in ("melee", "ability", "dot") and p.get("direction") == "incoming"
)
r_neutral = sum(p.get("amount") or 0 for p in reparsed if p["kind"] == "damage")
print(f"re-parsed: out={r_out} in={r_in} neutral_damage={r_neutral} events={len(reparsed)}")

miss = [e["raw"] for e in sess if not parse_line(e["raw"]) and len(e.get("raw", "")) > 8]
print(f"unparsed ({len(miss)}):")
for m in miss[:10]:
    print(f"  {m[:90]}")

# Test fixed lines
tests = [
    '": "a snake bites Termosas for 3 points of damage.',
    "a snake bites Termosas for 3 points of damage.",
    "points of Magic Damage.",
    '"kind": "damage",',
]
print("--- parse tests ---")
for t in tests:
    p = parse_line(t)
    print(
        repr(t[:50]),
        "->",
        p.get("kind"),
        p.get("actor"),
        p.get("target"),
        p.get("amount") if p else None,
    )
