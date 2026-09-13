#!/usr/bin/env python3
"""Audit CFC4 base map E0518[2] against the live 所有数 plaque.

The first CFC4 0x0800269C call at 0x0806CFF0 draws E0518[2] at (0,0).
This analyzer inspects that map structurally, including possible constant tile
index offsets between resource cells and live BG2 cells.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from analyze_ggen_advance_fixed_word_semantics_20260830 import parse_map
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
TABLE = 0x000E0518
INDEX = 2
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_cfc4_base_map_20260905.json"


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def main() -> int:
    rom = ORIGINAL_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(JP_STATE)
    plaque = owned.plaque_scan(state)
    if not plaque.get("found"):
        raise SystemExit("gate failed: plaque missing")
    ptr = u32(rom, TABLE + INDEX * 4)
    res = parse_map(rom, ptr)
    if res is None:
        raise SystemExit("gate failed: E0518[2] is not a map")
    w, h = int(res["width"]), int(res["height"])
    cells = [int(c) for c in res["cells"]]

    px0, py0 = int(plaque["x0"]), int(plaque["y0"])
    pw, ph = int(plaque["width"]), int(plaque["height"])
    overlap = []
    deltas = Counter()
    exact_cell = 0
    transformed_cell = 0
    palette_matches = 0
    TILE_ADD = 0x201
    PALETTE_OVERRIDE = 0xB000
    for py in range(ph):
        for px in range(pw):
            sx, sy = px0 + px, py0 + py
            if sx >= w or sy >= h:
                continue
            src = cells[sy * w + sx]
            live = int(plaque["map"][py][px]["cell"], 16)
            src_tile = src & 0x3FF
            live_tile = live & 0x3FF
            delta = live_tile - src_tile
            deltas[delta] += 1
            transformed = ((src_tile + TILE_ADD) & 0x3FF) | (src & 0x0C00) | PALETTE_OVERRIDE
            exact_cell += src == live
            transformed_cell += transformed == live
            palette_matches += ((transformed >> 12) & 0xF) == ((live >> 12) & 0xF)
            overlap.append({
                "screen_xy": [sx, sy],
                "source_cell": f"0x{src:04X}",
                "source_tile": src_tile,
                "source_palette": (src >> 12) & 0xF,
                "live_cell": f"0x{live:04X}",
                "live_tile": live_tile,
                "live_palette": (live >> 12) & 0xF,
                "tile_delta": delta,
                "cell_exact": src == live,
                "transformed_cell": f"0x{transformed:04X}",
                "transformed_exact": transformed == live,
            })
    common_delta, common_count = deltas.most_common(1)[0] if deltas else (None, 0)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_cfc4_base_map_20260905",
        "result": "PASS",
        "source": {"rom": advance_relative(ORIGINAL_ROM), "state": advance_relative(JP_STATE)},
        "base_map": {"index": INDEX, "pointer": f"0x{ptr:08X}", "size": [w, h]},
        "plaque_rect": [px0, py0, pw, ph],
        "overlap_count": len(overlap),
        "exact_cell_count": exact_cell,
        "transformed_cell_count": transformed_cell,
        "tile_add": TILE_ADD,
        "palette_override": "0xB000",
        "palette_match_count": palette_matches,
        "tile_delta_histogram": [{"delta": k, "count": v} for k, v in deltas.most_common()],
        "common_tile_delta": common_delta,
        "common_tile_delta_count": common_count,
        "overlap": overlap,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result":"PASS","out":advance_relative(OUT),"base_map":report["base_map"],
        "overlap":len(overlap),"exact":exact_cell,"transformed_exact":transformed_cell,"palette_matches":palette_matches,
        "delta_top":report["tile_delta_histogram"][:15],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
