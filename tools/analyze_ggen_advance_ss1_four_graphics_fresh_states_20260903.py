#!/usr/bin/env python3
"""Analyze fresh ss1/ss2 made with the four-graphics test candidate."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sortpatch
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

BASE = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_ss1_four_graphics"
ROM = BASE / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.gba"
STATES = {1: BASE / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.ss1", 2: BASE / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.ss2"}
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_ss1_four_graphics_fresh_analysis"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_ss1_four_graphics_fresh_states_20260903.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def region(state: bytes, layer: int, box: tuple[int, int, int, int]) -> dict[str, object]:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    x0, y0, x1, y1 = box
    cells = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            cell = bgutil.map_entry(vram, info["screen_base"], info["size"], x, y)
            cells.append({"x": x, "y": y, "address": f"0x{0x06000000 + info['screen_base'] + (y * 32 + x) * 2:08X}", "cell": f"0x{cell:04X}", "tile": cell & 0x3FF, "palette": cell >> 12})
    return {"binding": info, "cells": cells}


def main() -> int:
    rom = ROM.read_bytes()
    crc = binascii.crc32(rom) & 0xFFFFFFFF
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "kind": "ggen_advance_ss1_four_graphics_fresh_states_20260903", "result": "PASS", "candidate": {"path": advance_relative(ROM), "sha256": sha256(rom), "crc32": f"0x{crc:08X}"}, "states": {}}
    for number, path in STATES.items():
        state, _ = statefmt.parse_png_state(path)
        state_crc = struct.unpack_from("<I", state, 8)[0]
        layers = {}
        for layer in range(4):
            image = sortpatch.render_layer_native(state, layer)
            out_image = OUT_DIR / f"fresh_ss{number}_bg{layer}.png"
            image.save(out_image)
            layers[str(layer)] = advance_relative(out_image)
        result["states"][str(number)] = {
            "path": advance_relative(path), "sha256": sha256(path.read_bytes()), "embedded_crc32": f"0x{state_crc:08X}", "crc_matches_candidate": state_crc == crc,
            "query_hold_bg0": region(state, 0, (13, 0, 17, 4)),
            "query_hold_bg1": region(state, 1, (13, 0, 17, 4)),
            "query_owned_bg2": region(state, 2, (20, 8, 30, 13)),
            "disposal_cost_bg2": region(state, 2, (16, 9, 30, 15)),
            "layers": layers,
        }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "report": advance_relative(OUT), "candidate_crc32": f"0x{crc:08X}", "state_crc_matches": {n: result["states"][str(n)]["crc_matches_candidate"] for n in STATES}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
