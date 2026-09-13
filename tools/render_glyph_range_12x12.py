#!/usr/bin/env python3
"""Render labeled 12x12 1bpp glyph slots from the clean GGA ROM."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


FONT_12X12 = 0x0008AC40
STRIDE = 18


def decode(raw: bytes) -> list[list[int]]:
    bits: list[int] = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return [bits[y * 12 : (y + 1) * 12] for y in range(12)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("start", type=lambda value: int(value, 0))
    parser.add_argument("end", type=lambda value: int(value, 0))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--columns", type=int, default=16)
    args = parser.parse_args()
    data = args.rom.read_bytes()
    slots = list(range(args.start, args.end))
    if not slots or min(slots) < 0 or max(slots) >= 1992:
        raise ValueError("slot range outside 12x12 table")
    scale = args.scale
    cell_width = 14 * scale
    cell_height = 15 * scale
    rows = (len(slots) + args.columns - 1) // args.columns
    image = Image.new("RGB", (args.columns * cell_width, rows * cell_height), "#1d2228")
    draw = ImageDraw.Draw(image)
    for index, slot in enumerate(slots):
        raw = data[FONT_12X12 + slot * STRIDE : FONT_12X12 + (slot + 1) * STRIDE]
        pixels = decode(raw)
        x0 = (index % args.columns) * cell_width + scale
        y0 = (index // args.columns) * cell_height + scale
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                if value:
                    draw.rectangle(
                        (x0 + x * scale, y0 + y * scale,
                         x0 + (x + 1) * scale - 1, y0 + (y + 1) * scale - 1),
                        fill="#FFFFFF",
                    )
        draw.text(
            ((index % args.columns) * cell_width + scale, (index // args.columns) * cell_height + 13 * scale),
            f"{slot:02X}",
            fill="#7d8794",
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(str(args.out.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
