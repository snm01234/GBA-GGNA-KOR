#!/usr/bin/env python3
"""Revalidate the three non-FCE2D8 indirect text owners used by direct draws.

This advance-local analyzer covers:
- 0x00FCDF78 prefix 0..12 (13 entries, runtime field modulo 13)
- 0x00FCE128 11+11 variant table (22 entries)
- 0x00FCE2A8 sparse 12-slot table (10 text pointers, slots 2/11 NULL)

It deliberately does not treat adjacent pointer runs as one table.
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
DRAW_WRAPPER = 0x08000CA0
MOD_FUNCTION = 0x08085130
FCE128_INDEX_HELPER = 0x08064D38

OWNERS = {
    "FCDF78_prefix13": {"offset": 0x00FCDF78, "slots": 13},
    "FCE128_11x2": {"offset": 0x00FCE128, "slots": 22},
    "FCE2A8_sparse12": {"offset": 0x00FCE2A8, "slots": 12},
}

FCE2A8_LITERAL_OFFSETS = [0x000734C8, 0x000734E4, 0x000735AC, 0x000735F4]
FCE2A8_DRAW_CALLS = [0x0007348E, 0x000734DE, 0x0007351E, 0x00073576, 0x000735CA, 0x000735E2]


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


def parse_stream(data: bytes, offset: int, limit: int = 512) -> dict[str, object]:
    cursor = offset
    tokens = 0
    end = min(len(data), offset + limit)
    while cursor < end:
        lead = data[cursor]
        if lead == 0:
            if tokens == 0:
                raise ValueError(f"empty stream at 0x{offset:08X}")
            return {
                "byte_length_including_nul": cursor - offset + 1,
                "token_count": tokens,
                "raw_hex": data[offset:cursor].hex().upper(),
            }
        cursor += 1
        tokens += 1
        if lead >= 0xE0:
            if cursor >= end:
                break
            cursor += 1
    raise ValueError(f"unterminated stream at 0x{offset:08X}")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def owner_entries(data: bytes, offset: int, slots: int, null_allowed: set[int] | None = None):
    null_allowed = null_allowed or set()
    entries = []
    pointers = []
    for index in range(slots):
        field_offset = offset + index * 4
        value = u32(data, field_offset)
        if index in null_allowed:
            check(value == 0, f"expected NULL at 0x{field_offset:08X}")
            entries.append({"index": index, "pointer_field_offset": f"0x{field_offset:08X}", "value": None})
            continue
        check(ROM_BASE <= value < ROM_BASE + len(data), f"non-ROM pointer at 0x{field_offset:08X}")
        stream = parse_stream(data, value - ROM_BASE)
        pointers.append(value)
        entries.append(
            {
                "index": index,
                "pointer_field_offset": f"0x{field_offset:08X}",
                "target_address": f"0x{value:08X}",
                "target_offset": f"0x{value - ROM_BASE:08X}",
                "stream": stream,
            }
        )
    return entries, pointers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    # FCDF78: draw uses byte index into base and the same UI updates field +0x25 modulo 13.
    check(u32(data, 0x00060404) == ROM_BASE + OWNERS["FCDF78_prefix13"]["offset"], "FCDF78 literal drift")
    check(u16(data, 0x000603BE) == 0x6803, "FCDF78 indexed ldr r3,[r0] drift")
    check(thumb_bl_target(data, 0x000603CA) == DRAW_WRAPPER, "FCDF78 draw call drift")
    check(u16(data, 0x000604B2) == 0x3425, "FCDF78 +0x25 field address drift")
    check(u16(data, 0x000604E4) == 0x210D, "FCDF78 modulo divisor 13 drift")
    check(thumb_bl_target(data, 0x000604E6) == MOD_FUNCTION, "FCDF78 modulo helper drift")
    fcdf_entries, fcdf_ptrs = owner_entries(data, OWNERS["FCDF78_prefix13"]["offset"], 13)
    check(len(set(fcdf_ptrs)) == 13, "FCDF78 prefix target uniqueness drift")

    # FCE128: helper maps valid state to 0..10; caller optionally adds 11 before indexing 22 slots.
    check(u32(data, 0x00065454) == ROM_BASE + OWNERS["FCE128_11x2"]["offset"], "FCE128 literal drift")
    check(thumb_bl_target(data, 0x0006540E) == FCE128_INDEX_HELPER, "FCE128 index helper call drift")
    check(u16(data, 0x0006541E) == 0x320B, "FCE128 +11 variant drift")
    check(u16(data, 0x00065420) == 0x2A0A, "FCE128 base-domain compare drift")
    check(u16(data, 0x0006543A) == 0x6803, "FCE128 indexed ldr r3,[r0] drift")
    check(thumb_bl_target(data, 0x00065446) == DRAW_WRAPPER, "FCE128 draw call drift")
    # Index helper's explicit fallback outputs are 9 and 10; normal branch is r2*3+r1 with r1 <= 2.
    check(u16(data, 0x00064D46) == 0x2902, "FCE128 helper r1<=2 gate drift")
    check(u16(data, 0x00064D52) == 0x2009, "FCE128 helper output 9 drift")
    check(u16(data, 0x00064D58) == 0x200A, "FCE128 helper output 10 drift")
    fce128_entries, fce128_ptrs = owner_entries(data, OWNERS["FCE128_11x2"]["offset"], 22)

    # FCE2A8: four literal references feed six direct draws.  Physical slots 2 and 11 are NULL.
    for literal_offset in FCE2A8_LITERAL_OFFSETS:
        check(u32(data, literal_offset) == ROM_BASE + OWNERS["FCE2A8_sparse12"]["offset"], f"FCE2A8 literal drift at 0x{literal_offset:08X}")
    for call_offset in FCE2A8_DRAW_CALLS:
        check(thumb_bl_target(data, call_offset) == DRAW_WRAPPER, f"FCE2A8 draw call drift at 0x{call_offset:08X}")
    fce2a8_entries, fce2a8_ptrs = owner_entries(
        data,
        OWNERS["FCE2A8_sparse12"]["offset"],
        12,
        null_allowed={2, 11},
    )
    check(len(set(fce2a8_ptrs)) == 10, "FCE2A8 target uniqueness drift")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "owners": {
            "FCDF78_prefix13": {
                "offset": "0x00FCDF78",
                "physical_slots": 13,
                "text_entries": 13,
                "unique_targets": len(set(fcdf_ptrs)),
                "runtime_contract": "0x080603CA indexes table by RAM record field +0x25; input handler updates that field modulo 13 at 0x080604E4-0x080604E6",
                "semantic_review_status": "partial",
                "semantic_category": "mod13_indexed_label",
                "entries": fcdf_entries,
            },
            "FCE128_11x2": {
                "offset": "0x00FCE128",
                "physical_slots": 22,
                "text_entries": 22,
                "unique_targets": len(set(fce128_ptrs)),
                "runtime_contract": "base index 0..10 from 0x08064D38; caller optionally adds 11, yielding two 11-slot variants",
                "semantic_review_status": "partial",
                "semantic_category": "state_variant_label",
                "entries": fce128_entries,
            },
            "FCE2A8_sparse12": {
                "offset": "0x00FCE2A8",
                "physical_slots": 12,
                "text_entries": 10,
                "null_indices": [2, 11],
                "unique_targets": len(set(fce2a8_ptrs)),
                "runtime_contract": "four table-base literals feed six direct draw sites in the 0x080734xx-0x080735xx selection UI",
                "semantic_review_status": "partial",
                "semantic_category": "sparse_selection_label",
                "entries": fce2a8_entries,
            },
        },
        "summary": {
            "physical_pointer_fields_including_nulls": 47,
            "text_pointer_fields": 45,
            "unique_targets_across_owners": len(set(fcdf_ptrs + fce128_ptrs + fce2a8_ptrs)),
            "note": "Owners are intentionally separate despite physical adjacency near 0x00FCDF78-0x00FCE2D8.",
        },
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
