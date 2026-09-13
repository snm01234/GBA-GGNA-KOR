#!/usr/bin/env python3
"""Render a labeled range of the Advance 8x16 glyph slots for OCR/review."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_BASE = 0x00094028
FONT_COUNT = 2068
FONT_STRIDE = 32


def decode(raw: bytes) -> list[list[int]]:
    pixels = [[0] * 8 for _ in range(16)]
    for y in range(16):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                pixels[y][half * 4 + x] = value & 0x03
                value >>= 2
    return pixels


def render(data: bytes, start: int, end: int, out: Path) -> None:
    start = max(0, start)
    end = min(FONT_COUNT, end)
    scale = 6
    columns = 8
    cell_w = 80
    cell_h = 124
    rows = (end - start + columns - 1) // columns
    image = Image.new("RGB", (columns * cell_w, rows * cell_h), "#20252b")
    draw = ImageDraw.Draw(image)
    palette = [(32, 37, 43), (255, 255, 255), (160, 205, 255), (255, 170, 90)]
    for slot in range(start, end):
        raw = data[FONT_BASE + slot * FONT_STRIDE : FONT_BASE + (slot + 1) * FONT_STRIDE]
        pixels = decode(raw)
        cell_x = (slot - start) % columns * cell_w
        cell_y = (slot - start) // columns * cell_h
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                color = palette[value]
                image.paste(color, (cell_x + x * scale, cell_y + y * scale, cell_x + (x + 1) * scale, cell_y + (y + 1) * scale))
        label = f"0x{slot:04X}"
        draw.text((cell_x + 2, cell_y + 99), label, fill="#8fd3ff")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("--start", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--end", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    render(args.rom.read_bytes(), args.start, args.end, args.out)
    print(args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
