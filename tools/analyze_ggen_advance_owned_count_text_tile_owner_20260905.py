#!/usr/bin/env python3
"""Identify which live resource owns the actual 所有数 glyph-bearing BG2 tiles."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as dev
import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_owned_count_graphics_scan_20260904 as scan
import analyze_ggen_advance_owned_count_resource_bind_20260905 as bind
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_text_tile_owner_20260905.json"
RESOURCE = 0x08C4654C
ANIMATION = 8


def decode_tile(raw: bytes) -> list[list[int]]:
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + x // 2]
            out[y][x] = (packed >> (4 * (x & 1))) & 0xF
    return out


def plaque_canvas(state: bytes, plaque: dict[str, Any]) -> tuple[list[list[int]], list[list[dict[str, Any]]]]:
    x0, y0 = int(plaque["x0"]), int(plaque["y0"])
    width, height = int(plaque["width"]), int(plaque["height"])
    canvas = [[0] * (width * 8) for _ in range(height * 8)]
    cells: list[list[dict[str, Any]]] = []
    for cy in range(height):
        row = []
        for cx in range(width):
            cell = owned.map_cell(state, 2, x0 + cx, y0 + cy)
            pix = decode_tile(owned.bg_tile_bytes(state, 2, int(cell["tile"])))
            if cell["hflip"]:
                pix = [list(reversed(line)) for line in pix]
            if cell["vflip"]:
                pix = list(reversed(pix))
            for yy in range(8):
                canvas[cy * 8 + yy][cx * 8:cx * 8 + 8] = pix[yy]
            row.append(cell)
        cells.append(row)
    return canvas, cells


def animation_tile_map(rom: bytes, resource: int, animation: int) -> dict[bytes, list[int]]:
    header = dev.parse_resource_header(rom, resource)
    _gr, records = dev.sprite.animation_records(rom, resource)
    _parsed, ids = dev.parse_animation(records, animation)
    graphics = header["graphics"]
    reverse: dict[bytes, list[int]] = {}
    for sid in sorted(set(ids)):
        raw = bytes(graphics[sid * 32:(sid + 1) * 32])
        reverse.setdefault(raw, []).append(sid)
    return reverse


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rom = ORIGINAL_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(JP_STATE)
    plaque = owned.plaque_scan(state)
    if not plaque.get("found"):
        raise SystemExit("gate failed: plaque not found")
    canvas, cells = plaque_canvas(state, plaque)
    target = scan.native_word_mask(rom)
    best = scan.best_score(canvas, target)
    if best is None:
        raise SystemExit("gate failed: target scoring failed")

    bx, by = int(best["x"]), int(best["y"])
    bw, bh = 36, 12
    cx0, cy0 = bx // 8, by // 8
    cx1, cy1 = (bx + bw - 1) // 8, (by + bh - 1) // 8
    reverse = animation_tile_map(rom, RESOURCE, ANIMATION)
    text_cells = []
    matched_text_cells = []
    for cy in range(cy0, cy1 + 1):
        for cx in range(cx0, cx1 + 1):
            if not (0 <= cy < len(cells) and 0 <= cx < len(cells[0])):
                continue
            cell = cells[cy][cx]
            raw = owned.bg_tile_bytes(state, 2, int(cell["tile"]))
            row = {
                "plaque_cell": [cx, cy],
                "screen_map_cell": [int(plaque["x0"]) + cx, int(plaque["y0"]) + cy],
                "tile": int(cell["tile"]),
                "palette": int(cell["palette"]),
                "animation8_source_ids": reverse.get(raw, []),
            }
            text_cells.append(row)
            if row["animation8_source_ids"]:
                matched_text_cells.append(row)

    # Stronger: only cells containing pixels of the selected glyph palette in the scored bbox.
    glyph_cells = []
    pal = int(best["palette_index"])
    for cy in range(cy0, cy1 + 1):
        for cx in range(cx0, cx1 + 1):
            x_start, y_start = cx * 8, cy * 8
            has_glyph = False
            for yy in range(max(by, y_start), min(by + bh, y_start + 8)):
                for xx in range(max(bx, x_start), min(bx + bw, x_start + 8)):
                    if canvas[yy][xx] == pal:
                        has_glyph = True
                        break
                if has_glyph:
                    break
            if not has_glyph:
                continue
            cell = cells[cy][cx]
            raw = owned.bg_tile_bytes(state, 2, int(cell["tile"]))
            glyph_cells.append({
                "plaque_cell": [cx, cy],
                "tile": int(cell["tile"]),
                "animation8_source_ids": reverse.get(raw, []),
            })

    slots = [row for row in bind.sprite_slots(state) if row["resource"] == f"0x{RESOURCE:08X}" and int(row["animation"]) == ANIMATION]
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_text_tile_owner_20260905",
        "result": "PASS",
        "source": {"rom": advance_relative(ORIGINAL_ROM), "state": advance_relative(JP_STATE)},
        "live_bind": {"resource": f"0x{RESOURCE:08X}", "animation": ANIMATION, "slots": slots},
        "target_fit": best,
        "target_bbox": [bx, by, bw, bh],
        "target_text_cells": text_cells,
        "target_text_cells_exact_from_animation8": matched_text_cells,
        "glyph_palette_cells": glyph_cells,
        "glyph_palette_cell_count": len(glyph_cells),
        "glyph_palette_cells_exact_from_animation8": sum(bool(row["animation8_source_ids"]) for row in glyph_cells),
        "conclusion": (
            "animation 8 is the direct raw-tile source for all glyph-bearing 所有数 cells"
            if glyph_cells and all(row["animation8_source_ids"] for row in glyph_cells)
            else "animation 8 is only a partial/chrome source; 所有数 glyph ownership remains elsewhere"
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "live_bind": report["live_bind"],
        "target_fit": best,
        "target_bbox": report["target_bbox"],
        "glyph_cells": glyph_cells,
        "conclusion": report["conclusion"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
