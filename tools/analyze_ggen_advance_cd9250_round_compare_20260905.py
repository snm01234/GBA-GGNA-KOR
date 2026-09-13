#!/usr/bin/env python3
"""Compare CD9250 anim0/1/2 text-plane chrome, rounds, and glyph indices."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import analyze_ggen_advance_cd9250_warning_family_20260905 as fam
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_no_unit_warning"
RESOURCE = 0x08CD9250


def canvas_for(rom, anim):
    header = analysis.parse_resource_header(rom, RESOURCE)
    parsed, ids, by_object, lookup_rel, gfx_rel = fam.parse_anim(rom, RESOURCE, anim)
    text_idx = fam.text_object_indices(parsed)
    canvas = analysis.stitch(header["graphics"], parsed, ids, text_idx)
    return canvas, parsed, ids, by_object, text_idx, lookup_rel


def dump_corners(name, c):
    h, w = len(c), len(c[0])
    print(f"== {name} {w}x{h} ==")
    for y in range(h):
        print(f"{y:02d} " + "".join(f"{c[y][x]:x}" for x in range(min(16, w))) + " .. " + "".join(f"{c[y][x]:x}" for x in range(w - 16, w)))


def glyph_mask(c, face=11, shadow=5):
    h, w = len(c), len(c[0])
    face_pts = {(x, y) for y in range(h) for x in range(w) if c[y][x] == face}
    # shadow attached to face: index 5 within 2px of a face pixel
    attached = set()
    for x, y in face_pts:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h and c[yy][xx] == shadow:
                    attached.add((xx, yy))
    return face_pts | attached


def main():
    rom = MAIN_TIP_ROM.read_bytes()
    canvases = {}
    for anim in range(3):
        c, *_ = canvas_for(rom, anim)
        canvases[anim] = c
        dump_corners(f"anim{anim}", c)
        print("counts", Counter(v for row in c for v in row).most_common())
    a0, a2 = canvases[0], canvases[2]
    h, w = len(a0), len(a0[0])
    mask = glyph_mask(a0)
    diffs = []
    for y in range(h):
        for x in range(w):
            if (x, y) in mask:
                continue
            if a0[y][x] != a2[y][x]:
                diffs.append((x, y, a0[y][x], a2[y][x]))
    print("non-glyph anim0 vs anim2 diffs", len(diffs))
    print("sample diffs", diffs[:40])
    # which columns are glyph-free on anim0?
    free_cols = [x for x in range(w) if all((x, y) not in mask for y in range(h))]
    print("glyph-free columns", free_cols[:20], "...", free_cols[-10:], "count", len(free_cols))
    # y-range of glyphs
    ys = [y for x, y in mask]
    xs = [x for x, y in mask]
    print("glyph bbox", min(xs), min(ys), max(xs), max(ys), "n", len(mask))

    # compare left 8 columns fully
    print("left 8 cols anim0 vs anim2 match", all(a0[y][x] == a2[y][x] for y in range(h) for x in range(8)))
    print("right 8 cols match", all(a0[y][x] == a2[y][x] for y in range(h) for x in range(w - 8, w)))
    # corner 8x8
    for label, xs0, ys0 in (("TL", range(8), range(8)), ("TR", range(w-8, w), range(8)), ("BL", range(8), range(h-8, h)), ("BR", range(w-8, w), range(h-8, h))):
        same = all(a0[y][x] == a2[y][x] for y in ys0 for x in xs0)
        print(label, "same", same, "a0", Counter(a0[y][x] for y in ys0 for x in xs0).most_common(6), "a2", Counter(a2[y][x] for y in ys0 for x in xs0).most_common(6))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cd9250_round_compare.json").write_text(json.dumps({
        "non_glyph_diffs": len(diffs),
        "glyph_bbox": [min(xs), min(ys), max(xs), max(ys)],
        "free_col_count": len(free_cols),
        "free_cols_head": free_cols[:24],
        "free_cols_tail": free_cols[-24:],
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
