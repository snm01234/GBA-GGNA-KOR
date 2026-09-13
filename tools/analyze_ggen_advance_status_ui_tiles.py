#!/usr/bin/env python3
"""Analyze the fixed Japanese stat-label tilemaps used by G Generation Advance.

This is a read-only structural audit.  It proves that the labels visible on the
pilot/unit status screens are not ordinary NUL text records: they are tilemap
cells selected from the status UI resource table at 0x080E0518.  The report
also resolves the Guntank unit-category selector to the 4x2 `汎用` chunk used
in the measured screenshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT, TRANSLATION_MERGED_JSON

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DEFAULT_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_status_ui_tile_analysis_20260829.json"

RESOURCE_TABLE = 0x000E0518
PILOT_BASE_MAP_INDEX = 2
UNIT_BASE_MAP_INDEX = 35
UNIT_TYPE_CHUNK_BASE_INDEX = 40

# Measured screen coordinates.  Each map cell is one 8x8 BG tile.
PILOT_LABELS = {
    "近接": {"x": 14, "y": 7, "w": 4, "h": 2, "ko": "근접"},
    "操縦系": {"x": 20, "y": 7, "w": 5, "h": 2, "ko": "조종계"},
    "射撃": {"x": 14, "y": 9, "w": 4, "h": 2, "ko": "사격"},
    "EXP": {"x": 20, "y": 9, "w": 4, "h": 2, "ko": "EXP"},
    "反応": {"x": 14, "y": 11, "w": 4, "h": 2, "ko": "반응"},
    "NEXT": {"x": 20, "y": 11, "w": 4, "h": 2, "ko": "NEXT"},
}
UNIT_LABELS = {
    "運動": {"x": 13, "y": 7, "w": 4, "h": 2, "ko": "운동"},
    "装甲": {"x": 19, "y": 7, "w": 4, "h": 2, "ko": "장갑"},
    "限界": {"x": 13, "y": 9, "w": 4, "h": 2, "ko": "한계"},
    "移動": {"x": 19, "y": 9, "w": 4, "h": 2, "ko": "이동"},
}

# Renderer/accessor contracts established by static disassembly.
PILOT_SETUP = 0x0806BEB8
PILOT_RENDER = 0x0806CFC4
PILOT_WRAPPER = 0x0806D350
UNIT_RENDER = 0x0806C548
STATUS_WRAPPER = 0x0806B840
TILEMAP_BLIT = 0x0800277C
UNIT_RECORD_ACCESSOR = 0x080045B0
UNIT_TYPE_ACCESSOR = 0x08005518

UNIT_ID_TO_RECORD = 0x001A4298
UNIT_ID_MAP_END = 0x001A476C  # next database begins here; 618 u16 unit-id entries
UNIT_RECORD_BASE = 0x0018E2E4
UNIT_RECORD_STRIDE = 0xAC
UNIT_NAME_PTR_OFF = 0x04
UNIT_TYPE_OFF = 0x19
PILOT_BG1CNT = 0x4E05  # screenblock 14, charblock 1
UNIT_BG1CNT = 0x4E01   # screenblock 14, charblock 0
PILOT_CHARBLOCK_VRAM = 0x06004000
UNIT_CHARBLOCK_VRAM = 0x06000000

GUNTANK_NAME_TARGETS = {0x00179F06, 0x0017A7DB, 0x0017AE6B}


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def file_offset(address: int) -> int:
    gate(ROM_BASE <= address < ROM_BASE + EXPECTED_SIZE, f"ROM pointer outside 16 MiB: 0x{address:08X}")
    return address - ROM_BASE


def resource_pointer(data: bytes, index: int) -> int:
    return u32(data, RESOURCE_TABLE + index * 4)


def parse_tilemap(data: bytes, address: int) -> dict[str, Any]:
    offset = file_offset(address)
    width = data[offset]
    height = data[offset + 1]
    reserved = u16(data, offset + 2)
    count = width * height
    gate(count > 0, f"empty tilemap at 0x{offset:08X}")
    end = offset + 4 + count * 2
    gate(end <= len(data), f"tilemap overruns ROM at 0x{offset:08X}")
    cells = list(struct.unpack_from(f"<{count}H", data, offset + 4))
    return {
        "address": f"0x{address:08X}",
        "file_offset": f"0x{offset:08X}",
        "width": width,
        "height": height,
        "reserved_u16": f"0x{reserved:04X}",
        "byte_length": 4 + count * 2,
        "cells": cells,
    }


def region_report(tilemap: dict[str, Any], spec: dict[str, Any], charblock_vram: int) -> dict[str, Any]:
    width = int(tilemap["width"])
    base = int(str(tilemap["file_offset"]), 16)
    x0, y0, rw, rh = (int(spec[key]) for key in ("x", "y", "w", "h"))
    gate(x0 + rw <= width and y0 + rh <= int(tilemap["height"]), "label region outside tilemap")
    matrix: list[list[str]] = []
    cell_offsets: list[list[str]] = []
    raw_cells: list[list[str]] = []
    vram_addresses: list[list[str]] = []
    for y in range(y0, y0 + rh):
        ids: list[str] = []
        offsets: list[str] = []
        raw: list[str] = []
        vram: list[str] = []
        for x in range(x0, x0 + rw):
            index = y * width + x
            cell = int(tilemap["cells"][index])
            ids.append(f"0x{cell & 0x03FF:03X}")
            raw.append(f"0x{cell:04X}")
            offsets.append(f"0x{base + 4 + index * 2:08X}")
            vram.append(f"0x{charblock_vram + (cell & 0x03FF) * 32:08X}")
        matrix.append(ids)
        raw_cells.append(raw)
        cell_offsets.append(offsets)
        vram_addresses.append(vram)
    return {
        "ko_target": spec["ko"],
        "map_xy": [x0, y0],
        "pixel_xy": [x0 * 8, y0 * 8],
        "size_tiles": [rw, rh],
        "size_pixels": [rw * 8, rh * 8],
        "tile_ids": matrix,
        "raw_cells": raw_cells,
        "cell_file_offsets": cell_offsets,
        "tile_vram_addresses": vram_addresses,
    }


def text_corpus_evidence(merged: dict[str, Any], terms: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    rows = list(merged.get("records", []))
    for term in terms:
        exact = [row for row in rows if str(row.get("source_text") or "") == term]
        contains = [row for row in rows if term in str(row.get("source_text") or "")]
        result[term] = {
            "standalone_record_count": len(exact),
            "embedded_record_count": len(contains),
            "embedded_examples": [
                {
                    "record_id": row.get("record_id"),
                    "target_file_offset": row.get("target_file_offset"),
                    "source_scope": row.get("source_scope"),
                    "semantic_category": row.get("semantic_category"),
                    "source_text": row.get("source_text"),
                }
                for row in contains[:5]
            ],
        }
    return result


def find_guntank_records(data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # The mapping table contains u16 record indices.  Audit every reachable unit ID.
    max_ids = (UNIT_ID_MAP_END - UNIT_ID_TO_RECORD) // 2
    for unit_id in range(max_ids):
        record_index = u16(data, UNIT_ID_TO_RECORD + unit_id * 2)
        record = UNIT_RECORD_BASE + record_index * UNIT_RECORD_STRIDE
        if record + UNIT_RECORD_STRIDE > EXPECTED_SIZE:
            continue
        name_ptr = u32(data, record + UNIT_NAME_PTR_OFF)
        if name_ptr < ROM_BASE or name_ptr >= ROM_BASE + EXPECTED_SIZE:
            continue
        name_off = name_ptr - ROM_BASE
        if name_off not in GUNTANK_NAME_TARGETS:
            continue
        unit_type = data[record + UNIT_TYPE_OFF]
        chunk_index = UNIT_TYPE_CHUNK_BASE_INDEX + unit_type
        chunk_address = resource_pointer(data, chunk_index)
        chunk = parse_tilemap(data, chunk_address)
        rows.append(
            {
                "unit_id": unit_id,
                "record_index": record_index,
                "record_file_offset": f"0x{record:08X}",
                "name_target_file_offset": f"0x{name_off:08X}",
                "unit_type_byte_0x19": unit_type,
                "type_chunk_index": chunk_index,
                "type_chunk": {
                    "address": chunk["address"],
                    "file_offset": chunk["file_offset"],
                    "width": chunk["width"],
                    "height": chunk["height"],
                    "tile_ids": [
                        [
                            f"0x{int(chunk['cells'][y * int(chunk['width']) + x]) & 0x03FF:03X}"
                            for x in range(int(chunk["width"]))
                        ]
                        for y in range(int(chunk["height"]))
                    ],
                },
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--merged", type=Path, default=TRANSLATION_MERGED_JSON)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    gate(digest == EXPECTED_SHA256, f"unexpected clean-ROM SHA-256 {digest}")
    merged = json.loads(args.merged.read_text(encoding="utf-8"))

    pilot_address = resource_pointer(data, PILOT_BASE_MAP_INDEX)
    unit_address = resource_pointer(data, UNIT_BASE_MAP_INDEX)
    gate(pilot_address == 0x080DE548, f"pilot base-map pointer drift: 0x{pilot_address:08X}")
    gate(unit_address == 0x080DF588, f"unit base-map pointer drift: 0x{unit_address:08X}")
    pilot_map = parse_tilemap(data, pilot_address)
    unit_map = parse_tilemap(data, unit_address)
    gate((pilot_map["width"], pilot_map["height"]) == (32, 20), "pilot map is not 32x20")
    gate((unit_map["width"], unit_map["height"]) == (32, 20), "unit map is not 32x20")

    pilot_regions = {
        term: region_report(pilot_map, spec, PILOT_CHARBLOCK_VRAM)
        for term, spec in PILOT_LABELS.items()
    }
    unit_regions = {
        term: region_report(unit_map, spec, UNIT_CHARBLOCK_VRAM)
        for term, spec in UNIT_LABELS.items()
    }
    guntanks = find_guntank_records(data)
    gate(guntanks, "no Guntank unit records found")
    gate(all(row["unit_type_byte_0x19"] == 1 for row in guntanks), "Guntank unit type is not stable at 1")
    gate(all(row["type_chunk_index"] == 41 for row in guntanks), "Guntank type chunk is not table[41]")
    gate(all(row["type_chunk"]["file_offset"] == "0x000E01A0" for row in guntanks), "Guntank type chunk pointer drift")

    terms = ["近接", "射撃", "反応", "操縦系", "運動", "装甲", "限界", "移動", "汎用"]
    corpus = text_corpus_evidence(merged, terms)
    gate(all(corpus[term]["standalone_record_count"] == 0 for term in terms), "one fixed label unexpectedly became a standalone text record")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_status_ui_fixed_tile_analysis",
        "source": {"file": args.rom.name, "size": len(data), "sha256": digest},
        "result": "PASS",
        "conclusion": (
            "The measured pilot/unit stat labels are BG tilemap assets, not ordinary text records. "
            "Pilot labels are baked into resource-table map[2], unit labels into map[35], and "
            "the Guntank screenshot's 汎用 badge is dynamic unit-type chunk map[41]."
        ),
        "resource_contract": {
            "resource_pointer_table_file_offset": f"0x{RESOURCE_TABLE:08X}",
            "resource_pointer_table_address": f"0x{ROM_BASE + RESOURCE_TABLE:08X}",
            "tilemap_blitter": f"0x{TILEMAP_BLIT:08X}",
            "pilot": {
                "wrapper": f"0x{PILOT_WRAPPER:08X}",
                "setup": f"0x{PILOT_SETUP:08X}",
                "renderer": f"0x{PILOT_RENDER:08X}",
                "bg1cnt": f"0x{PILOT_BG1CNT:04X}",
                "bg1_charblock": 1,
                "bg1_charblock_vram": f"0x{PILOT_CHARBLOCK_VRAM:08X}",
                "base_map_index": PILOT_BASE_MAP_INDEX,
                "base_map": {key: pilot_map[key] for key in ("address", "file_offset", "width", "height", "byte_length")},
                "labels": pilot_regions,
            },
            "unit": {
                "status_wrapper": f"0x{STATUS_WRAPPER:08X}",
                "renderer": f"0x{UNIT_RENDER:08X}",
                "bg1cnt": f"0x{UNIT_BG1CNT:04X}",
                "bg1_charblock": 0,
                "bg1_charblock_vram": f"0x{UNIT_CHARBLOCK_VRAM:08X}",
                "base_map_index": UNIT_BASE_MAP_INDEX,
                "base_map": {key: unit_map[key] for key in ("address", "file_offset", "width", "height", "byte_length")},
                "labels": unit_regions,
                "unit_record_accessor": f"0x{UNIT_RECORD_ACCESSOR:08X}",
                "unit_type_accessor": f"0x{UNIT_TYPE_ACCESSOR:08X}",
                "unit_type_field": "+0x19",
                "unit_type_chunk_formula": "resource_table[40 + unit_type]",
                "guntank_measured_type_evidence": guntanks,
                "measured_guntank_badge": {
                    "source_text": "汎用",
                    "ko_target": "범용",
                    "resource_table_index": 41,
                    "chunk_file_offset": "0x000E01A0",
                    "chunk_size_tiles": [4, 2],
                    "draw_coordinate_observed_from_renderer": {"logical_x": 58, "wrapped_screen_x": 26, "y": 9, "pixel_x": 208, "pixel_y": 72},
                    "tile_ids": [["0x1A8", "0x1A9", "0x1AA", "0x1AB"], ["0x1AC", "0x1AD", "0x1AE", "0x1AF"]],
                    "tile_vram_range": ["0x06003500", "0x060035FF"],
                },
            },
        },
        "text_corpus_evidence": corpus,
        "patch_direction": {
            "preferred": (
                "Do not add these labels to the normal text relocation sheet.  Patch the status BG tile path: "
                "either replace the fixed tilemap regions with dedicated Korean tiles loaded into VRAM, or overlay "
                "Korean text after blanking the Japanese cells."
            ),
            "why_not_global_glyph_overwrite": (
                "Pilot label IDs are locally unique, but the unit map deliberately reuses tile IDs 0x149/0x150/0x151 "
                "between 運動 and 移動.  A blind atlas rewrite can therefore couple two labels unless the Korean layout "
                "preserves the shared component or those three map cells are remapped."
            ),
            "runtime_vram_override_feasibility": (
                "High.  The exact BG1 charblocks are known (pilot 0x06004000, unit 0x06000000), so a small status-screen "
                "hook can overwrite only the measured label tile slots after the common atlas is resident, avoiding any "
                "need to mutate unrelated normal-text data."
            ),
            "next_static_task": (
                "Trace the BG1 character-tile upload that supplies pilot tile IDs 0x044..0x079 and unit IDs "
                "0x146..0x1AF; then choose free/dedicated VRAM slots and build a Korean tile POC."
            ),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": report["result"],
        "output": str(args.out),
        "pilot_base_map": pilot_map["file_offset"],
        "unit_base_map": unit_map["file_offset"],
        "guntank_type_chunk": "0x000E01A0",
        "standalone_text_labels": sum(corpus[t]["standalone_record_count"] for t in terms),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
