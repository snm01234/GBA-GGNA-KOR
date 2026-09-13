#!/usr/bin/env python3
"""Promote only conflict-free weapon alignments into the 12x12 seed."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    alignment_path = Path("legacy/analysis/scenario_event_12x12_alignment_20260827.json")
    dictionary_path = Path("legacy/analysis/dictionary_comparison_20260827.json")
    production_seed_path = Path("font_tables/ggen_advance_japanese_charmap_seed_20260826.json")
    out_path = Path("legacy/analysis/scenario_event_12x12_charmap_seed_20260827.json")
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    dictionary = json.loads(dictionary_path.read_text(encoding="utf-8"))
    production_seed = json.loads(production_seed_path.read_text(encoding="utf-8"))
    bijection = dictionary["slot_bijection_8x16_to_12x12"]
    transferred = {
        large_slot: production_seed["verified_charmap"][small_slot]
        for small_slot, large_slot in bijection.items()
        if small_slot in production_seed["verified_charmap"]
    }
    mapping = dict(transferred)
    for slot, char in alignment["slot_to_char"].items():
        existing = mapping.get(slot)
        if existing is not None and existing != char:
            raise SystemExit(f"dictionary/alignment conflict at {slot}: {existing!r} vs {char!r}")
        mapping[slot] = char
    # The clean 12x12 atlas makes the low control/punctuation run and the
    # kana run directly legible.  These are deliberately limited to glyphs
    # whose bitmap identity is unambiguous; the remaining kanji stay pending.
    atlas_verified = {
        0x0001: " ", 0x0002: "、", 0x0003: "・", 0x0004: "？", 0x0005: "！",
        0x0006: "ー", 0x0007: "…", 0x0008: "「", 0x0009: "」",
        0x000A: "0", 0x000B: "A", 0x000C: "B", 0x000D: "C", 0x000E: "D",
        0x000F: "E", 0x0010: "F", 0x0011: "G", 0x0012: "J", 0x0013: "M",
        0x0014: "P", 0x0015: "S", 0x0016: "T", 0x0017: "X", 0x0018: "Z",
        0x0019: "e", 0x001A: "i", 0x001C: "n",
    }
    hiragana = (
        "ぁあいうえお"
        "かがきぎくけげこご"
        "さしじすずせそ"
        "たちつてでとど"
        "なにぬねのはばぱ"
        "ひびぴふぶぷへべぺほぼぽ"
        "まみむめもゃやゅゆょよ"
    )
    atlas_verified.update({0x001D + index: char for index, char in enumerate(hiragana)})
    katakana = {
        0x0059: "ァ", 0x005A: "ア", 0x005B: "ィ", 0x005C: "イ", 0x005D: "ウ",
        0x005E: "ェ", 0x005F: "エ", 0x0060: "ォ", 0x0061: "オ", 0x0062: "カ",
        0x0063: "ガ", 0x0064: "キ", 0x0065: "ギ", 0x0066: "ク", 0x0067: "グ",
        0x0068: "ケ", 0x0069: "ゲ", 0x006A: "コ", 0x006B: "ゴ", 0x006C: "サ",
        0x006D: "ザ", 0x006E: "シ", 0x006F: "ジ", 0x0070: "ス", 0x0071: "ズ",
        0x0072: "セ", 0x0073: "ゼ", 0x0074: "ソ", 0x0075: "タ", 0x0076: "ダ",
        0x0077: "チ", 0x0078: "ッ", 0x0079: "ツ", 0x007A: "テ", 0x007B: "デ",
        0x007C: "ト", 0x007D: "ド", 0x007E: "ナ", 0x007F: "ニ", 0x0080: "ネ",
        0x0081: "ノ", 0x0082: "ハ", 0x0083: "バ", 0x0084: "パ", 0x0085: "ヒ",
        0x0086: "ビ", 0x0087: "フ", 0x0088: "ブ", 0x0089: "プ", 0x008A: "ベ",
        0x008B: "ペ", 0x008C: "マ", 0x008D: "ミ", 0x008E: "ム", 0x008F: "メ",
        0x0090: "モ", 0x0091: "ャ", 0x0092: "ヤ", 0x0093: "ュ", 0x0094: "ユ",
        0x0095: "ョ", 0x0096: "ラ", 0x0097: "リ", 0x0098: "ル", 0x0099: "レ",
        0x009A: "ロ", 0x009B: "ワ", 0x009C: "ン", 0x009D: "ヴ",
        0x0139: "ピ", 0x013C: "ホ", 0x013D: "ポ",
    }
    atlas_verified.update(katakana)
    for slot, char in atlas_verified.items():
        existing = mapping.get(f"0x{slot:04X}")
        if existing is not None and existing != char:
            raise SystemExit(
                f"atlas/alignment conflict at 0x{slot:04X}: {existing!r} vs {char!r}"
            )
        mapping[f"0x{slot:04X}"] = char
    payload = {
        "schema_version": 1,
        "font_mode": "12x12",
        "method": (
            "Conflict-free positional alignment between the 12x12 dynamic weapon-fragment "
            "streams and the reviewed 4,069-record weapon-name list. Only rows with complete "
            "Japanese source and matching expanded-slot length were used."
        ),
        "verified_charmap": {slot: mapping[slot] for slot in sorted(mapping)},
        "evidence": {
            "alignment_report": str(alignment_path.resolve()),
            "dictionary_comparison": str(dictionary_path.resolve()),
            "production_seed": str(production_seed_path.resolve()),
            "fully_aligned_dynamic_records": alignment["fully_aligned_count"],
            "conflict_count": alignment["conflict_count"],
            "derived_alignment_slot_count": alignment["slot_mapping_count"],
            "transferred_8x16_to_12x12_slot_count": len(transferred),
            "atlas_verified_slot_count": len(atlas_verified),
            "combined_verified_slot_count": len(mapping),
        },
        "notes": [
            "This is a scenario/event 12x12 map and must not replace the existing 8x16 production-record seed.",
            "The dictionary pairing is conflict-free for the transferred slots; the original 8x16 seed remains read-only evidence.",
            "Unresolved slots remain explicit <slot> markers in the source inventory.",
            "The alignment proves slot identity for the included evidence; it does not by itself decode every kanji slot.",
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out_path.resolve()),
        "verified_slot_count": len(mapping),
        "fully_aligned_dynamic_records": alignment["fully_aligned_count"],
        "conflict_count": alignment["conflict_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
