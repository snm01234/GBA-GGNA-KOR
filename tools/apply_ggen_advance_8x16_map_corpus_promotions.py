#!/usr/bin/env python3
"""Apply exact GGA 8x16 promotions backed by same-ROM text evidence.

Only slots with an unambiguous alignment against the fully decoded GGA
map-script corpus (or a literal dictionary entry) belong in this batch.
The supplement is updated in place with provenance and collision guards.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTION_BATCH: dict[str, dict[str, object]] = {
    "0x001A": {
        "char": "ぇ",
        "basis": "same_game_phrase_context_exact",
        "evidence": (
            "GGA-TEXT-0017C361 => 恥かかすんじゃねぇぞ！ (name75_base_ko.json); "
            "GGA-TEXT-0017CA47 uses the same small-e shout pattern"
        ),
    },
    "0x001C": {
        "char": "ぉ",
        "basis": "same_game_phrase_context_exact",
        "evidence": (
            "GGA-TEXT-0017B4E1/0017BC0F/0017BE86/0017CAFA => うぉぉぉぉ・やめろぉぉ・なんとぉ・このぉ; "
            "same-game battle-voice corpus confirms small-o spelling"
        ),
    },
    "0x014C": {
        "char": "暗",
        "basis": "same_game_stage_location_exact",
        "evidence": (
            "GGA-TEXT-0018CF2F/001BF026 => 暗礁宙域; the same stage-location string is repeated "
            "in the reviewed title/UI corpus"
        ),
    },
    "0x015B": {
        "char": "域",
        "basis": "same_game_stage_location_exact",
        "evidence": (
            "GGA-TEXT-0018CF2F/001BF026 => 暗礁宙域; repeated location-name suffix aligns with the "
            "reviewed title/UI corpus"
        ),
    },
    "0x015F": {
        "char": "印",
        "basis": "same_game_id_effect_exact",
        "evidence": (
            "GGA-TEXT-0017B747/0017B8F4 => IDコマンド封印 / 散開封印&攻撃↑; repeated ID-effect "
            "labels share the same slot"
        ),
    },
    "0x017E": {
        "char": "戦",
        "basis": "same_game_stage_condition_exact",
        "evidence": (
            "GGA-TEXT-0018D4DF/0018D59F => 戦闘力増大; repeated reviewed stage-condition label"
        ),
    },
    "0x01AC": {
        "char": "開",
        "basis": "same_game_id_effect_exact",
        "evidence": (
            "GGA-TEXT-0017B8F4/0017BDAB => 散開封印&攻撃↑ / 強制散開; repeated ID-effect context"
        ),
    },
    "0x01B4": {
        "char": "街",
        "basis": "same_game_stage_location_exact",
        "evidence": (
            "GGA-TEXT-0018CF67/0018CF84 => 市街地; repeated reviewed stage-location label"
        ),
    },
    "0x0222": {
        "char": "力",
        "basis": "same_game_stage_condition_exact",
        "evidence": (
            "GGA-TEXT-0018D4DF/0018D59F => 戦闘力増大; repeated reviewed stage-condition label"
        ),
    },
    "0x02F3": {
        "char": "索",
        "basis": "same_game_selector_label_exact",
        "evidence": (
            "GGA-TEXT-001BEB92/001BF052 => 索敵 / 索敵地上; selector and stage-location labels agree"
        ),
    },
    "0x030B": {
        "char": "市",
        "basis": "same_game_stage_location_exact",
        "evidence": (
            "GGA-TEXT-0018CF67/0018CF84 => 市街地; repeated reviewed stage-location label"
        ),
    },
    "0x0438": {
        "char": "闘",
        "basis": "same_game_stage_condition_exact",
        "evidence": (
            "GGA-TEXT-0018D4DF/0018D59F => 戦闘力増大; repeated reviewed stage-condition label"
        ),
    },
    "0x0440": {
        "char": "門",
        "basis": "same_game_stage_condition_exact",
        "evidence": (
            "GGA-TEXT-0018D60C/001BE9E0 => 砲門開け!!; repeated reviewed condition component "
            "context and enclosing-glyph shape"
        ),
    },
    "0x0516": {
        "char": "封",
        "basis": "same_game_id_effect_exact",
        "evidence": (
            "GGA-TEXT-0017B747/0017B8F4 => IDコマンド封印 / 散開封印&攻撃↑; repeated ID-effect "
            "labels share the same slot"
        ),
    },
    "0x0560": {
        "char": "増",
        "basis": "same_game_stage_condition_exact",
        "evidence": (
            "GGA-TEXT-0018D4DF/0018D59F => 戦闘力増大; repeated reviewed stage-condition label"
        ),
    },
    "0x0693": {
        "char": "開",
        "basis": "same_game_stage_condition_exact",
        "evidence": (
            "GGA-TEXT-0018D60C/001BE9E0 => 砲門開け!!; repeated reviewed condition component "
            "context and enclosing-glyph shape"
        ),
    },
    "0x06FE": {
        "char": "礁",
        "basis": "same_game_stage_location_exact",
        "evidence": (
            "GGA-TEXT-0018CF2F/001BF026 => 暗礁宙域; repeated location-name middle character aligns "
            "with the reviewed title/UI corpus"
        ),
    },
    "0x002B": {
        "char": "ぜ",
        "basis": "atlas_internal_dakuten_exact",
        "evidence": (
            "8x16 glyph 0x002A=せ plus exact dakuten pixels equals 0x002B; "
            "contiguous kana sequence"
        ),
    },
    "0x003F": {
        "char": "び",
        "basis": "atlas_internal_dakuten_exact",
        "evidence": (
            "8x16 glyph 0x003E=ひ plus exact dakuten pixels equals 0x003F; "
            "contiguous kana sequence"
        ),
    },
    "0x0115": {
        "char": "ぶ",
        "basis": "dictionary_single_unknown_exact",
        "evidence": "legacy/analysis/ggen_advance_remaining_identification_20260828.json#dictionary_single_unknown_samples[0]",
    },
    "0x032D": {
        "char": "爵",
        "basis": "same_rom_map_script_exact_alignment",
        "evidence": "GGA-TEXT-0017C3AA,GGA-TEXT-00185B20 => デルマイユ公爵",
    },
    "0x0487": {
        "char": "島",
        "basis": "same_rom_map_script_exact_alignment",
        "evidence": "GGA-TEXT-0018D281 => ククルス・ドアンの島",
    },
    "0x0152": {
        "char": "威",
        "basis": "same_rom_repeated_id_effect_context",
        "evidence": (
            "GGA-TEXT-0017B407,0017B541,0017B576,0017B641,0017C0D1,"
            "0017C15B,0017C814,0017CB40 => 威力 (命中・威力↑/敵威力・装甲↓)"
        ),
    },
    "0x0391": {
        "char": "尻",
        "basis": "dictionary_position_exact_alignment",
        "evidence": (
            "legacy/analysis/dictionary_comparison_20260827.json#slot_bijection_8x16_to_12x12"
            " 0x0391->0x0400; reviewed 12x12 0x0400=尻"
        ),
    },
    "0x04F4": {
        "char": "連",
        "basis": "dictionary_position_exact_alignment",
        "evidence": (
            "legacy/analysis/dictionary_comparison_20260827.json#slot_bijection_8x16_to_12x12"
            " 0x04F4->0x05CC; reviewed 12x12 0x05CC=連"
        ),
    },
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified: dict[str, str] = payload["verified_charmap"]
    collisions: list[str] = []
    applied: dict[str, str] = {}
    already_present: list[str] = []
    for slot, item in PROMOTION_BATCH.items():
        char = str(item["char"])
        current = verified.get(slot)
        if current == char:
            already_present.append(slot)
        elif current is not None:
            collisions.append(f"{slot} has {current!r}, refused {char!r}")
        else:
            verified[slot] = char
            applied[slot] = char
    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1

    payload["verified_charmap"] = {
        key: verified[key] for key in sorted(verified, key=lambda value: int(value, 16))
    }
    provenance = payload.setdefault("added_same_rom_corpus_promotions_20260829", {})
    for slot, item in PROMOTION_BATCH.items():
        provenance[slot] = {
            "to": str(item["char"]),
            "basis": str(item["basis"]),
            "evidence": str(item["evidence"]),
        }
    payload["added_same_rom_corpus_promotions_20260829"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda value: int(value, 16))
    }
    payload["combined_slot_count"] = len(payload["verified_charmap"])
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "applied": len(applied),
        "already_present": len(already_present),
        "verified_charmap": len(payload["verified_charmap"]),
        "promoted": applied,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
