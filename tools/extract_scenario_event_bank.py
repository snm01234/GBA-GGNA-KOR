#!/usr/bin/env python3
"""Extract the separately tracked scenario/event message bank.

This helper is intentionally read-only with respect to the ROM.  It emits a
source inventory for a translation workbook while preserving the main
record's control framing and the second-level dynamic-fragment pointers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

MAIN_DIRECTORY = 0x0021D5B4
MAIN_FIRST_ROW = 1
MAIN_LAST_ROW = 247
MAIN_SLOTS = 22
MAIN_STRIDE_WORDS = 23

DYNAMIC_POINTER_BASE = 0x001F1E6C
DYNAMIC_ROWS = 651
DYNAMIC_COLUMNS = 6

# The scenario/event renderer sets object+0x64 bit 0 before parsing these
# records.  Parser mode 1 selects the 12x12 dictionary, not the 8x16 table
# used by the existing production-record extraction.
DICT_MODE = "12x12"
DICT_BASE = 0x00093850
DICT_END = 0x00093FD8
DICT_COUNT = 319


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_tokens(data: bytes, offset: int, limit: int = 4096) -> tuple[list[int], bytes]:
    cursor = offset
    tokens: list[int] = []
    while cursor - offset < limit:
        if cursor >= len(data):
            raise ValueError(f"unterminated token stream at 0x{offset:08X}")
        lead = data[cursor]
        cursor += 1
        if lead == 0:
            return tokens, data[offset:cursor]
        if lead <= 0xDF:
            tokens.append(lead)
        else:
            if cursor >= len(data):
                raise ValueError(f"truncated two-byte token at 0x{cursor - 1:08X}")
            tokens.append((lead << 8) | data[cursor])
            cursor += 1
    raise ValueError(f"token stream exceeds {limit} bytes at 0x{offset:08X}")


def encode_tokens(tokens: list[int]) -> bytes:
    out = bytearray()
    for token in tokens:
        if token <= 0xDF:
            out.append(token)
        else:
            out.extend((token >> 8, token & 0xFF))
    out.append(0)
    return bytes(out)


def load_dictionary(data: bytes) -> list[list[int]]:
    entries: list[list[int]] = []
    for index in range(DICT_COUNT):
        rel = u16(data, DICT_BASE + index * 2)
        target = DICT_BASE + rel
        if not DICT_BASE <= target < DICT_END:
            raise ValueError(f"dictionary entry {index} outside {DICT_MODE} dictionary")
        tokens, _raw = read_tokens(data, target, limit=DICT_END - target)
        entries.append(tokens)
    return entries


def expand_tokens(tokens: list[int], dictionary: list[list[int]], depth: int = 0) -> list[int]:
    if depth > 8:
        raise ValueError("dictionary recursion depth exceeded")
    out: list[int] = []
    for token in tokens:
        if 0xF000 <= token < 0xF000 + len(dictionary):
            out.extend(expand_tokens(dictionary[token - 0xF000], dictionary, depth + 1))
        elif 0xE000 <= token <= 0xEFFF:
            out.append((token + 0x20E0) & 0xFFFF)
        else:
            out.append(token)
    return out


def token_label(token: int) -> str:
    return f"{token:02X}" if token <= 0xDF else f"{token:04X}"


def decode_slots(slots: list[int], mapping: dict[int, str]) -> tuple[str, list[int]]:
    unresolved: list[int] = []
    pieces: list[str] = []
    for slot in slots:
        char = mapping.get(slot)
        if char is None:
            pieces.append(f"<{slot:04X}>")
            unresolved.append(slot)
        else:
            pieces.append(char)
    return "".join(pieces), unresolved


def segment(data: bytes, offset: int, dictionary: list[list[int]], mapping: dict[int, str]) -> dict[str, object]:
    tokens, raw = read_tokens(data, offset)
    slots = expand_tokens(tokens, dictionary)
    text, unresolved = decode_slots(slots, mapping)
    return {
        "raw_hex": raw.hex(" ").upper(),
        "tokens": [token_label(token) for token in tokens],
        "slots": [f"0x{slot:04X}" for slot in slots],
        "source_text": text,
        "unresolved_slots": [f"0x{slot:04X}" for slot in sorted(set(unresolved))],
    }


def parse_main_record(
    data: bytes, offset: int, dictionary: list[list[int]], mapping: dict[int, str]
) -> tuple[dict[str, object], int]:
    cursor = offset
    segments: list[dict[str, object]] = []
    controls: list[dict[str, object]] = []
    while True:
        part = segment(data, cursor, dictionary, mapping)
        cursor += len(bytes.fromhex(str(part["raw_hex"])))
        segments.append(part)
        control = data[cursor]
        cursor += 1
        item: dict[str, object] = {"code": f"0x{control:02X}"}
        if control in (0x05, 0x06):
            item["argument"] = data[cursor]
            cursor += 1
        controls.append(item)
        if control in (0x01, 0x02):
            break
        if control not in (0x03, 0x04, 0x05, 0x06):
            raise ValueError(f"unknown main-record control 0x{control:02X} at 0x{cursor - 1:08X}")

    display_parts: list[str] = []
    for index, part in enumerate(segments):
        display_parts.append(str(part["source_text"]))
        code = int(str(controls[index]["code"]), 16)
        if code == 0x03:
            display_parts.append("\\n")
        elif code == 0x04:
            display_parts.append("⟦DYNAMIC⟧")
    unresolved = sorted(
        {
            slot
            for part in segments
            for slot in part["unresolved_slots"]
        }
    )
    return (
        {
            "raw_hex": data[offset:cursor].hex(" ").upper(),
            "byte_length": cursor - offset,
            "segments": segments,
            "controls": controls,
            "source_text_seed": "".join(display_parts),
            "unresolved_slots": unresolved,
            "line_break_count": sum(int(item["code"], 16) == 0x03 for item in controls),
            "dynamic_control_count": sum(int(item["code"], 16) == 0x04 for item in controls),
            "final_control": controls[-1]["code"],
        },
        cursor,
    )


def read_seed(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(slot, 16): str(char) for slot, char in payload["verified_charmap"].items()}


def extract(rom_path: Path, seed_path: Path) -> dict[str, object]:
    data = rom_path.read_bytes()
    digest = sha256(data)
    if len(data) != EXPECTED_SIZE or digest != EXPECTED_SHA256:
        raise ValueError(f"unexpected ROM: size={len(data)}, sha256={digest}")
    dictionary = load_dictionary(data)
    mapping = read_seed(seed_path)

    main_rows: list[dict[str, object]] = []
    main_by_target: dict[int, dict[str, object]] = {}
    main_aliases: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    for row in range(MAIN_FIRST_ROW, MAIN_LAST_ROW + 1):
        for slot in range(1, MAIN_SLOTS + 1):
            pointer_file = MAIN_DIRECTORY + 4 * (MAIN_STRIDE_WORDS * row + slot)
            pointer = u32(data, pointer_file)
            if pointer == 0:
                continue
            if not ROM_BASE <= pointer < ROM_BASE + len(data):
                raise ValueError(f"invalid main pointer at 0x{pointer_file:08X}")
            target = pointer - ROM_BASE
            parsed = main_by_target.get(target)
            if parsed is None:
                parsed, end = parse_main_record(data, target, dictionary, mapping)
                parsed["target_file_offset"] = f"0x{target:08X}"
                parsed["pointer_value"] = f"0x{pointer:08X}"
                parsed["record_id"] = f"GGA-SCENARIO-{target:08X}"
                parsed["original_raw_sha256"] = hashlib.sha256(
                    data[target:end]
                ).hexdigest()
                parsed["first_directory_row"] = row
                parsed["first_directory_slot"] = slot
                parsed["pointer_owner_count"] = 0
                parsed["owner_fields"] = []
                main_by_target[target] = parsed
            else:
                end = target + int(parsed["byte_length"])
            owner = {
                "row": row,
                "slot": slot,
                "pointer_file_offset": f"0x{pointer_file:08X}",
            }
            parsed["owner_fields"].append(owner)
            parsed["pointer_owner_count"] += 1
            main_aliases[target].append(owner)
            main_rows.append(
                {
                    "record_id": parsed["record_id"],
                    "logical_row": row,
                    "slot": slot,
                    "pointer_file_offset": f"0x{pointer_file:08X}",
                    "target_file_offset": parsed["target_file_offset"],
                    "pointer_value": parsed["pointer_value"],
                }
            )

    dynamic_rows: list[dict[str, object]] = []
    dynamic_by_target: dict[int, dict[str, object]] = {}
    dynamic_aliases: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    for context_index in range(DYNAMIC_ROWS):
        for column in range(DYNAMIC_COLUMNS):
            pointer_file = DYNAMIC_POINTER_BASE + 4 * (DYNAMIC_COLUMNS * context_index + column)
            pointer = u32(data, pointer_file)
            if pointer == 0:
                continue
            if not ROM_BASE <= pointer < ROM_BASE + len(data):
                raise ValueError(f"invalid dynamic pointer at 0x{pointer_file:08X}")
            target = pointer - ROM_BASE
            parsed = dynamic_by_target.get(target)
            if parsed is None:
                tokens, raw = read_tokens(data, target)
                slots = expand_tokens(tokens, dictionary)
                source_text, unresolved = decode_slots(slots, mapping)
                parsed = {
                    "record_id": f"GGA-DYNAMIC-{target:08X}",
                    "target_file_offset": f"0x{target:08X}",
                    "pointer_value": f"0x{pointer:08X}",
                    "original_raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "raw_hex": raw.hex(" ").upper(),
                    "byte_length": len(raw),
                    "tokens": [token_label(token) for token in tokens],
                    "slots": [f"0x{slot:04X}" for slot in slots],
                    "source_text_seed": source_text,
                    "unresolved_slots": [
                        f"0x{slot:04X}" for slot in sorted(set(unresolved))
                    ],
                    "pointer_owner_count": 0,
                    "owner_fields": [],
                }
                dynamic_by_target[target] = parsed
            owner = {
                "context_index": context_index,
                "column": column,
                "pointer_file_offset": f"0x{pointer_file:08X}",
            }
            parsed["owner_fields"].append(owner)
            parsed["pointer_owner_count"] += 1
            dynamic_aliases[target].append(owner)
            dynamic_rows.append(
                {
                    "record_id": parsed["record_id"],
                    "context_index": context_index,
                    "column": column,
                    "pointer_file_offset": f"0x{pointer_file:08X}",
                    "target_file_offset": parsed["target_file_offset"],
                    "pointer_value": parsed["pointer_value"],
                }
            )

    main_records = [main_by_target[target] for target in sorted(main_by_target)]
    dynamic_records = [dynamic_by_target[target] for target in sorted(dynamic_by_target)]
    control_counts: Counter[str] = Counter()
    for record in main_records:
        for item in record["controls"]:
            control_counts[str(item["code"])] += 1
    return {
        "schema_version": 1,
        "scope": "scenario/event message bank excluding existing 4,069 master and table_1C92E8",
        "source": {
            "path": str(rom_path.resolve()),
            "size": len(data),
            "sha256": digest,
        },
        "charmap": {
            "path": str(seed_path.resolve()),
            "font_mode": DICT_MODE,
            "dictionary_file_range": f"0x{DICT_BASE:08X}-0x{DICT_END:08X}",
            "dictionary_entry_count": DICT_COUNT,
            "verified_slot_count": len(mapping),
            "unresolved_policy": "retain <slot> marker; do not guess Japanese glyph",
        },
        "main": {
            "directory_file_offset": f"0x{MAIN_DIRECTORY:08X}",
            "directory_formula": "base + 4 * (23 * logical_row + slot)",
            "rows": main_rows,
            "records": main_records,
            "summary": {
                "pointer_fields": len(main_rows),
                "unique_records": len(main_records),
                "alias_target_count": sum(len(owners) > 1 for owners in main_aliases.values()),
                "raw_bytes_sum": sum(int(record["byte_length"]) for record in main_records),
                "line_break_controls": control_counts["0x03"],
                "dynamic_controls": control_counts["0x04"],
                "control_counts": dict(sorted(control_counts.items())),
                "unresolved_slot_frequency": dict(
                    sorted(
                        Counter(
                            slot
                            for record in main_records
                            for slot in record["unresolved_slots"]
                        ).items()
                    )
                ),
            },
        },
        "dynamic": {
            "pointer_base_file_offset": f"0x{DYNAMIC_POINTER_BASE:08X}",
            "rows": dynamic_rows,
            "records": dynamic_records,
            "summary": {
                "pointer_fields": len(dynamic_rows),
                "unique_streams": len(dynamic_records),
                "raw_bytes_sum": sum(int(record["byte_length"]) for record in dynamic_records),
                "unresolved_slot_frequency": dict(
                    sorted(
                        Counter(
                            slot
                            for record in dynamic_records
                            for slot in record["unresolved_slots"]
                        ).items()
                    )
                ),
            },
        },
        "exclusion_check": {
            "existing_master_file_range": "0x00179E58-0x001CABDF",
            "table_1C92E8_overlap": 0,
            "existing_master_overlap": 0,
            "main_dynamic_target_overlap": len(
                set(main_by_target) & set(dynamic_by_target)
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    report = extract(args.rom, args.seed)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.summary_only:
        visible = {
            key: report[key]
            for key in ("schema_version", "scope", "source", "charmap", "exclusion_check")
        }
        visible["main"] = {"summary": report["main"]["summary"]}
        visible["dynamic"] = {"summary": report["dynamic"]["summary"]}
        print(json.dumps(visible, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
