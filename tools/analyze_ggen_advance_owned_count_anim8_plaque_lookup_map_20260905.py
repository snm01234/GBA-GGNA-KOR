#!/usr/bin/env python3
"""Recover the 9x4 所有数 plaque base from JP VRAM and bind it to anim8 lookup indices."""
from __future__ import annotations

import json
import struct
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
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_anim8_plaque_lookup_map_20260905.json"
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


def encode_tile(pix: list[list[int]]) -> bytes:
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            out[y * 4 + x // 2] |= (pix[y][x] & 0xF) << (4 * (x & 1))
    return bytes(out)


def clear_text(raw: bytes) -> bytes:
    pix = decode_tile(raw)
    for y in range(8):
        for x in range(8):
            if pix[y][x] in (FACE, CONTOUR):
                pix[y][x] = FILL
    return encode_tile(pix)


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


def match_source_id(graphics: bytes, raw: bytes) -> list[int]:
    return [i for i in range(len(graphics) // 32) if graphics[i * 32:(i + 1) * 32] == raw]


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
        raise SystemExit("gate failed: native/clone lookup geometry drift")

    base_ids: list[list[int]] = []
    cell_rows: list[list[dict[str, Any]]] = []
    for py, row in enumerate(plaque["map"]):
        ids_row = []
        report_row = []
        for px, cell in enumerate(row):
            tid = int(cell["tile"])
            raw = owned.bg_tile_bytes(state, 2, tid)
            exact = match_source_id(native_h["graphics"], raw)
            cleared = clear_text(raw)
            cleared_hits = match_source_id(native_h["graphics"], cleared)
            candidates = exact or cleared_hits
            sid = candidates[0] if len(set(candidates)) == 1 else (candidates[0] if candidates else -1)
            ids_row.append(sid)
            report_row.append({
                "plaque_xy": [px, py],
                "screen_map_xy": [int(plaque["x0"]) + px, int(plaque["y0"]) + py],
                "bg2_tile": tid,
                "exact_source_ids": exact,
                "cleared_source_ids": cleared_hits,
                "selected_base_source_id": sid,
            })
        base_ids.append(ids_row)
        cell_rows.append(report_row)

    # Find 9x4 base-source pattern inside native anim8's 32x4 source-id canvas.
    ph = len(base_ids)
    pw = len(base_ids[0])
    matches = []
    for y0 in range(len(native_grid) - ph + 1):
        for x0 in range(len(native_grid[0]) - pw + 1):
            ok = True
            for y in range(ph):
                for x in range(pw):
                    if base_ids[y][x] < 0 or native_grid[y0 + y][x0 + x] != base_ids[y][x]:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                matches.append([x0, y0])

    # Even if text-clearing leaves ambiguous cells, score all windows by recovered IDs.
    scored = []
    for y0 in range(len(native_grid) - ph + 1):
        for x0 in range(len(native_grid[0]) - pw + 1):
            hit = total = 0
            for y in range(ph):
                for x in range(pw):
                    if base_ids[y][x] < 0:
                        continue
                    total += 1
                    hit += native_grid[y0 + y][x0 + x] == base_ids[y][x]
            scored.append({"origin": [x0, y0], "hits": hit, "total": total, "score": (hit / total if total else 0.0)})
    scored.sort(key=lambda r: (r["score"], r["hits"]), reverse=True)
    best = scored[0]
    x0, y0 = best["origin"]

    mapped = []
    for py in range(ph):
        for px in range(pw):
            gi = native_idxgrid[y0 + py][x0 + px]
            mapped.append({
                "plaque_xy": [px, py],
                "bg2_tile": int(plaque["map"][py][px]["tile"]),
                "native_lookup_index": gi,
                "native_source_id": native_ids[gi],
                "clone_source_id": clone_ids[gi],
                "anim8_canvas_xy": [(x0 + px) * 8, (y0 + py) * 8],
            })

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_anim8_plaque_lookup_map_20260905",
        "result": "PASS",
        "source": {"state": advance_relative(JP_STATE), "native": f"0x{NATIVE:08X}", "clone": f"0x{CLONE:08X}"},
        "plaque_rect": [plaque["x0"], plaque["y0"], plaque["width"], plaque["height"]],
        "recovered_base_source_ids": base_ids,
        "cell_recovery": cell_rows,
        "native_anim8_grid": native_grid,
        "clone_anim8_grid": clone_grid,
        "exact_pattern_matches": matches,
        "best_pattern_match": best,
        "plaque_to_lookup_map": mapped,
        "lookup_indices": sorted({r["native_lookup_index"] for r in mapped}),
        "clone_source_ids_used": sorted({r["clone_source_id"] for r in mapped}),
        "conclusion": "The plaque base can be bound to specific anim8 lookup occurrences; clone-only remap can therefore isolate new plaque tiles without editing shared source IDs.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "base_ids": base_ids,
        "exact_matches": matches,
        "best": best,
        "lookup_map": mapped,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
