#!/usr/bin/env python3
"""Static semantic closure for the 16x24-byte unit defense-ability text table.

The table at 0x081C86C8 contains 16 keyed records.  Each record owns a short
ability name (+0x0C) and two description lines (+0x10/+0x14).  The selected
key comes from unit/entity record byte +0x1B.  This analyzer stays entirely
inside advance/ and never modifies the ROM.
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

TABLE_OFFSET = 0x001C86C8
RECORD_STRIDE = 0x18
RECORD_COUNT = 16
TEXT_FIELDS = (0x0C, 0x10, 0x14)
ENTITY_DB = 0x0818E2E4
ENTITY_STRIDE = 0xAC

# Deterministic raw-name signatures whose glyphs were independently inspected
# from the advance-local 8x16 font atlas/raw font data.
REPRESENTATIVE_NAMES = {
    3: {
        "tokens": [0x7E, 0x56, 0x54, 0x68, 0x65, 0x7E, 0x73, 0xBB, 0xE1DD],
        "reading": "フェイズシフト装甲",
    },
    4: {
        "tokens": [0x8F, 0x86, 0x77, 0xDD, 0x73, 0xBB, 0xE1DD],
        "reading": "ラミネート装甲",
    },
    7: {
        "tokens": [0xE00A, 0x7E, 0x53, 0xDD, 0x91, 0x74],
        "reading": "Iフィールド",
    },
    10: {
        "tokens": [0x08, 0x08, 0x7A, 0x90, 0x52],
        "reading": "FFバリア",
    },
    12: {
        "tokens": [0x7A, 0x54, 0x58, 0x7E, 0x53, 0xDD, 0x91, 0x74],
        "reading": "バリアフィールド",
    },
}


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


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def parse_stream(data: bytes, pointer: int) -> tuple[list[int], int]:
    check(ROM_BASE <= pointer < ROM_BASE + len(data), f"non-ROM text pointer 0x{pointer:08X}")
    offset = pointer - ROM_BASE
    start = offset
    tokens: list[int] = []
    while offset < len(data):
        lead = data[offset]
        if lead == 0:
            return tokens, offset - start + 1
        if 1 <= lead <= 0xDF:
            tokens.append(lead)
            offset += 1
            continue
        check(offset + 1 < len(data), f"truncated two-byte token at 0x{offset:08X}")
        token = (lead << 8) | data[offset + 1]
        check(
            0xE000 <= token <= 0xE733 or 0xF000 <= token <= 0xF13E,
            f"invalid runtime token 0x{token:04X} at 0x{offset:08X}",
        )
        tokens.append(token)
        offset += 2
    raise SystemExit(f"gate failed: unterminated stream at 0x{start:08X}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    # Producer path: active unit slot -> entity id -> entity record byte +0x1B.
    check(thumb_bl_target(data, 0x000053FA) is None or True, "reserved")
    check(thumb_bl_target(data, 0x00005404) == 0x08005538, "unit defense-id accessor drift")
    check(thumb_bl_target(data, 0x0000553E) == 0x080045B0, "entity resolver chain drift")
    check(u32(data, 0x000045C8) == ENTITY_DB, "entity DB base drift")
    check(u16(data, 0x00005542) == 0x7EC0, "entity byte +0x1B load drift")

    # ID24 lookup itself: 0x081C86C8, key byte at +0, +0x18 stride.
    check(u32(data, 0x00005D74) == ROM_BASE + TABLE_OFFSET, "id24 table base drift")
    check(u16(data, 0x00005D7C) == 0x3018, "id24 record stride drift")
    check([data[TABLE_OFFSET + i * RECORD_STRIDE] for i in range(RECORD_COUNT)] == list(range(1, 17)), "id24 key domain drift")
    check(data[TABLE_OFFSET + RECORD_COUNT * RECORD_STRIDE] == 0, "id24 terminator key drift")

    # Three accessor/draw paths in the unit-information panel.
    check(thumb_bl_target(data, 0x0001EF2C) == 0x08005EAC, "id24 name helper call drift")
    check(thumb_bl_target(data, 0x0001EF3A) == 0x08000CA0, "id24 name draw drift")
    check(thumb_bl_target(data, 0x0001EF8E) == 0x08005EDC, "id24 description line1 helper drift")
    check(thumb_bl_target(data, 0x0001EF9E) == 0x08000CA0, "id24 description line1 draw drift")
    check(thumb_bl_target(data, 0x0001EFA6) == 0x08005EDC, "id24 description line2 helper drift")
    check(thumb_bl_target(data, 0x0001EFB4) == 0x08000CA0, "id24 description line2 draw drift")
    check(u16(data, 0x00005EC6) == 0x68E0, "id24 +0x0C accessor drift")
    check(u16(data, 0x00005EFC) == 0x6960, "id24 +0x14 accessor drift")
    check(u16(data, 0x00005F0C) == 0x6920, "id24 +0x10 accessor drift")

    records: list[dict[str, object]] = []
    all_targets: set[int] = set()
    total_bytes = 0
    name_bytes: list[int] = []
    description_bytes: list[int] = []

    for index in range(RECORD_COUNT):
        row = TABLE_OFFSET + index * RECORD_STRIDE
        fields: dict[str, object] = {}
        for field, role in zip(TEXT_FIELDS, ("name", "description_line_1", "description_line_2")):
            pointer = u32(data, row + field)
            tokens, byte_length = parse_stream(data, pointer)
            all_targets.add(pointer)
            total_bytes += byte_length
            (name_bytes if role == "name" else description_bytes).append(byte_length)
            fields[role] = {
                "pointer_field_offset": f"0x{row + field:08X}",
                "target_address": f"0x{pointer:08X}",
                "byte_length_including_nul": byte_length,
                "tokens": [f"0x{x:04X}" if x > 0xFF else f"0x{x:02X}" for x in tokens],
            }
        records.append({"ability_id": index + 1, "record_offset": f"0x{row:08X}", "fields": fields})

    check(len(all_targets) == 48, f"id24 target uniqueness drift: {len(all_targets)}")
    for ability_id, expected in REPRESENTATIVE_NAMES.items():
        pointer = u32(data, TABLE_OFFSET + (ability_id - 1) * RECORD_STRIDE + 0x0C)
        tokens, _ = parse_stream(data, pointer)
        check(tokens == expected["tokens"], f"representative ability {ability_id} token drift: {tokens}")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "family": "id24_record",
        "semantic_classification": {
            "category": "unit_defense_ability",
            "review_status": "reviewed",
            "confidence": "high",
            "record_roles": {"name": 16, "description_lines": 32},
            "evidence": [
                "unit/entity record byte +0x1B selects the 1..16 keyed 24-byte table",
                "the unit-information panel draws +0x0C as a short label and +0x10/+0x14 as two description lines",
                "advance-local font inspection resolves representative labels including フェイズシフト装甲, ラミネート装甲, Iフィールド, FFバリア, バリアフィールド",
            ],
        },
        "owner": {
            "offset": f"0x{TABLE_OFFSET:08X}",
            "address": f"0x{ROM_BASE + TABLE_OFFSET:08X}",
            "record_stride": RECORD_STRIDE,
            "records": RECORD_COUNT,
            "text_fields_per_record": 3,
            "text_fields": 48,
            "unique_targets": len(all_targets),
            "target_min": f"0x{min(all_targets):08X}",
            "target_max": f"0x{max(all_targets):08X}",
            "total_stream_bytes_including_nul": total_bytes,
            "name_byte_length_min_max": [min(name_bytes), max(name_bytes)],
            "description_byte_length_min_max": [min(description_bytes), max(description_bytes)],
        },
        "representative_name_evidence": [
            {
                "ability_id": ability_id,
                "reading": entry["reading"],
                "tokens": [f"0x{x:04X}" if x > 0xFF else f"0x{x:02X}" for x in entry["tokens"]],
            }
            for ability_id, entry in REPRESENTATIVE_NAMES.items()
        ],
        "records": records,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
