#!/usr/bin/env python3
"""Close the stage victory/defeat-condition text producers in GGen Advance.

This advance-local analyzer proves three related structures:
1) the 64x0x20 search/stage record DB at 0x08D55888,
2) its parallel 64-field condition-body table at 0x08FCE1A0 (38 unique),
3) the length-prefixed two-line victory/defeat blocks selected by 0x08012408,
   including 38 record fallbacks and 18 flag-gated override blocks.
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

SEARCH_DB = 0x00D55888
SEARCH_STRIDE = 0x20
SEARCH_RECORDS = 64
PARALLEL_TABLE = 0x00FCE1A0
PAIR_FIELD = 0x14

OVERRIDE_LITERAL_OFFSETS = [
    0x0001249C, 0x000124B4, 0x000124CC, 0x000124E4, 0x000124FC,
    0x00012514, 0x0001252C, 0x00012540, 0x00012554, 0x00012568,
    0x0001257C, 0x00012590, 0x000125A4, 0x000125B8, 0x000125CC,
    0x000125E0, 0x000125F4, 0x00012608,
]

# Raw encoded prefixes. F0D4 expands to two glyphs in the 8x16 dictionary, so
# both prefixes display as five characters. Advance-local font inspection gives
# 勝利条件： and 敗北条件： respectively.
VICTORY_PREFIX = bytes.fromhex("F0 D4 E3 14 E1 C4 E0 03")
DEFEAT_PREFIX = bytes.fromhex("E4 B1 E5 5C E3 14 E1 C4 E0 03")


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def thumb_bl_target(data: bytes, offset: int) -> int | None:
    high = u16(data, offset)
    low = u16(data, offset + 2)
    if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
        return None
    displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
    if displacement & (1 << 22):
        displacement -= 1 << 23
    return (ROM_BASE + offset + 4 + displacement) & 0xFFFFFFFF


def parse_nul_stream(data: bytes, pointer: int) -> tuple[list[int], int]:
    check(ROM_BASE <= pointer < ROM_BASE + len(data), f"non-ROM pointer 0x{pointer:08X}")
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
        check(offset + 1 < len(data), f"truncated token at 0x{offset:08X}")
        token = (lead << 8) | data[offset + 1]
        check(0xE000 <= token <= 0xE733 or 0xF000 <= token <= 0xF13E, f"bad token 0x{token:04X}")
        tokens.append(token)
        offset += 2
    raise SystemExit(f"gate failed: unterminated stream at 0x{start:08X}")


def parse_pair(data: bytes, pointer: int) -> dict[str, object]:
    check(ROM_BASE <= pointer < ROM_BASE + len(data), f"non-ROM pair pointer 0x{pointer:08X}")
    offset = pointer - ROM_BASE
    length1 = data[offset]
    start1 = offset + 1
    end1 = start1 + length1
    check(end1 < len(data) and data[end1] == 0, f"pair line1 NUL drift at 0x{pointer:08X}")
    length2_offset = end1 + 1
    length2 = data[length2_offset]
    start2 = length2_offset + 1
    end2 = start2 + length2
    check(end2 < len(data) and data[end2] == 0, f"pair line2 NUL drift at 0x{pointer:08X}")
    body1 = data[start1:end1]
    body2 = data[start2:end2]
    # Validate token boundaries by parsing the embedded NUL streams.
    tokens1, bytes1 = parse_nul_stream(data, ROM_BASE + start1)
    tokens2, bytes2 = parse_nul_stream(data, ROM_BASE + start2)
    check(bytes1 == length1 + 1 and bytes2 == length2 + 1, f"length-prefix/token drift at 0x{pointer:08X}")
    return {
        "pair_address": f"0x{pointer:08X}",
        "line1_address": f"0x{ROM_BASE + start1:08X}",
        "line2_address": f"0x{ROM_BASE + start2:08X}",
        "line1_length": length1,
        "line2_length": length2,
        "line1_tokens": [f"0x{x:04X}" if x > 0xFF else f"0x{x:02X}" for x in tokens1],
        "line2_tokens": [f"0x{x:04X}" if x > 0xFF else f"0x{x:02X}" for x in tokens2],
        "victory_prefix_match": body1.startswith(VICTORY_PREFIX),
        "defeat_prefix_match": body2.startswith(DEFEAT_PREFIX),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    # 64 live 0x20-byte search records followed by an all-zero terminator record.
    for index in range(SEARCH_RECORDS):
        check(u32(data, SEARCH_DB + index * SEARCH_STRIDE + 4) != 0, f"search record {index} unexpectedly dead")
    check(data[SEARCH_DB + SEARCH_RECORDS * SEARCH_STRIDE:SEARCH_DB + (SEARCH_RECORDS + 1) * SEARCH_STRIDE] == b"\0" * SEARCH_STRIDE, "search terminator drift")

    search_keys = [data[SEARCH_DB + i * SEARCH_STRIDE] for i in range(SEARCH_RECORDS)]
    check(len(set(search_keys)) == SEARCH_RECORDS, "search-key uniqueness drift")
    key_to_index = {key: index for index, key in enumerate(search_keys)}

    # Parallel condition body table walks +4 while the keyed DB walks +0x20.
    parallel = [u32(data, PARALLEL_TABLE + i * 4) for i in range(SEARCH_RECORDS)]
    for pointer in parallel:
        parse_nul_stream(data, pointer)
    check(len(set(parallel)) == 38, f"parallel condition target count drift: {len(set(parallel))}")
    check(u32(data, 0x0006B170) == ROM_BASE + PARALLEL_TABLE, "parallel-table literal drift")
    check(thumb_bl_target(data, 0x0006AFD2) == 0x0806B148, "condition bridge call A drift")
    check(thumb_bl_target(data, 0x0006B3DE) == 0x0806B148, "condition bridge call B drift")
    check(thumb_bl_target(data, 0x0006AFE0) == 0x08000CA0, "condition body draw A drift")
    check(thumb_bl_target(data, 0x0006B3EC) == 0x08000CA0, "condition body draw B drift")

    # Path A derives the first condition key from search-record byte +1;
    # path B with zero argument uses byte +2.
    check(thumb_bl_target(data, 0x0006AF32) == 0x080100EC, "current search-record lookup A drift")
    check(thumb_bl_target(data, 0x0006AF36) == 0x0800FFF4, "condition-key +1 resolver drift")
    check(thumb_bl_target(data, 0x0006B330) == 0x080100EC, "current search-record lookup B drift")
    check(u16(data, 0x0006B338) == 0x7880, "search-record byte +2 load drift")

    # Stage 1 local invariant: key 1 maps condition keys +1=2 and +2=0x3D.
    check(search_keys[0] == 1 and data[SEARCH_DB + 1] == 2 and data[SEARCH_DB + 2] == 0x3D, "stage-1 condition-key tuple drift")
    check(key_to_index[2] == 1 and key_to_index[0x3D] == 36, "stage-1 condition target-key mapping drift")

    fallback_pointers = {u32(data, SEARCH_DB + i * SEARCH_STRIDE + PAIR_FIELD) for i in range(SEARCH_RECORDS)}
    check(len(fallback_pointers) == 38, f"fallback pair count drift: {len(fallback_pointers)}")
    fallback_pairs = [parse_pair(data, p) for p in sorted(fallback_pointers)]
    check(all(p["victory_prefix_match"] for p in fallback_pairs), "fallback victory-prefix drift")
    check(all(p["defeat_prefix_match"] for p in fallback_pairs), "fallback defeat-prefix drift")

    override_pointers = [u32(data, offset) for offset in OVERRIDE_LITERAL_OFFSETS]
    check(len(set(override_pointers)) == 18, "override pair uniqueness drift")
    check(not (set(override_pointers) & fallback_pointers), "override/fallback pair overlap drift")
    override_pairs = [parse_pair(data, p) for p in override_pointers]
    check(all(p["victory_prefix_match"] for p in override_pairs), "override victory-prefix drift")
    check(all(p["defeat_prefix_match"] for p in override_pairs), "override defeat-prefix drift")

    # 0x08012408 is the sole selector for the 18 override blobs and falls back
    # to current search-record +0x14. Its only caller then draws line1/line2.
    check(thumb_bl_target(data, 0x0001C72C) == 0x08012408, "pair selector caller drift")
    check(thumb_bl_target(data, 0x0001C746) == 0x08000CA0, "victory-line draw drift")
    check(thumb_bl_target(data, 0x0001C760) == 0x08000CA0, "defeat-line draw drift")
    check(u16(data, 0x0001260C) == 0x6960, "search-record +0x14 fallback load drift")

    override_line_targets = {
        int(pair["line1_address"], 16) for pair in override_pairs
    } | {
        int(pair["line2_address"], 16) for pair in override_pairs
    }
    check(len(override_line_targets) == 36, f"override line target count drift: {len(override_line_targets)}")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "semantic_classification": {
            "parallel_condition_table": {
                "category": "stage_battle_condition_text",
                "review_status": "reviewed",
                "confidence": "high",
                "unique_targets": 38,
            },
            "state_variant_pair": {
                "category": "stage_battle_condition_line",
                "review_status": "reviewed",
                "confidence": "high",
                "static_override_pairs": 18,
                "static_override_lines": 36,
            },
        },
        "search_record_db": {
            "offset": f"0x{SEARCH_DB:08X}",
            "address": f"0x{ROM_BASE + SEARCH_DB:08X}",
            "records": SEARCH_RECORDS,
            "stride": SEARCH_STRIDE,
            "unique_keys": len(set(search_keys)),
            "parallel_table_offset": f"0x{PARALLEL_TABLE:08X}",
            "parallel_pointer_fields": SEARCH_RECORDS,
            "parallel_unique_condition_targets": len(set(parallel)),
            "fallback_pair_unique_blobs": len(fallback_pointers),
        },
        "condition_key_contract": {
            "first_condition": "search-record byte +1, with 0x0800FFF4 dynamic remapping for special F0-F5 states",
            "second_condition": "search-record byte +2 on the zero-argument 0x0806B318 path",
            "bridge": "0x0806B148 searches the same keyed 0x20-byte record DB while advancing the parallel text table by +4",
        },
        "pair_format": {
            "layout": "[len1][victory NUL-stream][len2][defeat NUL-stream]",
            "victory_prefix_reading": "勝利条件：",
            "victory_prefix_raw_hex": VICTORY_PREFIX.hex(" ").upper(),
            "defeat_prefix_reading": "敗北条件：",
            "defeat_prefix_raw_hex": DEFEAT_PREFIX.hex(" ").upper(),
            "fallback_pairs": len(fallback_pairs),
            "fallback_prefix_pass": len(fallback_pairs),
            "override_pairs": len(override_pairs),
            "override_prefix_pass": len(override_pairs),
            "override_fallback_blob_intersection": 0,
        },
        "override_pointers": [f"0x{x:08X}" for x in override_pointers],
        "conclusion": "The search-record condition keys, the 38-target parallel table, and both lines of every fallback/override pair form the stage victory/defeat-condition domain. The 36 state_variant_pair static override lines can be promoted to reviewed semantic text, and the unresolved 38-target search parallel component is also a reviewed stage-condition family.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
