#!/usr/bin/env python3
"""Statically close the GGen Advance situation-menu fixed graphics and condition text.

The map situation screen entered from the popup-menu uses a dedicated 150-tile
4bpp atlas at 0x080E59FC plus three tilemaps behind the resource table at
0x080E667C.  Its bottom victory/defeat lines are a separate 12x12 text path:
0x0801C72C selects a length-prefixed pair and 0x0801C746/0x0801C760 render the
two lines through 0x08000CA0.

This analyzer is read-only.  It identifies the red/yellow fixed labels visible
in the situation screen and proves the complete 38 fallback + 18 override
condition-pair domain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT
from build_ggen_advance_map_menu_ui_ko_poc import lzss_decompress
import analyze_stage_condition_text as stage_conditions

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_situation_menu_ui_20260830.json"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

RESOURCE_TABLE = 0x000E667C
ATLAS_RESOURCE = 0x000E59FC
BASE_MAP = 0x000E6150
FRIEND_OVERLAY_MAP = 0x000E6604
EXTRA_OVERLAY_MAP = 0x000E664C
ATLAS_DECODED = 4800

# (map, x, y, width, height) in 8x8 cells.  The tile rectangles were measured
# against the 30x20 situation map and cross-checked against the original 12x12
# source glyphs (ターン数 / 艦 / 自軍 / 敵軍 / 友軍).
LABELS: tuple[dict[str, Any], ...] = (
    {"source": "ターン数", "ko": "턴 수", "map": BASE_MAP, "xy": (19, 1), "size": (8, 2), "role": "turn_count"},
    {"source": "艦", "ko": "함", "map": BASE_MAP, "xy": (23, 4), "size": (3, 2), "role": "ship_count"},
    {"source": "自軍", "ko": "아군", "map": BASE_MAP, "xy": (19, 6), "size": (5, 2), "role": "player_force"},
    {"source": "敵軍", "ko": "적군", "map": BASE_MAP, "xy": (19, 11), "size": (5, 2), "role": "enemy_force"},
    {"source": "友軍", "ko": "우군", "map": FRIEND_OVERLAY_MAP, "xy": (0, 0), "size": (5, 2), "role": "friend_force"},
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def thumb_bl_target(data: bytes, offset: int) -> int:
    high = u16(data, offset)
    low = u16(data, offset + 2)
    gate(high & 0xF800 == 0xF000 and low & 0xF800 == 0xF800, f"not Thumb BL at 0x{ROM_BASE+offset:08X}")
    displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
    if displacement & (1 << 22):
        displacement -= 1 << 23
    return (ROM_BASE + offset + 4 + displacement) & 0xFFFFFFFF


def parse_map(data: bytes, offset: int, expected: tuple[int, int]) -> dict[str, Any]:
    width, height = data[offset], data[offset + 1]
    gate((width, height) == expected, f"map dimensions drift at 0x{offset:08X}: {(width,height)}")
    count = width * height
    cells = list(struct.unpack_from(f"<{count}H", data, offset + 4))
    return {"file_offset": offset, "width": width, "height": height, "cells": cells}


def tile_rect(row: dict[str, Any], x: int, y: int, width: int, height: int) -> list[list[int]]:
    mw = int(row["width"])
    cells = row["cells"]
    return [
        [int(cells[(y + yy) * mw + x + xx]) & 0x03FF for xx in range(width)]
        for yy in range(height)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=JP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(len(data) == 16 * 1024 * 1024, "Japanese ROM must be 16 MiB")
    gate(digest == EXPECTED_JP_SHA256, f"Japanese ROM SHA-256 drift: {digest}")

    table = [u32(data, RESOURCE_TABLE + i * 4) for i in range(5)]
    gate(table == [0x080E59FC, 0, 0x080E6150, 0x080E6604, 0x080E664C], f"situation resource table drift: {table}")

    header = u32(data, ATLAS_RESOURCE)
    gate(header & 0x80000000, "situation atlas is not custom-LZSS")
    compressed_length = header & 0xFFFF
    atlas = lzss_decompress(data[ATLAS_RESOURCE + 4 : ATLAS_RESOURCE + 4 + compressed_length])
    gate(len(atlas) == ATLAS_DECODED, f"situation atlas decoded size drift: {len(atlas)}")
    gate(len(atlas) // 32 == 150, "situation atlas tile count drift")

    base = parse_map(data, BASE_MAP, (30, 20))
    friend = parse_map(data, FRIEND_OVERLAY_MAP, (11, 3))
    extra = parse_map(data, EXTRA_OVERLAY_MAP, (7, 3))
    by_offset = {BASE_MAP: base, FRIEND_OVERLAY_MAP: friend, EXTRA_OVERLAY_MAP: extra}

    label_report: list[dict[str, Any]] = []
    for spec in LABELS:
        x, y = spec["xy"]
        width, height = spec["size"]
        rect = tile_rect(by_offset[int(spec["map"])], x, y, width, height)
        label_report.append({
            "source": spec["source"],
            "translation": spec["ko"],
            "role": spec["role"],
            "map_file_offset": f"0x{int(spec['map']):08X}",
            "map_xy_tiles": [x, y],
            "size_tiles": [width, height],
            "tile_ids": [[f"0x{tile:03X}" for tile in row] for row in rect],
            "style": "12px fixed graphic; bright face index 0xB with dark index-0x4 contour inside the red/yellow label frame",
        })

    # Situation-screen renderer contract.
    gate(thumb_bl_target(data, 0x0001C5FA) == 0x0800261C, "atlas loader call drift")
    gate(thumb_bl_target(data, 0x0001C62E) == 0x0800269C, "base tilemap draw call drift")
    gate(thumb_bl_target(data, 0x0001C6D6) == 0x0800269C, "friend overlay draw call drift")
    gate(thumb_bl_target(data, 0x0001C720) == 0x0800269C, "extra overlay draw call drift")
    gate(thumb_bl_target(data, 0x0001C72C) == 0x08012408, "condition pair selector call drift")
    gate(thumb_bl_target(data, 0x0001C746) == 0x08000CA0, "victory text draw call drift")
    gate(thumb_bl_target(data, 0x0001C760) == 0x08000CA0, "defeat text draw call drift")

    fallback = {u32(data, stage_conditions.SEARCH_DB + i * stage_conditions.SEARCH_STRIDE + stage_conditions.PAIR_FIELD) for i in range(stage_conditions.SEARCH_RECORDS)}
    overrides = {u32(data, offset) for offset in stage_conditions.OVERRIDE_LITERAL_OFFSETS}
    gate(len(fallback) == 38, f"fallback pair count drift: {len(fallback)}")
    gate(len(overrides) == 18, f"override pair count drift: {len(overrides)}")
    gate(not (fallback & overrides), "fallback/override pair overlap drift")
    for pointer in fallback | overrides:
        parsed = stage_conditions.parse_pair(data, pointer)
        gate(bool(parsed["victory_prefix_match"]), f"victory prefix drift at 0x{pointer:08X}")
        gate(bool(parsed["defeat_prefix_match"]), f"defeat prefix drift at 0x{pointer:08X}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_situation_menu_ui_static_analysis",
        "result": "PASS",
        "source": {"path": args.rom.name, "size": len(data), "sha256": digest},
        "renderer": {
            "screen_function": "0x0801C5E0..0x0801C760",
            "resource_table": "0x080E667C",
            "atlas_load": "0x0801C5F4/0x0801C5F8 -> 0x080E59FC -> 0x0800261C",
            "base_map_draw": "0x0801C618/0x0801C62E -> resource_table[2]=0x080E6150 -> 0x0800269C",
            "friend_overlay_draw": "0x0801C6C4/0x0801C6D6 -> resource_table[3]=0x080E6604 -> 0x0800269C",
            "extra_overlay_draw": "0x0801C70C/0x0801C720 -> resource_table[4]=0x080E664C -> 0x0800269C",
        },
        "fixed_graphics": {
            "atlas_file_offset": f"0x{ATLAS_RESOURCE:08X}",
            "compressed_body_length": compressed_length,
            "decoded_bytes": len(atlas),
            "decoded_tiles": len(atlas) // 32,
            "base_map": {"file_offset": f"0x{BASE_MAP:08X}", "dimensions": [30, 20]},
            "friend_overlay_map": {"file_offset": f"0x{FRIEND_OVERLAY_MAP:08X}", "dimensions": [11, 3]},
            "extra_overlay_map": {"file_offset": f"0x{EXTRA_OVERLAY_MAP:08X}", "dimensions": [7, 3], "translation_target_found": False},
            "labels": label_report,
            "kept_literal": ["MS"],
        },
        "condition_text": {
            "font_mode": "12x12 token renderer",
            "selector": "0x08012408 called by 0x0801C72C",
            "victory_draw": "0x0801C746 -> 0x08000CA0 at x=8,y=0x80",
            "defeat_draw": "0x0801C760 -> 0x08000CA0 at x=8,y=0x90",
            "pair_layout": "[len1][victory NUL-stream][len2][defeat NUL-stream]",
            "fallback_unique_pairs": len(fallback),
            "override_unique_pairs": len(overrides),
            "total_unique_pairs": len(fallback | overrides),
            "total_lines": 2 * len(fallback | overrides),
            "example_stage1": {"victory": "勝利条件：敵軍全滅", "defeat": "敗北条件：キラ撃破"},
            "existing_summary": "legacy/analysis/stage_condition_text_static_summary_20260826.json",
        },
        "implementation_scope": {
            "fixed_graphic_targets": {spec["source"]: spec["ko"] for spec in LABELS},
            "condition_policy": "translate all 38 fallback + 18 override pairs, not only the Stage-1 screenshot",
            "preserve": ["MS", "resource dimensions", "unrelated atlas tiles", "condition selector code", "12x12 renderer code"],
        },
        "verification": {
            "result": "PASS",
            "resource_table_verified": True,
            "atlas_150_tiles_verified": True,
            "base_and_overlay_maps_verified": True,
            "five_fixed_label_rectangles_identified": True,
            "condition_selector_and_two_draw_calls_verified": True,
            "all_56_condition_pairs_prefix_validated": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "fixed_labels": len(label_report),
        "condition_pairs": len(fallback | overrides),
        "condition_lines": 2 * len(fallback | overrides),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
