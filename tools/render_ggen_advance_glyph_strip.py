#!/usr/bin/env python3
"""Render selected GBA atlas slots as a high-resolution inspection strip."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


BASE = 0x00094028
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


def decode12(raw: bytes) -> list[list[int]]:
    bits: list[int] = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return [bits[y * 12 : (y + 1) * 12] for y in range(12)]


def parse_slots(value: str) -> list[int]:
    result: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            left, right = part.split("-", 1)
            start, end = int(left, 0), int(right, 0)
            result.extend(range(start, end + 1))
        else:
            result.append(int(part, 0))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--slots", required=True, help="comma-separated slots or ranges, e.g. 0x51-0x7f")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("8x16", "12x12"), default="8x16")
    parser.add_argument("--columns", type=int, default=16)
    parser.add_argument("--no-label", action="store_true")
    parser.add_argument("--scale", type=int, default=8)
    args = parser.parse_args()
    data = args.rom.read_bytes()
    slots = parse_slots(args.slots)
    scale = max(1, args.scale)
    base = BASE if args.mode == "8x16" else 0x0008AC40
    stride = STRIDE if args.mode == "8x16" else 18
    width = 8 if args.mode == "8x16" else 12
    height = 16 if args.mode == "8x16" else 12
    cell_w = width * scale
    cell_h = height * scale
    gap = max(scale * 2, 8)
    label_h = max(scale * 2, 16)
    columns = max(1, min(len(slots), args.columns))
    rows = (len(slots) + columns - 1) // columns
    image = Image.new("L", (columns * (cell_w + gap) + gap, rows * (cell_h + label_h + gap) + gap), 0)
    draw = ImageDraw.Draw(image)
    for index, slot in enumerate(slots):
        raw = data[base + slot * stride : base + (slot + 1) * stride]
        glyph = Image.new("L", (width, height), 0)
        pixels = decode(raw) if args.mode == "8x16" else decode12(raw)
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                glyph.putpixel((x, y), 255 if value else 0)
        glyph = glyph.resize((cell_w, cell_h), Image.Resampling.NEAREST)
        col = index % columns
        row = index // columns
        x = gap + col * (cell_w + gap)
        y = gap + row * (cell_h + label_h + gap)
        image.paste(glyph, (x, y))
        if not args.no_label:
            draw.text((x, y + cell_h + 1), f"{slot:04X}", fill=180)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
