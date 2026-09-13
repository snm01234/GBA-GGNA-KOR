#!/usr/bin/env python3
"""Reconstruct the direct_pc_literal text family from the clean ROM.

A member is a direct call to text draw wrapper 0x08000CA0 whose r3 text argument
is loaded by a real Thumb-1 PC-relative ``LDR r3,[pc,#imm]`` in the immediately
preceding 12 bytes.  The literal must resolve to a valid non-empty ROM token
stream, and no later instruction before the call may overwrite r3.

The short local window is deliberate: GBA uses ARM7TDMI Thumb-1, where BL is a
32-bit instruction.  Starting a long disassembly window at an arbitrary
halfword can split a BL pair and produce false register-writer results.

This tool is self-contained under advance/ and never modifies the ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm import ARM_REG_R3

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DRAW_WRAPPER = 0x08000CA0
EXPECTED_DRAW_CALLS = 196
EXPECTED_PC_LITERAL_CALLS = 121
EXPECTED_UNIQUE_TARGETS = 67
LOCAL_LOOKBACK_BYTES = 12


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


def parse_stream(data: bytes, offset: int, limit: int = 512) -> dict[str, object] | None:
    cursor = offset
    token_count = 0
    end = min(len(data), offset + limit)
    while cursor < end:
        lead = data[cursor]
        if lead == 0:
            if token_count == 0:
                return None
            return {
                "byte_length_including_nul": cursor - offset + 1,
                "token_count": token_count,
                "raw_hex": data[offset:cursor].hex().upper(),
            }
        cursor += 1
        token_count += 1
        if lead >= 0xE0:
            if cursor >= end:
                return None
            cursor += 1
    return None


def literal_from_ldr_r3(data: bytes, instruction_offset: int) -> tuple[int, int] | None:
    """Return (literal_pool_offset, value) for Thumb-1 LDR r3,[pc,#imm8*4]."""
    halfword = u16(data, instruction_offset)
    if halfword & 0xFF00 != 0x4B00:
        return None
    literal_offset = ((instruction_offset + 4) & ~3) + ((halfword & 0xFF) << 2)
    if literal_offset + 4 > len(data):
        return None
    return literal_offset, u32(data, literal_offset)


def has_later_r3_writer(md: Cs, data: bytes, writer_offset: int, call_offset: int) -> bool:
    """Disassemble from a known-valid Thumb-1 LDR boundary to avoid BL desync."""
    for insn in md.disasm(data[writer_offset:call_offset], ROM_BASE + writer_offset):
        if insn.address >= ROM_BASE + call_offset:
            break
        if insn.address == ROM_BASE + writer_offset:
            continue
        try:
            _reads, writes = insn.regs_access()
        except Exception:
            continue
        if ARM_REG_R3 in writes:
            return True
    return False


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

    draw_calls = [
        offset
        for offset in range(0, len(data) - 3, 2)
        if thumb_bl_target(data, offset) == DRAW_WRAPPER
    ]
    check(len(draw_calls) == EXPECTED_DRAW_CALLS, f"draw call count drift: {len(draw_calls)}")

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True

    records: list[dict[str, object]] = []
    by_target: dict[int, list[int]] = defaultdict(list)
    distance_histogram: Counter[int] = Counter()

    for call_offset in draw_calls:
        candidates: list[tuple[int, int, int, dict[str, object]]] = []
        start = max(0, call_offset - LOCAL_LOOKBACK_BYTES)
        for writer_offset in range(start, call_offset, 2):
            literal = literal_from_ldr_r3(data, writer_offset)
            if literal is None:
                continue
            literal_offset, value = literal
            if not (ROM_BASE <= value < ROM_BASE + len(data)):
                continue
            stream = parse_stream(data, value - ROM_BASE)
            if stream is None:
                continue
            candidates.append((writer_offset, literal_offset, value, stream))

        if not candidates:
            continue

        writer_offset, literal_offset, value, stream = candidates[-1]
        check(
            not has_later_r3_writer(md, data, writer_offset, call_offset),
            f"later r3 writer found between literal load 0x{writer_offset:08X} and call 0x{call_offset:08X}",
        )
        distance = call_offset - writer_offset
        distance_histogram[distance] += 1
        by_target[value].append(call_offset)
        records.append(
            {
                "call_offset": f"0x{call_offset:08X}",
                "call_address": f"0x{ROM_BASE + call_offset:08X}",
                "r3_writer_offset": f"0x{writer_offset:08X}",
                "r3_writer_address": f"0x{ROM_BASE + writer_offset:08X}",
                "writer_to_call_bytes": distance,
                "literal_pool_offset": f"0x{literal_offset:08X}",
                "literal_pool_value": f"0x{value:08X}",
                "text_target_offset": f"0x{value - ROM_BASE:08X}",
                "stream": stream,
            }
        )

    check(
        len(records) == EXPECTED_PC_LITERAL_CALLS,
        f"PC-literal call-site count drift: {len(records)}",
    )
    check(
        len(by_target) == EXPECTED_UNIQUE_TARGETS,
        f"PC-literal unique target count drift: {len(by_target)}",
    )

    targets = []
    record_by_value = {int(record["literal_pool_value"], 16): record for record in records}
    for value, call_offsets in sorted(by_target.items()):
        first = record_by_value[value]
        targets.append(
            {
                "text_pointer_address": f"0x{value:08X}",
                "text_target_offset": f"0x{value - ROM_BASE:08X}",
                "call_site_count": len(call_offsets),
                "call_sites": [f"0x{ROM_BASE + x:08X}" for x in call_offsets],
                "stream": first["stream"],
            }
        )

    total_unique_bytes = sum(int(target["stream"]["byte_length_including_nul"]) for target in targets)
    total_unique_tokens = sum(int(target["stream"]["token_count"]) for target in targets)

    report = {
        "schema_version": 2,
        "rom_sha256": digest,
        "family": "direct_pc_literal",
        "semantic_classification": {
            "category": "static_ui_literal_text",
            "review_status": "partial",
            "confidence": "high for provenance / mixed exact UI roles unresolved",
            "evidence": [
                "all 196 direct calls to 0x08000CA0 are scanned from the clean ROM",
                "121 call sites have a valid Thumb-1 PC-relative LDR r3 within the immediately preceding 12 bytes",
                "no reconstructed call has a later r3 writer between the literal load and draw call",
                "the 121 literal loads resolve to exactly 67 unique valid ROM token streams",
                "the 67-target count matches the historical direct_pc_literal family size",
            ],
        },
        "reconstruction": {
            "draw_wrapper": f"0x{DRAW_WRAPPER:08X}",
            "all_direct_draw_calls": len(draw_calls),
            "pc_literal_draw_calls": len(records),
            "unique_text_targets": len(targets),
            "local_lookback_bytes": LOCAL_LOOKBACK_BYTES,
            "writer_to_call_distance_histogram": {str(k): v for k, v in sorted(distance_histogram.items())},
            "classification_rule": "nearest valid Thumb-1 LDR r3,[pc,#imm] in preceding 12 bytes; literal is non-empty ROM text; no later r3 writer",
            "preliminary_118_count_correction": "superseded: long arbitrary Capstone backtrack windows can begin on the second halfword of a 32-bit Thumb BL and desynchronize writer analysis; local raw Thumb-1 LDR decoding yields 121 call sites",
        },
        "corpus": {
            "target_min": f"0x{min(by_target):08X}",
            "target_max": f"0x{max(by_target):08X}",
            "unique_stream_bytes_including_nul": total_unique_bytes,
            "unique_stream_tokens": total_unique_tokens,
        },
        "call_sites": records,
        "targets": targets,
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
