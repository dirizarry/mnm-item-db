#!/usr/bin/env python3
"""Crop the Race/Class panel and the attributes panel from character-creation
screenshots, upscale, and stitch into one legible image per source shot.

Outputs to data/creation_crops/<orig>.png for downstream extraction.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

SRC = Path(r"C:\Users\84dan\Documents\ShareX\Screenshots\2026-06")
OUT = Path(__file__).parent / "data" / "creation_crops"
OUT.mkdir(parents=True, exist_ok=True)

# Fractional crop boxes (left, top, right, bottom) for a 3840x1080 ultrawide shot.
RACE_BOX = (0.005, 0.03, 0.165, 0.72)  # Race/Class columns + description header
STAT_BOX = (0.905, 0.02, 1.0, 0.45)  # Points Remaining + 7 attributes
SCALE = 2


def crop_frac(im, box):
    w, h = im.size
    left, top, right, bottom = box
    return im.crop((int(left * w), int(top * h), int(right * w), int(bottom * h)))


def process(path: Path) -> Path:
    im = Image.open(path).convert("RGB")
    race = crop_frac(im, RACE_BOX)
    stat = crop_frac(im, STAT_BOX)
    # normalize heights, place side by side
    h = max(race.height, stat.height)

    def fit(c):
        if c.height != h:
            c = c.resize((int(c.width * h / c.height), h))
        return c

    race, stat = fit(race), fit(stat)
    combo = Image.new("RGB", (race.width + stat.width + 20, h), (20, 16, 12))
    combo.paste(race, (0, 0))
    combo.paste(stat, (race.width + 20, 0))
    combo = combo.resize((combo.width * SCALE, combo.height * SCALE), Image.LANCZOS)
    out = OUT / (path.stem + ".png")
    combo.save(out)
    return out


def main(argv):
    if argv:
        for name in argv:
            print(process(SRC / name))
    else:
        # batch: all jpgs in the creation time window passed via stdin list
        names = [line.strip() for line in sys.stdin if line.strip()]
        for n in names:
            process(SRC / n)
        print(f"Wrote {len(names)} crops to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
