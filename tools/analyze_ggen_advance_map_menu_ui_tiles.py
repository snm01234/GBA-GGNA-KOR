#!/usr/bin/env python3
"""Audit the map popup-menu fixed graphics and focused-item overlays.

This is a read-only structural analyzer for the separate map-menu 4bpp atlas.
It proves that the five visible commands are stored twice: once in the normal
10x14 popup map and once again as independent 8x2 focused overlays selected by
the cursor.  The menu atlas is distinct from the status UI atlas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DEFAULT_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_map_menu_ui_tiles_20260829.json"

MENU_RESOURCE_TABLE = 0x000D354C
MENU_ATLAS_RESOURCE = 0x000D2490
MENU_ATLAS_EXPECTED_DECODED = 6944
MENU_NORMAL_RESOURCE = 2
MENU_NORMAL_MAP = 0x000D311C
MENU_ALT_RESOURCE = 3
MENU_ALT_MAP = 0x000D3238
FOCUS_RESOURCES = (4, 5, 6, 7, 8)
FOCUS_OFFSETS = (0x000D3450, 0x000D3474, 0x000D3498, 0x000D34BC, 0x000D34E0)
EXTRA_RESOURCE = 9
EXTRA_OFFSET = 0x000D3504
SECOND_EXTRA_RESOURCE = 10
SECOND_EXTRA_OFFSET = 0x000D3528

COMMANDS = (
    ("ターン終了", "턴 종료"),
    ("中断", "중단"),
    ("状況", "상황"),
    ("部隊一覧", "부대목록"),
    ("設定", "설정"),
)

# x=1..8 inside resource[2], two tile rows per command.
NORMAL_TILE_IDS = {
    "ターン終了": [[0x008, 0x009, 0x00A, 0x00B, 0x00C, 0x00D, 0x00E, 0x00F],
                 [0x011, 0x012, 0x013, 0x014, 0x015, 0x016, 0x017, 0x018]],
    "中断": [[0x019, 0x01A, 0x01B, 0x01C, 0x01D, 0x01E, 0x01A, 0x01F],
             [0x020, 0x021, 0x022, 0x023, 0x024, 0x025, 0x021, 0x026]],
    "状況": [[0x019, 0x01A, 0x027, 0x028, 0x029, 0x02A, 0x01A, 0x01F],
             [0x020, 0x021, 0x02B, 0x02C, 0x02D, 0x02E, 0x021, 0x026]],
    "部隊一覧": [[0x02F, 0x030, 0x031, 0x032, 0x033, 0x034, 0x035, 0x036],
                 [0x037, 0x038, 0x039, 0x03A, 0x03B, 0x03C, 0x03D, 0x03E]],
    "設定": [[0x019, 0x01A, 0x03F, 0x040, 0x041, 0x042, 0x01A, 0x01F],
             [0x020, 0x021, 0x043, 0x044, 0x045, 0x046, 0x021, 0x026]],
}

FOCUS_TILE_IDS = {
    "ターン終了": [[0x07C, 0x07D, 0x07E, 0x07F, 0x080, 0x081, 0x082, 0x083],
                 [0x084, 0x085, 0x086, 0x087, 0x088, 0x089, 0x08A, 0x08B]],
    "中断": [[0x08C, 0x08D, 0x08E, 0x08F, 0x090, 0x091, 0x08D, 0x092],
             [0x093, 0x094, 0x095, 0x096, 0x097, 0x098, 0x094, 0x099]],
    "状況": [[0x08C, 0x08D, 0x09A, 0x09B, 0x09C, 0x09D, 0x08D, 0x092],
             [0x093, 0x094, 0x09E, 0x09F, 0x0A0, 0x0A1, 0x094, 0x099]],
    "部隊一覧": [[0x0A2, 0x0A3, 0x0A4, 0x0A5, 0x0A6, 0x0A7, 0x0A8, 0x0A9],
                 [0x0AA, 0x0AB, 0x0AC, 0x0AD, 0x086, 0x0AE, 0x0AF, 0x0B0]],
    "設定": [[0x08C, 0x08D, 0x0B1, 0x0B2, 0x0B3, 0x0B4, 0x08D, 0x092],
             [0x093, 0x094, 0x0B5, 0x0B6, 0x0B7, 0x0B8, 0x094, 0x099]],
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def lzss_decompress(payload: bytes) -> bytes:
    ring = bytearray(4096)
    ring_pos = 4078
    out = bytearray()
    src = 0
    flags = 0
    while src < len(payload):
        flags >>= 1
        if (flags & 0x100) == 0:
            flags = payload[src] | 0xFF00
            src += 1
        if flags & 1:
            gate(src < len(payload), "literal overruns compressed menu atlas")
            value = payload[src]
            src += 1
            out.append(value)
            ring[ring_pos] = value
            ring_pos = (ring_pos + 1) & 0xFFF
        else:
            gate(src + 1 < len(payload), "back-reference overruns compressed menu atlas")
            lo = payload[src]
            hi = payload[src + 1]
            src += 2
            offset = lo | ((hi & 0xF0) << 4)
            length = (hi & 0x0F) + 3
            for index in range(length):
                value = ring[(offset + index) & 0xFFF]
                out.append(value)
                ring[ring_pos] = value
                ring_pos = (ring_pos + 1) & 0xFFF
    return bytes(out)


def parse_map(data: bytes, index: int) -> dict[str, Any]:
    address = u32(data, MENU_RESOURCE_TABLE + index * 4)
    gate(ROM_BASE <= address < ROM_BASE + EXPECTED_SIZE, f"menu resource[{index}] pointer outside ROM")
    offset = address - ROM_BASE
    width, height = data[offset], data[offset + 1]
    count = width * height
    gate(width > 0 and height > 0 and count <= 1000, f"menu resource[{index}] invalid dimensions")
    gate(offset + 4 + count * 2 <= len(data), f"menu resource[{index}] overruns ROM")
    cells = list(struct.unpack_from(f"<{count}H", data, offset + 4))
    return {
        "index": index,
        "file_offset": offset,
        "address": address,
        "width": width,
        "height": height,
        "cells": cells,
    }


def tile_rows(row: dict[str, Any]) -> list[list[int]]:
    width = int(row["width"])
    return [
        [int(cell) & 0x03FF for cell in row["cells"][y * width : (y + 1) * width]]
        for y in range(int(row["height"]))
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(len(data) == EXPECTED_SIZE, f"unexpected ROM size: {len(data)}")
    gate(digest == EXPECTED_SHA256, f"unexpected Japanese ROM hash: {digest}")

    atlas_header = u32(data, MENU_ATLAS_RESOURCE)
    gate(atlas_header & 0x80000000, "menu atlas is not custom-LZSS compressed")
    comp_len = atlas_header & 0xFFFF
    atlas = lzss_decompress(data[MENU_ATLAS_RESOURCE + 4 : MENU_ATLAS_RESOURCE + 4 + comp_len])
    gate(len(atlas) == MENU_ATLAS_EXPECTED_DECODED, f"menu atlas decoded-size drift: {len(atlas)}")
    gate(len(atlas) % 32 == 0, "menu atlas not aligned to GBA 4bpp tiles")

    normal = parse_map(data, MENU_NORMAL_RESOURCE)
    alt = parse_map(data, MENU_ALT_RESOURCE)
    gate(normal["file_offset"] == MENU_NORMAL_MAP, "normal menu resource[2] pointer drift")
    gate((normal["width"], normal["height"]) == (10, 14), "normal menu map dimensions drift")
    gate(alt["file_offset"] == MENU_ALT_MAP, "alternate menu resource[3] pointer drift")
    gate((alt["width"], alt["height"]) == (19, 14), "alternate menu map dimensions drift")
    normal_rows = tile_rows(normal)

    normal_report: dict[str, Any] = {}
    for cursor, (source, ko) in enumerate(COMMANDS):
        y = 1 + cursor * 2
        actual = [normal_rows[y][1:9], normal_rows[y + 1][1:9]]
        gate(actual == NORMAL_TILE_IDS[source], f"normal {source} tile layout drift")
        normal_report[source] = {
            "ko_target": ko,
            "cursor_index": cursor,
            "map_xy": [1, y],
            "size_tiles": [8, 2],
            "tile_ids": [[f"0x{x:03X}" for x in row] for row in actual],
        }

    focus_report: dict[str, Any] = {}
    for cursor, (source, ko) in enumerate(COMMANDS):
        index = FOCUS_RESOURCES[cursor]
        row = parse_map(data, index)
        gate(row["file_offset"] == FOCUS_OFFSETS[cursor], f"focus resource[{index}] pointer drift")
        gate((row["width"], row["height"]) == (8, 2), f"focus resource[{index}] dimensions drift")
        actual = tile_rows(row)
        gate(actual == FOCUS_TILE_IDS[source], f"focus {source} tile layout drift")
        focus_report[source] = {
            "ko_target": ko,
            "cursor_index": cursor,
            "resource_index": index,
            "file_offset": f"0x{row['file_offset']:08X}",
            "size_tiles": [8, 2],
            "tile_ids": [[f"0x{x:03X}" for x in tiles] for tiles in actual],
        }

    extra = parse_map(data, EXTRA_RESOURCE)
    gate(extra["file_offset"] == EXTRA_OFFSET, "extra resource[9] pointer drift")
    gate((extra["width"], extra["height"]) == (8, 2), "extra resource[9] dimensions drift")
    second_extra = parse_map(data, SECOND_EXTRA_RESOURCE)
    gate(second_extra["file_offset"] == SECOND_EXTRA_OFFSET, "extra resource[10] pointer drift")
    gate(
        (second_extra["width"], second_extra["height"]) == (8, 2),
        "extra resource[10] dimensions drift",
    )
    gate(
        tile_rows(second_extra)
        == [list(range(0x0C9, 0x0D1)), list(range(0x0D1, 0x0D9))],
        "focused cancel tile layout drift",
    )

    # The renderer at 0x08021A8C proves the focus asset is independently drawn:
    # r5=table, base resource[2] at [r5+8], cursor y=2*index+5, then
    # resource pointer=(index+4)*4+table.  This is the structural reason a
    # highlighted command looks enlarged/different in the screenshot.
    renderer_contract = {
        "function": "0x08021A8C",
        "table_literal_refs": ["0x080219F0", "0x08021AE8", "0x08021B40"],
        "normal_draw": {
            "resource_index": 2,
            "table_load": "ldr r3,[r5,#8]",
            "screen_tile_xy": [3, 4],
        },
        "focus_draw": {
            "resource_formula": "resource_table[4 + cursor_index]",
            "screen_x_tiles": 4,
            "screen_y_formula": "2*cursor_index + 5",
            "blitter": "0x0800269C",
        },
        "conclusion": "focused menu item is a separate 8x2 graphic overlay, not a palette-only enlargement",
    }

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_map_menu_ui_tiles",
        "result": "PASS",
        "source": {"path": args.rom.name, "size": len(data), "sha256": digest},
        "menu_asset_family": {
            "resource_table_file_offset": f"0x{MENU_RESOURCE_TABLE:08X}",
            "resource_table_address": f"0x{ROM_BASE + MENU_RESOURCE_TABLE:08X}",
            "atlas_file_offset": f"0x{MENU_ATLAS_RESOURCE:08X}",
            "atlas_address": f"0x{ROM_BASE + MENU_ATLAS_RESOURCE:08X}",
            "compressed_body_length": comp_len,
            "decoded_size": len(atlas),
            "decoded_tile_count": len(atlas) // 32,
            "tile_format": "GBA 4bpp 8x8",
            "separate_from_status_atlas": True,
        },
        "renderer_contract": renderer_contract,
        "normal_menu": normal_report,
        "focused_menu": focus_report,
        "alternate_context": {
            "resource_index": 3,
            "file_offset": f"0x{alt['file_offset']:08X}",
            "size_tiles": [alt["width"], alt["height"]],
            "status": "identified as a second menu-context map; semantic mapping remains pending",
        },
        "extra_focus_like_resource": {
            "resource_index": 9,
            "file_offset": f"0x{extra['file_offset']:08X}",
            "size_tiles": [extra["width"], extra["height"]],
            "semantic": "終了する focused overlay",
            "ko_target": "종료한다",
        },
        "second_extra_focus_resource": {
            "resource_index": 10,
            "file_offset": f"0x{second_extra['file_offset']:08X}",
            "size_tiles": [second_extra["width"], second_extra["height"]],
            "tile_ids": [
                [f"0x{x:03X}" for x in row]
                for row in tile_rows(second_extra)
            ],
            "semantic": "キャンセル focused overlay",
            "ko_target": "캔슬",
            "collision_warning": "tiles 0x0C9..0x0D8 are occupied and must never be used as scratch space",
        },
        "implementation_plan": {
            "normal": "rewrite both normal 8x2 label rows using the original normal-row frame/background and Korean condensed 8x16 glyphs",
            "focus": "rewrite resource[4..8] separately using the original focused frame/background and larger Korean 12x12 glyphs",
            "translations": {source: ko for source, ko in COMMANDS},
            "preserve": ["palette data", "resource dimensions", "resource[9] tilemap", "resource[10] tilemap"],
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "menu_atlas_decoded": len(atlas),
        "normal_commands": len(normal_report),
        "focus_overlays": len(focus_report),
        "focus_is_separate_graphic": True,
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
