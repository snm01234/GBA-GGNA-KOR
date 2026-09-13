#!/usr/bin/env python3
"""Match LANDFORM VRAM tiles to E0518 atlas and find live 海 pointer in EWRAM."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass4_20260905.json"
TABLE = 0x000E0518
ROM_BASE = 0x08000000
EWRAM_OFF = 0x21000
SEA_TOKEN = bytes.fromhex("E0 E1")


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def find_all(hay, needle, limit=64):
    hits = []
    start = 0
    while len(hits) < limit:
        pos = hay.find(needle, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
    return hits


def parse_map(rom, ptr):
    if not ROM_BASE <= ptr < ROM_BASE + min(len(rom), 0x01000000):
        return None
    off = ptr - ROM_BASE
    if off + 4 > len(rom):
        return None
    width, height = rom[off], rom[off + 1]
    count = width * height
    if not (1 <= width <= 32 and 1 <= height <= 32) or off + 4 + count * 2 > len(rom):
        return None
    cells = list(struct.unpack_from(f"<{count}H", rom, off + 4))
    return {"index_off": off, "width": width, "height": height, "cells": cells}


def payload_at(rom, addr):
    off = addr - ROM_BASE
    if off < 0 or off >= len(rom):
        return b""
    end = rom.find(b"\x00", off, off + 32)
    if end < 0:
        end = off + 16
    return rom[off : end + 1]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    state, _ = statefmt.parse_png_state(STATE)
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    ewram = state[EWRAM_OFF : EWRAM_OFF + 0x40000]
    info = bg.bg_info(state, 0)

    atlas_ptr = u32(rom, TABLE)
    off = atlas_ptr - ROM_BASE
    header = u32(rom, off)
    atlas = scan.lzss_decompress(rom[off + 4 : off + 4 + (header & 0xFFFF)])
    jp_ptr = u32(japan, TABLE)
    jp_off = jp_ptr - ROM_BASE
    jp_header = u32(japan, jp_off)
    jp_atlas = scan.lzss_decompress(japan[jp_off + 4 : jp_off + 4 + (jp_header & 0xFFFF)])
    lookup_ko = {}
    lookup_jp = {}
    for tile in range(len(atlas) // 32):
        lookup_ko.setdefault(bytes(atlas[tile * 32 : tile * 32 + 32]), []).append(tile)
    for tile in range(len(jp_atlas) // 32):
        lookup_jp.setdefault(bytes(jp_atlas[tile * 32 : tile * 32 + 32]), []).append(tile)

    window = []
    for ty in range(7, 14):
        row = []
        for tx in range(7, 23):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tid = cell & 0x3FF
            raw = bytes(vram[tid * 32 : tid * 32 + 32])
            row.append(
                {
                    "tx": tx,
                    "ty": ty,
                    "dest": tid,
                    "bank": (cell >> 12) & 0xF,
                    "ko_atlas": lookup_ko.get(raw, []),
                    "jp_atlas": lookup_jp.get(raw, []),
                    "unique": raw not in lookup_ko and raw not in lookup_jp,
                }
            )
        window.append(row)

    evade = [cell for row in window for cell in row if 13 <= cell["tx"] <= 16 and 11 <= cell["ty"] <= 12]
    sea = [cell for row in window for cell in row if 12 <= cell["tx"] <= 15 and 9 <= cell["ty"] <= 10]

    maps = []
    for index in range(80):
        parsed = parse_map(rom, u32(rom, TABLE + index * 4))
        if not parsed:
            continue
        if parsed["width"] == 16 and parsed["height"] in (6, 7, 8, 9):
            maps.append({"index": index, "width": parsed["width"], "height": parsed["height"], "offset": hex(parsed["index_off"]), "first": [hex(c) for c in parsed["cells"][:8]]})
        tiles = [c & 0x3FF for c in parsed["cells"]]
        # 회피 status tiles 0x1A0..1A7 as 4x2
        if parsed["width"] == 4 and parsed["height"] == 2 and tiles[:4] in ([0x1A0, 0x1A1, 0x1A2, 0x1A3], [0x00, 0x01, 0x02, 0x03]):
            maps.append({"index": index, "role": "4x2", "tiles": [hex(t) for t in tiles]})

    # EWRAM 海 token and ROM pointers to E0E100 strings
    token_hits = find_all(ewram, SEA_TOKEN + b"\x00", 24)
    sea_strings = find_all(japan, SEA_TOKEN + b"\x00", 40)
    live_ptrs = []
    for soff in sea_strings:
        addr = ROM_BASE + soff
        needle = struct.pack("<I", addr)
        for space, blob, base in (("ewram", ewram, 0x02000000), ("iwram", state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + 0x8000], 0x03000000)):
            for hit in find_all(blob, needle, 8):
                live_ptrs.append({"payload": hex(soff), "address": hex(addr), "space": space, "offset": hex(hit), "cpu": hex(base + hit)})

    # Any aligned EWRAM word that points at a short ROM C-string containing the sea token.
    candidates = []
    for hit in range(0, len(ewram) - 4, 4):
        ptr = u32(ewram, hit)
        if not (ROM_BASE <= ptr < ROM_BASE + 0x01000000):
            continue
        payload = payload_at(japan, ptr)
        if SEA_TOKEN in payload and 2 <= len(payload) <= 16:
            candidates.append({"ewram": hex(0x02000000 + hit), "ptr": hex(ptr), "payload": payload.hex(), "file": hex(ptr - ROM_BASE)})

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    exact = []
    slot_records = []
    for row in merged["records"]:
        raw = str(row.get("raw_hex") or "").replace(" ", "").upper()
        source = str(row.get("source_text") or "")
        if raw in {"E0E100", "E0 E1 00".replace(" ", "")} or source == "海":
            exact.append(
                {
                    "record_id": row["record_id"],
                    "source_text": source,
                    "translation_ko": row.get("translation_ko"),
                    "translation_status": row.get("translation_status"),
                    "raw_hex": row.get("raw_hex"),
                    "owner_ids": row.get("owner_ids"),
                    "uses_12x12": row.get("uses_12x12"),
                }
            )
        unresolved = [str(x).lower() for x in (row.get("source_unresolved_slots") or [])]
        if "0x01c1" in unresolved and len(source) <= 8:
            slot_records.append(
                {
                    "record_id": row["record_id"],
                    "source_text": source,
                    "translation_ko": row.get("translation_ko"),
                    "translation_status": row.get("translation_status"),
                    "raw_hex": row.get("raw_hex"),
                    "owner_ids": row.get("owner_ids"),
                }
            )

    atlas_counts = Counter()
    for row in window:
        for cell in row:
            for tid in cell["jp_atlas"][:1]:
                atlas_counts[tid] += 1

    report = {
        "atlas_ptr": hex(atlas_ptr),
        "evade_cells": evade,
        "sea_cells": sea,
        "maps_16wide": maps,
        "ewram_token_hits": [hex(h) for h in token_hits],
        "live_ptrs": live_ptrs,
        "ewram_sea_candidates": candidates[:40],
        "ewram_sea_candidate_count": len(candidates),
        "exact_records": exact,
        "slot_01c1_short": slot_records,
        "jp_atlas_tile_histogram_top": atlas_counts.most_common(12),
        "unique_window_tiles": sum(1 for row in window for cell in row if cell["unique"]),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("evade", evade)
    print("sea", sea)
    print("maps", maps)
    print("token_hits", token_hits)
    print("live_ptrs", live_ptrs)
    print("candidates", len(candidates), candidates[:8])
    print("exact", exact)
    print("slot_short", slot_records)
    print("unique", report["unique_window_tiles"], "hist", atlas_counts.most_common(8))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
