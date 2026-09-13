#!/usr/bin/env python3
"""Find the LANDFORM tilemap for the 0xE3154 sheet and 海 name consumers."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass9_20260905.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
GFX = 0x000E3154
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
    lookup = {}
    for tile in range(160):
        raw = bytes(japan[GFX + tile * 32 : GFX + tile * 32 + 32])
        lookup.setdefault(raw, []).append(tile)
    wanted_src = []
    wanted_cells = []
    for ty in range(7, 14):
        for tx in range(7, 23):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tid = cell & 0x3FF
            raw = bytes(vram[tid * 32 : tid * 32 + 32])
            srcs = lookup.get(raw, [])
            src = srcs[0] if srcs else None
            bank = (cell >> 12) & 0xF
            wanted_src.append(src)
            wanted_cells.append(None if src is None else ((bank << 12) | src))
    known_src = [s for s in wanted_src if s is not None]
    known_cells = [c for c in wanted_cells if c is not None]
    # Search first fully-known run (row 0 is chrome).
    row0 = wanted_src[:16]
    assert all(s is not None for s in row0)
    first16 = struct.pack("<16H", *row0)
    first16_hits = []
    pos = 0
    while len(first16_hits) < 12:
        hit = japan.find(first16, pos)
        if hit < 0:
            break
        first16_hits.append(hex(hit))
        pos = hit + 1
    row0_cells = wanted_cells[:16]
    first16_cells = struct.pack("<16H", *row0_cells)
    first16_cell_hits = []
    pos = 0
    while len(first16_cell_hits) < 12:
        hit = japan.find(first16_cells, pos)
        if hit < 0:
            break
        first16_cell_hits.append(hex(hit))
        pos = hit + 1
    evade_idx = [70, 71, 72, 73, 86, 87, 88, 89]
    evade_src = [wanted_src[i] for i in evade_idx]
    evade_needle = struct.pack("<4H", *[s for s in evade_src[:4] if s is not None][:4]) if all(wanted_src[i] is not None for i in (70, 71, 72, 73)) else b""
    evade_hits = []
    pos = 0
    while evade_needle and len(evade_hits) < 16:
        hit = japan.find(evade_needle, pos)
        if hit < 0:
            break
        evade_hits.append(hex(hit))
        pos = hit + 1
    src_hits = []
    cell_hits = []

    # gfx pointer variants (thumb-aligned, file offset, GBA addr)
    ptrs = {
        "gfx_gba": [],
        "gfx_file_u32": [],
    }
    needle = struct.pack("<I", ROM_BASE + GFX)
    pos = 0
    while len(ptrs["gfx_gba"]) < 16:
        hit = rom.find(needle, pos)
        if hit < 0:
            break
        ptrs["gfx_gba"].append(hex(hit))
        pos = hit + 1
    needle = struct.pack("<I", GFX)
    pos = 0
    while len(ptrs["gfx_file_u32"]) < 16:
        hit = rom.find(needle, pos)
        if hit < 0:
            break
        ptrs["gfx_file_u32"].append(hex(hit))
        pos = hit + 1

    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    def decode_at(off):
        try:
            tokens, raw = read_tokens(japan, off, limit=32)
            slots = expand_to_slots(tokens, dict12)
            text = "".join(charmap.get(s, f"<{s:04X}>") for s in slots)
            return {"offset": hex(off), "text": text, "raw": raw.hex()}
        except Exception as exc:
            return {"offset": hex(off), "error": str(exc)}

    # Pointer table near likely terrain names: scan for consecutive pointers to 1-4 glyph strings.
    terrain_tables = []
    for off in range(0, 0x01000000 - 16, 4):
        ptr = u32(japan, off)
        if ptr != ROM_BASE + 0x00357016 and not (ROM_BASE <= ptr < ROM_BASE + 0x01000000):
            continue
        # only keep if this pointer is 海 and neighbors also decode as short names
        if ptr != ROM_BASE + 0x00357016:
            continue
        group = []
        for n in range(-8, 12):
            p = u32(japan, off + n * 4)
            if not (ROM_BASE <= p < ROM_BASE + 0x01000000):
                continue
            row = decode_at(p - ROM_BASE)
            if "text" in row and 1 <= len(row["text"]) <= 6:
                group.append({"slot": n, "ptr_off": hex(off + n * 4), **row})
        terrain_tables.append({"table": hex(off), "group": group})
        break

    report = {
        "wanted_src_row0": wanted_src[:16],
        "wanted_cells_row0": [hex(c) for c in wanted_cells[:16]],
        "evade_src": evade_src,
        "src_hits": src_hits,
        "cell_hits": cell_hits,
        "first16_hits": first16_hits,
        "first16_cell_hits": first16_cell_hits,
        "evade_row_hits": evade_hits,
        "ptrs": ptrs,
        "terrain_tables": terrain_tables,
        "sea_decode": decode_at(0x00357016),
        "missing_src_indices": [i for i, src in enumerate(wanted_src) if src is None],
        "first16_hits_main": [hex(rom.find(first16))] if rom.find(first16) >= 0 else [],
        "first16_cell_hits_main": [hex(rom.find(first16_cells))] if rom.find(first16_cells) >= 0 else [],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
