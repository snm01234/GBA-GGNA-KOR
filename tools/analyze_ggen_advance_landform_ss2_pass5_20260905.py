#!/usr/bin/env python3
"""Identify LANDFORM graphic resource and 海 dictionary/text source."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, DICT_8X16_BASE, DICT_8X16_END, load_dictionary

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass5_20260905.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
ROM_BASE = 0x08000000
SEA_SLOT = 0x01C1


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def try_kind2(rom, offset):
    if offset < 0 or offset + 16 > len(rom):
        return None
    kind, dimensions, header_bytes, map_bytes, graphics_rel, graphics_bytes, palette_rel, palette_bytes = struct.unpack_from("<8H", rom, offset)
    if kind != 2 or header_bytes not in (0x10, 0x14):
        return None
    width = dimensions & 0xFF
    height = dimensions >> 8
    if not (1 <= width <= 64 and 1 <= height <= 64):
        return None
    if graphics_bytes == 0 or graphics_bytes % 32:
        return None
    if graphics_rel < header_bytes or offset + graphics_rel + graphics_bytes > len(rom):
        return None
    return {
        "offset": hex(offset),
        "kind": kind,
        "header_bytes": header_bytes,
        "width": width,
        "height": height,
        "map_bytes": map_bytes,
        "graphics_rel": hex(graphics_rel),
        "graphics_offset": hex(offset + graphics_rel),
        "graphics_bytes": graphics_bytes,
        "tile_count": graphics_bytes // 32,
        "palette_rel": hex(palette_rel),
        "palette_bytes": palette_bytes,
    }


def nearest_kind2(rom, hit):
    for back in range(0, 0x4000, 2):
        parsed = try_kind2(rom, hit - back)
        if parsed and int(parsed["graphics_offset"], 16) <= hit < int(parsed["graphics_offset"], 16) + parsed["graphics_bytes"]:
            parsed["tile_index"] = (hit - int(parsed["graphics_offset"], 16)) // 32
            return parsed
    return None


def decode_slots(charmap, slots):
    return "".join(charmap.get(slot, f"<{slot:04X}>") for slot in slots)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    rom = MAIN_TIP_ROM.read_bytes()
    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    dict8 = load_dictionary(japan, DICT_8X16_BASE, DICT_8X16_END)
    sea_dict12 = []
    for index, slots in enumerate(dict12):
        if SEA_SLOT in slots:
            sea_dict12.append({"index": index, "token": hex(0xF000 + index), "slots": [hex(s) for s in slots], "text": decode_slots(charmap, slots)})
    sea_dict8 = []
    for index, slots in enumerate(dict8):
        if SEA_SLOT in slots:
            sea_dict8.append({"index": index, "token": hex(0xF000 + index), "slots": [hex(s) for s in slots]})

    kind2 = nearest_kind2(japan, 0x000E3834)
    landform = japan.find(b"LANDFORM")
    landform_hits = []
    start = 0
    while True:
        pos = japan.find(b"LANDFORM", start)
        if pos < 0:
            break
        landform_hits.append(hex(pos))
        start = pos + 1

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    cats = Counter(str(row.get("semantic_category") or "") for row in merged["records"])
    pending_loc = []
    for row in merged["records"]:
        if row.get("semantic_category") != "stage_location_name":
            continue
        if row.get("translation_status") != "pending":
            continue
        pending_loc.append(
            {
                "record_id": row["record_id"],
                "source_text": row.get("source_text"),
                "raw_hex": row.get("raw_hex"),
                "owner_ids": row.get("owner_ids"),
                "unresolved": row.get("source_unresolved_slots"),
            }
        )

    # ROM owners of kind2 header
    owners = []
    if kind2:
        addr = ROM_BASE + int(kind2["offset"], 16)
        needle = struct.pack("<I", addr)
        pos = 0
        while True:
            hit = rom.find(needle, pos)
            if hit < 0:
                break
            owners.append(hex(hit))
            pos = hit + 1
            if len(owners) >= 20:
                break

    state, _ = statefmt.parse_png_state(STATE)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    raw807 = bytes(vram[807 * 32 : 807 * 32 + 32])
    evade_kind2 = nearest_kind2(japan, japan.find(raw807))

    report = {
        "sea_dict12": sea_dict12,
        "sea_dict8": sea_dict8,
        "kind2_from_e3834": kind2,
        "kind2_from_live807": evade_kind2,
        "kind2_rom_owners": owners,
        "landform_ascii": landform_hits,
        "pending_stage_location_name": pending_loc,
        "semantic_category_top": cats.most_common(40),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("sea_dict12", "sea_dict8", "kind2_from_e3834", "kind2_from_live807", "kind2_rom_owners", "landform_ascii", "pending_stage_location_name")}, ensure_ascii=False, indent=2))
    print("cats", cats.most_common(20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
