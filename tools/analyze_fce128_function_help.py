#!/usr/bin/env python3
"""Close FCE128 as the 11-function map/system callback help-text table."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def bl_target(data: bytes, offset: int) -> int | None:
    hi, lo = struct.unpack_from("<HH", data, offset)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    disp = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return ROM_BASE + offset + 4 + disp


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    args = ap.parse_args()
    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, "ROM size drift")
    check(digest == EXPECTED_SHA256, f"ROM hash drift: {digest}")

    # Shared code->index mapping. high nibble 0..2 x low nibble 0..2 => 0..8;
    # low==3 => 9; other low values => 10.
    check(u16(data, 0x00064D38) == 0xB500, "index normalizer entry drift")
    check(u16(data, 0x00064D46) == 0x2902, "low-nibble <=2 gate drift")
    check(u16(data, 0x00064D52) == 0x2009, "special index 9 drift")
    check(u16(data, 0x00064D54) == 0x2903, "low-nibble ==3 gate drift")
    check(u16(data, 0x00064D58) == 0x200A, "special index 10 drift")

    # Selector execution path: map code -> shared index -> callback registry[index] -> bx r0 trampoline.
    check(bl_target(data, 0x000643DE) == 0x08064D38, "selector normalizer call drift")
    check(u32(data, 0x000643F4) == 0x08D58D0C, "callback registry literal drift")
    check(bl_target(data, 0x000643EA) == 0x0808505C, "callback trampoline call drift")
    check(u16(data, 0x0008505C) == 0x4700, "0x0808505C is no longer bx r0")

    callbacks = [u32(data, 0x00D58D0C + i * 4) for i in range(11)]
    expected_callbacks = [
        0x0806B775, 0x0806B485, 0x0806B07D, 0x08066785, 0x0806D3BD,
        0x0806EDD1, 0x080708B9, 0x08078199, 0x080790F1, 0x080735F9, 0x08073609,
    ]
    check(callbacks == expected_callbacks, "11-function callback registry drift")

    # Help/description path uses the same index and optionally selects the second 11-slot variant.
    check(bl_target(data, 0x0006540E) == 0x08064D38, "help renderer normalizer call drift")
    check(u16(data, 0x0006541E) == 0x320B, "help renderer +11 variant drift")
    check(u32(data, 0x00065454) == 0x08FCE128, "FCE128 table literal drift")
    check(bl_target(data, 0x00065446) == 0x08000CA0, "FCE128 draw call drift")

    fields = [u32(data, 0x00FCE128 + i * 4) for i in range(22)]
    check(all(ROM_BASE <= p < ROM_BASE + len(data) for p in fields), "FCE128 pointer domain drift")
    check(len(set(fields)) == 16, "FCE128 unique target count drift")

    # The two final registry entries are the already-proven stage-condition callbacks, anchoring
    # this registry in the map/system UI domain.
    check(callbacks[9] == 0x080735F9 and callbacks[10] == 0x08073609, "condition callback anchor drift")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "family": "FCE128_11x2",
        "semantic_category": "map_system_function_help",
        "semantic_review_status": "reviewed",
        "confidence": "high",
        "physical_fields": 22,
        "unique_records": 16,
        "index_contract": {
            "indices_0_8": "3x3 high-nibble/low-nibble mapping",
            "index_9": "low nibble == 3",
            "index_10": "other low-nibble value",
            "variant": "renderer adds 11 when the per-index state byte selects the alternate help/status text"
        },
        "callback_registry": {
            "address": "0x08D58D0C",
            "entries": [f"0x{x:08X}" for x in callbacks],
            "stage_condition_anchor_indices": [9, 10]
        },
        "evidence": [
            "0x080643DE maps the selected code with 0x08064D38, then invokes 0x08D58D0C[index] through the bx-r0 trampoline 0x0808505C.",
            "0x0806540E uses the same 0x08064D38 index; 0x0806541E optionally adds 11 and 0x08065446 draws FCE128[index] at the help/status line.",
            "Callback registry indices 9 and 10 are the registered stage battle-condition callbacks 0x080735F8 and 0x08073608, fixing the registry in the map/system function domain."
        ],
        "conclusion": "FCE128 is the two-variant help/status text table aligned one-to-one with the 11 selectable map/system callback functions."
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
