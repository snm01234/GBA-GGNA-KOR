#!/usr/bin/env python3
"""Inventory all direct text draw sources for G Generation Advance.

The clean ROM has 196 direct BL calls to 0x08000CA0.  This tool classifies the
nearest real 16-bit Thumb instruction that writes r3, the text pointer argument,
without depending on parent-project producer tooling.

For r0-forward patterns it also records the nearest preceding BL helper whose
return value is moved into r3.  The resulting report is intended as an
advance-local roadmap for remaining semantic/source closure work.
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
LOOKBACK_BYTES = 0x30
HELPER_LOOKBACK_BYTES = 0x10

KNOWN_SPECIAL_CALLS = {
    0x0001C63E: "current_search_record_text_10",
    0x0005F860: "unreferenced_debug_menu_runtime_list",
    0x0006100C: "direct_struct8_text",
    0x000611FC: "direct_struct72_text",
}

FCE2D8_DRAW_CALLS = {
    0x00073B54,
    0x00073B68,
    0x00073C20,
    0x00073C34,
    0x00073E94,
    0x00073EA8,
    0x00073F10,
    0x00073F24,
}


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def thumb_bl_target(data: bytes, offset: int) -> int | None:
    high = u16(data, offset)
    low = u16(data, offset + 2)
    if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
        return None
    displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
    if displacement & (1 << 22):
        displacement -= 1 << 23
    return (ROM_BASE + offset + 4 + displacement) & 0xFFFFFFFF


def nearest_r3_writer(md: Cs, data: bytes, call_offset: int):
    candidates = []
    start = max(0, call_offset - LOOKBACK_BYTES)
    for offset in range(start, call_offset, 2):
        insn = next(md.disasm(data[offset : offset + 4], ROM_BASE + offset, count=1), None)
        if insn is None or insn.size != 2:
            continue
        try:
            _reads, writes = insn.regs_access()
        except Exception:
            continue
        if ARM_REG_R3 in writes:
            candidates.append((offset, insn))
    return candidates[-1] if candidates else None


def classify_writer(mnemonic: str, op_str: str) -> str:
    if mnemonic == "ldr" and op_str.startswith("r3, [pc,"):
        return "pc_literal"
    if mnemonic == "adds" and op_str == "r3, r0, #0":
        return "forward_r0"
    if mnemonic == "adds" and op_str == "r3, r4, #0":
        return "forward_r4"
    if mnemonic == "adds" and op_str == "r3, r5, #0":
        return "forward_r5"
    if mnemonic == "ldr" and op_str == "r3, [r0]":
        return "indirect_r0"
    return "special"


def nearest_preceding_helper(data: bytes, writer_offset: int) -> tuple[int, int] | None:
    candidates = []
    for offset in range(max(0, writer_offset - HELPER_LOOKBACK_BYTES), writer_offset, 2):
        target = thumb_bl_target(data, offset)
        if target is not None:
            candidates.append((offset, target))
    return candidates[-1] if candidates else None


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

    records = []
    category_counts: Counter[str] = Counter()
    exact_writer_counts: Counter[str] = Counter()
    forward_r0_helpers: dict[int, list[int]] = defaultdict(list)
    indirect_r0_calls = []
    special_calls = []

    for call_offset in draw_calls:
        result = nearest_r3_writer(md, data, call_offset)
        check(result is not None, f"no local r3 writer for draw 0x{call_offset:08X}")
        writer_offset, insn = result
        source_class = classify_writer(insn.mnemonic, insn.op_str)
        category_counts[source_class] += 1
        exact_writer_counts[f"{insn.mnemonic} {insn.op_str}"] += 1

        helper = None
        if source_class == "forward_r0":
            helper = nearest_preceding_helper(data, writer_offset)
            check(helper is not None, f"no helper before r0-forward writer 0x{writer_offset:08X}")
            forward_r0_helpers[helper[1]].append(call_offset)
        elif source_class == "indirect_r0":
            indirect_r0_calls.append(call_offset)
        elif source_class == "special":
            special_calls.append(call_offset)

        annotation = KNOWN_SPECIAL_CALLS.get(call_offset)
        if call_offset in FCE2D8_DRAW_CALLS:
            annotation = "table_FCE2D8_flat69_paired_selection"

        records.append(
            {
                "call_offset": f"0x{call_offset:08X}",
                "call_address": f"0x{ROM_BASE + call_offset:08X}",
                "writer_offset": f"0x{writer_offset:08X}",
                "writer_address": f"0x{ROM_BASE + writer_offset:08X}",
                "writer": f"{insn.mnemonic} {insn.op_str}",
                "source_class": source_class,
                "preceding_helper_call_offset": f"0x{helper[0]:08X}" if helper else None,
                "preceding_helper_target": f"0x{helper[1]:08X}" if helper else None,
                "known_annotation": annotation,
            }
        )

    expected_counts = {
        "pc_literal": 121,
        "forward_r0": 44,
        "indirect_r0": 16,
        "forward_r4": 8,
        "forward_r5": 3,
        "special": 4,
    }
    check(dict(category_counts) == expected_counts, f"source class drift: {dict(category_counts)}")
    check(set(FCE2D8_DRAW_CALLS).issubset(indirect_r0_calls), "FCE2D8 calls no longer indirect_r0")
    check(set(KNOWN_SPECIAL_CALLS).issubset(draw_calls), "known special draw call missing")

    unresolved_indirect_r0 = sorted(set(indirect_r0_calls) - FCE2D8_DRAW_CALLS)

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "draw_wrapper": f"0x{DRAW_WRAPPER:08X}",
        "direct_draw_calls": len(draw_calls),
        "source_class_counts": dict(category_counts),
        "exact_writer_histogram": dict(exact_writer_counts.most_common()),
        "forward_r0_helper_groups": [
            {
                "helper_target": f"0x{target:08X}",
                "draw_call_count": len(calls),
                "draw_calls": [f"0x{ROM_BASE + call:08X}" for call in calls],
            }
            for target, calls in sorted(forward_r0_helpers.items(), key=lambda item: (-len(item[1]), item[0]))
        ],
        "indirect_r0": {
            "all_calls": [f"0x{ROM_BASE + call:08X}" for call in indirect_r0_calls],
            "known_fce2d8_calls": [f"0x{ROM_BASE + call:08X}" for call in sorted(FCE2D8_DRAW_CALLS)],
            "remaining_owner_calls": [f"0x{ROM_BASE + call:08X}" for call in unresolved_indirect_r0],
            "remaining_owner_count": len(unresolved_indirect_r0),
        },
        "special_calls": [
            next(record for record in records if record["call_offset"] == f"0x{call:08X}")
            for call in special_calls
        ],
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
