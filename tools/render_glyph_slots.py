#!/usr/bin/env python3
"""Render a selected set of 8x16 glyph slots from the clean GGA ROM."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


FONT_8X16 = 0x00094028
STRIDE = 32


def decode(raw: bytes) -> list[list[int]]:
    pixels = [[0] * 8 for _ in range(16)]
    for y in range(16):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                pixels[y][half * 4 + x] = value & 0x03
                value >>= 2
    return pixels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("slots", nargs="+", help="slot ids, e.g. 0x00D2 0x0041")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = args.rom.read_bytes()
    slots = [int(value, 0) for value in args.slots]
    columns = 8
    cell_width = 64
    cell_height = 66
    rows = (len(slots) + columns - 1) // columns
    image = Image.new("RGB", (columns * cell_width, rows * cell_height), "#1d2228")
    draw = ImageDraw.Draw(image)
    palette = [(29, 34, 40), (255, 255, 255), (150, 200, 255), (255, 170, 80)]
    for index, slot in enumerate(slots):
        if not 0 <= slot < 2068:
            raise ValueError(f"slot outside 8x16 table: 0x{slot:04X}")
        raw = data[FONT_8X16 + slot * STRIDE : FONT_8X16 + (slot + 1) * STRIDE]
        pixels = decode(raw)
        x0 = (index % columns) * cell_width + 24
        y0 = (index // columns) * cell_height + 4
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                image.putpixel((x0 + x * 4, y0 + y * 3), palette[value])
                image.putpixel((x0 + x * 4 + 1, y0 + y * 3), palette[value])
                image.putpixel((x0 + x * 4, y0 + y * 3 + 1), palette[value])
                image.putpixel((x0 + x * 4 + 1, y0 + y * 3 + 1), palette[value])
                image.putpixel((x0 + x * 4 + 2, y0 + y * 3), palette[value])
                image.putpixel((x0 + x * 4 + 3, y0 + y * 3), palette[value])
        draw.text(((index % columns) * cell_width + 2, (index // columns) * cell_height + 52), f"0x{slot:04X}", fill="#7d8794")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(str(args.out.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
