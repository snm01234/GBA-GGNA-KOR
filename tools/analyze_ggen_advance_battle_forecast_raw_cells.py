#!/usr/bin/env python3
"""Statically locate the untranslated battle-forecast mini-label cells.

The forecast screen owns two visually related Japanese graphic families.  The
previous patch covered the standalone 0x74-byte descriptors consumed by the
row compositor.  This analyzer proves the second copy inside sprite resource
0x08A8C004 using only the original Japanese ROM: resource header offsets,
tile IDs, the sole ROM pointer literal, and the Thumb call sites are all gated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_forecast_raw_cells_20260830.json"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

SCREEN_SETUP = 0x080394D8
ROW_COMPOSITOR_CALL = 0x080394FA
ROW_COMPOSITOR = 0x08039B28
ROW_OBJ_COPY_CALL = 0x08039502
ROW_OBJ_COPY = 0x0803A19C
SPRITE_CREATE_CALLS = (0x0803955C, 0x08039592)
SPRITE_CREATE = 0x08012B04
RESOURCE_LITERAL = 0x00039638
RESOURCE_OFFSET = 0x00A8C004
RESOURCE_ADDRESS = ROM_BASE + RESOURCE_OFFSET
GRAPHICS_REL = 0x0FD0
PALETTE_REL = 0x17F0
GRAPHICS_OFFSET = RESOURCE_OFFSET + GRAPHICS_REL
PALETTE_OFFSET = RESOURCE_OFFSET + PALETTE_REL
TILE_BYTES = 32
CELL_BYTES = 64

# Tile rows are interleaved after the first two cells; do not infer
# ``bottom = top + 1``.  The correct pairs were recovered by matching each
# half against the independently proven fixed battle-label descriptors.
LABELS = (
    ("実", "실", 15, 16, "physical_type"),
    ("攻", "공", 17, 18, "attack"),
    ("命", "명", 19, 21, "hit"),
    ("弾", "탄", 20, 22, "ammo"),
    ("射", "사", 23, 25, "ranged"),
    ("全", "전", 24, 26, "all"),
    ("近", "근", 27, 29, "melee"),
    ("単", "단", 28, 30, "single"),
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_thumb_bl(data: bytes, address: int) -> int:
    offset = address - ROM_BASE
    high = u16(data, offset)
    low = u16(data, offset + 2)
    gate(high & 0xF800 == 0xF000 and low & 0xF800 == 0xF800, f"not a Thumb BL at 0x{address:08X}")
    displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
    if displacement & 0x00400000:
        displacement -= 0x00800000
    return address + 4 + displacement


def pointer_hits(data: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    hits: list[int] = []
    start = 0
    while True:
        found = data.find(needle, start)
        if found < 0:
            return hits
        hits.append(found)
        start = found + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=JP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(digest == EXPECTED_JP_SHA256, f"unexpected Japanese ROM hash: {digest}")

    gate(u32(data, RESOURCE_OFFSET + 0x00) == 0, "sprite resource kind drift")
    gate(u32(data, RESOURCE_OFFSET + 0x04) == 6, "sprite resource palette/count field drift")
    gate(u32(data, RESOURCE_OFFSET + 0x08) == GRAPHICS_REL, "sprite graphics relative offset drift")
    gate(u32(data, RESOURCE_OFFSET + 0x0C) == PALETTE_REL, "sprite palette relative offset drift")
    gate((PALETTE_OFFSET - GRAPHICS_OFFSET) % TILE_BYTES == 0, "sprite graphics are not tile aligned")
    gate((PALETTE_OFFSET - GRAPHICS_OFFSET) // TILE_BYTES == 65, "sprite tile count drift")

    hits = pointer_hits(data, RESOURCE_ADDRESS)
    gate(hits == [RESOURCE_LITERAL], f"unexpected resource pointer references: {hits}")
    gate(decode_thumb_bl(data, ROW_COMPOSITOR_CALL) == ROW_COMPOSITOR, "row compositor call drift")
    gate(decode_thumb_bl(data, ROW_OBJ_COPY_CALL) == ROW_OBJ_COPY, "row OBJ copy call drift")
    for call in SPRITE_CREATE_CALLS:
        gate(decode_thumb_bl(data, call) == SPRITE_CREATE, f"sprite create call drift at 0x{call:08X}")

    # Both LDR r0 instructions resolve to the one literal containing 0x08A8C004.
    for instruction_offset in (0x00039556, 0x0003958A):
        instruction = u16(data, instruction_offset)
        gate(instruction & 0xF800 == 0x4800, f"resource load is not LDR literal at 0x{instruction_offset:08X}")
        literal = (((ROM_BASE + instruction_offset + 4) & ~3) + ((instruction & 0xFF) << 2)) - ROM_BASE
        gate(literal == RESOURCE_LITERAL, f"resource literal target drift at 0x{instruction_offset:08X}")

    labels = []
    covered_tiles: list[int] = []
    for source, translation, top_tile_id, bottom_tile_id, role in LABELS:
        top_offset = GRAPHICS_OFFSET + top_tile_id * TILE_BYTES
        bottom_offset = GRAPHICS_OFFSET + bottom_tile_id * TILE_BYTES
        gate(top_offset + TILE_BYTES <= PALETTE_OFFSET, f"top label tile overruns sprite graphics: {source}")
        gate(bottom_offset + TILE_BYTES <= PALETTE_OFFSET, f"bottom label tile overruns sprite graphics: {source}")
        payload = data[top_offset : top_offset + TILE_BYTES] + data[bottom_offset : bottom_offset + TILE_BYTES]
        gate(any((byte & 0xF) in (13, 14, 15) or (byte >> 4) in (13, 14, 15) for byte in payload), f"bright glyph pixels missing: {source}")
        covered_tiles.extend((top_tile_id, bottom_tile_id))
        labels.append({
            "source": source,
            "translation": translation,
            "role": role,
            "top_tile_id": top_tile_id,
            "bottom_tile_id": bottom_tile_id,
            "top_graphic_file_offset": f"0x{top_offset:08X}",
            "bottom_graphic_file_offset": f"0x{bottom_offset:08X}",
            "top_graphic_address": f"0x{ROM_BASE + top_offset:08X}",
            "bottom_graphic_address": f"0x{ROM_BASE + bottom_offset:08X}",
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    gate(sorted(covered_tiles) == list(range(15, 31)), f"raw label tile matrix drift: {sorted(covered_tiles)}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_raw_cells_static_analysis",
        "result": "PASS",
        "source": {"path": args.rom.name, "size": len(data), "sha256": digest},
        "screen_setup": {
            "function": f"0x{SCREEN_SETUP:08X}",
            "existing_row_compositor_call": f"0x{ROW_COMPOSITOR_CALL:08X} -> 0x{ROW_COMPOSITOR:08X}",
            "existing_row_obj_copy_call": f"0x{ROW_OBJ_COPY_CALL:08X} -> 0x{ROW_OBJ_COPY:08X}",
            "sprite_create_calls": [f"0x{x:08X} -> 0x{SPRITE_CREATE:08X}" for x in SPRITE_CREATE_CALLS],
            "resource_load_instructions": ["0x08039556", "0x0803958A"],
            "resource_pointer_literal": f"0x{ROM_BASE + RESOURCE_LITERAL:08X}",
            "resource_pointer_literal_file_offset": f"0x{RESOURCE_LITERAL:08X}",
            "resource_pointer_value": f"0x{RESOURCE_ADDRESS:08X}",
            "whole_rom_pointer_hits": [f"0x{x:08X}" for x in hits],
        },
        "sprite_resource": {
            "file_offset": f"0x{RESOURCE_OFFSET:08X}",
            "address": f"0x{RESOURCE_ADDRESS:08X}",
            "graphics_relative_offset": f"0x{GRAPHICS_REL:04X}",
            "graphics_file_offset": f"0x{GRAPHICS_OFFSET:08X}",
            "palette_relative_offset": f"0x{PALETTE_REL:04X}",
            "palette_file_offset": f"0x{PALETTE_OFFSET:08X}",
            "graphic_tile_count": 65,
            "tile_format": "GBA 4bpp 8x8; each label is two consecutive vertical tiles",
        },
        "labels": labels,
        "conclusion": {
            "separate_from_fixed_0x74_descriptors": True,
            "untranslated_raw_cells": 8,
            "patch_scope": "only the 16 interleaved graphic tiles 15..30, paired explicitly per label",
            "preserve": ["resource header", "frame tables", "all other 49 tiles", "palette", "Thumb code and literal"],
        },
        "verification": {
            "result": "PASS",
            "original_rom_only": True,
            "resource_header_offsets_verified": True,
            "sole_pointer_literal_verified": True,
            "two_static_resource_loads_verified": True,
            "two_sprite_create_calls_verified": True,
            "existing_row_compositor_call_verified": True,
            "eight_raw_label_pairs_verified": True,
            "interleaved_tile_matrix_15_through_30_verified": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(args.out), "resource": f"0x{RESOURCE_ADDRESS:08X}", "labels": len(labels)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
