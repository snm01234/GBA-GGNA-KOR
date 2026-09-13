#!/usr/bin/env python3
"""Identify remaining unified-sheet text without guessing translations.

This read-only helper:

- classifies every pending translate row
- decodes both 319-entry dictionaries with the current font maps
- lists dictionary positions where exactly one glyph is unknown
- lists pending rows whose only unknown text slots are a small set

The immutable unified source is never rewritten.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_dictionary import (
    DICT_12X12,
    DICT_8X16,
    END_12X12,
    END_8X16,
    glyph_slot,
    parse_dictionary,
)
from analyze_ggen_advance_pending_decode import (
    CORRECTED_LOW_KANA,
    EIGHT_SCOPES,
    RESERVED,
    SCENARIO_SCOPES,
    decode_text,
    load_map,
    remaining_slots,
)
DEFAULT_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
DEFAULT_MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
DEFAULT_MAP8 = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_remaining_identification_20260828.json"


def decode_slots(slots: list[int], charmap: dict[int, str]) -> tuple[str, list[int]]:
    chars: list[str] = []
    missing: list[int] = []
    for slot in slots:
        if slot in RESERVED:
            missing.append(slot)
            chars.append(f"<SLOT:{slot:04X}>")
            continue
        char = charmap.get(slot)
        if char is None:
            missing.append(slot)
            chars.append(f"<SLOT:{slot:04X}>")
        else:
            chars.append(char)
    return "".join(chars), missing


def classify_row(row: dict, leftover: list[int], decoded: str) -> str:
    leftover_text = [slot for slot in leftover if slot not in RESERVED]
    leftover_reserved = [slot for slot in leftover if slot in RESERVED]
    if not leftover_text:
        body = decoded.replace("＠", "")
        if "セリフ" in body and decoded.count("＠") >= 2:
            return "unused_bark_template"
        if leftover_reserved:
            return "reserved_markers_only"
        return "fully_decoded"
    if len(leftover_text) == 1:
        return "single_unknown_text_slot"
    if len(leftover_text) <= 3:
        return "few_unknown_text_slots"
    return "many_unknown_text_slots"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--map12", type=Path, default=DEFAULT_MAP12)
    parser.add_argument("--map8", type=Path, default=DEFAULT_MAP8)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    map12 = load_map(args.map12)
    map12.update(CORRECTED_LOW_KANA)
    map8 = load_map(args.map8)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    rom = args.rom.read_bytes()

    dict8 = parse_dictionary(rom, DICT_8X16, END_8X16)
    dict12 = parse_dictionary(rom, DICT_12X12, END_12X12)
    dictionary_rows: list[dict] = []
    single_unknown_dict: list[dict] = []
    hole_votes: dict[str, Counter[str]] = defaultdict(Counter)
    for index, (tokens8, tokens12) in enumerate(zip(dict8["entries"], dict12["entries"])):
        slots8 = [slot for token in tokens8 if (slot := glyph_slot(token)) is not None]
        slots12 = [slot for token in tokens12 if (slot := glyph_slot(token)) is not None]
        text8, miss8 = decode_slots(slots8, map8)
        text12, miss12 = decode_slots(slots12, map12)
        row = {
            "index": index,
            "slots_8x16": [f"0x{slot:04X}" for slot in slots8],
            "slots_12x12": [f"0x{slot:04X}" for slot in slots12],
            "decoded_8x16": text8,
            "decoded_12x12": text12,
            "missing_8x16": [f"0x{slot:04X}" for slot in miss8],
            "missing_12x12": [f"0x{slot:04X}" for slot in miss12],
        }
        dictionary_rows.append(row)
        if len(miss8) == 1 and not miss12:
            slot = miss8[0]
            char = map12.get(slots12[slots8.index(slot)]) if slot in slots8 else None
            if char:
                hole_votes[f"8x16:0x{slot:04X}"][char] += 1
            single_unknown_dict.append({**row, "fill_font": "8x16", "fill_slot": f"0x{slot:04X}", "fill_char": char})
        if len(miss12) == 1 and not miss8:
            slot = miss12[0]
            char = map8.get(slots8[slots12.index(slot)]) if slot in slots12 else None
            if char:
                hole_votes[f"12x12:0x{slot:04X}"][char] += 1
            single_unknown_dict.append({**row, "fill_font": "12x12", "fill_slot": f"0x{slot:04X}", "fill_char": char})

    unique_dict_fills: list[dict] = []
    for key, votes in sorted(hole_votes.items()):
        ranked = votes.most_common()
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            font, slot = key.split(":")
            unique_dict_fills.append({"font": font, "slot": slot, "char": ranked[0][0], "votes": ranked[0][1], "alts": ranked[1:]})

    pending_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    class_by_scope: dict[str, Counter[str]] = defaultdict(Counter)
    single_unknown: dict[int, list[dict]] = defaultdict(list)
    leftover1_nonbark: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    leftover1_bark: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    slot_freq: Counter[tuple[str, int]] = Counter()
    slot_scopes: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    fully_decoded_samples: list[dict] = []
    for row in merged.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        scope = str(row.get("source_scope", ""))
        pending_counts[scope] += 1
        if scope in SCENARIO_SCOPES:
            font, charmap = "12x12", map12
        elif scope in EIGHT_SCOPES:
            font, charmap = "8x16", map8
        else:
            class_counts["unknown_scope"] += 1
            continue
        leftover = remaining_slots(row, charmap)
        decoded, _ = decode_text(str(row.get("source_text", "")), charmap)
        kind = classify_row(row, leftover, decoded)
        class_counts[kind] += 1
        class_by_scope[scope][kind] += 1
        leftover_text = [slot for slot in leftover if slot not in RESERVED]
        for slot in leftover_text:
            key = (font, slot)
            slot_freq[key] += 1
            slot_scopes[key][scope] += 1
        if kind == "fully_decoded" and len(fully_decoded_samples) < 40:
            fully_decoded_samples.append({
                "record_id": row.get("record_id"),
                "source_scope": scope,
                "semantic_category": row.get("semantic_category"),
                "decoded_text": decoded,
            })
        if kind == "single_unknown_text_slot" and leftover_text:
            slot = leftover_text[0]
            key = (font, slot)
            if len(single_unknown[slot]) < 8:
                single_unknown[slot].append({
                    "record_id": row.get("record_id"),
                    "source_scope": scope,
                    "semantic_category": row.get("semantic_category"),
                    "decoded_text": decoded,
                    "source_text": row.get("source_text"),
                })
            frame = decoded.replace("\n", " / ")
            if "セリフ" in decoded and decoded.count("＠") >= 2:
                leftover1_bark[key][frame] += 1
            else:
                leftover1_nonbark[key][frame] += 1

    remaining_slot_holds: list[dict] = []
    hold_counts: Counter[str] = Counter()
    hold_counts_by_font: dict[str, Counter[str]] = defaultdict(Counter)
    for key, count in slot_freq.most_common():
        font, slot = key
        nonbark = leftover1_nonbark.get(key, Counter())
        bark = leftover1_bark.get(key, Counter())
        nonbark_n = len(nonbark)
        bark_n = len(bark)
        if nonbark_n == 0 and bark_n == 0:
            reason = "no_single_unknown"
        elif nonbark_n == 0:
            reason = "bark_template_only"
        elif nonbark_n == 1:
            reason = "single_collocation"
        else:
            reason = "mixed_frames_held"
        hold_counts[reason] += 1
        hold_counts_by_font[font][reason] += 1
        remaining_slot_holds.append({
            "font": font,
            "slot": f"0x{slot:04X}",
            "pending_records": count,
            "scopes": dict(slot_scopes[key]),
            "hold_reason": reason,
            "leftover1_nonbark_frames": nonbark_n,
            "leftover1_bark_frames": bark_n,
            "top_nonbark": [frame[:80] for frame, _ in nonbark.most_common(3)],
        })

    payload = {
        "schema_version": 1,
        "merged": str(args.merged),
        "map12_slots": len(map12),
        "map8_slots": len(map8),
        "pending_translate": dict(pending_counts),
        "pending_total": sum(pending_counts.values()),
        "classification": dict(class_counts),
        "classification_by_scope": {scope: dict(counts) for scope, counts in class_by_scope.items()},
        "dictionary_entry_count": len(dictionary_rows),
        "dictionary_fully_decoded": sum(1 for row in dictionary_rows if not row["missing_8x16"] and not row["missing_12x12"]),
        "dictionary_single_unknown": len(single_unknown_dict),
        "unique_dictionary_fills": unique_dict_fills,
        "dictionary_single_unknown_samples": single_unknown_dict[:80],
        "remaining_unique_text_slots": len(slot_freq),
        "remaining_unique_text_slots_by_font": dict(Counter(font for font, _ in slot_freq)),
        "high_frequency_remaining_slots": [
            {"font": font, "slot": f"0x{slot:04X}", "pending_records": count}
            for (font, slot), count in slot_freq.most_common(80)
        ],
        "single_unknown_slot_count": len(single_unknown),
        "single_unknown_samples": {
            f"0x{slot:04X}": samples
            for slot, samples in sorted(single_unknown.items(), key=lambda item: -len(item[1]))[:40]
        },
        "fully_decoded_samples": fully_decoded_samples,
        "dictionary_entries_with_holes": [
            row for row in dictionary_rows if row["missing_8x16"] or row["missing_12x12"]
        ],
        "remaining_slot_hold_counts": dict(hold_counts),
        "remaining_slot_hold_counts_by_font": {
            font: dict(counts) for font, counts in hold_counts_by_font.items()
        },
        "remaining_slot_holds": remaining_slot_holds,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "pending_total": payload["pending_total"],
        "classification": payload["classification"],
        "dictionary_fully_decoded": payload["dictionary_fully_decoded"],
        "dictionary_with_holes": len(payload["dictionary_entries_with_holes"]),
        "unique_dictionary_fills": unique_dict_fills,
        "remaining_unique_text_slots": payload["remaining_unique_text_slots"],
        "single_unknown_slots": payload["single_unknown_slot_count"],
        "remaining_slot_hold_counts": dict(hold_counts),
        "remaining_slot_hold_counts_by_font": {
            font: dict(counts) for font, counts in hold_counts_by_font.items()
        },
        "remaining_unique_text_slots_by_font": dict(Counter(font for font, _ in slot_freq)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
