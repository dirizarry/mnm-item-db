#!/usr/bin/env python3
"""Cut isometric map into draggable room PNGs. Run from site/maps/."""

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
DATA = json.loads((ROOT / "data" / "wyrmsbane-pieces.json").read_text(encoding="utf-8"))
REF = ROOT / DATA["refImage"]
OUT = ROOT / "pieces"
OUT.mkdir(exist_ok=True)

img = Image.open(REF).convert("RGBA")
for piece in DATA["pieces"]:
    x, y, w, h = piece["crop"]
    crop = img.crop((x, y, x + w, y + h))
    out_path = OUT / f"{piece['id']}.png"
    crop.save(out_path)
    print(f"  {piece['id']}: {w}x{h} -> {out_path.name}")

print(f"\nWrote {len(DATA['pieces'])} pieces to {OUT}")
