#!/usr/bin/env python3
"""Find pre-rendered forecast labels in pointer-referenced custom-LZSS atlases.

This is a read-only ROM diagnostic.  It compares the original 12x12 font
bitmaps for the forecast badge characters with every colour plane in each
pointer-referenced custom-LZSS 4bpp resource.  No emulator state is used.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

from build_ggen_advance_status_ui_tile_overlay_poc import lzss_decompress


ROM_BASE = 0x08000000
FONT_BASE = 0x0008AC40
FONT_STRIDE = 18
TARGETS = {
    "U+5B9F": 0x0381,  # 実
    "U+653B": 0x02F0,  # 攻
    "U+547D": 0x00DA,  # 命
    "U+5F3E": 0x00CC,  # 弾
    "U+5C04": 0x0382,  # 射
    "U+5358": 0x04D0,  # 単
    "U+5168": 0x00C5,  # 全
    "U+8FD1": 0x0271,  # 近
}


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def glyph_mask(data: bytes, slot: int) -> set[tuple[int, int]]:
    start = FONT_BASE + slot * FONT_STRIDE
    raw = data[start : start + FONT_STRIDE]
    return {
        (x, y)
        for y in range(12)
        for x in range(12)
        if (raw[(y * 12 + x) // 8] >> ((y * 12 + x) % 8)) & 1
    }


def tile(data: bytes, index: int) -> list[list[int]]:
    raw = data[index * 32 : (index + 1) * 32]
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 15) for x in range(8)]
        for y in range(8)
    ]


def score(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def candidates(data: bytes) -> list[tuple[int, int]]:
    pointer_targets = {
        value - ROM_BASE
        for offset in range(0, len(data) - 3, 2)
        if ROM_BASE <= (value := u32(data, offset)) < ROM_BASE + len(data)
    }
    found = []
    for offset in pointer_targets:
        # Real resources in this family are word-aligned.  Requiring alignment
        # rejects accidental high-bit words inside text/font payloads.
        if offset & 3:
            continue
        if offset + 4 > len(data):
            continue
        header = u32(data, offset)
        length = header & 0x7FFFFFFF
        if header & 0x80000000 and 8 <= length <= 0x20000 and offset + 4 + length <= len(data):
            found.append((offset, length))
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    sources = {name: glyph_mask(rom, slot) for name, slot in TARGETS.items()}
    ranked: dict[str, list[tuple[float, int, int, int, int, int, int]]] = {name: [] for name in TARGETS}

    for resource, compressed_length in candidates(rom):
        try:
            decoded = lzss_decompress(rom[resource + 4 : resource + 4 + compressed_length])
        except (IndexError, SystemExit):
            continue
        tile_count = len(decoded) // 32
        if tile_count < 4:
            continue
        tiles = [tile(decoded, index) for index in range(tile_count)]
        # These resources are uploaded as GBA character blocks and inspected in
        # the two conventional atlas widths.  Trying every possible width only
        # manufactures accidental adjacencies and obscures provenance.
        for width in (16, 32):
            if tile_count < width * 2:
                continue
            height = tile_count // width
            for ty in range(height - 1):
                for tx in range(width - 1):
                    ids = (ty * width + tx, ty * width + tx + 1, (ty + 1) * width + tx, (ty + 1) * width + tx + 1)
                    block = [[0] * 16 for _ in range(16)]
                    for quadrant, tile_id in enumerate(ids):
                        ox, oy = (quadrant & 1) * 8, (quadrant >> 1) * 8
                        for y, row in enumerate(tiles[tile_id]):
                            for x, value in enumerate(row):
                                block[oy + y][ox + x] = value
                    for colour in range(1, 16):
                        for dy in range(5):
                            for dx in range(5):
                                mask = {(x, y) for y in range(12) for x in range(12) if block[dy + y][dx + x] == colour}
                                if len(mask) < 8:
                                    continue
                                for name, source in sources.items():
                                    value = score(source, mask)
                                    row = (value, resource, compressed_length, width, ids[0], colour, dx | (dy << 8))
                                    best = ranked[name]
                                    if len(best) < args.top or value > best[0][0]:
                                        best.append(row)
                                        best.sort()
                                        del best[:-args.top]

    for name, slot in TARGETS.items():
        print(f"{name} slot=0x{slot:04X}")
        for value, resource, clen, width, first_tile, colour, shift in reversed(ranked[name]):
            print(
                f"  score={value:.4f} resource=0x{resource:08X} compressed=0x{clen:X} "
                f"width={width} tile=0x{first_tile:X} colour={colour} dx={shift & 255} dy={shift >> 8}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
