#!/usr/bin/env python3
"""Static runtime-access audit for G Generation Advance table 0x00FCE2D8.

The historical extractor grouped the first 69 fields as 23x3.  This analyzer
checks the actual runtime access pattern.  The game code treats the owner as a
flat pointer array selected by byte indices, with several paths constructing
adjacent even/odd index pairs.

The tool is read-only and prints JSON to stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

TABLE_OFFSET = 0x00FCE2D8
TABLE_ADDRESS = ROM_BASE + TABLE_OFFSET
TABLE_FIELDS = 69

TABLE_LITERAL_OFFSETS = (0x00073B70, 0x00073C40, 0x00073EB0, 0x00073F68)
TABLE_LDR_SITES = (
    (0x00073B40, 5, 0x00073B70),
    (0x00073C0C, 5, 0x00073C40),
    (0x00073E80, 5, 0x00073EB0),
    (0x00073EFC, 4, 0x00073F68),
)

DRAW_WRAPPER = 0x08000CA0
DRAW_CALL_SITES = (
    0x00073B54,
    0x00073B68,
    0x00073C20,
    0x00073C34,
    0x00073E94,
    0x00073EA8,
    0x00073F10,
    0x00073F24,
)

MODE0_RENDER = 0x08073A04
MODE1_RENDER = 0x08073D14
COMMON_UI = 0x08073634
NORMALIZER = 0x08074088
NORMALIZER_CALL_SITES = (
    0x00073B00,
    0x00073B16,
    0x00073D9C,
    0x00073E44,
    0x00073E5A,
)


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
    result: list[int] = []
    for offset in range(0, len(data) - 3, 2):
        if thumb_bl_target(data, offset) == target:
            result.append(offset)
    return result


def literal_ldr_target(offset: int, halfword: int) -> tuple[int, int] | None:
    if halfword & 0xF800 != 0x4800:
        return None
    register = (halfword >> 8) & 0x7
    literal_offset = ((offset + 4) & ~3) + ((halfword & 0xFF) << 2)
    return register, literal_offset


def strict_stream(data: bytes, offset: int) -> tuple[int, int]:
    cursor = offset
    tokens = 0
    while cursor < len(data):
        lead = data[cursor]
        if lead == 0:
            return cursor - offset + 1, tokens
        cursor += 1
        tokens += 1
        if lead >= 0xE0:
            if cursor >= len(data):
                break
            cursor += 1
    raise ValueError(f"unterminated token stream at 0x{offset:08X}")


def normalize_selection_code(value: int) -> int:
    """Python transcription of the arithmetic in 0x08074088.

    This is not a claim that all 0..255 inputs are valid at the caller.  It is
    used to document the transformation for the code classes explicitly handled
    by the routine.
    """
    value &= 0xFF
    if value == 0x1F:
        normalized = 0x14
    elif ((value - 0x3D) & 0xFF) <= 0x13:
        normalized = (value - 0x3D) & 0xFF
    elif ((value - 0x65) & 0xFF) <= 4:
        normalized = (value + 0xB0) & 0xFF
    elif ((value - 0x6F) & 0xFF) <= 4:
        normalized = (value + 0xA6) & 0xFF
    elif ((value + 0x37) & 0xFF) <= 1:
        normalized = (value + 0x51) & 0xFF
    elif value == 0:
        normalized = 0
    else:
        normalized = (value - 1) & 0xFF
    return (normalized * 2) & 0xFF


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    # The runtime has four literal-pool copies of the same table address.
    for offset in TABLE_LITERAL_OFFSETS:
        check(u32(data, offset) == TABLE_ADDRESS, f"table literal drift at 0x{offset:08X}")
    literal_hits: list[int] = []
    needle = struct.pack("<I", TABLE_ADDRESS)
    cursor = 0
    while True:
        cursor = data.find(needle, cursor)
        if cursor < 0:
            break
        literal_hits.append(cursor)
        cursor += 1
    check(literal_hits == list(TABLE_LITERAL_OFFSETS), f"unexpected table xrefs: {literal_hits}")

    for site, register, literal_offset in TABLE_LDR_SITES:
        decoded = literal_ldr_target(site, u16(data, site))
        check(decoded == (register, literal_offset), f"table LDR drift at 0x{site:08X}: {decoded}")

    for site in DRAW_CALL_SITES:
        check(thumb_bl_target(data, site) == DRAW_WRAPPER, f"draw call drift at 0x{site:08X}")
    for site in NORMALIZER_CALL_SITES:
        check(thumb_bl_target(data, site) == NORMALIZER, f"normalizer call drift at 0x{site:08X}")

    # Common UI selects one of two table-using render paths based on its mode.
    check(thumb_bl_target(data, 0x000736D2) == MODE0_RENDER, "mode-0 render call drift")
    check(thumb_bl_target(data, 0x000736F6) == MODE1_RENDER, "mode-1 render call drift")
    check(bl_callers(data, MODE0_RENDER) == [0x000736D2], "mode-0 direct caller set drift")
    check(bl_callers(data, MODE1_RENDER) == [0x000736F6], "mode-1 direct caller set drift")

    # Two registered wrappers call the common UI with fixed mode 0/1.
    check(thumb_bl_target(data, 0x000735FC) == COMMON_UI, "mode-0 wrapper drift")
    check(thumb_bl_target(data, 0x0007360C) == COMMON_UI, "mode-1 wrapper drift")
    check(u32(data, 0x00D58D30) == 0x080735F9, "registered mode-0 callback pointer drift")
    check(u32(data, 0x00D58D34) == 0x08073609, "registered mode-1 callback pointer drift")

    pointers = [u32(data, TABLE_OFFSET + index * 4) for index in range(TABLE_FIELDS)]
    check(all(ROM_BASE <= pointer < ROM_BASE + len(data) for pointer in pointers), "non-ROM table pointer")
    target_counts = Counter(pointers)
    duplicates = {pointer: count for pointer, count in target_counts.items() if count > 1}
    check(len(target_counts) == 68, f"unique-target count drift: {len(target_counts)}")
    check(duplicates == {0x081BE9D7: 2}, f"duplicate-target set drift: {duplicates}")
    duplicate_indices = [index for index, pointer in enumerate(pointers) if pointer == 0x081BE9D7]
    check(duplicate_indices == [60, 61], f"duplicate indices drift: {duplicate_indices}")

    entries: list[dict[str, object]] = []
    total_bytes = 0
    unique_stream_bytes = sum(strict_stream(data, pointer - ROM_BASE)[0] for pointer in set(pointers))
    for index, pointer in enumerate(pointers):
        target_offset = pointer - ROM_BASE
        byte_length, token_count = strict_stream(data, target_offset)
        total_bytes += byte_length
        entries.append(
            {
                "index": index,
                "pair_number": index // 2,
                "pair_side": "even/base" if index % 2 == 0 else "odd/companion",
                "pointer_field_offset": f"0x{TABLE_OFFSET + index * 4:08X}",
                "target_address": f"0x{pointer:08X}",
                "target_offset": f"0x{target_offset:08X}",
                "byte_length_including_nul": byte_length,
                "token_count": token_count,
            }
        )

    explicit_normalizer_cases: dict[str, list[dict[str, object]]] = {
        "0x3D-0x50": [],
        "0x65-0x69": [],
        "0x6F-0x73": [],
        "0xC9-0xCA": [],
        "0x1F": [],
    }
    for value in range(0x3D, 0x51):
        explicit_normalizer_cases["0x3D-0x50"].append(
            {"input": f"0x{value:02X}", "base_index": normalize_selection_code(value)}
        )
    for value in range(0x65, 0x6A):
        explicit_normalizer_cases["0x65-0x69"].append(
            {"input": f"0x{value:02X}", "base_index": normalize_selection_code(value)}
        )
    for value in range(0x6F, 0x74):
        explicit_normalizer_cases["0x6F-0x73"].append(
            {"input": f"0x{value:02X}", "base_index": normalize_selection_code(value)}
        )
    for value in (0xC9, 0xCA):
        explicit_normalizer_cases["0xC9-0xCA"].append(
            {"input": f"0x{value:02X}", "base_index": normalize_selection_code(value)}
        )
    explicit_normalizer_cases["0x1F"].append(
        {"input": "0x1F", "base_index": normalize_selection_code(0x1F)}
    )

    # These explicit classes all resolve to even base indices in the table domain.
    explicit_outputs = [
        item["base_index"]
        for group in explicit_normalizer_cases.values()
        for item in group
    ]
    check(all(isinstance(value, int) and value % 2 == 0 for value in explicit_outputs), "odd normalized base")
    check(max(explicit_outputs) <= 54, f"explicit normalized base escaped expected range: {max(explicit_outputs)}")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "historical_family_name": "table_FCE2D8_23x3",
        "runtime_structure": {
            "recommended_family_name": "table_FCE2D8_flat69_paired_selection",
            "classification": "paired_selection_code_label_table",
            "semantic_review_status": "partial",
            "confidence": "high for structure / unresolved for exact screen noun",
            "reason": (
                "Runtime code never computes row*3+column for this owner. It loads the base as a flat "
                "pointer array and indexes it with byte values. The normalizer at 0x08074088 maps the "
                "explicitly handled selection-code classes to even base indices, while caller code also "
                "constructs adjacent base+1 companion indices."
            ),
        },
        "table": {
            "offset": f"0x{TABLE_OFFSET:08X}",
            "address": f"0x{TABLE_ADDRESS:08X}",
            "pointer_fields": TABLE_FIELDS,
            "unique_targets": len(target_counts),
            "duplicate_target": "0x081BE9D7",
            "duplicate_indices": duplicate_indices,
            "total_stream_bytes_including_nul_per_field": total_bytes,
            "unique_stream_bytes_including_nul": unique_stream_bytes,
            "literal_xrefs": [f"0x{offset:08X}" for offset in literal_hits],
        },
        "runtime_access": {
            "common_ui": f"0x{COMMON_UI:08X}",
            "mode0_render": f"0x{MODE0_RENDER:08X}",
            "mode1_render": f"0x{MODE1_RENDER:08X}",
            "registered_callback_pointer_fields": ["0x00D58D30", "0x00D58D34"],
            "table_load_sites": [f"0x{ROM_BASE + site:08X}" for site, _, _ in TABLE_LDR_SITES],
            "draw_calls": [f"0x{ROM_BASE + site:08X}" for site in DRAW_CALL_SITES],
            "normalizer": f"0x{NORMALIZER:08X}",
            "normalizer_calls": [f"0x{ROM_BASE + site:08X}" for site in NORMALIZER_CALL_SITES],
            "observed_layout": {
                "mode0_first_pair": ["(x=0x10,y=0x20)", "(x=0x50,y=0x20)"],
                "mode0_second_pair": ["(x=0x10,y=0x70)", "(x=0x50,y=0x70)"],
                "mode1_first_pair": ["(x=0x10,y=0x28)", "(x=0x50,y=0x28)"],
                "mode1_second_pair": ["(x=0x30,y=0x40)", "(x=0x70,y=0x40)"],
            },
        },
        "normalizer_explicit_cases": explicit_normalizer_cases,
        "pairing_evidence": [
            "0x08073B00/0x08073B16 call 0x08074088 and store its even result as a flat table index.",
            "0x08073B22 adds 1 to a normalized base for an adjacent companion index; one special branch uses literal index 0x39.",
            "0x08073D9C, 0x08073E44 and 0x08073E5A reuse the same normalizer in the second UI mode.",
            "Physical indices 60 and 61 intentionally share target 0x081BE9D7, so 69 fields contain 68 unique streams.",
        ],
        "entries": entries,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
