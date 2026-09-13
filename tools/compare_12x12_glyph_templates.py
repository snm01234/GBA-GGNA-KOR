#!/usr/bin/env python3
"""Compare the GGA 12x12 kana atlas with installed Japanese font glyphs.

This is a read-only diagnostic used to identify the compact low-kana order;
it never changes the ROM, source manifest, or translation outputs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_BASE = 0x0008AC40
STRIDE = 18
DEFAULT_FONT_PATHS = (
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
    Path(r"C:\Windows\Fonts\YuGothM.ttc"),
    Path(r"C:\Windows\Fonts\GOTHIC.TTF"),
)


def atlas_mask(data: bytes, slot: int) -> set[tuple[int, int]]:
    start = FONT_BASE + slot * STRIDE
    return {
        (x, y)
        for y in range(12)
        for x in range(12)
        if (data[start + (y * 12 + x) // 8] >> ((y * 12 + x) % 8)) & 1
    }


def font_mask(font: ImageFont.FreeTypeFont, char: str, dx: int, dy: int) -> set[tuple[int, int]]:
    image = Image.new("L", (24, 24), 0)
    ImageDraw.Draw(image).text((dx, dy), char, font=font, fill=255, stroke_width=0)
    return {
        (x, y)
        for y in range(12)
        for x in range(12)
        if image.getpixel((x, y)) >= 128
    }


def score(actual: set[tuple[int, int]], candidate: set[tuple[int, int]]) -> float:
    union = len(actual | candidate)
    return len(actual & candidate) / union if union else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--start", type=lambda value: int(value, 0), default=0x1D)
    parser.add_argument("--end", type=lambda value: int(value, 0), default=0x59)
    parser.add_argument("--font", type=Path, action="append")
    parser.add_argument("--size", type=int, action="append")
    args = parser.parse_args()
    data = args.rom.read_bytes()
    font_paths = tuple(args.font) if args.font else DEFAULT_FONT_PATHS
    chars = "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞたちぢつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわをん"
    for font_path in font_paths:
        if not font_path.exists():
            continue
        print(f"FONT {font_path}")
        sizes = args.size or list(range(10, 17))
        for size in sizes:
            font = ImageFont.truetype(str(font_path), size=size, index=0)
            candidate_masks = {
                char: [font_mask(font, char, dx, dy) for dx in range(-3, 4) for dy in range(-8, 4)]
                for char in chars
            }
            best_by_slot: list[str] = []
            for slot in range(args.start, args.end):
                actual = atlas_mask(data, slot)
                ranked: list[tuple[float, str]] = []
                for char in chars:
                    best = max(score(actual, mask) for mask in candidate_masks[char])
                    ranked.append((best, char))
                ranked.sort(reverse=True)
                best_by_slot.append(
                    f"{slot:02X}:" + ",".join(f"U+{ord(char):04X}:{value:.2f}" for value, char in ranked[:5])
                )
            print(f"SIZE {size} " + " ".join(best_by_slot))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
