#!/usr/bin/env python3
"""Static closure for G Generation Advance table 0x001C92E8.

This tool is intentionally self-contained under advance/ and never writes to the
clean ROM.  It proves the VM dispatch path for the 114-entry table and exports a
machine-readable structural report.
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

TABLE_OFFSET = 0x001C92E8
TABLE_COUNT = 114
TABLE_LITERAL_OFFSET = 0x00011714
TABLE_LDR_OFFSET = 0x000116CC
DRAW_FUNCTION = 0x080116C4
DRAW_WRAPPER = 0x08000CA0
DRAW_CALL_OFFSET = 0x0001170C
HANDLER_FUNCTION = 0x0800C63C
HANDLER_CALL_OFFSET = 0x0000C65C
VM_DISPATCH_FUNCTION = 0x0800CE8C
VM_DISPATCH_CALL_OFFSET = 0x0000819A
VM_PRIMARY_TABLE_OFFSET = 0x0000823C
VM_PRIMARY_OPCODE = 0x18
VM_PRIMARY_HANDLER = 0x08008334
VM_SUBCOMMAND = 0xE1
VM_SUBCOMMAND_TABLE_OFFSET = 0x00FCDA44
VM_SUBCOMMAND_POINTER_OFFSET = VM_SUBCOMMAND_TABLE_OFFSET + VM_SUBCOMMAND * 4
VM_SUBCOMMAND_HANDLER_THUMB = HANDLER_FUNCTION | 1


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
    hits: list[int] = []
    for offset in range(0, len(data) - 3, 2):
        if thumb_bl_target(data, offset) == target:
            hits.append(offset)
    return hits


def literal_ldr_target(offset: int, halfword: int) -> tuple[int, int] | None:
    # Thumb-1 LDR Rt, [PC, #imm8*4]
    if halfword & 0xF800 != 0x4800:
        return None
    register = (halfword >> 8) & 0x7
    literal_offset = ((offset + 4) & ~3) + ((halfword & 0xFF) << 2)
    return register, literal_offset


def parse_multiline_blob(data: bytes, target_offset: int) -> tuple[list[dict[str, object]], int]:
    cursor = target_offset
    lines: list[dict[str, object]] = []
    while True:
        line_start = cursor
        tokens = 0
        while True:
            if cursor >= len(data):
                raise ValueError(f"unterminated stream at 0x{target_offset:08X}")
            lead = data[cursor]
            if lead == 0:
                break
            cursor += 1
            tokens += 1
            if lead >= 0xE0:
                if cursor >= len(data):
                    raise ValueError(f"truncated two-byte token at 0x{cursor - 1:08X}")
                cursor += 1
        line_end = cursor
        lines.append(
            {
                "offset": f"0x{line_start:08X}",
                "byte_length": line_end - line_start,
                "token_count": tokens,
                "raw_hex": data[line_start:line_end].hex().upper(),
            }
        )
        cursor += 1  # line NUL
        if cursor >= len(data):
            raise ValueError(f"missing blob terminator at 0x{target_offset:08X}")
        if data[cursor] == 0:
            cursor += 1  # second NUL terminates the blob
            break
    return lines, cursor - target_offset


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

    # Table literal and the LDR that consumes it.
    check(u32(data, TABLE_LITERAL_OFFSET) == ROM_BASE + TABLE_OFFSET, "table literal drift")
    ldr = literal_ldr_target(TABLE_LDR_OFFSET, u16(data, TABLE_LDR_OFFSET))
    check(ldr is not None, "table load is no longer Thumb literal LDR")
    check(ldr == (0, TABLE_LITERAL_OFFSET), f"table LDR drift: {ldr}")

    # Draw routine identity and sole direct caller.
    check(thumb_bl_target(data, DRAW_CALL_OFFSET) == DRAW_WRAPPER, "draw-wrapper call drift")
    draw_callers = bl_callers(data, DRAW_FUNCTION)
    check(draw_callers == [HANDLER_CALL_OFFSET], f"draw function callers drift: {draw_callers}")

    # Handler pops four stack values before forwarding r0-r3 to the draw routine.
    pop_calls = [0x0000C63E, 0x0000C644, 0x0000C64A, 0x0000C650]
    for offset in pop_calls:
        check(thumb_bl_target(data, offset) == 0x08007F4C, f"stack-pop call drift at 0x{offset:08X}")
    check(thumb_bl_target(data, HANDLER_CALL_OFFSET) == DRAW_FUNCTION, "handler draw call drift")

    # VM primary opcode 0x18 selects the subcommand dispatcher.
    primary_target = u32(data, VM_PRIMARY_TABLE_OFFSET + (VM_PRIMARY_OPCODE - 1) * 4)
    check(primary_target == VM_PRIMARY_HANDLER, f"primary opcode 0x18 drift: 0x{primary_target:08X}")
    check(thumb_bl_target(data, VM_DISPATCH_CALL_OFFSET) == VM_DISPATCH_FUNCTION, "VM dispatch call drift")

    # Subcommand E1 resolves to the 0x0800C63C handler.
    check(u32(data, 0x0000CEA4) == ROM_BASE + VM_SUBCOMMAND_TABLE_OFFSET, "subcommand table literal drift")
    subcommand_target = u32(data, VM_SUBCOMMAND_POINTER_OFFSET)
    check(
        subcommand_target == VM_SUBCOMMAND_HANDLER_THUMB,
        f"subcommand E1 handler drift: 0x{subcommand_target:08X}",
    )

    pointers = [u32(data, TABLE_OFFSET + index * 4) for index in range(TABLE_COUNT)]
    check(all(ROM_BASE <= pointer < ROM_BASE + len(data) for pointer in pointers), "non-ROM table pointer")
    check(len(set(pointers)) == TABLE_COUNT, "table target dedupe changed")

    entries: list[dict[str, object]] = []
    line_histogram: Counter[int] = Counter()
    total_lines = 0
    total_blob_bytes = 0
    max_blob_bytes = 0
    max_lines = 0

    for index, pointer in enumerate(pointers):
        target_offset = pointer - ROM_BASE
        lines, blob_bytes = parse_multiline_blob(data, target_offset)
        line_count = len(lines)
        line_histogram[line_count] += 1
        total_lines += line_count
        total_blob_bytes += blob_bytes
        max_blob_bytes = max(max_blob_bytes, blob_bytes)
        max_lines = max(max_lines, line_count)
        entries.append(
            {
                "index": index,
                "pointer_field_offset": f"0x{TABLE_OFFSET + index * 4:08X}",
                "target_address": f"0x{pointer:08X}",
                "target_offset": f"0x{target_offset:08X}",
                "line_count": line_count,
                "blob_bytes_including_double_nul": blob_bytes,
                "lines": lines,
            }
        )

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "family": "table_1C92E8",
        "semantic_classification": {
            "category": "scripted_multiline_text",
            "review_status": "reviewed",
            "confidence": "high",
            "evidence": [
                "VM primary opcode 0x18 reads a subcommand byte and dispatches through 0x08FCDA44",
                "subcommand 0xE1 resolves to Thumb handler 0x0800C63C",
                "handler pops four VM stack values and forwards them as r0-r3 to 0x080116C4",
                "0x080116C4 selects table[index], draws it, advances Y by 0x10, and repeats until double NUL",
            ],
        },
        "dispatch": {
            "vm_primary_opcode": f"0x{VM_PRIMARY_OPCODE:02X}",
            "vm_primary_handler": f"0x{VM_PRIMARY_HANDLER:08X}",
            "vm_subcommand": f"0x{VM_SUBCOMMAND:02X}",
            "vm_subcommand_table_offset": f"0x{VM_SUBCOMMAND_TABLE_OFFSET:08X}",
            "vm_subcommand_pointer_offset": f"0x{VM_SUBCOMMAND_POINTER_OFFSET:08X}",
            "vm_subcommand_handler": f"0x{HANDLER_FUNCTION:08X}",
            "draw_function": f"0x{DRAW_FUNCTION:08X}",
            "draw_function_direct_callers": [f"0x{ROM_BASE + x:08X}" for x in draw_callers],
            "argument_contract": ["x", "y", "draw_config", "table_index"],
            "line_y_advance_pixels": 16,
        },
        "table": {
            "offset": f"0x{TABLE_OFFSET:08X}",
            "address": f"0x{ROM_BASE + TABLE_OFFSET:08X}",
            "entries": TABLE_COUNT,
            "unique_targets": len(set(pointers)),
            "target_min": f"0x{min(pointers):08X}",
            "target_max": f"0x{max(pointers):08X}",
            "total_lines": total_lines,
            "line_count_histogram": {str(key): value for key, value in sorted(line_histogram.items())},
            "total_blob_bytes_including_double_nul": total_blob_bytes,
            "max_blob_bytes_including_double_nul": max_blob_bytes,
            "max_lines_per_entry": max_lines,
        },
        "entries": entries,
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
