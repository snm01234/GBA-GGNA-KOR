#!/usr/bin/env python3
"""Bind LANDFORM window to E0518 maps, 海 strings, and 回避 atlas tiles."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_status_ui_tile_overlay_poc as status
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
)

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass3_20260905.json"
TABLE = 0x000E0518
ROM_BASE = 0x08000000


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def find_all(hay, needle, limit=80):
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
    if not ROM_BASE <= ptr < ROM_BASE + len(rom):
        return None
    off = ptr - ROM_BASE
    width, height = rom[off], rom[off + 1]
    count = width * height
    if width == 0 or height == 0 or count > 2048 or off + 4 + count * 2 > len(rom):
        return None
    cells = list(struct.unpack_from(f"<{count}H", rom, off + 4))
    return {"offset": off, "width": width, "height": height, "cells": cells}


def main():
    state, _ = statefmt.parse_png_state(STATE)
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    info = bg.bg_info(state, 0)
    live = []
    for ty in range(7, 14):
        for tx in range(7, 23):
            live.append(bg.map_entry(vram, info["screen_base"], info["size"], tx, ty) & 0x3FF)

    table_hits = []
    for index in range(80):
        ptr = u32(rom, TABLE + index * 4)
        parsed = parse_map(rom, ptr)
        if not parsed:
            continue
        tiles = [cell & 0x3FF for cell in parsed["cells"]]
        if tiles[:16] == live[:16] or tiles == live:
            table_hits.append({"index": index, "ptr": f"0x{ptr:08X}", **{k: parsed[k] for k in ("offset", "width", "height")}, "first16": tiles[:16]})
        elif parsed["width"] == 16 and parsed["height"] == 7:
            table_hits.append({"index": index, "ptr": f"0x{ptr:08X}", "width": 16, "height": 7, "first16": tiles[:16], "live_prefix": live[:16]})

    # Compare live VRAM tile 736 payload to ROM sheets.
    raw736 = bytes(vram[736 * 32 : 736 * 32 + 32])
    raw806 = bytes(vram[806 * 32 : 806 * 32 + 32])
    window_start_guess = 0x000E2F74
    window_blob = japan[window_start_guess : window_start_guess + 112 * 32]

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    family = []
    for row in merged["records"]:
        rid = str(row.get("record_id") or "")
        if rid.startswith("GGA-TEXT-0018CF") or rid.startswith("GGA-TEXT-0018D"):
            family.append(
                {
                    "record_id": rid,
                    "source_text": row.get("source_text"),
                    "translation_ko": row.get("translation_ko"),
                    "translation_status": row.get("translation_status"),
                    "raw_hex": row.get("raw_hex"),
                    "owner_ids": row.get("owner_ids"),
                    "source_unresolved_slots": row.get("source_unresolved_slots"),
                }
            )

    sea_payloads = find_all(japan, bytes.fromhex("E0 E1 00"), 40)
    sea_payloads_main = find_all(rom, bytes.fromhex("E0 E1 00"), 40)

    iwram = state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    pointer_hits = []
    for off in sea_payloads:
        addr = ROM_BASE + off
        needle = struct.pack("<I", addr)
        hits = find_all(iwram, needle, 8)
        rom_owners = find_all(rom, needle, 12)
        if hits or rom_owners:
            pointer_hits.append(
                {
                    "payload_offset": f"0x{off:08X}",
                    "address": f"0x{addr:08X}",
                    "iwram": [f"0x{h:08X}" for h in hits],
                    "rom_owners": [f"0x{h:08X}" for h in rom_owners],
                }
            )

    # Atlas 회피 tiles 0x1A0-0x1A7 vs live 回避.
    atlas_ptr = u32(rom, TABLE)
    atlas_off = atlas_ptr - ROM_BASE
    header = u32(rom, atlas_off)
    decoded = scan.lzss_decompress(rom[atlas_off + 4 : atlas_off + 4 + (header & 0xFFFF)])
    evade_live = b"".join(bytes(vram[tid * 32 : tid * 32 + 32]) for tid in (806, 807, 808, 809, 822, 823, 824, 825))
    evade_atlas = b"".join(decoded[tid * 32 : tid * 32 + 32] for tid in (0x1A0, 0x1A1, 0x1A2, 0x1A3, 0x1A4, 0x1A5, 0x1A6, 0x1A7))
    jp_atlas_ptr = u32(japan, TABLE)
    jp_off = jp_atlas_ptr - ROM_BASE
    jp_header = u32(japan, jp_off)
    jp_atlas = scan.lzss_decompress(japan[jp_off + 4 : jp_off + 4 + (jp_header & 0xFFFF)])

    report = {
        "live_first16": live[:16],
        "live_count": len(live),
        "raw736_jp_hits": [f"0x{h:08X}" for h in find_all(japan, raw736, 8)],
        "raw806_jp_hits": [f"0x{h:08X}" for h in find_all(japan, raw806, 8)],
        "window_guess_matches_vram736": window_blob[:32] == raw736,
        "window_guess_tile70_matches_806": window_blob[70 * 32 : 71 * 32] == raw806,
        "table_hits": table_hits,
        "atlas_ptr_main": f"0x{atlas_ptr:08X}",
        "atlas_decoded": len(decoded),
        "live_evade_equals_main_atlas_회피": evade_live == evade_atlas,
        "live_evade_equals_jp_atlas_회피_tiles": evade_live == b"".join(jp_atlas[tid * 32 : tid * 32 + 32] for tid in (0x1A0, 0x1A1, 0x1A2, 0x1A3, 0x1A4, 0x1A5, 0x1A6, 0x1A7)),
        "cf_family_count": len(family),
        "cf_family": family,
        "sea_payload_jp": [f"0x{h:08X}" for h in sea_payloads],
        "sea_payload_main": [f"0x{h:08X}" for h in sea_payloads_main],
        "sea_pointer_hits": pointer_hits,
        "exact_sea_records": [
            {
                "record_id": row["record_id"],
                "source_text": row.get("source_text"),
                "translation_ko": row.get("translation_ko"),
                "translation_status": row.get("translation_status"),
                "raw_hex": row.get("raw_hex"),
                "owner_ids": row.get("owner_ids"),
            }
            for row in merged["records"]
            if str(row.get("source_text") or "") in {"海", "海上", "水中", "宇宙", "地上", "空中", "砂漠", "森林", "市街", "山岳", "月", "空"}
            or str(row.get("translation_ko") or "") in {"바다", "해", "우주", "지상", "공중", "사막", "삼림", "시가", "산악"}
        ],
    }
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
    print("table_hits", table_hits)
    print("window736", report["raw736_jp_hits"], "match", report["window_guess_matches_vram736"])
    print("evade_eq_ko_atlas", report["live_evade_equals_main_atlas_회피"])
    print("evade_eq_jp_atlas", report["live_evade_equals_jp_atlas_회피_tiles"])
    print("sea_payloads", report["sea_payload_jp"][:12], "pointers", pointer_hits)
    print("exact_sea", [(r["record_id"], r["source_text"], r["translation_ko"], r["translation_status"]) for r in report["exact_sea_records"]])
    print("cf_count", len(family))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
