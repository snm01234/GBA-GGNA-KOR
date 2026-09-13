#!/usr/bin/env python3
"""Static closure for the 70-entry direct_struct8_text family.

The owner is the counted 8-byte record table at file 0x001C94B0.  Each record
contains a ROM text pointer followed by a 32-bit query/status id.  The runtime
renderer at 0x08060F8C walks these records with an 8-byte stride and draws up to
8 rows at a time.

This tool is self-contained under advance/ and never modifies the ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

TABLE_OFFSET = 0x001C94B0
EXPECTED_COUNT = 70
RECORD_OFFSET = TABLE_OFFSET + 4
RECORD_STRIDE = 8
TABLE_LITERAL_OFFSET = 0x0006106C
RENDER_FUNCTION = 0x08060F8C
RENDER_CALL_OFFSETS = [0x000610AE, 0x00061158]
DRAW_WRAPPER = 0x08000CA0
ROW_DRAW_CALL_OFFSET = 0x0006100C
QUERY_FUNCTION = 0x0800E54C
QUERY_CALL_OFFSET = 0x00061012


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def thumb_bl_target(data: bytes, offset: int) -> int | None:
    high = u16(data, offset)
    low = u16(data, offset + 2)
    if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
        return None
    displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
    if displacement & (1 << 22):
        displacement -= 1 << 23
    return (ROM_BASE + offset + 4 + displacement) & 0xFFFFFFFF


def bl_callers(data: bytes, target: int) -> list[int]:
    return [
        offset
        for offset in range(0, len(data) - 3, 2)
        if thumb_bl_target(data, offset) == target
    ]


def parse_stream(data: bytes, offset: int, limit: int = 512) -> dict[str, object]:
    cursor = offset
    token_count = 0
    end = min(len(data), offset + limit)
    while cursor < end:
        lead = data[cursor]
        if lead == 0:
            return {
                "byte_length_including_nul": cursor - offset + 1,
                "token_count": token_count,
                "raw_hex": data[offset:cursor].hex().upper(),
            }
        cursor += 1
        token_count += 1
        if lead >= 0xE0:
            if cursor >= end:
                break
            cursor += 1
    raise ValueError(f"unterminated token stream at 0x{offset:08X}")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    count = u32(data, TABLE_OFFSET)
    check(count == EXPECTED_COUNT, f"record count drift: {count}")
    check(u32(data, TABLE_LITERAL_OFFSET) == ROM_BASE + TABLE_OFFSET, "table literal drift")
    check(bl_callers(data, RENDER_FUNCTION) == RENDER_CALL_OFFSETS, "render caller set drift")
    check(thumb_bl_target(data, ROW_DRAW_CALL_OFFSET) == DRAW_WRAPPER, "row draw call drift")
    check(thumb_bl_target(data, QUERY_CALL_OFFSET) == QUERY_FUNCTION, "row query call drift")

    # Key Thumb instructions in the renderer.  These gates encode the proven
    # contract without depending on an external disassembler at runtime.
    check(u16(data, 0x00060FA6) == 0xCF01, "count load (ldm r7!, {r0}) drift")
    check(u16(data, 0x00061000) == 0x683B, "row text load (ldr r3, [r7]) drift")
    check(u16(data, 0x00061010) == 0x7938, "row +4 byte query load drift")
    check(u16(data, 0x00061028) == 0x3708, "8-byte row stride drift")
    check(u16(data, 0x00061038) == 0x2807, "8-row visible-window gate drift")

    records: list[dict[str, object]] = []
    pointers: list[int] = []
    query_ids: list[int] = []
    total_stream_bytes = 0
    total_tokens = 0

    for index in range(count):
        field_offset = RECORD_OFFSET + index * RECORD_STRIDE
        pointer = u32(data, field_offset)
        query_id = u32(data, field_offset + 4)
        check(ROM_BASE <= pointer < ROM_BASE + len(data), f"record {index} non-ROM text pointer")
        stream = parse_stream(data, pointer - ROM_BASE)
        pointers.append(pointer)
        query_ids.append(query_id)
        total_stream_bytes += int(stream["byte_length_including_nul"])
        total_tokens += int(stream["token_count"])
        records.append(
            {
                "index": index,
                "record_offset": f"0x{field_offset:08X}",
                "text_pointer_address": f"0x{pointer:08X}",
                "text_target_offset": f"0x{pointer - ROM_BASE:08X}",
                "query_id": query_id,
                "stream": stream,
            }
        )

    check(len(set(pointers)) == count, "text target uniqueness drift")
    check(query_ids == list(range(1, count + 1)), "query id sequence is no longer 1..70")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "family": "direct_struct8_text",
        "semantic_classification": {
            "category": "scroll_list_label",
            "review_status": "reviewed",
            "confidence": "high",
            "exact_screen_noun_status": "unresolved",
            "evidence": [
                "0x08060F8C reads a counted table whose 70 records are exactly 8 bytes each",
                "each record is {text_pointer, query_id}; query ids are exactly 1..70",
                "the renderer loads record[0] into r3 and draws it through 0x08000CA0",
                "the renderer reads record+4 for a per-row query and advances the record pointer by 8",
                "the visible loop is capped at eight rows and is called again after scroll-position changes",
            ],
        },
        "owner": {
            "table_offset": f"0x{TABLE_OFFSET:08X}",
            "table_address": f"0x{ROM_BASE + TABLE_OFFSET:08X}",
            "table_literal_offset": f"0x{TABLE_LITERAL_OFFSET:08X}",
            "count": count,
            "record_offset": f"0x{RECORD_OFFSET:08X}",
            "record_stride": RECORD_STRIDE,
            "record_contract": ["text_pointer_u32", "query_id_u32"],
            "query_id_range": [min(query_ids), max(query_ids)],
        },
        "runtime": {
            "renderer": f"0x{RENDER_FUNCTION:08X}",
            "renderer_direct_callers": [f"0x{ROM_BASE + x:08X}" for x in RENDER_CALL_OFFSETS],
            "row_draw_call": f"0x{ROM_BASE + ROW_DRAW_CALL_OFFSET:08X}",
            "row_query_call": f"0x{ROM_BASE + QUERY_CALL_OFFSET:08X}",
            "row_stride_bytes": RECORD_STRIDE,
            "visible_row_cap": 8,
        },
        "corpus": {
            "records": count,
            "unique_text_targets": len(set(pointers)),
            "target_min": f"0x{min(pointers):08X}",
            "target_max": f"0x{max(pointers):08X}",
            "total_stream_bytes_including_nul": total_stream_bytes,
            "total_tokens": total_tokens,
        },
        "records": records,
    }

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
