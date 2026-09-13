#!/usr/bin/env python3
"""Infer the shared 32x16 plaque template across ss4 stat-badge resources 20..27."""
from __future__ import annotations

import collections
import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import build_ggen_advance_status_ui_tile_overlay_poc as status
from ggen_advance_project_paths import MAIN_TIP_ROM

TABLE = 0x000E0518
FAMILY = tuple(range(20, 28))


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_map(data: bytes, index: int) -> dict:
    obj = sem.parse_map(data, u32(data, TABLE + index * 4))
    assert obj is not None and (obj["width"], obj["height"]) == (4, 2), index
    return obj


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    atlas_off = u32(rom, TABLE) - 0x08000000
    header = u32(rom, atlas_off)
    atlas = status.lzss_decompress(rom[atlas_off + 4:atlas_off + 4 + (header & 0xFFFF)])
    canvases = [sem.stitch(atlas, parse_map(rom, i)) for i in FAMILY]

    mode_rows = []
    vote_rows = []
    unanimous = 0
    for y in range(16):
        mode_row = []
        vote_row = []
        for x in range(32):
            counts = collections.Counter(c[y][x] for c in canvases)
            value, votes = counts.most_common(1)[0]
            mode_row.append(format(value, "X"))
            vote_row.append(str(votes))
            unanimous += votes == len(canvases)
        mode_rows.append("".join(mode_row))
        vote_rows.append(" ".join(vote_row))

    # A strict template-preservation mask: positions equal in all 8 resources.
    strict_rows = []
    for y in range(16):
        chars = []
        for x in range(32):
            vals = {c[y][x] for c in canvases}
            chars.append(format(next(iter(vals)), "X") if len(vals) == 1 else ".")
        strict_rows.append("".join(chars))

    print(json.dumps({
        "family": list(FAMILY),
        "mode_rows": mode_rows,
        "vote_rows": vote_rows,
        "strict_common_rows": strict_rows,
        "strict_common_pixels": unanimous,
        "total_pixels": 32 * 16,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
