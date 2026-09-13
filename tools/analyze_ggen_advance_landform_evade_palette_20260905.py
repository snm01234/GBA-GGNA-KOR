#!/usr/bin/env python3
"""Classify LANDFORM 回避 palette roles from ss2 bank 11 + source tiles."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_turn_ability_overlays_20260905 as raster
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

GFX = 0x000E3154
EVADE = (55, 56, 57, 58, 67, 68, 69, 70)
STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"


def stitch(rom: bytes) -> list[list[int]]:
    canvas = [[0] * 32 for _ in range(16)]
    for index, tile in enumerate(EVADE):
        tx, ty = index % 4, index // 4
        pix = raster.decode_tile(bytes(rom[GFX + tile * 32 : GFX + tile * 32 + 32]))
        for y in range(8):
            canvas[ty * 8 + y][tx * 8 : tx * 8 + 8] = pix[y]
    return canvas


def lum(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rom = MAIN_TIP_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    colors = raster.palette_rgb(bytes(pal[11 * 32 : 12 * 32]))
    canvas = stitch(rom)
    used = Counter(canvas[y][x] for y in range(16) for x in range(32))
    roles = {}
    for index, n in used.most_common():
        roles[index] = {"rgb": list(colors[index]), "luminance": round(lum(colors[index]), 2), "pixels": n}

    # Neighbor offsets of darker pixels around brighter pixels
    indices = [i for i, n in used.items() if n]
    by_lum = sorted(indices, key=lambda i: lum(colors[i]))
    shadow, mid, bg = by_lum[0], by_lum[1], by_lum[2]
    offsets = Counter()
    for y in range(16):
        for x in range(32):
            if canvas[y][x] != mid:
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < 32 and 0 <= yy < 16 and canvas[yy][xx] == shadow:
                        offsets[(dx, dy)] += 1

    report = {
        "palette": {str(i): {"rgb": list(colors[i]), "luminance": round(lum(colors[i]), 2)} for i in range(16)},
        "used": roles,
        "by_luminance_dark_to_light": by_lum,
        "inferred": {"shadow": shadow, "face": mid, "background": bg},
        "shadow_offsets_around_face": [[list(k), v] for k, v in offsets.most_common(12)],
        "edges": {
            "row0": canvas[0],
            "row15": canvas[15],
            "col0": [canvas[y][0] for y in range(16)],
            "col31": [canvas[y][31] for y in range(16)],
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
