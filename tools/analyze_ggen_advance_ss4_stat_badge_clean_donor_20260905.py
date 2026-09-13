#!/usr/bin/env python3
"""Search E0518 map resources for a clean 32x16 donor sharing the stat-badge cap."""
from __future__ import annotations

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
REFERENCE = 24
JP = {5, 6, 7}


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_map(data: bytes, index: int):
    try:
        ptr = u32(data, TABLE + index * 4)
        obj = sem.parse_map(data, ptr)
    except Exception:
        return None
    if obj is None or (obj.get("width"), obj.get("height")) != (4, 2):
        return None
    return obj


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    atlas_off = u32(rom, TABLE) - 0x08000000
    header = u32(rom, atlas_off)
    atlas = status.lzss_decompress(rom[atlas_off + 4:atlas_off + 4 + (header & 0xFFFF)])
    ref = parse_map(rom, REFERENCE)
    assert ref is not None
    ref_canvas = sem.stitch(atlas, ref)
    ref_cap = [[ref_canvas[y][x] for x in range(24, 32)] for y in range(16)]

    rows = []
    for idx in range(0, 256):
        obj = parse_map(rom, idx)
        if obj is None:
            continue
        try:
            c = sem.stitch(atlas, obj)
        except Exception:
            continue
        cap = [[c[y][x] for x in range(24, 32)] for y in range(16)]
        cap_diff = sum(cap[y][x] != ref_cap[y][x] for y in range(16) for x in range(8))
        jp_count = sum(c[y][x] in JP for y in range(1, 14) for x in range(24))
        non_dark = sum(c[y][x] != 3 for y in range(1, 14) for x in range(24))
        if cap_diff <= 8:
            rows.append({
                "resource": idx,
                "tiles": [cell & 0x3FF for cell in obj["cells"]],
                "cap_diff_pixels": cap_diff,
                "jp_5_6_7_pixels": jp_count,
                "non_dark_body_pixels": non_dark,
                "rows": ["".join(format(v, "X") for v in row) for row in c],
            })
    rows.sort(key=lambda r: (r["cap_diff_pixels"], r["jp_5_6_7_pixels"], r["non_dark_body_pixels"], r["resource"]))
    print(json.dumps(rows[:40], ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
