#!/usr/bin/env python3
"""Audit the original ROM for omitted battle-event dialogue cases.

This is deliberately independent of the Korean candidate.  It closes the
known battle-event accessor, its 256x23 pointer table, the encoded source pool,
and ROM-wide aligned references into those regions.  It does not claim that a
runtime-generated string (if one existed outside this accessor) can be proven
from static ROM bytes alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_battle_event_dialogue_original_static_audit_20260831.json"
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
ROM_BASE = 0x08000000

# The accessor at 0x08058441 loads this literal and computes
# ((row * 23) + column) * 4 + table_base.
CONSUMER_FUNCTION_OFFSET = 0x00058440
CONSUMER_INDEX_LDR_OFFSET = 0x00058466
CONSUMER_INDEX_FORMULA_OFFSET = 0x00058468
TABLE_BASE_LITERAL_OFFSET = 0x00058508
TABLE_START = 0x00D34588
TABLE_ROWS = 256
TABLE_COLUMNS = 23
TABLE_END = TABLE_START + TABLE_ROWS * TABLE_COLUMNS * 4
STRING_START = 0x00D34130
STRING_END = TABLE_START
INDEX_FORMULA_PATTERN = bytes.fromhex("70008019c000801bc019800040180168")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def hex32(value: int) -> str:
    return f"0x{value:08X}"


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def find_all(data: bytes, pattern: bytes) -> list[int]:
    result: list[int] = []
    start = 0
    while True:
        found = data.find(pattern, start)
        if found < 0:
            return result
        result.append(found)
        start = found + 1


def decode_thumb_bl_targets(data: bytes, target: int) -> list[int]:
    """Return halfword offsets containing Thumb-1 BLs to target (Thumb bit ignored)."""
    target &= ~1
    result: list[int] = []
    for offset in range(0, len(data) - 3, 2):
        first, second = struct.unpack_from("<HH", data, offset)
        if (first & 0xF800) != 0xF000 or (second & 0xF800) != 0xF800:
            continue
        sign = (first >> 10) & 1
        imm10 = first & 0x03FF
        j1 = (second >> 13) & 1
        j2 = (second >> 11) & 1
        imm11 = second & 0x07FF
        i1 = 1 ^ (j1 ^ sign)
        i2 = 1 ^ (j2 ^ sign)
        immediate = (sign << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
        if immediate & (1 << 24):
            immediate -= 1 << 25
        destination = (ROM_BASE + offset + 4 + immediate) & ~1
        if destination == target:
            result.append(offset)
    return result


def parse_stream(
    rom: bytes,
    target: int,
    dictionary: list[list[int]],
    charmap: dict[int, str],
    read_tokens: Any,
    expand_to_slots: Any,
) -> dict[str, Any]:
    cursor = target
    segments: list[dict[str, Any]] = []
    controls: list[int] = []
    while True:
        tokens, raw = read_tokens(rom, cursor)
        slots = expand_to_slots(tokens, dictionary)
        text = "".join(charmap.get(slot, f"<{slot:04X}>") for slot in slots)
        cursor += len(raw)
        gate(cursor < STRING_END, f"stream at {hex32(target)} ran beyond source pool")
        code = rom[cursor]
        cursor += 1
        argument = None
        if code in (0x05, 0x06):
            argument = rom[cursor]
            cursor += 1
        gate(code in (0x01, 0x02, 0x03, 0x05, 0x06), f"unknown control {code:02X} at {hex32(cursor - 1)}")
        controls.append(code)
        segment: dict[str, Any] = {
            "segment_index": len(segments),
            "text": text,
            "raw_size": len(raw),
            "control": f"0x{code:02X}",
        }
        if argument is not None:
            segment["argument"] = argument
        segments.append(segment)
        if code == 0x01:
            break
    return {
        "source_file_offset": hex32(target),
        "end_file_offset_exclusive": hex32(cursor),
        "size": cursor - target,
        "segments": segments,
        "control_codes": [f"0x{code:02X}" for code in controls],
        "text": "\\n".join(segment["text"] for segment in segments if segment["text"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROM_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rom_path = args.rom if args.rom.is_absolute() else ROOT / args.rom
    rom_path = rom_path.resolve()
    rom = rom_path.read_bytes()
    gate(len(rom) == 16 * 1024 * 1024, f"unexpected original ROM size: {len(rom)}")
    rom_sha = sha256(rom)
    gate(rom_sha == EXPECTED_SHA256, f"unexpected ROM SHA-256: {rom_sha}")

    # Import the project codec only after the ROM identity gate.  These modules
    # are local and do not inspect or modify the candidate ROM.
    sys.path.insert(0, str(ROOT / "tools"))
    from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402
    from ggen_advance_text_codec import (  # noqa: E402
        DICT_12X12_BASE,
        DICT_12X12_END,
        expand_to_slots,
        load_dictionary,
        read_tokens,
    )

    dictionary = load_dictionary(rom, DICT_12X12_BASE, DICT_12X12_END)
    charmap = load_map(ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json")
    charmap.update(CORRECTED_LOW_KANA)

    pointers: list[dict[str, Any]] = []
    targets: list[int] = []
    for index in range(TABLE_ROWS * TABLE_COLUMNS):
        owner_offset = TABLE_START + index * 4
        pointer = u32(rom, owner_offset)
        if pointer == 0:
            continue
        target = pointer - ROM_BASE
        gate(STRING_START <= target < STRING_END, f"table pointer outside source pool at {hex32(owner_offset)}")
        row, column = divmod(index, TABLE_COLUMNS)
        pointers.append(
            {
                "row": row,
                "column": column,
                "owner_file_offset": hex32(owner_offset),
                "pointer": hex32(pointer),
                "target_file_offset": hex32(target),
            }
        )
        targets.append(target)

    gate(len(targets) == len(set(targets)), "duplicate nonzero table targets")
    streams = [parse_stream(rom, target, dictionary, charmap, read_tokens, expand_to_slots) for target in sorted(targets)]

    # The source pool is a packed set of those streams with zero alignment
    # padding between records.  Any nonzero gap would be an orphan candidate.
    gap_ranges: list[dict[str, Any]] = []
    orphan_nonzero: list[dict[str, Any]] = []
    previous = STRING_START
    stream_bytes = 0
    for stream in streams:
        start = int(stream["source_file_offset"], 16)
        end = int(stream["end_file_offset_exclusive"], 16)
        gate(start >= previous, f"overlapping source stream at {hex32(start)}")
        gap = rom[previous:start]
        if gap:
            nonzero = [previous + i for i, value in enumerate(gap) if value]
            gap_ranges.append(
                {
                    "start": hex32(previous),
                    "end_exclusive": hex32(start),
                    "size": len(gap),
                    "all_zero": not nonzero,
                }
            )
            orphan_nonzero.extend({"file_offset": hex32(offset), "byte": rom[offset]} for offset in nonzero)
        stream_bytes += end - start
        previous = end
    tail = rom[previous:STRING_END]
    if tail:
        nonzero = [previous + i for i, value in enumerate(tail) if value]
        gap_ranges.append(
            {
                "start": hex32(previous),
                "end_exclusive": hex32(STRING_END),
                "size": len(tail),
                "all_zero": not nonzero,
            }
        )
        orphan_nonzero.extend({"file_offset": hex32(offset), "byte": rom[offset]} for offset in nonzero)
    gate(not orphan_nonzero, "nonzero bytes in source-pool gaps indicate an orphan stream")

    # Aligned ROM-wide pointer scan: if this accessor had another statically
    # referenced string in its source pool, it would appear here outside the
    # table's own 49 owner fields.
    pool_refs: list[dict[str, Any]] = []
    table_refs: list[dict[str, Any]] = []
    for offset in range(0, len(rom) - 3, 4):
        value = u32(rom, offset)
        if ROM_BASE + STRING_START <= value < ROM_BASE + STRING_END:
            pool_refs.append({"file_offset": hex32(offset), "pointer": hex32(value)})
        if ROM_BASE + TABLE_START <= value < ROM_BASE + TABLE_END:
            table_refs.append({"file_offset": hex32(offset), "pointer": hex32(value)})
    table_owner_offsets = {TABLE_START + index * 4 for index in range(TABLE_ROWS * TABLE_COLUMNS)}
    external_pool_refs = [item for item in pool_refs if int(item["file_offset"], 16) not in table_owner_offsets]
    pool_refs_byte_scan = [
        {"file_offset": hex32(offset), "pointer": hex32(u32(rom, offset))}
        for offset in range(0, len(rom) - 3)
        if ROM_BASE + STRING_START <= u32(rom, offset) < ROM_BASE + STRING_END
    ]
    external_pool_refs_byte_scan = [
        item for item in pool_refs_byte_scan if int(item["file_offset"], 16) not in table_owner_offsets
    ]
    for item in table_refs:
        target_offset = int(item["pointer"], 16) - ROM_BASE
        item["target_four_bytes_all_zero"] = rom[target_offset : target_offset + 4] == b"\x00" * 4

    literal_occurrences = find_all(rom, struct.pack("<I", ROM_BASE + TABLE_START))
    formula_occurrences = find_all(rom, INDEX_FORMULA_PATTERN)
    callsites = decode_thumb_bl_targets(rom, ROM_BASE + CONSUMER_FUNCTION_OFFSET)

    control_counts = Counter(code for stream in streams for code in stream["control_codes"])
    output = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_event_dialogue_original_static_audit",
        "rom": {
            "path": str(rom_path.relative_to(ROOT)).replace("\\", "/"),
            "size": len(rom),
            "sha256": rom_sha,
        },
        "consumer": {
            "function_file_offset": hex32(CONSUMER_FUNCTION_OFFSET),
            "function_thumb_address": hex32(ROM_BASE + CONSUMER_FUNCTION_OFFSET + 1),
            "index_ldr_file_offset": hex32(CONSUMER_INDEX_LDR_OFFSET),
            "index_formula_file_offset": hex32(CONSUMER_INDEX_FORMULA_OFFSET),
            "table_base_literal_file_offset": hex32(TABLE_BASE_LITERAL_OFFSET),
            "table_base_literal": hex32(u32(rom, TABLE_BASE_LITERAL_OFFSET)),
            "table_base_literal_occurrences": [hex32(offset) for offset in literal_occurrences],
            "index_formula_pattern_occurrences": [hex32(offset) for offset in formula_occurrences],
            "thumb_bl_callsite_count": len(callsites),
            "thumb_bl_callsites": [hex32(offset) for offset in callsites],
            "alternate_same_formula_consumer_count": len(formula_occurrences),
        },
        "pointer_table": {
            "file_offset": hex32(TABLE_START),
            "end_exclusive": hex32(TABLE_END),
            "shape": [TABLE_ROWS, TABLE_COLUMNS],
            "cells": TABLE_ROWS * TABLE_COLUMNS,
            "nonzero_entries": len(pointers),
            "zero_entries": TABLE_ROWS * TABLE_COLUMNS - len(pointers),
            "unique_targets": len(set(targets)),
            "target_min": hex32(min(targets)) if targets else None,
            "target_max": hex32(max(targets)) if targets else None,
            "entries": pointers,
        },
        "source_pool": {
            "file_offset": hex32(STRING_START),
            "end_exclusive": hex32(STRING_END),
            "size": STRING_END - STRING_START,
            "parsed_stream_count": len(streams),
            "stream_bytes": stream_bytes,
            "padding_bytes": (STRING_END - STRING_START) - stream_bytes,
            "padding_ranges": gap_ranges,
            "orphan_nonzero_bytes": orphan_nonzero,
            "all_streams_terminal": all("0x01" in stream["control_codes"][-1:] for stream in streams),
            "control_code_counts": dict(sorted(control_counts.items())),
            "streams": streams,
        },
        "rom_wide_pointer_scan": {
            "aligned_word_scan": True,
            "references_into_source_pool": len(pool_refs),
            "references_into_source_pool_outside_49_table_owners": len(external_pool_refs),
            "external_source_pool_references": external_pool_refs,
            "byte_scan_references_into_source_pool": len(pool_refs_byte_scan),
            "byte_scan_source_pool_references_outside_49_table_owners": len(external_pool_refs_byte_scan),
            "byte_scan_external_source_pool_references": external_pool_refs_byte_scan,
            "references_into_table_region": len(table_refs),
            "table_region_references": table_refs,
        },
        "verification": {
            "result": "PASS" if not external_pool_refs_byte_scan and not orphan_nonzero and len(targets) == 49 else "FAIL",
            "additional_statically_reachable_cases": len(external_pool_refs_byte_scan),
            "orphan_source_streams": len(orphan_nonzero),
            "known_table_entries_closed": len(targets) == 49,
            "dynamic_runtime_strings_out_of_scope": True,
            "verdict": "no additional statically reachable battle_event_dialogue cases detected for this accessor",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["verification"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
