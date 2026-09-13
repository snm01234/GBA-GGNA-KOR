#!/usr/bin/env python3
"""Close semantic provenance for FCE2D8 and FCE2A8 stage-condition UI tables."""
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


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def thumb_bl_target(data: bytes, offset: int) -> int | None:
    hi = u16(data, offset)
    lo = u16(data, offset + 2)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    disp = ((hi & 0x07FF) << 12) | ((lo & 0x07FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (ROM_BASE + offset + 4 + disp) & 0xFFFFFFFF


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def pointer_targets(data: bytes, offset: int, count: int) -> list[int]:
    out: list[int] = []
    for index in range(count):
        value = u32(data, offset + index * 4)
        if value:
            check(ROM_BASE <= value < ROM_BASE + len(data), f"non-ROM pointer at 0x{offset + index*4:08X}")
            out.append(value)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    # FCE2D8: flat 69-field paired condition-component table.
    fce2d8 = pointer_targets(data, 0x00FCE2D8, 69)
    check(len(fce2d8) == 69, "FCE2D8 field count drift")
    check(len(set(fce2d8)) == 68, "FCE2D8 unique-target count drift")
    check(fce2d8[60] == fce2d8[61] == 0x081BE9D7, "FCE2D8 duplicate-pair drift")

    # The only entry points into the common condition display are its two registered callbacks.
    check(u32(data, 0x00D58D30) == 0x080735F9, "mode0 callback registration drift")
    check(u32(data, 0x00D58D34) == 0x08073609, "mode1 callback registration drift")
    check(thumb_bl_target(data, 0x000735FC) == 0x08073634, "mode0 callback -> common UI drift")
    check(thumb_bl_target(data, 0x0007360C) == 0x08073634, "mode1 callback -> common UI drift")
    check(thumb_bl_target(data, 0x000736D2) == 0x08073A04, "common UI -> mode0 renderer drift")
    check(thumb_bl_target(data, 0x000736F6) == 0x08073D14, "common UI -> mode1 renderer drift")

    # Both renderers reuse the same condition-code normalizer and FCE2D8 table.
    normalizer_calls = [0x00073B00, 0x00073B16, 0x00073D9C, 0x00073E44, 0x00073E5A]
    for call in normalizer_calls:
        check(thumb_bl_target(data, call) == 0x08074088, f"condition normalizer call drift at 0x{call:08X}")
    for literal in (0x00073B70, 0x00073C40, 0x00073EB0, 0x00073F68):
        check(u32(data, literal) == 0x08FCE2D8, f"FCE2D8 literal drift at 0x{literal:08X}")
    for draw in (0x00073B54, 0x00073B68, 0x00073C20, 0x00073C34, 0x00073E94, 0x00073EA8, 0x00073F10, 0x00073F24):
        check(thumb_bl_target(data, draw) == DRAW_WRAPPER, f"FCE2D8 draw drift at 0x{draw:08X}")

    # FCE2A8: sparse condition-target/qualifier labels in the immediately preceding selector UI.
    fce2a8_fields = [u32(data, 0x00FCE2A8 + index * 4) for index in range(12)]
    check([index for index, value in enumerate(fce2a8_fields) if value == 0] == [2, 11], "FCE2A8 NULL-slot drift")
    fce2a8 = [value for value in fce2a8_fields if value]
    check(len(fce2a8) == 10 and len(set(fce2a8)) == 10, "FCE2A8 target count drift")
    check(set(fce2a8).isdisjoint(set(fce2d8)), "FCE2A8/FCE2D8 target overlap drift")

    # Selector helpers: one path draws a character DB name; companion path draws FCE2A8 labels.
    check(thumb_bl_target(data, 0x000733C0) == 0x0800755C, "condition selector character-id helper drift")
    check(thumb_bl_target(data, 0x000733F2) == 0x0800752C, "condition selector character-name accessor drift")
    check(thumb_bl_target(data, 0x00073402) == DRAW_WRAPPER, "condition selector character-name draw drift")
    check(thumb_bl_target(data, 0x000734DE) == DRAW_WRAPPER, "FCE2A8 selector draw drift")
    check(thumb_bl_target(data, 0x0007351E) == DRAW_WRAPPER, "FCE2A8 selector draw2 drift")
    check(thumb_bl_target(data, 0x00073576) == DRAW_WRAPPER, "FCE2A8 selector draw3 drift")
    check(thumb_bl_target(data, 0x000735CA) == DRAW_WRAPPER, "FCE2A8 selector draw4 drift")
    check(thumb_bl_target(data, 0x000735E2) == DRAW_WRAPPER, "FCE2A8 selector draw5 drift")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "semantic_closure": {
            "FCE2D8": {
                "records": 68,
                "category": "stage_battle_condition_component",
                "review_status": "reviewed",
                "confidence": "high",
                "reason": "The table is consumed only by the two registered stage-condition render modes; both normalize the same condition-code classes and draw adjacent component pairs."
            },
            "FCE2A8": {
                "records": 10,
                "category": "stage_battle_condition_target_label",
                "review_status": "reviewed",
                "confidence": "high",
                "reason": "The sparse table is consumed by the immediately preceding condition-target selector; its companion path draws character names from the character DB in the same selector UI."
            }
        },
        "counts": {
            "reviewed_records_promoted_from_partial": 78,
            "FCE2D8_unique_targets": len(set(fce2d8)),
            "FCE2A8_unique_targets": len(set(fce2a8)),
            "cross_table_target_overlap": 0
        },
        "runtime": {
            "registered_callbacks": ["0x080735F8", "0x08073608"],
            "common_ui": "0x08073634",
            "condition_renderers": ["0x08073A04", "0x08073D14"],
            "condition_code_normalizer": "0x08074088",
            "condition_target_selector_helpers": ["0x0807338C", "0x08073424"]
        }
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
