#!/usr/bin/env python3
"""Decode remaining Japanese dynamic BG text in user ss1..ss5 savestates.

The screenshots show several labels that are not fixed graphic resources.  This
analyzer reconstructs each 8x16 BG glyph from two live 8x8 cells, honors GBA
H/V-flip bits, and matches the visible palette-index footprint against every
native Japanese 8x16 font slot.  It then scans known text records in the merged
translation master for the same expanded glyph-slot sequence, including 8x16
dictionary expansion.  The result binds on-screen text to concrete ROM owner
records without guessing from screenshot wording.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, TRANSLATION_MERGED_JSON, advance_relative
from ggen_advance_text_codec import (
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
)

OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_remaining_ui_dynamic_text_20260902.json"
CHARMAP = ADVANCE_ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
FONT8_BASE = 0x00094028
FONT8_STRIDE = 32
FONT8_COUNT = 2068
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

# Coordinates are native GBA 8x8 BG cells.  x ranges intentionally include a
# little right padding; high-confidence glyph matches stop at the actual text.
TARGETS: dict[int, list[dict[str, Any]]] = {
    1: [
        {"name": "運動", "layer": 3, "x0": 16, "x1": 20, "y": 13},
        {"name": "限界", "layer": 3, "x0": 23, "x1": 27, "y": 13},
        {"name": "移動", "layer": 3, "x0": 7, "x1": 11, "y": 15},
        {"name": "装甲", "layer": 3, "x0": 15, "x1": 19, "y": 15},
        {"name": "残り回数", "layer": 3, "x0": 20, "x1": 29, "y": 17},
    ],
    2: [
        {"name": "強化費用", "layer": 2, "x0": 17, "x1": 27, "y": 10},
        {"name": "補給P", "layer": 2, "x0": 18, "x1": 27, "y": 12},
    ],
    3: [
        {"name": "変形", "layer": 3, "x0": 24, "x1": 29, "y": 18},
    ],
    4: [
        {"name": "移動タイプ", "layer": 3, "x0": 17, "x1": 24, "y": 13},
        {"name": "現在の所属", "layer": 3, "x0": 17, "x1": 25, "y": 15},
    ],
    5: [
        {"name": "パイロット", "layer": 3, "x0": 20, "x1": 28, "y": 12},
        {"name": "ユニット", "layer": 3, "x0": 20, "x1": 28, "y": 14},
        {"name": "パーツ", "layer": 3, "x0": 20, "x1": 28, "y": 16},
    ],
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def font_mask(data: bytes, slot: int) -> frozenset[tuple[int, int]]:
    raw = data[FONT8_BASE + slot * FONT8_STRIDE : FONT8_BASE + (slot + 1) * FONT8_STRIDE]
    gate(len(raw) == FONT8_STRIDE, f"8x16 font slot overrun 0x{slot:04X}")
    return frozenset(
        (x, y)
        for y in range(16)
        for x in range(8)
        if (raw[y * 2 + x // 4] >> (2 * (x & 3))) & 3
    )


def decode_4bpp_tile(vram: bytes, charblock: int, cell: int) -> list[list[int]]:
    tile_id = cell & 0x03FF
    raw = vram[charblock * 0x4000 + tile_id * 32 : charblock * 0x4000 + (tile_id + 1) * 32]
    gate(len(raw) == 32, f"VRAM tile overrun 0x{tile_id:03X}")
    tile = [[(raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0x0F for x in range(8)] for y in range(8)]
    if cell & 0x0400:
        tile = [list(reversed(row)) for row in tile]
    if cell & 0x0800:
        tile = list(reversed(tile))
    return tile


def live_block(state: bytes, layer: int, x: int, y: int) -> dict[str, Any]:
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    cnt = u16(io, 8 + layer * 2)
    charblock = (cnt >> 2) & 3
    screenblock = (cnt >> 8) & 31
    cells = [u16(vram, screenblock * 0x800 + ((y + dy) * 32 + x) * 2) for dy in (0, 1)]
    pixels = decode_4bpp_tile(vram, charblock, cells[0]) + decode_4bpp_tile(vram, charblock, cells[1])
    counts = {value: sum(row.count(value) for row in pixels) for value in range(16)}
    values = [value for value, count in counts.items() if count]
    return {
        "bgcnt": cnt,
        "charblock": charblock,
        "screenblock": screenblock,
        "cells": cells,
        "pixels": pixels,
        "counts": counts,
        "values": values,
    }


def dice(a: set[tuple[int, int]] | frozenset[tuple[int, int]], b: set[tuple[int, int]] | frozenset[tuple[int, int]]) -> float:
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def glyph_candidates(block: dict[str, Any], masks: list[frozenset[tuple[int, int]]], slot_to_char: dict[int, str]) -> list[dict[str, Any]]:
    pixels = block["pixels"]
    values = list(block["values"])
    # The face is normally one palette index; some renderers split face and
    # antialias/shadow across two indices.  Try every singleton and pair except
    # the most common background-only value.
    dominant = max(values, key=lambda value: block["counts"][value]) if values else 0
    combos: list[tuple[int, ...]] = [(v,) for v in values if v != dominant]
    combos += [pair for pair in itertools.combinations([v for v in values if v != dominant], 2)]
    scored: list[tuple[float, int, tuple[int, ...], int, int]] = []
    for combo in combos:
        observed = frozenset(
            (x, y)
            for y, row in enumerate(pixels)
            for x, value in enumerate(row)
            if value in combo
        )
        if not observed:
            continue
        for slot in range(1, FONT8_COUNT):
            mask = masks[slot]
            if not mask:
                continue
            score = dice(observed, mask)
            if score >= 0.58:
                scored.append((score, slot, combo, len(observed), len(mask)))
    scored.sort(key=lambda item: (item[0], -abs(item[3] - item[4])), reverse=True)
    rows = []
    seen: set[int] = set()
    for score, slot, combo, observed_pixels, glyph_pixels in scored:
        if slot in seen:
            continue
        seen.add(slot)
        rows.append({
            "score": round(score, 6),
            "slot": f"0x{slot:04X}",
            "char": slot_to_char.get(slot, ""),
            "palette_indices": list(combo),
            "observed_pixels": observed_pixels,
            "glyph_pixels": glyph_pixels,
        })
        if len(rows) >= 8:
            break
    return rows


def parse_tokens(raw: bytes) -> list[int]:
    tokens: list[int] = []
    pos = 0
    while pos < len(raw):
        lead = raw[pos]
        pos += 1
        if lead == 0:
            break
        if lead <= 0xDF:
            tokens.append(lead)
        else:
            if pos >= len(raw):
                return []
            tokens.append((lead << 8) | raw[pos])
            pos += 1
    return tokens


def record_slot_sequence(row: dict[str, Any], dictionary: list[list[int]]) -> list[int]:
    raw_hex = str(row.get("raw_hex") or "").replace(" ", "")
    if not raw_hex:
        return []
    try:
        raw = bytes.fromhex(raw_hex)
        return expand_to_slots(parse_tokens(raw), dictionary)
    except Exception:
        return []


def expected_slots(name: str, char_to_slot: dict[str, int]) -> list[int | None]:
    return [char_to_slot.get(char) for char in name]


def scan_literal_bank(
    data: bytes,
    dictionary: list[list[int]],
    target_slots: dict[str, list[int]],
    slot_to_char: dict[int, str],
    *,
    start: int = 0x001BE700,
    end: int = 0x001BEF80,
) -> dict[str, list[dict[str, Any]]]:
    matches: dict[str, list[dict[str, Any]]] = {name: [] for name in target_slots}
    for off in range(start, end):
        raw = bytearray()
        pos = off
        valid = True
        while pos < min(end, off + 96):
            lead = data[pos]
            raw.append(lead)
            pos += 1
            if lead == 0:
                break
            if lead > 0xDF:
                if pos >= end:
                    valid = False
                    break
                raw.append(data[pos])
                pos += 1
        if not valid or not raw or raw[-1] != 0:
            continue
        try:
            slots = expand_to_slots(parse_tokens(bytes(raw)), dictionary)
        except Exception:
            continue
        if not slots or len(slots) > 48:
            continue
        decoded = "".join(slot_to_char.get(slot, f"<{slot:04X}>") for slot in slots)
        for name, needle in target_slots.items():
            for index in range(0, len(slots) - len(needle) + 1):
                if slots[index : index + len(needle)] == needle:
                    matches[name].append({
                        "file_offset": f"0x{off:08X}",
                        "address": f"0x{0x08000000 + off:08X}",
                        "raw_hex": bytes(raw).hex(" ").upper(),
                        "slot_count": len(slots),
                        "match_start": index,
                        "decoded_12x12": decoded,
                    })
                    break
    for name in matches:
        # Multiple starts inside the same stream can match because every byte is
        # probed.  Prefer true stream starts (preceded by NUL) and shortest rows.
        matches[name].sort(key=lambda row: (0 if int(row["file_offset"], 16) == start or data[int(row["file_offset"], 16) - 1] == 0 else 1, row["slot_count"], int(row["file_offset"], 16)))
        matches[name] = matches[name][:32]
    return matches


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"unexpected Japanese ROM hash {sha256(jp)}")
    cmap_payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    slot_to_char = {int(str(slot), 16): str(char) for slot, char in cmap_payload["verified_charmap"].items()}
    char_to_slot: dict[str, int] = {}
    for slot, char in slot_to_char.items():
        char_to_slot.setdefault(char, slot)
    masks = [frozenset()] + [font_mask(jp, slot) for slot in range(1, FONT8_COUNT)]
    dictionary = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)
    dictionary12 = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    cmap12_payload = json.loads(CHARMAP12.read_text(encoding="utf-8"))
    slot12_to_char = {int(str(slot), 16): str(char) for slot, char in cmap12_payload["verified_charmap"].items()}
    char12_to_slot: dict[str, int] = {}
    for slot, char in slot12_to_char.items():
        char12_to_slot.setdefault(char, slot)
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    records = list(merged["records"])
    record_slots = [(row, record_slot_sequence(row, dictionary)) for row in records]
    record_slots12 = [(row, record_slot_sequence(row, dictionary12)) for row in records]

    target_slot_map12: dict[str, list[int]] = {}
    for targets in TARGETS.values():
        for target in targets:
            slots = expected_slots(str(target["name"]), char12_to_slot)
            if all(slot is not None for slot in slots):
                target_slot_map12[str(target["name"])] = [int(slot) for slot in slots if slot is not None]
    literal_bank_matches = scan_literal_bank(jp, dictionary12, target_slot_map12, slot12_to_char)

    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ggen_advance_remaining_ui_dynamic_text_20260902",
        "result": "PASS",
        "source": {"rom": advance_relative(ORIGINAL_ROM), "sha256": sha256(jp)},
        "literal_bank_12x12_matches": literal_bank_matches,
        "states": {},
    }
    for state_no, targets in TARGETS.items():
        path = ADVANCE_ROOT / f"SD Gundam GGeneration Advance (Korean).ss{state_no}"
        state, _chunks = statefmt.parse_png_state(path)
        state_rows = []
        for target in targets:
            glyphs = []
            selected_slots: list[int] = []
            for x in range(int(target["x0"]), int(target["x1"]) + 1):
                block = live_block(state, int(target["layer"]), x, int(target["y"]))
                candidates = glyph_candidates(block, masks, slot_to_char)
                if candidates and float(candidates[0]["score"]) >= 0.86:
                    selected_slots.append(int(str(candidates[0]["slot"]), 16))
                glyphs.append({
                    "x": x,
                    "cells": [f"0x{value:04X}" for value in block["cells"]],
                    "palette_bank": (block["cells"][0] >> 12) & 0x0F,
                    "counts": {str(k): v for k, v in block["counts"].items() if v},
                    "candidates": candidates,
                })
            known_expected = expected_slots(str(target["name"]), char_to_slot)
            expected12 = expected_slots(str(target["name"]), char12_to_slot)
            exact12_matches = []
            if all(slot is not None for slot in expected12):
                needle12 = [int(slot) for slot in expected12 if slot is not None]
                for row, slots12 in record_slots12:
                    for start in range(0, len(slots12) - len(needle12) + 1):
                        if slots12[start : start + len(needle12)] == needle12:
                            exact12_matches.append({
                                "record_id": row.get("record_id"),
                                "target_file_offset": row.get("target_file_offset"),
                                "source_text": row.get("source_text"),
                                "semantic_category": row.get("semantic_category"),
                                "translation_policy": row.get("translation_policy"),
                                "translation_status": row.get("translation_status"),
                                "translation_ko": row.get("translation_ko"),
                                "owner_ids": row.get("owner_ids"),
                                "match_start": start,
                                "slot_count": len(slots12),
                            })
                            break
            # Find source records containing the confidently decoded run.  This
            # is intentionally a contiguous subsequence match because target
            # x-ranges include UI padding and some labels are preceded by icons.
            source_matches = []
            if selected_slots:
                needle = selected_slots
                for row, slots in record_slots:
                    for start in range(0, len(slots) - len(needle) + 1):
                        if slots[start : start + len(needle)] == needle:
                            source_matches.append({
                                "record_id": row.get("record_id"),
                                "target_file_offset": row.get("target_file_offset"),
                                "source_text": row.get("source_text"),
                                "semantic_category": row.get("semantic_category"),
                                "translation_policy": row.get("translation_policy"),
                                "translation_status": row.get("translation_status"),
                                "translation_ko": row.get("translation_ko"),
                                "owner_ids": row.get("owner_ids"),
                                "match_start": start,
                            })
                            break
            state_rows.append({
                **target,
                "expected_known_slots": [f"0x{slot:04X}" if slot is not None else None for slot in known_expected],
                "expected_12x12_slots": [f"0x{slot:04X}" if slot is not None else None for slot in expected12],
                "exact_12x12_source_matches": exact12_matches[:80],
                "confident_live_slots": [f"0x{slot:04X}" for slot in selected_slots],
                "glyphs": glyphs,
                "source_matches": source_matches[:80],
            })
        result["states"][str(state_no)] = {
            "path": advance_relative(path),
            "targets": state_rows,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "literal_bank12": {
            name: [[m["file_offset"], m["decoded_12x12"]] for m in rows[:8]]
            for name, rows in literal_bank_matches.items()
        },
        "targets": {
            f"ss{state_no}:{row['name']}": {
                "live_slots": row["confident_live_slots"],
                "matches": [
                    [m["record_id"], m["target_file_offset"], m["source_text"]]
                    for m in row["source_matches"][:8]
                ],
                "matches12": [
                    [m["record_id"], m["target_file_offset"], m["source_text"], m["semantic_category"]]
                    for m in row["exact_12x12_source_matches"][:12]
                ],
            }
            for state_no, state_row in result["states"].items()
            for row in state_row["targets"]
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
