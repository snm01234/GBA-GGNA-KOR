#!/usr/bin/env python3
"""Verify LANDFORM 16x7 map vs graphics sheet vs live VRAM."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, MAIN_TIP_ROM

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass8_20260905.json"
ROM_BASE = 0x08000000


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    rom = MAIN_TIP_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    info = bg.bg_info(state, 0)
    live = []
    for ty in range(7, 14):
        for tx in range(7, 23):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tid = cell & 0x3FF
            live.append({"cell": cell, "bank": (cell >> 12) & 0xF, "dest": tid, "raw": bytes(vram[tid * 32 : tid * 32 + 32])})

    gfx = 0xE3154
    # How many unique sequential tiles from gfx match any live raw?
    lookup = {}
    for tile in range(256):
        raw = bytes(japan[gfx + tile * 32 : gfx + tile * 32 + 32])
        lookup.setdefault(raw, []).append(tile)

    mapped = []
    for index, row in enumerate(live):
        mapped.append({"i": index, "dest": row["dest"], "bank": row["bank"], "src": lookup.get(row["raw"], [])})

    # Search nearby ROM for 16x7/16x8 maps whose source tiles match live payloads via gfx
    found = []
    for off in range(0xE2000, 0xE3154):
        w, h = japan[off], japan[off + 1]
        if (w, h) not in {(16, 6), (16, 7), (16, 8), (16, 9), (18, 7), (15, 7)}:
            continue
        count = w * h
        if off + 4 + count * 2 > gfx:
            continue
        cells = list(struct.unpack_from(f"<{count}H", japan, off + 4))
        ok = 0
        for index, cell in enumerate(cells[: len(live)]):
            src = cell & 0x3FF
            raw = bytes(japan[gfx + src * 32 : gfx + src * 32 + 32])
            if src < 256 and raw == live[index]["raw"]:
                ok += 1
        if ok >= 20:
            found.append({"map": hex(off), "w": w, "h": h, "matched": ok, "first": [hex(c) for c in cells[:8]]})

    # Also try graphics immediately after each candidate map
    found2 = []
    for off in range(0xE2000, 0xE4000):
        w, h = japan[off], japan[off + 1]
        if (w, h) != (16, 7):
            continue
        count = 112
        map_end = off + 4 + count * 2
        gfx2 = (map_end + 3) & ~3
        if gfx2 + 32 > len(japan):
            continue
        cells = list(struct.unpack_from(f"<{count}H", japan, off + 4))
        max_src = max(c & 0x3FF for c in cells)
        if max_src > 200:
            continue
        ok = 0
        for index, cell in enumerate(cells):
            src = cell & 0x3FF
            raw = bytes(japan[gfx2 + src * 32 : gfx2 + src * 32 + 32])
            if index < len(live) and raw == live[index]["raw"]:
                ok += 1
        if ok >= 8:
            found2.append({"map": hex(off), "gfx": hex(gfx2), "max_src": max_src, "matched": ok, "first": [hex(c) for c in cells[:8]]})

    # Pointers to 0x08E3066 / gfx 0x08E3154
    ptrs = {}
    for label, off in {"e3066": 0xE3066, "e3154": 0xE3154, "e3814": 0xE3814, "e3834": 0xE3834}.items():
        needle = struct.pack("<I", ROM_BASE + off)
        hits = []
        pos = 0
        while len(hits) < 12:
            hit = rom.find(needle, pos)
            if hit < 0:
                break
            hits.append(hex(hit))
            pos = hit + 1
        ptrs[label] = hits

    report = {
        "live_to_gfx_e3154": mapped,
        "src_tile_set": sorted({s for row in mapped for s in row["src"]}),
        "found_with_fixed_gfx": found,
        "found_gfx_after_map": found2,
        "pointers": ptrs,
        "hex_e3058": japan[0xE3058:0xE3160].hex(),
    }
    OUT.write_text(json.dumps({k: v for k, v in report.items() if k != "live_to_gfx_e3154"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("src tiles", report["src_tile_set"][:40], "count", len(report["src_tile_set"]))
    print("found_fixed", found)
    print("found_after", found2)
    print("ptrs", ptrs)
    print("sample map", mapped[0], mapped[69], mapped[70])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
