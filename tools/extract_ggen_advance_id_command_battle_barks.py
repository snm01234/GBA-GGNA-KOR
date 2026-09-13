#!/usr/bin/env python3
"""Extract the 256x3 12x12 ID-command battle-bark containers.

The live table is file 0x00226984 / GBA 0x08226984.  Slots 0..2 are NULL;
slots 3..767 point at a compact container consumed by 0x08018058.  Each
container is a sequence of strict NUL token streams separated by one-byte
continuation markers.  Marker 0x01 or 0x02 terminates the container; any other
marker is skipped and the next NUL stream is rendered.

This tool is read-only.  It records structural ownership, decoded 12x12 text,
and the corresponding character-db 8x16 ID-command A/B fields so the battle
family can be translated without guessing or rewriting its metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    expand_to_slots,
    load_dictionary,
    read_tokens_strict,
)

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
TABLE_BASE = 0x00226984
TABLE_SLOTS = 768
ENTRY_SIZE = 8
FIRST_LIVE = 3
LIVE_COUNT = 765
CHAR_DB = 0x001A476C
CHAR_STRIDE = 0x78
CHAR_PRIMARY_PTR = 0x04
COMMAND_STRIDE = 0x1C
COMMAND_A_PTR = 0x24
COMMAND_B_PTR = 0x2C
DEFAULT_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_MAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
DEFAULT_MAP8 = ADVANCE_ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
DEFAULT_MAP12_CORRECTIONS = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_id_command_battle_barks_20260829.json"


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def file_offset(address: int) -> int:
    gate(ROM_BASE <= address < ROM_BASE + EXPECTED_SIZE, f"pointer outside original ROM: 0x{address:08X}")
    return address - ROM_BASE


def load_slot_map(path: Path, corrections: Path | None = None) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = {
        int(str(slot), 16): str(char)
        for slot, char in payload.get("verified_charmap", {}).items()
        if isinstance(char, str) and char
    }
    if corrections is not None and corrections.exists():
        correction_payload = json.loads(corrections.read_text(encoding="utf-8"))
        for slot_text, row in correction_payload.get("corrections", {}).items():
            if isinstance(row, dict) and row.get("after"):
                result[int(str(slot_text), 16)] = str(row["after"])
    return result


def decode_tokens(tokens: list[int], dictionary: list[list[int]], slot_map: dict[int, str]) -> tuple[str, list[int]]:
    slots = expand_to_slots(tokens, dictionary)
    unresolved = sorted({slot for slot in slots if slot not in slot_map})
    text = "".join(slot_map.get(slot, f"<{slot:04X}>") for slot in slots)
    return text, unresolved


def read_decoded_stream(
    data: bytes,
    start: int,
    limit: int,
    dictionary: list[list[int]],
    slot_map: dict[int, str],
) -> dict[str, Any]:
    gate(start < limit, f"empty stream boundary at 0x{start:08X}")
    tokens, raw = read_tokens_strict(data, start, limit=limit - start)
    text, unresolved = decode_tokens(tokens, dictionary, slot_map)
    return {
        "start_file_offset": f"0x{start:08X}",
        "start_address": f"0x{ROM_BASE + start:08X}",
        "raw_hex": raw.hex(" ").upper(),
        "raw_byte_length": len(raw),
        "source_text": text,
        "source_decode_status": "complete" if not unresolved else "partial",
        "source_unresolved_slots": [f"0x{slot:04X}" for slot in unresolved],
    }


def parse_container(
    data: bytes,
    start: int,
    boundary: int,
    dictionary12: list[list[int]],
    map12: dict[int, str],
) -> dict[str, Any]:
    cursor = start
    streams: list[dict[str, Any]] = []
    separators: list[dict[str, Any]] = []
    terminal_marker: int | None = None
    while True:
        stream = read_decoded_stream(data, cursor, boundary, dictionary12, map12)
        stream["stream_index"] = len(streams)
        streams.append(stream)
        cursor += int(stream["raw_byte_length"])
        gate(cursor < boundary, f"container lacks terminal marker at 0x{start:08X}")
        marker_offset = cursor
        marker = data[cursor]
        cursor += 1
        separators.append(
            {
                "after_stream_index": len(streams) - 1,
                "marker_file_offset": f"0x{marker_offset:08X}",
                "marker": f"0x{marker:02X}",
                "role": "terminal" if marker in (0x01, 0x02) else "continuation",
            }
        )
        if marker in (0x01, 0x02):
            terminal_marker = marker
            break
        gate(cursor < boundary, f"continuation marker reaches boundary at 0x{marker_offset:08X}")
    tail = data[cursor:boundary]
    return {
        "container_start_file_offset": f"0x{start:08X}",
        "container_start_address": f"0x{ROM_BASE + start:08X}",
        "container_boundary_file_offset": f"0x{boundary:08X}",
        "container_consumed_end_file_offset": f"0x{cursor:08X}",
        "terminal_marker": f"0x{terminal_marker:02X}",
        "tail_padding_hex": tail.hex(" ").upper(),
        "streams": streams,
        "separators": separators,
    }


def canonical_rows_by_target(merged: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in merged.get("records", []):
        if row.get("scope_status") != "included":
            continue
        text = str(row.get("target_file_offset") or "")
        if not text:
            continue
        out[int(text, 16)] = row
    return out


def translated_exact_index(merged: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in merged.get("records", []):
        if row.get("scope_status") != "included" or row.get("translation_status") != "translated":
            continue
        record_id = str(row.get("record_id") or "")
        jp = str(row.get("source_text") or "")
        ko = str(row.get("translation_ko") or "")
        if jp and ko.strip():
            out[jp].append({"record_id": record_id, "translation_ko": ko, "match_kind": "record"})
        segments = row.get("segments") or []
        translations = row.get("translation_segments") or []
        if isinstance(segments, list) and isinstance(translations, list) and len(segments) == len(translations):
            for index, (segment, translated) in enumerate(zip(segments, translations)):
                if not isinstance(segment, dict):
                    continue
                segment_jp = str(segment.get("source_text") or "")
                segment_ko = str(translated or "")
                if segment_jp and segment_ko.strip():
                    out[segment_jp].append(
                        {
                            "record_id": record_id,
                            "translation_ko": segment_ko,
                            "match_kind": f"segment_{index}",
                        }
                    )
    return out


def command_reference(
    data: bytes,
    character_index: int,
    command_index: int,
    dictionary8: list[list[int]],
    map8: dict[int, str],
    by_target: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    record = CHAR_DB + character_index * CHAR_STRIDE
    primary_ptr_source = record + CHAR_PRIMARY_PTR
    primary_target = file_offset(u32(data, primary_ptr_source))
    primary = read_decoded_stream(data, primary_target, EXPECTED_SIZE, dictionary8, map8)
    primary_row = by_target.get(primary_target)

    refs: dict[str, Any] = {
        "character_record_file_offset": f"0x{record:08X}",
        "character_name": primary["source_text"],
        "character_name_ko": str(primary_row.get("translation_ko") or "") if primary_row else "",
        "character_primary_pointer_source": f"0x{primary_ptr_source:08X}",
    }
    for label, field in (("A", COMMAND_A_PTR), ("B", COMMAND_B_PTR)):
        source = record + command_index * COMMAND_STRIDE + field
        address = u32(data, source)
        if address == 0:
            refs[f"command_{label}"] = {
                "pointer_source_file_offset": f"0x{source:08X}",
                "target_file_offset": "",
                "source_text": "",
                "translation_ko": "",
                "translation_status": "missing",
                "record_id": "",
            }
            continue
        target = file_offset(address)
        decoded = read_decoded_stream(data, target, EXPECTED_SIZE, dictionary8, map8)
        row = by_target.get(target)
        refs[f"command_{label}"] = {
            "pointer_source_file_offset": f"0x{source:08X}",
            "target_file_offset": f"0x{target:08X}",
            "source_text": decoded["source_text"],
            "source_unresolved_slots": decoded["source_unresolved_slots"],
            "translation_ko": str(row.get("translation_ko") or "") if row else "",
            "translation_status": str(row.get("translation_status") or "") if row else "",
            "record_id": str(row.get("record_id") or "") if row else "",
        }
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--map12", type=Path, default=DEFAULT_MAP12)
    parser.add_argument("--map8", type=Path, default=DEFAULT_MAP8)
    parser.add_argument("--map12-corrections", type=Path, default=DEFAULT_MAP12_CORRECTIONS)
    parser.add_argument("--merged", type=Path, default=TRANSLATION_MERGED_JSON)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    gate(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    map12 = load_slot_map(args.map12, args.map12_corrections)
    map8 = load_slot_map(args.map8)
    dictionary12 = load_dictionary(data, DICT_12X12_BASE, DICT_12X12_END)
    dictionary8 = load_dictionary(data, DICT_8X16_BASE, DICT_8X16_END)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    by_target = canonical_rows_by_target(merged)
    exact_index = translated_exact_index(merged)

    pointers = [u32(data, TABLE_BASE + index * ENTRY_SIZE) for index in range(TABLE_SLOTS)]
    gate(pointers[:FIRST_LIVE] == [0, 0, 0], f"first three battle-bark pointers are not NULL: {pointers[:3]}")
    live_addresses = pointers[FIRST_LIVE:]
    gate(len(live_addresses) == LIVE_COUNT, "live battle-bark count drift")
    gate(all(ROM_BASE <= value < ROM_BASE + TABLE_BASE for value in live_addresses), "battle-bark pointer outside payload range")
    live_offsets = [value - ROM_BASE for value in live_addresses]
    gate(len(set(live_offsets)) == LIVE_COUNT, "battle-bark container pointers are not unique")
    gate(all(a < b for a, b in zip(live_offsets, live_offsets[1:])), "battle-bark container pointers are not strictly increasing")
    gate(live_offsets[-1] < TABLE_BASE, "last battle-bark container overlaps table")

    entries: list[dict[str, Any]] = []
    stream_count_dist: Counter[int] = Counter()
    marker_counts: Counter[str] = Counter()
    decode_counts: Counter[str] = Counter()
    exact_seed_instances = 0
    exact_seed_unique_jp: set[str] = set()
    nonempty_streams = 0
    empty_streams = 0
    all_stream_starts: set[int] = set()

    for logical_index in range(FIRST_LIVE, TABLE_SLOTS):
        character_index, command_index = divmod(logical_index, 3)
        table_source = TABLE_BASE + logical_index * ENTRY_SIZE
        start = live_offsets[logical_index - FIRST_LIVE]
        boundary = (
            live_offsets[logical_index - FIRST_LIVE + 1]
            if logical_index + 1 < TABLE_SLOTS
            else TABLE_BASE
        )
        container = parse_container(data, start, boundary, dictionary12, map12)
        refs = command_reference(data, character_index, command_index, dictionary8, map8, by_target)
        stream_count_dist[len(container["streams"])] += 1
        for sep in container["separators"]:
            marker_counts[sep["marker"]] += 1
        for stream in container["streams"]:
            stream_start = int(stream["start_file_offset"], 16)
            gate(stream_start not in all_stream_starts, f"duplicate visible stream start 0x{stream_start:08X}")
            all_stream_starts.add(stream_start)
            decode_counts[stream["source_decode_status"]] += 1
            if str(stream["source_text"]):
                nonempty_streams += 1
            else:
                empty_streams += 1
            candidates = exact_index.get(str(stream["source_text"]), []) if str(stream["source_text"]) else []
            unique_ko = sorted({item["translation_ko"] for item in candidates})
            stream["exact_translation_candidates"] = candidates
            stream["exact_translation_unique_ko"] = unique_ko
            stream["exact_translation_seedable"] = len(unique_ko) == 1
            if len(unique_ko) == 1:
                exact_seed_instances += 1
                exact_seed_unique_jp.add(str(stream["source_text"]))
        entries.append(
            {
                "logical_index": logical_index,
                "character_index": character_index,
                "command_index": command_index,
                "table_entry_file_offset": f"0x{table_source:08X}",
                "container_pointer": f"0x{ROM_BASE + start:08X}",
                "metadata_u32": f"0x{u32(data, table_source + 4):08X}",
                "character_command_reference": refs,
                **container,
            }
        )

    gate(len(entries) == LIVE_COUNT, f"extracted entry count drift: {len(entries)}")
    total_streams = sum(len(row["streams"]) for row in entries)
    gate(total_streams == len(all_stream_starts), "visible stream uniqueness count drift")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_id_command_battle_bark_extract",
        "source": {"file": args.rom.name, "size": len(data), "sha256": digest},
        "renderer_contract": {
            "table_file_offset": f"0x{TABLE_BASE:08X}",
            "table_address": f"0x{ROM_BASE + TABLE_BASE:08X}",
            "entry_size": ENTRY_SIZE,
            "physical_slots": TABLE_SLOTS,
            "null_slots": [0, 1, 2],
            "live_slots": "3..767",
            "live_count": LIVE_COUNT,
            "accessor": "0x0804FB2C",
            "draw_function": "0x08018058",
            "text_builder": "0x08000648",
            "continuation_loop": "0x08018100..0x0801811C",
            "container_rule": "render NUL stream; read one marker; marker 01/02 terminates, otherwise skip marker and render next NUL stream",
            "font_mode": "12x12",
        },
        "summary": {
            "entries": len(entries),
            "parser_streams": total_streams,
            "nonempty_text_streams": nonempty_streams,
            "empty_placeholder_streams": empty_streams,
            "unique_stream_starts": len(all_stream_starts),
            "stream_count_distribution": {str(key): value for key, value in sorted(stream_count_dist.items())},
            "marker_counts": dict(sorted(marker_counts.items())),
            "decode_status_counts": dict(sorted(decode_counts.items())),
            "exact_translation_seed_instances": exact_seed_instances,
            "exact_translation_seed_unique_jp": len(exact_seed_unique_jp),
            "first_container_file_offset": f"0x{live_offsets[0]:08X}",
            "last_container_file_offset": f"0x{live_offsets[-1]:08X}",
            "payload_boundary_file_offset": f"0x{TABLE_BASE:08X}",
        },
        "entries": entries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
