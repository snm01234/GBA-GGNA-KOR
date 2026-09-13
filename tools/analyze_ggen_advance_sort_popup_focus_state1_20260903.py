#!/usr/bin/env python3
"""Analyze the user-captured ascending-focus state from the sort-popup candidate."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_sort_popup_state6_candidate_20260903 as builder
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

STATE = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup" / "ggen_advance_sort_popup_state6_ko_candidate_20260903.ss1"
ROM = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup" / "ggen_advance_sort_popup_state6_ko_candidate_20260903.gba"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_sort_popup_focus_state1_20260903.json"
PREVIEW = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup" / "ggen_advance_sort_popup_focus_state1_layers_20260903.png"

FOCUS_POSITIONS = {
    "HP": (9, 8, 7),
    "오름": (16, 8, 5),
    "이름": (9, 10, 7),
    "내림": (16, 10, 5),
    "배치중": (9, 12, 7),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def layer_cells(state: bytes, layer: int, x: int, y: int, width: int) -> tuple[dict, list[int]]:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    cells = [
        bgutil.map_entry(vram, info["screen_base"], info["size"], x + dx, y + dy)
        for dy in range(2) for dx in range(width)
    ]
    return info, cells


def live_tile_payload(state: bytes, info: dict, cells: list[int]) -> bytes:
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    out = bytearray()
    for cell in cells:
        tile = cell & 0x3FF
        start = info["char_base"] + tile * 32
        out += vram[start:start + 32]
    return bytes(out)


def save_layer_preview(state: bytes) -> None:
    sheet = Image.new("RGB", (240 * 3, 160), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for column, layer in enumerate((0, 1, 2)):
        frame = builder.render_layer_native(state, layer)
        background = Image.new("RGBA", frame.size, (24, 24, 24, 255))
        background.alpha_composite(frame)
        sheet.paste(background.convert("RGB"), (column * 240, 0))
        draw.text((column * 240 + 4, 4), f"BG{layer}", fill=(255, 255, 255))
    sheet.resize((1440, 320), Image.Resampling.NEAREST).save(PREVIEW)


def main() -> int:
    raw_state_file = STATE.read_bytes()
    state, chunks = statefmt.parse_png_state(STATE)
    rom = ROM.read_bytes()
    state_crc = struct.unpack_from("<I", state, 8)[0]
    rom_crc = binascii.crc32(rom) & 0xFFFFFFFF
    if state_crc != rom_crc:
        raise SystemExit(f"state/ROM CRC mismatch: {state_crc:08X} != {rom_crc:08X}")

    layers = {}
    for layer in range(4):
        info = bgutil.bg_info(state, layer)
        positions = {}
        for label, (x, y, width) in FOCUS_POSITIONS.items():
            _info, cells = layer_cells(state, layer, x, y, width)
            positions[label] = {
                "first_cell": f"0x{cells[0]:04X}",
                "cells": [f"0x{value:04X}" for value in cells],
                "first_palette_bank": (cells[0] >> 12) & 15,
                "first_tile_id": cells[0] & 0x3FF,
                "all_empty_0x02FF": all(value == 0x02FF for value in cells),
            }
        layers[f"BG{layer}"] = {
            "bgcnt": f"0x{info['cnt']:04X}",
            "charblock": info["char_base"] // 0x4000,
            "screenblock": info["screen_base"] // 0x800,
            "positions": positions,
        }

    asc_info, asc_cells = layer_cells(state, 0, *FOCUS_POSITIONS["오름"])
    asc_live = live_tile_payload(state, asc_info, asc_cells)
    expected = rom[builder.FOCUS_FILES["오름"]:builder.FOCUS_FILES["오름"] + len(asc_live)]
    stub = rom[builder.STUB_FILE:builder.STUB_FILE + len(builder.STUB)]
    bg0_asc_map_address = 0x06000000 + 12 * 0x800 + (8 * 32 + 16) * 2
    bg1_asc_map_address = 0x06000000 + 14 * 0x800 + (8 * 32 + 16) * 2

    save_layer_preview(state)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_sort_popup_focus_state1_20260903",
        "result": "PASS",
        "state": {
            "path": advance_relative(STATE),
            "sha256": sha256(raw_state_file),
            "rom_crc32": f"0x{state_crc:08X}",
            "chunks": chunks,
        },
        "candidate_rom": {
            "path": advance_relative(ROM),
            "sha256": sha256(rom),
            "crc32": f"0x{rom_crc:08X}",
        },
        "layers": layers,
        "measured_focus": {
            "label": "오름 / visible source text 昇順",
            "owner": "BG0",
            "bgcnt": f"0x{asc_info['cnt']:04X}",
            "charblock": asc_info["char_base"] // 0x4000,
            "screenblock": asc_info["screen_base"] // 0x800,
            "map_xy": [16, 8],
            "map_address": f"0x{bg0_asc_map_address:08X}",
            "cells": [f"0x{value:04X}" for value in asc_cells],
            "tile_ids": [f"0x{value & 0x3FF:03X}" for value in asc_cells],
            "palette_bank": (asc_cells[0] >> 12) & 15,
            "live_payload_sha256": sha256(asc_live),
            "expected_korean_payload_sha256": sha256(expected),
            "live_matches_expected_korean": asc_live == expected,
            "different_bytes_from_expected_korean": sum(a != b for a, b in zip(asc_live, expected)),
        },
        "current_hook_mismatch": {
            "monitored_BG1_asc_map_address": f"0x{bg1_asc_map_address:08X}",
            "measured_BG1_cell": layers["BG1"]["positions"]["오름"]["first_cell"],
            "actual_BG0_asc_map_address": f"0x{bg0_asc_map_address:08X}",
            "measured_BG0_cell": layers["BG0"]["positions"]["오름"]["first_cell"],
            "stub_contains_BG1_address": struct.pack("<I", bg1_asc_map_address) in stub,
            "stub_contains_BG0_address": struct.pack("<I", bg0_asc_map_address) in stub,
            "root_cause": "the live focus strip is on BG0 screenblock 12, while the hook scans only BG1 screenblock 14",
        },
        "important_followup": {
            "scan_both_BG0_and_BG1": True,
            "require_palette_bank_E_not_merely_nonempty": True,
            "reason": "BG0 also contains non-focus palette-B cells at the 이름/배치중 coordinates; nonempty-only detection would misclassify later focus rows",
            "write_using_actual_10bit_tile_id": True,
        },
        "preview": advance_relative(PREVIEW),
        "status": "analysis_only_no_ROM_change",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "owner": "BG0",
        "asc_cells": report["measured_focus"]["cells"],
        "BG1_cell": report["current_hook_mismatch"]["measured_BG1_cell"],
        "live_matches_expected_korean": report["measured_focus"]["live_matches_expected_korean"],
        "different_bytes": report["measured_focus"]["different_bytes_from_expected_korean"],
        "report": advance_relative(OUT),
        "preview": advance_relative(PREVIEW),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
