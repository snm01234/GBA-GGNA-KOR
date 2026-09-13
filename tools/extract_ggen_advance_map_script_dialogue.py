#!/usr/bin/env python3
"""Extract inline 12x12 map-event dialogue from G Generation Advance scripts.

Map cutscene lines are not in the 0x0021D5B4 scenario directory.  They sit
inside event bytecode as opcode 0x18 followed by one or more NUL-terminated
token streams.  The common setup is:

    17 E6 08 <speaker> 00    set speaker / portrait
    17 34 18 <line> 00 ...   open box, then inline 12x12 text
    17 10 18 ...             same print with a different box setup

A line break inside one box is another token stream after 00.  A new box
for the same speaker is 00 18 without a fresh 17 34.  Some same-speaker
boxes insert a one-byte 0x01 wait before the next 0x18 (00 01 18), as in
the Strike OS "Armor Schneider" box.  Flow commands at a line boundary
are 17 xx and 08 xx 00/80; 08 11 09 is the glyphs 「G」.

Does not rewrite the immutable unified source or the ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ADVANCE_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402
from ggen_advance_text_codec import (  # noqa: E402
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
    token_label,
)

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
BANK_START = 0x00F00000
BANK_END = 0x00FC0000
PRINT_SETUP = {0x34, 0x10, 0x1C, 0x1D, 0xEE, 0x35, 0x03, 0x11, 0xDD}
SPEAKER_LOOKBACK = 48


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hex32(value: int) -> str:
    return f"0x{value:08X}"


def hex16(value: int) -> str:
    return f"0x{value:04X}"


def decode_slots(slots: list[int], mapping: dict[int, str]) -> tuple[str, list[int]]:
    pieces: list[str] = []
    unresolved: list[int] = []
    for slot in slots:
        char = mapping.get(slot)
        if char is None:
            pieces.append(f"<{slot:04X}>")
            unresolved.append(slot)
        else:
            pieces.append(char)
    return "".join(pieces), unresolved


def is_command_boundary(data: bytes, cursor: int) -> bool:
    if cursor >= len(data):
        return True
    lead = data[cursor]
    # A wait before a new print is bytecode, not the space/Z glyph pair.
    if data[cursor:cursor + 2] == b"\x01\x18":
        return True
    if lead == 0x17:
        return True
    if lead == 0x08 and cursor + 2 < len(data):
        third = data[cursor + 2]
        if third in (0x00, 0x80):
            return True
    return False


def recent_speaker(data: bytes, print_at: int) -> int | None:
    start = max(BANK_START, print_at - SPEAKER_LOOKBACK)
    window = data[start:print_at]
    needle = bytes((0x17, 0xE6, 0x08))
    last = window.rfind(needle)
    if last < 0 or last + 5 > len(window):
        return None
    speaker = window[last + 3]
    if window[last + 4] != 0:
        return None
    return speaker


def parse_print(
    data: bytes,
    opcode_18: int,
    dictionary: list[list[int]],
    mapping: dict[int, str],
) -> tuple[dict[str, Any], int]:
    if data[opcode_18] != 0x18:
        raise ValueError(f"print does not start with 0x18 at 0x{opcode_18:08X}")
    cursor = opcode_18 + 1
    segments: list[dict[str, Any]] = []
    while cursor < BANK_END:
        if is_command_boundary(data, cursor) or data[cursor] == 0x18:
            break
        tokens, raw = read_tokens(data, cursor, limit=512)
        if not tokens:
            cursor += len(raw)
            break
        slots = expand_to_slots(tokens, dictionary)
        text, unresolved = decode_slots(slots, mapping)
        segments.append(
            {
                "segment_index": len(segments),
                "raw_hex": raw.hex(" ").upper(),
                "tokens": [token_label(token) for token in tokens],
                "slots": [hex16(slot) for slot in slots],
                "source_text": text,
                "unresolved_slots": [hex16(slot) for slot in sorted(set(unresolved))],
                "is_text_segment": True,
            }
        )
        cursor += len(raw)
        if cursor >= BANK_END:
            break
        if is_command_boundary(data, cursor) or data[cursor] == 0x18:
            break
    if not segments:
        raise ValueError(f"empty map-script print at 0x{opcode_18:08X}")
    raw_span = data[opcode_18 + 1 : cursor]
    unresolved = sorted(
        {
            int(slot, 16)
            for part in segments
            for slot in part["unresolved_slots"]
        }
    )
    display = "\\n".join(str(part["source_text"]) for part in segments)
    return (
        {
            "opcode_18_file_offset": hex32(opcode_18),
            "target_file_offset": hex32(opcode_18 + 1),
            "target_address": hex32(ROM_BASE + opcode_18 + 1),
            "byte_length": len(raw_span),
            "raw_hex": raw_span.hex(" ").upper(),
            "original_raw_sha256": sha256_bytes(raw_span),
            "segments": segments,
            "source_text_seed": display,
            "unresolved_slots": [hex16(slot) for slot in unresolved],
            "line_count": len(segments),
        },
        cursor,
    )


def find_setup_prints(data: bytes) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    cursor = BANK_START
    end = min(BANK_END, len(data)) - 2
    while cursor < end:
        if data[cursor] == 0x17 and data[cursor + 1] in PRINT_SETUP and data[cursor + 2] == 0x18:
            found.append((cursor + 2, data[cursor + 1]))
            cursor += 3
            continue
        if data[cursor] == 0x17 and data[cursor + 1] in PRINT_SETUP and data[cursor + 2:cursor + 4] == b"\x01\x18":
            found.append((cursor + 3, data[cursor + 1]))
            cursor += 4
            continue
        cursor += 1
    return found


def extract(rom_path: Path, charmap_path: Path) -> dict[str, Any]:
    data = rom_path.read_bytes()
    digest = sha256_bytes(data)
    if len(data) != EXPECTED_SIZE or digest != EXPECTED_SHA256:
        raise ValueError(f"unexpected ROM: size={len(data)}, sha256={digest}")
    mapping = load_map(charmap_path)
    mapping.update(CORRECTED_LOW_KANA)
    dictionary = load_dictionary(data, DICT_12X12_BASE, DICT_12X12_END)

    records: list[dict[str, Any]] = []
    seen_18: set[int] = set()
    setup_counts: Counter[str] = Counter()
    chained = 0
    skipped_empty = 0

    def emit(opcode_18: int, setup: int, chained_flag: bool) -> int:
        nonlocal chained, skipped_empty
        if opcode_18 in seen_18:
            return opcode_18 + 1
        parsed, cursor = parse_print(data, opcode_18, dictionary, mapping)
        seen_18.add(opcode_18)
        speaker = recent_speaker(data, opcode_18)
        record_id = f"GGA-MAPSCRIPT-{opcode_18 + 1:08X}"
        parsed.update(
            {
                "record_id": record_id,
                "print_setup": hex16(setup) if setup else "",
                "chained_box": chained_flag,
                "speaker_id": hex16(speaker) if speaker is not None else "",
                "owner_fields": [
                    {
                        "kind": "inline_print_18",
                        "opcode_file_offset": hex32(opcode_18),
                        "pointer_file_offset": hex32(opcode_18),
                    }
                ],
            }
        )
        records.append(parsed)
        setup_counts[parsed["print_setup"] or "continuation"] += 1
        if chained_flag:
            chained += 1
        return cursor

    for opcode_18, setup in find_setup_prints(data):
        try:
            cursor = emit(opcode_18, setup, False)
        except ValueError:
            skipped_empty += 1
            continue
        while cursor < BANK_END:
            # End-of-box pause followed by wait/print (Jaburo air raid).
            if data[cursor:cursor + 4] == b"\x06\x00\x01\x18":
                cursor += 3
            if cursor + 1 < BANK_END and data[cursor] == 0x00 and data[cursor + 1] == 0x18:
                cursor += 1
            elif cursor + 1 < BANK_END and data[cursor] == 0x01 and data[cursor + 1] == 0x18:
                cursor += 1
            if cursor < BANK_END and data[cursor] == 0x18:
                try:
                    cursor = emit(cursor, 0, True)
                except ValueError:
                    skipped_empty += 1
                    break
                continue
            break

    records.sort(key=lambda row: int(row["target_file_offset"], 16))
    unresolved_freq: Counter[str] = Counter()
    complete = 0
    for row in records:
        slots = row["unresolved_slots"]
        if not slots:
            complete += 1
        unresolved_freq.update(slots)

    needles = {
        "nani_tekikan": "なにっ！\\n敵艦が接近中だと！？",
        "nasuka": "ナスカ",
        "ramiasu_renraku": "ラミアス大尉に連",
        "g_hannyu": "「G」",
    }
    needle_hits = {
        name: sum(1 for row in records if token in str(row["source_text_seed"]))
        for name, token in needles.items()
    }

    return {
        "schema_version": 1,
        "scope": "map/event bytecode inline 12x12 dialogue",
        "source": {
            "path": str(rom_path),
            "size": len(data),
            "sha256": digest,
        },
        "bank": {
            "file_range": f"{hex32(BANK_START)}-{hex32(BANK_END)}",
            "print_opcode": "0x18",
            "setup_opcodes": [
                "0x17 0x34 0x18",
                "0x17 0x10 0x18",
                "0x17 0x1C 0x18",
                "0x17 0x1D 0x18",
                "0x17 0xEE 0x18",
                "0x17 0x35 0x18",
                "0x17 0x03 0x18",
            ],
            "speaker_opcode": "0x17 0xE6 0x08 id 0x00",
        },
        "charmap": {
            "path": str(charmap_path).replace("\\", "/"),
            "font_mode": "12x12",
            "slot_count": len(mapping),
        },
        "summary": {
            "records": len(records),
            "unique_targets": len({row["target_file_offset"] for row in records}),
            "complete_decode": complete,
            "partial_decode": len(records) - complete,
            "chained_boxes": chained,
            "skipped_empty": skipped_empty,
            "setup_counts": dict(setup_counts),
            "unique_unresolved_slots": len(unresolved_freq),
            "screenshot_needles": needle_hits,
            "top_unresolved_slots": unresolved_freq.most_common(24),
        },
        "records": records,
    }


def leftover_frames(payload: dict[str, Any]) -> dict[str, Any]:
    freq: Counter[str] = Counter()
    frames: dict[str, Counter[str]] = defaultdict(Counter)
    samples: dict[str, list[str]] = defaultdict(list)
    for row in payload["records"]:
        for part in row.get("segments") or []:
            text = str(part.get("source_text") or "")
            for slot in part.get("unresolved_slots") or []:
                freq[slot] += 1
                frames[slot][text] += 1
                if len(samples[slot]) < 8 and text not in samples[slot]:
                    samples[slot].append(text)
    leftover1 = sorted(
        (
            {
                "slot": slot,
                "hits": freq[slot],
                "unique_frames": len(frames[slot]),
                "top_frames": frames[slot].most_common(6),
                "samples": samples[slot],
            }
            for slot, count in freq.items()
            if len(frames[slot]) <= 4
        ),
        key=lambda item: (-item["hits"], item["slot"]),
    )
    return {
        "unique_slots": len(freq),
        "leftover_small_frame_slots": len(leftover1),
        "candidates": leftover1[:80],
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rom",
        type=Path,
        default=ADVANCE_DIR / "SD Gundam GGeneration Advance (Japan).gba",
    )
    parser.add_argument(
        "--charmap",
        type=Path,
        default=ADVANCE_DIR / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ADVANCE_DIR / "legacy" / "analysis" / "ggen_advance_map_script_translation_source_20260828.json",
    )
    args = parser.parse_args(argv)
    payload = extract(args.rom, args.charmap)
    payload["leftover"] = leftover_frames(payload)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "output": str(args.out),
                **payload["summary"],
                "leftover_unique_slots": payload["leftover"]["unique_slots"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
