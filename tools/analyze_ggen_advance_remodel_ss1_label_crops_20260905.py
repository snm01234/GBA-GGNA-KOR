#!/usr/bin/env python3
"""Crop remodel anim3 label objects and search live VRAM for 持."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spr
import analyze_ggen_advance_settings_suspend_ui as spritefmt
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_status_ui_tile_overlay_poc as status
import build_ggen_advance_turn_ability_overlays_20260905 as raster
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM

OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_ss1_badges"
KO_RES = 0x092D8000
JP_RES = 0x08C64140
TABLE = 0x000E0518


def parse_anim(rom, addr, index):
    header = spr.parse_resource_header(rom, addr)
    _rel, records = spritefmt.animation_records(rom, addr)
    record = records[index][1]
    marker = spr.find_marker(record)
    parsed = spritefmt.parse_animation_oam(record[marker:])
    total = sum(int(o["tile_count"]) for o in parsed["objects"])
    blob = b"".join(item[1] for item in records[index:])[marker:]
    ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
    return header, parsed, ids


def main():
    ko = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    ko_state, _ = statefmt.parse_png_state(ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1")
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for tag, rom, addr in (("ko", ko, KO_RES), ("jp", jp, JP_RES)):
        header, parsed, ids = parse_anim(rom, addr, 3)
        pal = raster.palette_rgb(header["palettes"][:32])
        for index in (18, 29, 30, 32, 34, 35, 38):
            canvas = spr.stitch(header["graphics"], parsed, ids, [index])
            obj = parsed["objects"][index]
            im = raster.render_canvas(canvas, pal).resize(
                (max(16, len(canvas[0]) * 4), max(16, len(canvas) * 4)), Image.Resampling.NEAREST
            )
            items.append((f"{tag} o{index} {obj['x']},{obj['y']} {obj['size_px']}", im))
    from ggen_ss_tiles_common_20260905 import gallery
    gallery(items, OUT / "label_object_crops.png", 1)

    ptr = struct.unpack_from("<I", ko, TABLE)[0] - 0x08000000
    atlas = status.lzss_decompress(ko[ptr + 4:ptr + 4 + (struct.unpack_from("<I", ko, ptr)[0] & 0xFFFF)])
    hold = atlas[0x09B * 32:0x09D * 32]
    objvram = ko_state[statefmt.STATE_VRAM + 0x10000:statefmt.STATE_IWRAM]
    hits = []
    for tid in range(len(objvram) // 32):
        raw = bytes(objvram[tid * 32:(tid + 1) * 32])
        if raw in (hold[:32], hold[32:]):
            hits.append(tid)
    c5 = ko[0xC5CEB0:0xC5CEB0 + 32]
    c5_hits = [tid for tid in range(len(objvram) // 32) if bytes(objvram[tid * 32:(tid + 1) * 32]) == c5]
    print("e0518_hold_obj_tiles", hits, "c5ceb0", c5_hits)
    header, parsed, ids = parse_anim(ko, KO_RES, 3)
    gfx = header["graphics"]
    print("obj30 in package vs live")
    # dest tile 905 is OAM 59
    for name, dest, srcs in (
        ("o30", 905, [225, 226, 227, 228]),
        ("o34", 961, [208, 255, 256, 257, 212, 258, 259, 260]),
        ("o38", 997, [269, 270, 271, 272, 273, 274, 275, 276]),
    ):
        print(name, [(src, bytes(objvram[dest * 32:(dest + 1) * 32]) == gfx[src * 32:(src + 1) * 32]) for src in srcs[:1]])


if __name__ == "__main__":
    main()
