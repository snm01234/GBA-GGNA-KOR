#!/usr/bin/env python3
"""Recover anim0 inner-well chrome after removing face+attached shadow."""
from __future__ import annotations

from collections import Counter

import analyze_ggen_advance_cd9250_warning_family_20260905 as fam
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_ss3_no_unit_warning_20260905 as dump
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

RESOURCE = 0x08CD9250
OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_no_unit_warning"
FACE, SHADOW = 11, 5


def glyph_mask(c, radius=2):
    h, w = len(c), len(c[0])
    face = {(x, y) for y in range(h) for x in range(w) if c[y][x] == FACE}
    attached = set()
    for x, y in face:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h and c[yy][xx] == SHADOW:
                    attached.add((xx, yy))
    return face, attached, face | attached


def hexrow(row):
    return "".join(f"{v:x}" for v in row)


def main():
    rom = MAIN_TIP_ROM.read_bytes()
    header = analysis.parse_resource_header(rom, RESOURCE)
    colors = [dump.rgb555(__import__("struct").unpack_from("<H", header["palettes"], i * 2)[0]) for i in range(16)]
    for anim in (0, 1):
        parsed, ids, by_object, lookup_rel, gfx_rel = fam.parse_anim(rom, RESOURCE, anim)
        text_idx = fam.text_object_indices(parsed)
        c = analysis.stitch(header["graphics"], parsed, ids, text_idx)
        full = analysis.stitch(header["graphics"], parsed, ids, list(range(len(parsed["objects"]))))
        face, attached, mask = glyph_mask(c)
        h, w = len(c), len(c[0])
        cleaned = [row[:] for row in c]
        for x, y in mask:
            cleaned[y][x] = 15  # sentinel
        print(f"\n=== anim{anim} face={len(face)} shadow={len(attached)} mask={len(mask)} ===")
        leftover5 = [(x, y) for y in range(h) for x in range(w) if (x, y) not in mask and c[y][x] == SHADOW]
        print("leftover index5 not attached to face", len(leftover5), leftover5[:30])
        for y in range(h):
            sent = sum(1 for x in range(w) if cleaned[y][x] == 15)
            print(f"{y:02d} sent={sent:3d} " + hexrow(cleaned[y][:24]) + " .. " + hexrow(cleaned[y][-16:]))
        dump.canvas_image(c, colors, 4).save(OUT / f"cd9250_anim{anim}_text.png")
        # visualize mask
        vis = [row[:] for row in c]
        for x, y in face:
            vis[y][x] = 12
        for x, y in attached:
            vis[y][x] = 1
        dump.canvas_image(vis, colors, 4).save(OUT / f"cd9250_anim{anim}_mask.png")
        dump.canvas_image(full, colors, 3).save(OUT / f"cd9250_anim{anim}_full.png")
        print("full size", len(full[0]), len(full))


if __name__ == "__main__":
    main()
