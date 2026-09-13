#!/usr/bin/env python3
"""Analyze ss1..ss6 remaining Japanese UI consumers from the current main TIP.

Read-only ownership pass.  BG regions from ss1/ss2 are matched against every
custom-LZSS 4bpp stream by exact live VRAM tile payload.  ss3..ss6 report live
sprite-manager resources/OAM geometry so follow-up builders can bind normal and
focus variants without relying on screenshot color alone.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_remaining_ui_states_20260902.json"
SPRITE_OBJECT_TABLE = 0x03001F98
SPRITE_OBJECT_SIZE = 40

# Screenshot-measured rectangles expressed as tile coordinates.  We deliberately
# include a one-tile margin; scoring is exact-tile based, so flat/background
# tiles do not dominate resource ownership.
BG_CASES = {
    1: {
        "layer": 3,
        "label": "unit-cost/status lower panel: 運動/限界/移動/装甲/残り回数",
        "rect": [6, 12, 29, 19],
    },
    2: {
        "layer": 2,
        "label": "develop detail cost panel: 強化費用/補給P",
        "rect": [16, 9, 29, 14],
    },
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def custom_streams(rom: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for off in range(0, len(rom) - 8, 4):
        header = u32(rom, off)
        if (header & 0xFFFF0000) != 0x80000000:
            continue
        body_len = header & 0xFFFF
        if body_len < 16 or off + 4 + body_len > len(rom):
            continue
        try:
            decoded = scan.lzss_decompress(rom[off + 4:off + 4 + body_len])
        except (ValueError, IndexError):
            continue
        if not decoded or len(decoded) % 32 or len(decoded) > 4096 * 32:
            continue
        lookup: dict[bytes, list[int]] = {}
        for tile in range(len(decoded) // 32):
            raw = decoded[tile * 32:(tile + 1) * 32]
            lookup.setdefault(raw, []).append(tile)
        rows.append({"offset": off, "body_len": body_len, "decoded": decoded, "lookup": lookup})
    return rows


def bg_case(state: bytes, case: dict[str, Any], streams: list[dict[str, Any]]) -> dict[str, Any]:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    layer = int(case["layer"])
    cnt = u16(io, 8 + layer * 2)
    charblock = (cnt >> 2) & 3
    screenblock = (cnt >> 8) & 31
    x0, y0, x1, y1 = [int(v) for v in case["rect"]]
    cells = []
    payloads: list[bytes] = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            cell = u16(vram, screenblock * 0x800 + (y * 32 + x) * 2)
            tile = cell & 0x03FF
            raw = bytes(vram[charblock * 0x4000 + tile * 32:charblock * 0x4000 + (tile + 1) * 32])
            cells.append({"x": x, "y": y, "cell": f"0x{cell:04X}", "tile": tile, "palette_bank": (cell >> 12) & 0xF})
            if len(set(raw)) > 1:
                payloads.append(raw)
    unique = list(dict.fromkeys(payloads))
    ranked = []
    for row in streams:
        matched = [raw for raw in unique if raw in row["lookup"]]
        if not matched:
            continue
        tile_hits = sorted({tile for raw in matched for tile in row["lookup"][raw]})
        ranked.append({
            "resource_file_offset": f"0x{row['offset']:08X}",
            "resource_address": f"0x{0x08000000 + row['offset']:08X}",
            "compressed_body_length": row["body_len"],
            "decoded_tiles": len(row["decoded"]) // 32,
            "unique_live_tiles": len(unique),
            "matched_unique_tiles": len(matched),
            "match_ratio": len(matched) / max(1, len(unique)),
            "matched_decoded_tile_ids": tile_hits[:96],
        })
    ranked.sort(key=lambda r: (r["matched_unique_tiles"], r["match_ratio"]), reverse=True)
    return {
        "label": case["label"],
        "bg_layer": layer,
        "bgcnt": f"0x{cnt:04X}",
        "charblock": charblock,
        "screenblock": screenblock,
        "rect_tiles": case["rect"],
        "cells": cells,
        "ranked_exact_resource_matches": ranked[:20],
    }


def sprite_slots(state: bytes) -> list[dict[str, Any]]:
    iwram = state[statefmt.STATE_IWRAM:statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    base = SPRITE_OBJECT_TABLE - 0x03000000
    rows = []
    for index in range(80):
        off = base + index * SPRITE_OBJECT_SIZE
        ptr = u32(iwram, off)
        if 0x08000000 <= ptr < 0x0A000000:
            x = u16(iwram, off + 0x0A)
            y = u16(iwram, off + 0x0C)
            if x >= 0xFF00:
                x -= 0x10000
            if y >= 0xFF00:
                y -= 0x10000
            rows.append({"slot": index, "resource": f"0x{ptr:08X}", "x": x, "y": y, "animation": iwram[off + 0x11]})
    return rows


def visible_oam(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    rows = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            rows.append(row)
    return rows


def main() -> int:
    main = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main) == manifest["sha256"], "main TIP hash/manifest drift")
    streams = custom_streams(main)
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ggen_advance_remaining_ui_states_20260902",
        "result": "PASS",
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(main), "size": len(main)},
        "custom_lzss_streams_scanned": len(streams),
        "states": {},
    }
    for number in range(1, 7):
        path = ADVANCE_ROOT / f"SD Gundam GGeneration Advance (Korean).ss{number}"
        raw = path.read_bytes()
        state, _ = statefmt.parse_png_state(path)
        row: dict[str, Any] = {
            "path": advance_relative(path),
            "sha256": sha256(raw),
            "sprite_slots": sprite_slots(state),
            "visible_oam": visible_oam(state),
        }
        if number in BG_CASES:
            row["bg_target"] = bg_case(state, BG_CASES[number], streams)
        result["states"][str(number)] = row
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "main_sha256": sha256(main),
        "streams": len(streams),
        "bg_top": {
            str(n): result["states"][str(n)]["bg_target"]["ranked_exact_resource_matches"][:5]
            for n in BG_CASES
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
