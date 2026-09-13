#!/usr/bin/env python3
"""Robustly bind the 9x4 live 所有数 plaque to native/clone anim8 lookup occurrences.

A source tile is compatible with a live plaque tile when every differing pixel
can be explained by the live tile overlaying face/contour (10/5) onto source
background fill 11. This avoids requiring a byte-exact post-composition match.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_images_20260901 as catalog
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as packagefmt
import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_settings_suspend_ui as spritefmt
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

NATIVE = 0x08C4654C
CLONE = 0x092D0000
ANIM = 8
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_anim8_plaque_lookup_map_v2_20260905.json"
FACE = 10
CONTOUR = 5
FILL = 11


def decode_tile(raw: bytes) -> list[list[int]]:
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            b = raw[y * 4 + x // 2]
            out[y][x] = (b >> (4 * (x & 1))) & 0xF
    return out


def overlay_compatible(source: bytes, live: bytes) -> bool:
    a = decode_tile(source)
    b = decode_tile(live)
    for y in range(8):
        for x in range(8):
            if a[y][x] == b[y][x]:
                continue
            if b[y][x] in (FACE, CONTOUR) and a[y][x] == FILL:
                continue
            return False
    return True


def parse_anim(rom: bytes, address: int):
    header = packagefmt.parse_resource_header(rom, address)
    _gr, records = spritefmt.animation_records(rom, address)
    parsed, ids, lookup_file = catalog.parse_anim(records, ANIM)
    return header, parsed, ids, lookup_file


def id_grid(parsed: dict[str, Any], ids: list[int]) -> tuple[list[list[int]], list[list[int]]]:
    gx0 = min(int(o["x"]) for o in parsed["objects"])
    gy0 = min(int(o["y"]) for o in parsed["objects"])
    gx1 = max(int(o["x"]) + int(o["size_px"][0]) for o in parsed["objects"])
    gy1 = max(int(o["y"]) + int(o["size_px"][1]) for o in parsed["objects"])
    w = (gx1 - gx0) // 8
    h = (gy1 - gy0) // 8
    grid = [[-1] * w for _ in range(h)]
    idxgrid = [[-1] * w for _ in range(h)]
    cursor = 0
    for obj in parsed["objects"]:
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        ox = (int(obj["x"]) - gx0) // 8
        oy = (int(obj["y"]) - gy0) // 8
        for ty in range(ht):
            for tx in range(wt):
                idx = cursor + ty * wt + tx
                grid[oy + ty][ox + tx] = int(ids[idx])
                idxgrid[oy + ty][ox + tx] = idx
        cursor += int(obj["tile_count"])
    return grid, idxgrid


def compatible_ids(graphics: bytes, live: bytes) -> list[int]:
    return [
        sid for sid in range(len(graphics) // 32)
        if overlay_compatible(graphics[sid * 32:(sid + 1) * 32], live)
    ]


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    main = MAIN_TIP_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(JP_STATE)
    plaque = owned.plaque_scan(state)
    if not plaque.get("found"):
        raise SystemExit("gate failed: plaque not found")

    native_h, native_p, native_ids, native_lookup = parse_anim(jp, NATIVE)
    clone_h, clone_p, clone_ids, clone_lookup = parse_anim(main, CLONE)
    native_grid, native_idxgrid = id_grid(native_p, native_ids)
    clone_grid, clone_idxgrid = id_grid(clone_p, clone_ids)
    if native_idxgrid != clone_idxgrid:
        raise SystemExit("gate failed: native/clone geometry drift")

    compat: list[list[list[int]]] = []
    cell_rows = []
    for py, row in enumerate(plaque["map"]):
        compat_row = []
        report_row = []
        for px, cell in enumerate(row):
            tid = int(cell["tile"])
            live = owned.bg_tile_bytes(state, 2, tid)
            ids = compatible_ids(native_h["graphics"], live)
            exact = [sid for sid in ids if native_h["graphics"][sid * 32:(sid + 1) * 32] == live]
            compat_row.append(ids)
            report_row.append({
                "plaque_xy": [px, py],
                "bg2_tile": tid,
                "compatible_source_ids": ids,
                "exact_source_ids": exact,
            })
        compat.append(compat_row)
        cell_rows.append(report_row)

    ph, pw = len(compat), len(compat[0])
    scored = []
    for y0 in range(len(native_grid) - ph + 1):
        for x0 in range(len(native_grid[0]) - pw + 1):
            hit = 0
            details = []
            for py in range(ph):
                for px in range(pw):
                    sid = native_grid[y0 + py][x0 + px]
                    ok = sid in compat[py][px]
                    hit += ok
                    details.append({"plaque_xy": [px, py], "source_id": sid, "compatible": ok})
            scored.append({"origin": [x0, y0], "hits": hit, "total": ph * pw, "score": hit / (ph * pw), "details": details})
    scored.sort(key=lambda r: (r["hits"], -r["origin"][1], -r["origin"][0]), reverse=True)
    best = scored[0]
    x0, y0 = best["origin"]

    mapped = []
    for py in range(ph):
        for px in range(pw):
            idx = native_idxgrid[y0 + py][x0 + px]
            mapped.append({
                "plaque_xy": [px, py],
                "screen_map_xy": [int(plaque["x0"]) + px, int(plaque["y0"]) + py],
                "bg2_tile": int(plaque["map"][py][px]["tile"]),
                "lookup_index": idx,
                "native_source_id": int(native_ids[idx]),
                "clone_source_id": int(clone_ids[idx]),
                "compatible": int(native_ids[idx]) in compat[py][px],
                "anim8_canvas_xy": [(x0 + px) * 8, (y0 + py) * 8],
            })

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_anim8_plaque_lookup_map_v2_20260905",
        "result": "PASS",
        "source": {"state": advance_relative(JP_STATE), "native": f"0x{NATIVE:08X}", "clone": f"0x{CLONE:08X}"},
        "plaque_rect": [plaque["x0"], plaque["y0"], plaque["width"], plaque["height"]],
        "cell_compatibility": cell_rows,
        "top_windows": [{k: row[k] for k in ("origin", "hits", "total", "score")} for row in scored[:10]],
        "best_window": {k: best[k] for k in ("origin", "hits", "total", "score")},
        "plaque_to_lookup_map": mapped,
        "all_cells_compatible": all(row["compatible"] for row in mapped),
        "lookup_indices": [row["lookup_index"] for row in mapped],
        "clone_source_ids": [row["clone_source_id"] for row in mapped],
        "conclusion": (
            "Full 36/36 overlay-compatible plaque-to-anim8 lookup mapping proven."
            if best["hits"] == ph * pw else
            "Mapping remains partial; do not patch from this result alone."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "top_windows": report["top_windows"],
        "best_window": report["best_window"],
        "all_cells_compatible": report["all_cells_compatible"],
        "lookup_map": mapped,
        "conclusion": report["conclusion"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
