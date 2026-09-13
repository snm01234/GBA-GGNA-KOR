#!/usr/bin/env python3
"""Prove that the FCDF78 modulo-13 owner is the per-unit AI-type table."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DICT_8X16 = 0x000A42A8


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def thumb_bl_target(data: bytes, offset: int) -> int | None:
    hi = u16(data, offset)
    lo = u16(data, offset + 2)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    disp = ((hi & 0x07FF) << 12) | ((lo & 0x07FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return ROM_BASE + offset + 4 + disp


def parse_tokens(data: bytes, offset: int) -> list[int]:
    out: list[int] = []
    while True:
        lead = data[offset]
        offset += 1
        if lead == 0:
            return out
        if lead < 0xE0:
            out.append(lead)
        else:
            out.append((lead << 8) | data[offset])
            offset += 1


def expand_dictionary(data: bytes, tokens: list[int]) -> list[int]:
    out: list[int] = []
    for token in tokens:
        if 0xF000 <= token <= 0xF13E:
            index = token - 0xF000
            relative = u16(data, DICT_8X16 + index * 2)
            out.extend(expand_dictionary(data, parse_tokens(data, DICT_8X16 + relative)))
        else:
            out.append(token)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    # 18-item parent menu jump table: index 9 is the FCDF78 editor.
    check(u32(data, 0x0005F3E0) == 0x0805F5C8, "parent menu index-9 dispatch drift")
    check(thumb_bl_target(data, 0x0005F5CA) == 0x08060410, "index-9 -> AI editor call drift")

    # The corresponding menu label is drawn as the 10th left-column item.
    check(thumb_bl_target(data, 0x0005F1E8) == 0x08000CA0, "parent menu label draw drift")
    check(u32(data, 0x0005F2B4) == 0x081BECF2, "index-9 label pointer drift")
    label_tokens = parse_tokens(data, 0x001BECF2)
    expanded_label = expand_dictionary(data, label_tokens)
    expected = [0x03, 0xE00A, 0x6C, 0x54, 0x80, 0x4F, 0xE44D, 0xE1D8, 0x28, 0x4B]
    check(expanded_label == expected, f"AI menu label token drift: {[hex(x) for x in expanded_label]}")

    # FCDF78 owner and modulo-13 update path.
    values = [u32(data, 0x00FCDF78 + index * 4) for index in range(13)]
    check(all(ROM_BASE <= value < ROM_BASE + len(data) for value in values), "FCDF78 pointer domain drift")
    check(len(set(values)) == 13, "FCDF78 unique-target count drift")
    check(u32(data, 0x00060404) == 0x08FCDF78, "FCDF78 table literal drift")
    check(thumb_bl_target(data, 0x00060396) == 0x080051EC, "AI editor unit-name accessor drift")
    check(thumb_bl_target(data, 0x000603CA) == 0x08000CA0, "AI type label draw drift")
    check(thumb_bl_target(data, 0x000604E6) == 0x08085130, "AI type modulo helper drift")
    check(u16(data, 0x000604E2) == 0x3001 and u16(data, 0x000604E4) == 0x210D, "AI type +1/mod13 argument drift")
    check(u16(data, 0x000604EA) == 0x7020, "AI type state write drift")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "family": "FCDF78_prefix13",
        "semantic_category": "unit_ai_type",
        "semantic_review_status": "reviewed",
        "confidence": "high",
        "records": 13,
        "menu": {
            "parent_dispatch_index": 9,
            "label_pointer": "0x081BECF2",
            "label_reading": "AIタイプを変更する",
            "expanded_literal_tokens": [f"0x{token:04X}" for token in expanded_label],
            "editor": "0x08060410",
            "renderer": "0x08060340"
        },
        "runtime_contract": {
            "left_column": "unit name via 0x080051EC",
            "right_column": "FCDF78[RAM unit record +0x25]",
            "edit": "left/right input updates RAM record +0x25 modulo 13"
        },
        "conclusion": "FCDF78 is the 13-entry per-unit AI-type name table used by the parent menu item AIタイプを変更する."
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
