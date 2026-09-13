#!/usr/bin/env python3
"""Search Korean stat-badge placements that avoid native protected frame pixels."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import build_ggen_advance_status_ui_tile_overlay_poc as status
import build_ggen_advance_turn_ability_overlays_20260905 as raster
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import FONT_ZIP, MAIN_TIP_ROM

TABLE = 0x000E0518
TARGETS = [(24, "명중"), (27, "반응"), (21, "운동"), (23, "위력"), (25, "장갑")]
FONTS = ("Galmuri11.bdf", "Galmuri11-Condensed.bdf", "Galmuri9.bdf", "Galmuri7.bdf")
# Live ss4 bank-13 indices that make up the red/blue/green/white native frame,
# cap and accents.  Any placement that touches these is unsafe for the user's
# preserve-frame requirement.
FRAME_INDICES = {12, 13, 14}
X0, X1, Y0, Y1 = 0, 24, 1, 14


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    atlas_off = u32(rom, TABLE) - 0x08000000
    header = u32(rom, atlas_off)
    atlas = status.lzss_decompress(rom[atlas_off + 4:atlas_off + 4 + (header & 0xFFFF)])
    out = []
    with ZipFile(FONT_ZIP) as archive:
        for font_name in FONTS:
            font = fontpair.load_bdf(archive, font_name)
            for idx, text in TARGETS:
                obj = sem.parse_map(rom, u32(rom, TABLE + idx * 4))
                c = sem.stitch(atlas, obj)
                protected_positions = {
                    (x, y) for y in range(16) for x in range(32)
                    if c[y][x] in FRAME_INDICES
                }
                raw_ink, w, h = raster.native_ink(font, text)
                candidates = []
                for oy in range(Y0 + 1, max(Y0 + 2, Y1 - h)):
                    for ox in range(X0 + 1, max(X0 + 2, X1 - w)):
                        ink = {(x + ox, y + oy) for x, y in raw_ink}
                        edge = raster.dilate(ink, 32, 16)
                        if not all(X0 <= x < X1 and Y0 <= y < Y1 for x, y in edge):
                            continue
                        blocked_ink = sum((x, y) in protected_positions for x, y in ink)
                        blocked_edge = sum((x, y) in protected_positions for x, y in edge)
                        center_penalty = abs((ox + w / 2) - 12) + abs((oy + h / 2) - 8)
                        candidates.append((blocked_ink, blocked_edge, center_penalty, ox, oy))
                candidates.sort()
                out.append({"font": font_name, "resource": idx, "text": text, "size": [w, h], "best": candidates[:8]})
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
