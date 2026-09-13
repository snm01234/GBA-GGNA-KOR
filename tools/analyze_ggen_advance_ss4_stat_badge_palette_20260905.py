#!/usr/bin/env python3
"""Inspect ss4 live palette bank 13 and native stat-badge raster indices."""
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
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_status_ui_tile_overlay_poc as status
import build_ggen_advance_turn_ability_overlays_20260905 as raster
from ggen_ss_tiles_common_20260905 import ROOT
from ggen_advance_project_paths import MAIN_TIP_ROM

TABLE = 0x000E0518
STATE = ROOT / "SD Gundam GGeneration Advance (Korean).ss4"
TARGETS = [(21, "運動"), (23, "威力"), (24, "命中"), (25, "装甲"), (27, "反応")]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_map(data: bytes, index: int) -> dict:
    obj = sem.parse_map(data, u32(data, TABLE + index * 4))
    assert obj is not None and (obj["width"], obj["height"]) == (4, 2), index
    return obj


def stitch(atlas: bytes, obj: dict) -> list[list[int]]:
    return sem.stitch(atlas, obj)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rom = MAIN_TIP_ROM.read_bytes()
    atlas_off = u32(rom, TABLE) - 0x08000000
    header = u32(rom, atlas_off)
    atlas = status.lzss_decompress(rom[atlas_off + 4:atlas_off + 4 + (header & 0xFFFF)])

    state, _ = statefmt.parse_png_state(STATE)
    pal = raster.palette_rgb(state[statefmt.STATE_PALETTE + 13 * 32:statefmt.STATE_PALETTE + 14 * 32])

    result = {"palette_bank": 13, "palette_rgb": {str(i): list(rgb) for i, rgb in enumerate(pal)}, "resources": []}
    for idx, label in TARGETS:
        obj = parse_map(rom, idx)
        c = stitch(atlas, obj)
        whole = collections.Counter(v for row in c for v in row)
        interior = collections.Counter(c[y][x] for y in range(1, 15) for x in range(0, 27))
        right = collections.Counter(c[y][x] for y in range(16) for x in range(27, 32))
        top_bottom = collections.Counter(c[y][x] for y in (0, 15) for x in range(32))
        cols = {str(x): dict(sorted(collections.Counter(c[y][x] for y in range(16)).items())) for x in range(32)}
        result["resources"].append({
            "resource": idx,
            "source": label,
            "tiles": [cell & 0x3FF for cell in obj["cells"]],
            "whole_counts": dict(sorted(whole.items())),
            "interior_x0_26_y1_14_counts": dict(sorted(interior.items())),
            "right_cap_x27_31_counts": dict(sorted(right.items())),
            "top_bottom_counts": dict(sorted(top_bottom.items())),
            "column_counts": cols,
            "rows": ["".join(format(v, "X") for v in row) for row in c],
        })

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
