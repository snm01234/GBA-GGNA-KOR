#!/usr/bin/env python3
"""Statically close the G Generation Advance settings and suspend-message UI.

This analyzer is intentionally read-only.  It proves two screen families that
remain Japanese in the approved Korean main TIP:

* map-menu Settings (設定): three 30x20 BG resources are loaded by 0x08020EC8.
  The visible yellow/green fixed-label layer is 0x08C70DF0, while ON/OFF and
  the 1..4 speed buttons are separately composited from a six-record table.
  The footer title is a normal 12x12 text-render call.
* map-menu Suspend (中断): 0x08020AAC does not print the warning through the
  text renderer.  It instantiates animation 11 from shared sprite resource
  0x08C7504C.  The warning sentence is therefore baked into OBJ graphics.

The follow-up analysis additionally separates OBJ destination tile numbers
from the resource-local source-tile lookup that follows animation 11's OAM
entries.  This distinction explains the first candidate's real-hardware
failure: it repainted destination IDs as though they were ROM source tiles.
The complete warning text field is 144x48 (upper objects 9..11 plus lower
objects 2..6), not the earlier 144x32 assumption.  The recommended
implementation is a cloned resource with private appended source tiles and only
the suspend call-site literal redirected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM

ROM_BASE = 0x08000000
EXPECTED_JP_SIZE = 16 * 1024 * 1024
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_settings_suspend_ui_20260830.json"

MENU_ACTION_TABLE = 0x00D56408
SUSPEND_FUNCTION = 0x08020AAC
SETTINGS_FUNCTION = 0x08020EC8
SPRITE_CREATE = 0x08012B04
TEXT_DRAW_12 = 0x08000CA0
BG_RESOURCE_DRAW = 0x08001D70
CUSTOM_LZSS = 0x08001A84

SETTINGS_RESOURCES = (
    {"address": 0x08C727E4, "literal": 0x00021040, "call": 0x08020F4C, "destination": 0x0600F800, "role": "background_layer_a"},
    {"address": 0x08C71984, "literal": 0x00021048, "call": 0x08020F66, "destination": 0x06007800, "role": "background_layer_b"},
    {"address": 0x08C70DF0, "literal": 0x00021050, "call": 0x08020F8C, "destination": 0x0600E800, "role": "foreground_fixed_labels"},
)
SETTINGS_FOREGROUND = 0x08C70DF0
OPTION_TABLE = 0x00D562B4
TITLE_LITERAL = 0x0002105C
TITLE_POINTER = 0x081BE8C4
TITLE_DRAW_CALL = 0x0802100A
SETTINGS_FOREGROUND_RUNTIME_TILE_BASE = 0x00C9
SETTINGS_OPTION_RUNTIME_TILE_BASE = 0x0191
SETTINGS_MAX_FOREGROUND_TILES = SETTINGS_OPTION_RUNTIME_TILE_BASE - SETTINGS_FOREGROUND_RUNTIME_TILE_BASE

SUSPEND_RESOURCE = 0x08C7504C
SUSPEND_RESOURCE_LITERAL = 0x00020B98
SUSPEND_CREATE_CALL = 0x08020B10
SUSPEND_POST_CREATE_CALL = 0x08020B56
SUSPEND_SAVE_CALL = 0x08020B2A
SUSPEND_SAVE_TARGET = 0x08061984
SUSPEND_ANIMATION = 11
POST_ANIMATION = 5
RESOURCE_POINTER_HITS = [0x0001212C, 0x000121CC, 0x00020B98, 0x00026B6C, 0x0007385C]

# GBA OBJ tile dimensions by shape (attr0 bits14..15) and size (attr1 bits14..15).
OBJ_DIMS = {
    (0, 0): (1, 1), (0, 1): (2, 2), (0, 2): (4, 4), (0, 3): (8, 8),
    (1, 0): (2, 1), (1, 1): (4, 1), (1, 2): (4, 2), (1, 3): (8, 4),
    (2, 0): (1, 2), (2, 1): (1, 4), (2, 2): (2, 4), (2, 3): (4, 8),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def thumb_bl_target(data: bytes | bytearray, address: int) -> int:
    offset = address - ROM_BASE
    high = u16(data, offset)
    low = u16(data, offset + 2)
    gate(high & 0xF800 == 0xF000 and low & 0xF800 == 0xF800, f"not Thumb BL at 0x{address:08X}")
    displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
    if displacement & 0x00400000:
        displacement -= 0x00800000
    return (address + 4 + displacement) & 0xFFFFFFFF


def literal_address(data: bytes | bytearray, instruction_address: int) -> tuple[int, int]:
    """Resolve a Thumb16 LDR literal and return (literal_address, value)."""
    offset = instruction_address - ROM_BASE
    insn = u16(data, offset)
    gate(insn & 0xF800 == 0x4800, f"not Thumb LDR literal at 0x{instruction_address:08X}")
    literal = ((instruction_address + 4) & ~3) + ((insn & 0xFF) << 2)
    return literal, u32(data, literal - ROM_BASE)


def pointer_hits(data: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    hits: list[int] = []
    cursor = 0
    while True:
        found = data.find(needle, cursor)
        if found < 0:
            return hits
        hits.append(found)
        cursor = found + 1


def custom_lzss_decompress(payload: bytes) -> bytes:
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
            gate(src < len(payload), "literal overruns settings resource")
            value = payload[src]
            src += 1
            out.append(value)
            ring[ring_pos] = value
            ring_pos = (ring_pos + 1) & 0xFFF
        else:
            gate(src + 1 < len(payload), "back-reference overruns settings resource")
            lo = payload[src]
            hi = payload[src + 1]
            src += 2
            source = lo | ((hi & 0xF0) << 4)
            length = (hi & 0x0F) + 3
            for index in range(length):
                value = ring[(source + index) & 0xFFF]
                out.append(value)
                ring[ring_pos] = value
                ring_pos = (ring_pos + 1) & 0xFFF
    return bytes(out)


def parse_bg_resource(data: bytes, address: int) -> dict[str, Any]:
    offset = address - ROM_BASE
    flags = data[offset]
    width = data[offset + 2]
    height = data[offset + 3]
    map_rel, map_len, tiles_rel, compressed_len, palette_rel, palette_len = struct.unpack_from("<HHHHHH", data, offset + 4)
    gate((width, height) == (30, 20), f"settings BG dimensions drift at 0x{address:08X}")
    gate(map_len == width * height * 2, f"settings map length drift at 0x{address:08X}")
    map_offset = offset + map_rel
    cells = list(struct.unpack_from(f"<{width*height}H", data, map_offset))
    compressed = data[offset + tiles_rel : offset + tiles_rel + compressed_len]
    decoded = custom_lzss_decompress(compressed)
    gate(len(decoded) % 32 == 0, f"decoded settings tiles are not 4bpp aligned at 0x{address:08X}")
    return {
        "address": address,
        "file_offset": offset,
        "flags": flags,
        "width": width,
        "height": height,
        "map_relative_offset": map_rel,
        "map_length": map_len,
        "tiles_relative_offset": tiles_rel,
        "compressed_tile_length": compressed_len,
        "decoded_tile_bytes": len(decoded),
        "decoded_tiles": len(decoded) // 32,
        "palette_relative_offset": palette_rel,
        "palette_length": palette_len,
        "cells": cells,
    }


def map_rect(resource: dict[str, Any], x: int, y: int, width: int, height: int) -> list[list[int]]:
    map_width = int(resource["width"])
    cells = resource["cells"]
    return [
        [int(cells[(y + yy) * map_width + x + xx]) & 0x03FF for xx in range(width)]
        for yy in range(height)
    ]


def animation_records(data: bytes, resource_address: int) -> tuple[int, list[tuple[int, bytes]]]:
    offset = resource_address - ROM_BASE
    graphics_rel = u32(data, offset + 0x08)
    count = u32(data, offset + 0x10)
    gate(1 <= count <= 64, f"implausible sprite animation count: {count}")
    rels = [u32(data, offset + 0x14 + index * 4) for index in range(count)]
    starts = [offset + 0x14 + rel for rel in rels]
    ends = starts[1:] + [offset + graphics_rel]
    records: list[tuple[int, bytes]] = []
    for index, (start, end) in enumerate(zip(starts, ends)):
        gate(start < end <= offset + graphics_rel, f"animation {index} record outside resource header area")
        records.append((start, data[start:end]))
    return graphics_rel, records


def parse_animation_oam(record: bytes) -> dict[str, Any]:
    marker = record.find(b"\x40\x00\x40\x00")
    gate(marker >= 0, "animation metasprite marker not found")
    gate(marker + 0x2C <= len(record), "truncated animation metasprite header")
    object_count = u16(record, marker + 0x22)
    entries_start = marker + 0x2C
    gate(1 <= object_count <= 64, f"implausible OBJ count: {object_count}")
    gate(entries_start + object_count * 8 <= len(record), "animation OBJ entries overrun record")
    objects: list[dict[str, Any]] = []
    for index in range(object_count):
        attr0, attr1, attr2, _padding = struct.unpack_from("<HHHH", record, entries_start + index * 8)
        shape = (attr0 >> 14) & 3
        size = (attr1 >> 14) & 3
        gate((shape, size) in OBJ_DIMS, f"unsupported OBJ shape/size {shape}/{size}")
        tiles_w, tiles_h = OBJ_DIMS[(shape, size)]
        tile_count = tiles_w * tiles_h
        tile_start = attr2 & 0x03FF
        tile_end = tile_start + tile_count - 1
        x = attr1 & 0x01FF
        y = attr0 & 0x00FF
        if x >= 256:
            x -= 512
        if y >= 128:
            y -= 256
        objects.append({
            "index": index,
            "x": x,
            "y": y,
            "shape": shape,
            "size": size,
            "size_px": [tiles_w * 8, tiles_h * 8],
            "tile_count": tile_count,
            "tile_start": tile_start,
            "tile_end": tile_end,
            "palette_bank": (attr2 >> 12) & 0xF,
        })
    return {
        "marker_offset": marker,
        "object_count": object_count,
        "entries_start": entries_start,
        "entries_end": entries_start + object_count * 8,
        "objects": objects,
    }


def parse_animation_source_tiles(record: bytes, parsed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse the source-tile lookup that follows the metasprite OAM entries.

    OAM attr2 contains *destination* OBJ-VRAM tile IDs.  The resource-local
    source graphics are selected by a second u16 table immediately after the
    OAM list, one source tile ID per destination tile.  The previous analysis
    incorrectly treated attr2 ranges as source graphic offsets, which explains
    the real-hardware symptom where Japanese text stayed intact while unrelated
    Korean fragments appeared near the warning icon.
    """
    if parsed is None:
        parsed = parse_animation_oam(record)
    source_start = int(parsed["entries_end"])
    total_tiles = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    source_end = source_start + total_tiles * 2
    gate(source_end <= len(record), "animation source-tile lookup overruns record")
    source_ids = list(struct.unpack_from(f"<{total_tiles}H", record, source_start))
    by_object: list[list[int]] = []
    cursor = 0
    for obj in parsed["objects"]:
        count = int(obj["tile_count"])
        by_object.append(source_ids[cursor : cursor + count])
        cursor += count
    gate(cursor == total_tiles, "animation source-tile lookup length drift")
    return {
        "source_table_offset": source_start,
        "source_table_end": source_end,
        "total_source_entries": total_tiles,
        "source_ids": source_ids,
        "by_object": by_object,
        "trailer": record[source_end:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=JP_ROM)
    parser.add_argument("--main", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    jp = args.rom.read_bytes()
    main_tip = args.main.read_bytes()
    gate(len(jp) == EXPECTED_JP_SIZE, "Japanese ROM must be 16 MiB")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM hash drift: {sha256(jp)}")
    gate(len(main_tip) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    manifest_main_hash = str(main_manifest.get("sha256", ""))
    gate(manifest_main_hash and sha256(main_tip) == manifest_main_hash, f"main TIP/manifest hash drift: rom={sha256(main_tip)} manifest={manifest_main_hash}")

    # Map popup dispatch: index 1 = 中断, index 4 = 設定.  Thumb pointers carry bit0.
    gate(u32(jp, MENU_ACTION_TABLE + 1 * 4) == SUSPEND_FUNCTION + 1, "map menu suspend dispatch drift")
    gate(u32(jp, MENU_ACTION_TABLE + 4 * 4) == SETTINGS_FUNCTION + 1, "map menu settings dispatch drift")

    settings_report: list[dict[str, Any]] = []
    parsed_by_address: dict[int, dict[str, Any]] = {}
    for spec in SETTINGS_RESOURCES:
        address = int(spec["address"])
        literal = int(spec["literal"])
        call = int(spec["call"])
        gate(u32(jp, literal) == address, f"settings resource literal drift at 0x{literal:08X}")
        gate(thumb_bl_target(jp, call) == BG_RESOURCE_DRAW, f"settings BG draw call drift at 0x{call:08X}")
        resource = parse_bg_resource(jp, address)
        parsed_by_address[address] = resource
        settings_report.append({
            "role": spec["role"],
            "address": f"0x{address:08X}",
            "file_offset": f"0x{resource['file_offset']:08X}",
            "literal_file_offset": f"0x{literal:08X}",
            "draw_call": f"0x{call:08X} -> 0x{BG_RESOURCE_DRAW:08X}",
            "destination": f"0x{int(spec['destination']):08X}",
            "dimensions": [resource["width"], resource["height"]],
            "decoded_tiles": resource["decoded_tiles"],
            "compressed_tile_length": resource["compressed_tile_length"],
            "palette_length": resource["palette_length"],
            "whole_rom_pointer_hits": [f"0x{x:08X}" for x in pointer_hits(jp, address)],
        })

    foreground = parsed_by_address[SETTINGS_FOREGROUND]
    # Fixed label rectangles are contiguous unique 2-row tile strips in the foreground map.
    fixed_rects = {
        "各種設定を行います": (8, 1, 14, 2),
        "攻撃方法の確認": (6, 5, 12, 2),
        "メッセージの自動送り": (4, 9, 14, 2),
        # The speed row mixes fixed text with separately overlaid numbered buttons.
        "メッセージ表示速度_早い_遅い": (1, 13, 29, 2),
    }
    fixed_report: dict[str, Any] = {}
    for source, rect in fixed_rects.items():
        x, y, width, height = rect
        tiles = map_rect(foreground, x, y, width, height)
        fixed_report[source] = {
            "map_xy": [x, y],
            "size_tiles": [width, height],
            "tile_ids": [[f"0x{value:03X}" for value in row] for row in tiles],
        }
    gate(map_rect(foreground, 8, 1, 14, 2) == [list(range(0x005, 0x013)), list(range(0x013, 0x021))], "settings title strip tile IDs drift")
    gate(map_rect(foreground, 6, 5, 12, 2) == [list(range(0x021, 0x02D)), list(range(0x02D, 0x039))], "settings attack strip tile IDs drift")
    gate(map_rect(foreground, 4, 9, 14, 2) == [list(range(0x039, 0x047)), list(range(0x047, 0x055))], "settings auto-message strip tile IDs drift")

    option_rows: list[dict[str, Any]] = []
    expected_meta = [0x00000514, 0x00000519, 0x00000D12, 0x00000D14, 0x00000D16, 0x00000D18]
    for index in range(6):
        offset = OPTION_TABLE + index * 0x10
        normal, selected, alternate, meta = struct.unpack_from("<IIII", jp, offset)
        gate(meta == expected_meta[index], f"settings option-table metadata drift at record {index}")
        option_rows.append({
            "index": index,
            "normal_graphic": f"0x{normal:08X}",
            "selected_graphic": f"0x{selected:08X}",
            "alternate_graphic": f"0x{alternate:08X}",
            "meta": f"0x{meta:08X}",
            "x_tiles": meta & 0xFF,
            "y_tiles": (meta >> 8) & 0xFF,
            "semantic": (
                "ON/OFF choice" if index < 2 else f"speed button {index-1}"
            ),
        })

    gate(u32(jp, TITLE_LITERAL) == TITLE_POINTER, "settings footer title pointer drift")
    gate(thumb_bl_target(jp, TITLE_DRAW_CALL) == TEXT_DRAW_12, "settings footer is no longer 12x12 text draw")

    # Runtime tile ownership.  The fixed foreground is loaded at tile base 0xC9.
    # The option helper later starts its transient graphics at 0x191.  The first
    # failed candidate expanded the foreground to 269 tiles, so 0xC9+269=0x1D6
    # crossed the option base and produced the observed ON/OFF fragments.
    gate(u16(jp, 0x00020F6A) == 0x22C9, "settings foreground runtime tile-base instruction drift")
    gate(u16(jp, 0x00020F90) == 0x23C8 and u16(jp, 0x00020F92) == 0x4499, "settings option runtime tile-base add drift")
    gate(foreground["decoded_tiles"] == 131, "settings original foreground tile count drift")
    gate(SETTINGS_FOREGROUND_RUNTIME_TILE_BASE + foreground["decoded_tiles"] <= SETTINGS_OPTION_RUNTIME_TILE_BASE, "original settings foreground unexpectedly overlaps dynamic options")

    # Suspend warning popup.
    gate(u32(jp, SUSPEND_RESOURCE_LITERAL) == SUSPEND_RESOURCE, "suspend sprite resource literal drift")
    gate(thumb_bl_target(jp, SUSPEND_CREATE_CALL) == SPRITE_CREATE, "suspend warning create call drift")
    gate(thumb_bl_target(jp, SUSPEND_POST_CREATE_CALL) == SPRITE_CREATE, "suspend post-warning create call drift")
    gate(thumb_bl_target(jp, SUSPEND_SAVE_CALL) == SUSPEND_SAVE_TARGET, "suspend save routine call drift")

    suspend_start = SUSPEND_FUNCTION - ROM_BASE
    suspend_end = 0x00020C2C
    text_draw_calls: list[int] = []
    for offset in range(suspend_start, suspend_end - 3, 2):
        high = u16(jp, offset)
        low = u16(jp, offset + 2)
        if high & 0xF800 == 0xF000 and low & 0xF800 == 0xF800:
            address = ROM_BASE + offset
            if thumb_bl_target(jp, address) == TEXT_DRAW_12:
                text_draw_calls.append(address)
    gate(not text_draw_calls, "suspend function unexpectedly uses the 12x12 text renderer")

    resource_offset = SUSPEND_RESOURCE - ROM_BASE
    gate(u32(jp, resource_offset + 0x00) == 0, "suspend sprite resource kind drift")
    gate(u32(jp, resource_offset + 0x04) == 6, "suspend sprite resource header field drift")
    graphics_rel = u32(jp, resource_offset + 0x08)
    palette_rel = u32(jp, resource_offset + 0x0C)
    animation_count = u32(jp, resource_offset + 0x10)
    gate(graphics_rel == 0x0E04, "suspend resource graphics offset drift")
    gate(palette_rel == 0x2EC4, "suspend resource palette offset drift")
    gate(animation_count == 12, "suspend sprite animation count drift")
    graphics_bytes = palette_rel - graphics_rel
    gate(graphics_bytes % 32 == 0 and graphics_bytes // 32 == 262, "suspend sprite graphics tile count drift")

    _graphics_rel, records = animation_records(jp, SUSPEND_RESOURCE)
    animation_reports: list[dict[str, Any]] = []
    destination_tile_users: dict[int, list[int]] = {}
    parsed_records: list[dict[str, Any]] = []
    for index, (start, record) in enumerate(records):
        parsed = parse_animation_oam(record)
        parsed_records.append(parsed)
        ranges: list[list[int]] = []
        for obj in parsed["objects"]:
            a = int(obj["tile_start"])
            b = int(obj["tile_end"])
            ranges.append([a, b])
            for tile in range(a, b + 1):
                destination_tile_users.setdefault(tile, []).append(index)
        animation_reports.append({
            "animation_id": index,
            "record_file_offset": f"0x{start:08X}",
            "record_size": len(record),
            "metasprite_marker_offset": f"0x{int(parsed['marker_offset']):X}",
            "object_count": parsed["object_count"],
            "destination_tile_ranges": ranges,
        })

    warning = animation_reports[SUSPEND_ANIMATION]
    warning_parsed = parsed_records[SUSPEND_ANIMATION]
    warning_source = parse_animation_source_tiles(records[SUSPEND_ANIMATION][1], warning_parsed)
    gate(warning["object_count"] == 12, "suspend animation 11 OBJ count drift")
    expected_warning_ranges = [[0, 15], [16, 23], [24, 27], [28, 35], [36, 43], [44, 51], [52, 59], [60, 63], [64, 65], [66, 97], [98, 129], [130, 137]]
    gate(warning["destination_tile_ranges"] == expected_warning_ranges, "suspend animation 11 destination-tile range drift")
    gate(warning_source["total_source_entries"] == 138, "suspend animation 11 source lookup length drift")
    gate(warning_source["trailer"] == b"\x00\x00\xF1\xFF" * 3, "suspend animation 11 source lookup trailer drift")

    text_object_indices = (2, 3, 4, 5, 6, 9, 10, 11)
    text_objects = [warning_parsed["objects"][index] for index in text_object_indices]
    min_x = min(int(obj["x"]) for obj in text_objects)
    min_y = min(int(obj["y"]) for obj in text_objects)
    max_x = max(int(obj["x"]) + int(obj["size_px"][0]) for obj in text_objects)
    max_y = max(int(obj["y"]) + int(obj["size_px"][1]) for obj in text_objects)
    gate((min_x, min_y, max_x, max_y) == (-60, -24, 84, 24), "suspend full text-panel geometry drift")
    text_source_entry_count = sum(len(warning_source["by_object"][index]) for index in text_object_indices)
    gate(text_source_entry_count == 108, "suspend full text-panel source entry count drift")
    gate(warning_source["by_object"][3][:4] == list(range(0xD5, 0xD9)), "suspend lower source run D5-D8 drift")
    gate(warning_source["by_object"][4][:4] == list(range(0xD9, 0xDD)), "suspend lower source run D9-DC drift")
    gate(warning_source["by_object"][5][:4] == list(range(0xDD, 0xE1)), "suspend lower source run DD-E0 drift")
    gate(warning_source["by_object"][6][:4] == list(range(0xE1, 0xE5)), "suspend lower source run E1-E4 drift")
    gate(warning_source["by_object"][9][8:24] == list(range(0xE5, 0xF5)), "suspend upper source run E5-F4 drift")
    gate(warning_source["by_object"][10][8:24] == list(range(0xF5, 0x105)), "suspend upper source run F5-104 drift")
    gate(0x105 in warning_source["by_object"][11], "suspend source tile 0x105 missing")

    destination_high_tile_animations = sorted({animation for tile in range(66, 138) for animation in destination_tile_users.get(tile, [])})
    gate(destination_high_tile_animations == [10, 11], f"destination OBJ tile overlap drift: {destination_high_tile_animations}")
    hits = pointer_hits(jp, SUSPEND_RESOURCE)
    gate(hits == RESOURCE_POINTER_HITS, f"shared suspend sprite resource references drift: {hits}")

    # The current approved main TIP still has both graphic families byte-exact to JP.
    foreground_end = parsed_by_address[0x08C71984]["file_offset"]
    foreground_start = foreground["file_offset"]
    gate(main_tip[foreground_start:foreground_end] == jp[foreground_start:foreground_end], "settings foreground family is no longer untouched in main TIP")
    sprite_span_end = resource_offset + palette_rel + 0x40
    gate(main_tip[resource_offset:sprite_span_end] == jp[resource_offset:sprite_span_end], "shared system sprite bank is no longer untouched in main TIP")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_settings_suspend_ui_static_analysis",
        "result": "PASS",
        "source": {
            "japanese_rom": args.rom.name,
            "japanese_sha256": sha256(jp),
            "main_tip": str(args.main.relative_to(ADVANCE_ROOT)),
            "main_tip_sha256": sha256(main_tip),
        },
        "map_menu_dispatch": {
            "table": f"0x{ROM_BASE + MENU_ACTION_TABLE:08X}",
            "suspend_index": 1,
            "suspend_function": f"0x{SUSPEND_FUNCTION:08X}",
            "settings_index": 4,
            "settings_function": f"0x{SETTINGS_FUNCTION:08X}",
        },
        "settings": {
            "function": f"0x{SETTINGS_FUNCTION:08X}",
            "bg_loader": f"0x{BG_RESOURCE_DRAW:08X}",
            "custom_lzss": f"0x{CUSTOM_LZSS:08X}",
            "resources": settings_report,
            "foreground_fixed_label_resource": f"0x{SETTINGS_FOREGROUND:08X}",
            "fixed_label_rectangles": fixed_report,
            "dynamic_choice_graphics": {
                "helper": "0x08020C54",
                "table": f"0x{ROM_BASE + OPTION_TABLE:08X}",
                "records": option_rows,
                "conclusion": "ON/OFF and speed buttons 1..4 are graphic pieces composited separately from the fixed Japanese BG labels",
            },
            "runtime_tile_ownership": {
                "foreground_runtime_tile_base": SETTINGS_FOREGROUND_RUNTIME_TILE_BASE,
                "original_foreground_decoded_tiles": foreground["decoded_tiles"],
                "original_foreground_runtime_end_exclusive": SETTINGS_FOREGROUND_RUNTIME_TILE_BASE + foreground["decoded_tiles"],
                "dynamic_option_runtime_tile_base": SETTINGS_OPTION_RUNTIME_TILE_BASE,
                "maximum_safe_foreground_decoded_tiles": SETTINGS_MAX_FOREGROUND_TILES,
                "first_failed_candidate_decoded_tiles": 269,
                "first_failed_candidate_runtime_end_exclusive": SETTINGS_FOREGROUND_RUNTIME_TILE_BASE + 269,
                "first_failed_candidate_overlap_tiles": SETTINGS_FOREGROUND_RUNTIME_TILE_BASE + 269 - SETTINGS_OPTION_RUNTIME_TILE_BASE,
                "real_hardware_failure_explanation": "the 269-tile foreground clone occupied runtime tiles 0x0C9..0x1D5, so the option compositor beginning at 0x191 overwrote/remixed the translated map labels; keep the follow-up clone within the original 131-tile budget",
            },
            "footer_title": {
                "source_pointer": f"0x{TITLE_POINTER:08X}",
                "literal_file_offset": f"0x{TITLE_LITERAL:08X}",
                "draw_call": f"0x{TITLE_DRAW_CALL:08X} -> 0x{TEXT_DRAW_12:08X}",
                "source_japanese": "Gジェネレーション アドバンス",
                "current_main_tip_behavior": "already translated by the existing 12x12 text pipeline",
            },
            "translation_plan": {
                "patch_target": "clone/rebuild only foreground BG resource 0x08C70DF0; preserve frame/background/palette and the two other settings layers",
                "fixed_labels": {
                    "各種設定を行います": "각종 설정을 합니다",
                    "攻撃方法の確認": "공격방법 확인",
                    "メッセージの自動送り": "메시지 자동 진행",
                    "メッセージ表示速度": "메시지 표시 속도",
                    "早い": "빠름",
                    "遅い": "느림",
                },
                "preserve": ["ON/OFF graphic pieces", "speed buttons 1..4", "footer 12x12 text path", "two non-foreground BG resources"],
            },
        },
        "suspend": {
            "function": f"0x{SUSPEND_FUNCTION:08X}",
            "text_renderer_calls_inside_function": [],
            "sprite_create": f"0x{SPRITE_CREATE:08X}",
            "warning_create_call": f"0x{SUSPEND_CREATE_CALL:08X}",
            "warning_animation_id": SUSPEND_ANIMATION,
            "post_operation_create_call": f"0x{SUSPEND_POST_CREATE_CALL:08X}",
            "post_operation_animation_id": POST_ANIMATION,
            "save_operation": f"0x{SUSPEND_SAVE_CALL:08X} -> 0x{SUSPEND_SAVE_TARGET:08X}",
            "shared_sprite_resource": {
                "address": f"0x{SUSPEND_RESOURCE:08X}",
                "file_offset": f"0x{resource_offset:08X}",
                "literal_file_offset": f"0x{SUSPEND_RESOURCE_LITERAL:08X}",
                "whole_rom_pointer_hits": [f"0x{x:08X}" for x in hits],
                "graphics_relative_offset": f"0x{graphics_rel:04X}",
                "graphics_file_offset": f"0x{resource_offset + graphics_rel:08X}",
                "palette_relative_offset": f"0x{palette_rel:04X}",
                "palette_file_offset": f"0x{resource_offset + palette_rel:08X}",
                "graphic_tiles": graphics_bytes // 32,
                "animation_count": animation_count,
            },
            "warning_animation": {
                "animation_id": SUSPEND_ANIMATION,
                "record_file_offset": warning["record_file_offset"],
                "record_size": warning["record_size"],
                "object_count": warning["object_count"],
                "destination_tile_ranges": warning["destination_tile_ranges"],
                "source_lookup_offset_in_record": f"0x{int(warning_source['source_table_offset']):X}",
                "source_lookup_entries": warning_source["total_source_entries"],
                "source_lookup_trailer_hex": warning_source["trailer"].hex(" "),
                "text_object_indices": list(text_object_indices),
                "text_content_geometry": "objects 9..11 cover the upper 144x32 and objects 2..6 cover the lower 144x16; together they form the complete 144x48 text panel",
                "text_content_source_entries": text_source_entry_count,
                "text_object_source_maps": {
                    str(index): [f"0x{value:03X}" for value in warning_source["by_object"][index]]
                    for index in text_object_indices
                },
                "destination_vs_source_correction": "OAM attr2 ranges such as 66..137 are destination OBJ-VRAM tile IDs. They are not ROM source graphic IDs. The actual source IDs are the u16 lookup entries following the OAM list.",
                "source_japanese": ["中断処理を行っています", "電源を切らないでください"],
            },
            "shared_resource_hazard": {
                "destination_tile_66_137_animations": destination_high_tile_animations,
                "destination_tile_overlap_is_not_source_graphics_overlap": True,
                "whole_rom_resource_pointer_consumers": len(hits),
                "in_place_patch_safe": False,
                "reason": "0x08C7504C is shared by five consumers. Clone the resource for suspend instead of rewriting original source graphics; within the clone append private source tiles and remap only animation-11 text lookup entries.",
            },
            "translation_plan": {
                "recommended": "clone resource 0x08C7504C, keep all original 262 source graphic tiles byte-exact, append private Korean source tiles, rewrite only animation-11 source lookup entries for objects 2..6 and 9..11, shift palette_rel accordingly, and redirect only literal 0x08020B98",
                "preserve": ["exclamation icon objects 0/1", "right-edge objects 7/8", "all original 262 source tiles", "animations 0..10", "post-operation animation 5", "original shared resource and four other consumers"],
                "candidate_lines": ["중단 처리 중입니다", "전원을 끄지 마세요"],
            },
            "all_animation_destination_tile_ranges": animation_reports,
        },
        "similar_case_policy": {
            "fixed_BG_labels": "identify descriptor/map/atlas, preserve native frame and background, repaint only glyph footprint, relocate resource when compressed size/layout changes",
            "shared_OBJ_messages": "enumerate resource pointer consumers and animation tile sharing before editing; clone and redirect one consumer when tiles are shared",
            "dynamic_text": "prefer existing 12x12/8x16 token pipeline when the screen actually calls a text renderer; audit token-slot-painted-glyph identity",
            "dynamic_choice_graphics": "leave language-neutral ON/OFF/digit controls intact unless separately requested",
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_hash_verified": sha256(main_tip) == manifest_main_hash,
            "settings_three_bg_resources_verified": True,
            "settings_foreground_30x20_fixed_label_map_verified": True,
            "settings_dynamic_controls_separated_from_fixed_labels": True,
            "settings_runtime_tile_bases_verified": True,
            "settings_original_131_tiles_end_before_option_base": SETTINGS_FOREGROUND_RUNTIME_TILE_BASE + foreground["decoded_tiles"] <= SETTINGS_OPTION_RUNTIME_TILE_BASE,
            "settings_first_candidate_269_tiles_would_overlap_options": SETTINGS_FOREGROUND_RUNTIME_TILE_BASE + 269 > SETTINGS_OPTION_RUNTIME_TILE_BASE,
            "settings_footer_12x12_text_path_verified": True,
            "suspend_has_no_12x12_text_draw": True,
            "suspend_animation_11_shared_sprite_path_verified": True,
            "suspend_destination_tile_ranges_verified": warning["destination_tile_ranges"] == expected_warning_ranges,
            "suspend_source_lookup_table_verified": warning_source["total_source_entries"] == 138,
            "suspend_full_text_panel_144x48_verified": (min_x, min_y, max_x, max_y) == (-60, -24, 84, 24),
            "suspend_text_object_source_entries_verified": text_source_entry_count == 108,
            "suspend_destination_source_distinction_verified": True,
            "shared_sprite_consumer_count_verified": len(hits) == 5,
            "destination_tile_10_11_overlap_verified": destination_high_tile_animations == [10, 11],
            "current_main_tip_graphic_families_untouched": True,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "main_tip_sha256": sha256(main_tip),
        "settings_foreground_tiles": foreground["decoded_tiles"],
        "settings_dynamic_option_records": len(option_rows),
        "suspend_sprite_animations": animation_count,
        "suspend_warning_objects": warning["object_count"],
        "destination_warning_tile_animations": destination_high_tile_animations,
        "suspend_text_panel": "144x48 via objects 2..6 and 9..11",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
