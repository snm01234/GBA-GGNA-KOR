#!/usr/bin/env python3
"""Measure name/SP/effect columns on ss4/ss6 ID-command rows."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PREV = ROOT / "outputs" / "20260909_idcmd_desc_overflow" / "previews"


def ink_cols(im: Image.Image, y0: int, y1: int, thresh: int = 180) -> list[int]:
    xs = []
    for y in range(y0, y1):
        for x in range(im.width):
            r, g, b = im.getpixel((x, y))[:3]
            if r > thresh and g > thresh and b > thresh * 0.6:
                xs.append(x)
    if not xs:
        return []
    return [min(xs), max(xs)]


def main():
    for n in (4, 6):
        im = Image.open(PREV / f"ss{n}_composite.png")
        print(f"ss{n} size", im.size)
        # native y of command rows ~48-120 at 4x
        for y0 in range(40 * 4, 128 * 4, 8):
            y1 = y0 + 16
            cols = ink_cols(im, y0, y1)
            if not cols:
                continue
            native = [c // 4 for c in cols]
            width = native[1] - native[0] + 1
            print(f"  y={y0//4:3d} ink x={native[0]:3d}-{native[1]:3d} w={width:3d} cells8={width/8:.1f} cells12={width/12:.1f}")


if __name__ == "__main__":
    main()
