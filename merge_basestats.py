#!/usr/bin/env python3
"""Merge data/base_stats_part*.json into data/base_stats.json (dedup by source)."""

import glob
import json
from pathlib import Path

ROOT = Path(__file__).parent / "data"
merged = {}
for f in sorted(glob.glob(str(ROOT / "base_stats_part*.json"))):
    for rec in json.loads(Path(f).read_text(encoding="utf-8")):
        merged[rec.get("source") or f"{rec.get('race')}|{rec.get('class')}"] = rec
rows = list(merged.values())
(ROOT / "base_stats.json").write_text(
    json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
)
combos = sorted({f"{r.get('race')}/{r.get('class')}" for r in rows})
print(f"Merged {len(rows)} records, {len(combos)} distinct race/class combos.")
nullc = [r.get("source") for r in rows if not r.get("race") or not r.get("class")]
if nullc:
    print("Records missing race/class:", nullc)
