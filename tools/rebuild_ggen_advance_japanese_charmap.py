#!/usr/bin/env python3
"""Rebuild the verified Japanese charmap seed entirely under advance/.

The anchor corpus is the same high-confidence known plaintext used by the
historical analyzer: upgrade-part names, selected entity/unit names, and four
direct weapon names.  No web access is performed.  The clean Japanese ROM is
the authoritative byte/glyph source; external guide spellings are provenance
only and are normalized to the ROM spelling where documented.

A successful run must reproduce the pinned 2026-08-26 139-slot snapshot exactly.
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
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_stage2_production_reference_manifest as production  # noqa: E402
import ggen_advance_text_codec as codec  # noqa: E402

EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = production.ROM_SHA256
ROM_BASE = production.ROM_BASE
PINNED_SEED = ROOT / "font_tables" / "ggen_advance_japanese_charmap_seed_20260826.json"

NORMALIZED_TABLE = 0x0018DD68
NORMALIZED_STRIDE = 8
ENTITY_DB = 0x0018E2E4
ENTITY_STRIDE = 0xAC
ENTITY_NAME_FIELD = 4
ENTITY_PREFIX_SLOT = 0x07FB

KNOWN_PLAINTEXT_REFERENCES = [
    {
        "id": "gamefaqs_units_parts_guide_v1_5",
        "title": "SD Gundam G Generation Advance Units and Parts Guide",
        "url": "https://gamefaqs.gamespot.com/gba/919133-sd-gundam-g-generation-advance/faqs/27424",
        "version": "1.5",
        "updated": "2004-03-17",
        "usage": "Japanese upgrade-part and unit-name spellings; ROM glyph patterns take precedence for spacing/long-vowel normalization",
    }
]

PART_PLAINTEXT = {
    0: "カスタムパーツ",
    1: "クリアランスパーツ",
    2: "アップグレードパーツ",
    3: "ハイクリアランスパーツ",
    4: "ハイグレードパーツ",
    5: "陸戦キット",
    6: "スナイパーライフル",
    7: "ビームキャノン",
    8: "ガンダリウムγ",
    9: "Iフィールド",
    10: "ムーバブルフレーム",
    11: "可変フレーム",
    12: "高機動スラスター",
    13: "メガバズーカランチャー",
    14: "ハイメガキャノン",
    15: "アーマーユニット",
    16: "ディフェンサーユニット",
    17: "BWS",
    18: "アームドベース",
    19: "ベクタードスラスター",
    20: "サラミス砲",
    21: "インコム",
    22: "バイオセンサー",
    23: "サイココントローラー",
    24: "サイコフレーム",
    26: "マグネットコーティング",
    27: "フィンファンネル",
}

DIRECT_PLAINTEXT = {
    0x00179E6A: "ヒートホーク",
    0x00179E9D: "ミサイルポッド",
    0x00179EB8: "メガ粒子砲",
    0x0017A11D: "ショットガン",
}

ENTITY_PLAINTEXT = {
    1: "ザクⅡ ドアン機", 3: "ザクⅡF", 4: "ザクⅡJ", 5: "ジム",
    6: "アプサラスⅡ", 7: "グフ", 8: "コア・ブースター", 9: "シャア専用ザク",
    10: "ライデン専用ザク", 11: "イフリート改", 12: "ガンタンク", 13: "ザクⅡFZ",
    14: "ジム・コマンド", 15: "ズゴック", 16: "ドム", 17: "ハイゴッグ",
    18: "ビグロ", 19: "BDⅠ", 20: "エルメス", 21: "ガンキャノン",
    22: "グフカスタム", 23: "ゲルググ", 24: "NT試験用ジム ジャグラー",
    25: "ドム・トローペン", 26: "陸戦型ガンダム", 27: "ガンダム", 28: "ゲルググM",
    29: "ジムカスタム", 30: "シャア専用ズゴック", 31: "ズゴックE", 32: "Ez8",
    33: "Ez8改", 34: "Ez8HMC", 35: "Ez8HAC", 36: "アプサラスⅢ",
    38: "ジムキャノンⅡ", 39: "ドム・バインニヒツ", 40: "MCガンダム", 41: "ヴァル・ヴァロ",
    42: "ガザC", 44: "ジムⅡ", 45: "ドム・グロースバイル", 46: "ハイザック",
    47: "BDⅡ", 49: "BDⅢ", 51: "NT-1 アレックス", 53: "ケンプファー",
    54: "GP01ゼフィランサス", 55: "GP01フルバーニアン", 56: "ガザD", 61: "GP02サイサリス",
    62: "GP03Sステイメン", 63: "GP03デンドロビウム", 64: "ガンダムMkⅡ", 66: "ガンダムMkⅡ0号機",
    85: "バクゥ", 86: "キュベレイMkⅡ", 87: "ギラ・ドーガ", 92: "ウォドム",
    93: "ガンダムMkⅤ", 96: "フルアーマー百式改", 97: "量産型キュベレイ", 98: "R・ジャジャ",
    105: "スモー シルバータイプ", 110: "ヤクト・ドーガ", 126: "Gフォートレス", 129: "∀ガンダム",
    131: "ガンダムアシュタロン", 133: "スモー ゴールドタイプ", 134: "F91", 135: "V2ガンダム",
    136: "αアジール", 137: "ガンダムエピオン", 140: "ガンダムX", 143: "∀ガンダム<∀99>",
    144: "∀ガンダム<月光蝶>", 149: "ストライクルージュ", 151: "トールギス",
    314: "ホワイトベース", 315: "グワジン", 317: "グワデン",
}


def u32(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 4], "little")


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def slots_for_pointer(data: bytes, pointer: int, dictionary: list[list[int]]) -> tuple[list[int], bytes]:
    tokens, raw = codec.read_tokens_strict(data, pointer - ROM_BASE)
    check(codec.encode_tokens(tokens) == raw, f"anchor round-trip drift 0x{pointer:08X}")
    return codec.expand_to_slots(tokens, dictionary), raw


def build_seed(data: bytes) -> dict[str, Any]:
    dictionary = codec.load_dictionary(data, codec.DICT_8X16_BASE, codec.DICT_8X16_END)
    slot_to_chars: dict[int, set[str]] = defaultdict(set)
    char_to_slots: dict[str, set[int]] = defaultdict(set)
    anchors: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    def apply_anchor(source: str, index: int, text: str, pointer: int, slots: list[int]) -> None:
        if len(slots) != len(text):
            mismatches.append({
                "source": source,
                "index": index,
                "text": text,
                "glyph_count": len(slots),
                "text_length": len(text),
                "address": f"0x{pointer:08X}",
            })
            return
        pairs = []
        for slot, char in zip(slots, text):
            slot_to_chars[slot].add(char)
            char_to_slots[char].add(slot)
            pairs.append({"slot": f"0x{slot:04X}", "char": char})
        anchors.append({
            "source": source,
            "index": index,
            "expected_text": text,
            "address": f"0x{pointer:08X}",
            "glyph_count": len(slots),
            "pairs": pairs,
        })

    for index, text in PART_PLAINTEXT.items():
        source = NORMALIZED_TABLE + index * NORMALIZED_STRIDE
        pointer = u32(data, source)
        slots, _raw = slots_for_pointer(data, pointer, dictionary)
        apply_anchor("upgrade_parts", index, text, pointer, slots)

    for record_index, text in ENTITY_PLAINTEXT.items():
        source = ENTITY_DB + record_index * ENTITY_STRIDE + ENTITY_NAME_FIELD
        pointer = u32(data, source)
        slots, _raw = slots_for_pointer(data, pointer, dictionary)
        check(slots and slots[0] == ENTITY_PREFIX_SLOT, f"entity {record_index} missing 07FB prefix")
        apply_anchor("entity_unit_name", record_index, text, pointer, slots[1:])

    for file_offset, text in DIRECT_PLAINTEXT.items():
        pointer = ROM_BASE + file_offset
        slots, _raw = slots_for_pointer(data, pointer, dictionary)
        apply_anchor("direct_weapon_name", file_offset, text, pointer, slots)

    slot_conflicts = {
        f"0x{slot:04X}": sorted(chars)
        for slot, chars in sorted(slot_to_chars.items())
        if len(chars) > 1
    }
    verified = {
        slot: next(iter(chars))
        for slot, chars in slot_to_chars.items()
        if len(chars) == 1
    }
    char_aliases = {
        char: [f"0x{slot:04X}" for slot in sorted(slots)]
        for char, slots in sorted(char_to_slots.items())
        if len(slots) > 1
    }

    check(not mismatches, f"anchor length mismatch count: {len(mismatches)}")
    check(not slot_conflicts, f"slot conflict count: {len(slot_conflicts)}")
    check(len(anchors) == 112, f"anchor count drift: {len(anchors)}")
    check(len(verified) == 139, f"verified slot count drift: {len(verified)}")
    check(len(set(verified.values())) == 137, "verified Unicode character count drift")

    pinned = json.loads(PINNED_SEED.read_text(encoding="utf-8"))
    pinned_map = {int(slot, 16): char for slot, char in pinned["verified_charmap"].items()}
    check(verified == pinned_map, "rebuilt charmap differs from pinned seed snapshot")

    # Measure directly against the production-complete 4,069 records.
    production_report = production.build_manifest(data)
    total_units = 0
    mapped_units = 0
    complete = 0
    unresolved: Counter[int] = Counter()
    for row in production_report["records"]:
        pointer = int(row["target_address"], 16)
        slots, _raw = slots_for_pointer(data, pointer, dictionary)
        total_units += len(slots)
        mapped = sum(slot in verified for slot in slots)
        mapped_units += mapped
        if mapped == len(slots):
            complete += 1
        for slot in slots:
            if slot not in verified:
                unresolved[slot] += 1

    mapping_payload = [
        {"slot": f"0x{slot:04X}", "char": verified[slot]}
        for slot in sorted(verified)
    ]
    mapping_sha256 = hashlib.sha256(
        json.dumps(mapping_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": 1,
        "method": "advance-local known-plaintext anchor reconstruction",
        "source_references": KNOWN_PLAINTEXT_REFERENCES,
        "source": {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "anchor_count": len(anchors),
        "length_mismatches": mismatches,
        "slot_conflicts": slot_conflicts,
        "char_aliases": char_aliases,
        "verified_slot_count": len(verified),
        "verified_character_count": len(set(verified.values())),
        "verified_charmap": {f"0x{slot:04X}": verified[slot] for slot in sorted(verified)},
        "mapping_sha256": mapping_sha256,
        "pinned_snapshot_match": True,
        "anchors": anchors,
        "coverage_4069": {
            "records": len(production_report["records"]),
            "expanded_units": total_units,
            "mapped_units": mapped_units,
            "mapped_percent": round(mapped_units * 100 / total_units, 3),
            "complete_records": complete,
            "complete_percent": round(complete * 100 / len(production_report["records"]), 3),
            "unresolved_unique_slots": len(unresolved),
            "top_unresolved_slots": [
                {"slot": f"0x{slot:04X}", "occurrences": count}
                for slot, count in unresolved.most_common(100)
            ],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    data = args.rom.read_bytes()
    check(len(data) == EXPECTED_SIZE, f"ROM size drift: {len(data)}")
    check(hashlib.sha256(data).hexdigest() == EXPECTED_SHA256, "ROM hash drift")
    report = build_seed(data)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    visible = {
        key: report[key]
        for key in (
            "schema_version", "method", "source_references", "source", "anchor_count",
            "length_mismatches", "slot_conflicts", "char_aliases", "verified_slot_count",
            "verified_character_count", "mapping_sha256", "pinned_snapshot_match", "coverage_4069",
        )
    } if args.summary_only else report
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
