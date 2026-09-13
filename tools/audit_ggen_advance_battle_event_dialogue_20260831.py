#!/usr/bin/env python3
"""Audit the isolated battle-event dialogue patch and reported screenshot paths."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ROM_BASE = 0x08000000
TABLE_START = 0x00D34588
TABLE_CELLS = 256 * 23
ORIGINAL_POOL_START = 0x00D34130
ORIGINAL_POOL_END = 0x00D34588
MAP_LOOKUP_START = 0x010CA9EC
MAP_LOOKUP_ENTRIES = 24472
MAP_ENTRY_SIZE = 12

SCREENSHOTS = [
    (1, "battle_event_dialogue", "GGA-BATTLEEVENT-00D341DC", "자쿠 따위와는\n장갑도 파워도！！"),
    (2, "battle_event_dialogue", "GGA-BATTLEEVENT-00D3418C", "신형 모빌슈트가 뭐냐！"),
    (3, "battle_event_dialogue", "GGA-BATTLEEVENT-00D341A0", "우와아아앗！"),
    (4, "battle_event_dialogue", "GGA-BATTLEEVENT-00D341AC", "해볼 만해……！"),
    (5, "battle_event_dialogue", "GGA-BATTLEEVENT-00D341B8", "제법이군……"),
    (6, "battle_event_dialogue", "GGA-BATTLEEVENT-00D341C4", "자쿠와는 다르다고！\n자쿠와는！！"),
    (7, "battle_event_dialogue", "GGA-BATTLEEVENT-00D341DC", "이, 이 녀석, 다르다……！"),
    (8, "scenario_map_script", "GGA-MAPSCRIPT-00F54360", "네놈들이이잇！！"),
    (9, "scenario_map_script", "GGA-MAPSCRIPT-00F54344", "기회는 이번뿐이다！"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate",
        type=Path,
        default=ROOT / "outputs/20260831_battle_event_dialogue/ggen_advance_battle_event_dialogue_main_tip_candidate.gba",
    )
    parser.add_argument(
        "--patch-manifest",
        type=Path,
        default=ROOT / "legacy/analysis/ggen_advance_battle_event_dialogue_main_tip_20260831.json",
    )
    parser.add_argument(
        "--merged",
        type=Path,
        default=ROOT / "integrated/translation/ggen_advance_translation_merged.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "legacy/analysis/ggen_advance_battle_event_dialogue_audit_20260831.json",
    )
    args = parser.parse_args()

    candidate_path = args.candidate if args.candidate.is_absolute() else ROOT / args.candidate
    candidate_path = candidate_path.resolve()
    rom = candidate_path.read_bytes()
    patch_manifest = json.loads(args.patch_manifest.read_text(encoding="utf-8"))
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    records = {row["record_id"]: row for row in merged["records"]}

    table_values = [u32(rom, TABLE_START + index * 4) for index in range(TABLE_CELLS)]
    nonzero = [value for value in table_values if value]
    allocation = patch_manifest["battle_event_dialogue"]["allocation"]
    alloc_start = ROM_BASE + int(allocation["file_offset"], 16)
    alloc_end = ROM_BASE + int(allocation["end_exclusive"], 16)
    gate(len(nonzero) == 49, f"battle-event nonzero table entries: {len(nonzero)}")
    gate(len(set(nonzero)) == 49, "battle-event pointer table contains duplicate targets")
    gate(all(alloc_start <= value < alloc_end for value in nonzero), "battle-event pointer outside relocation allocation")
    gate(
        not any(ROM_BASE + ORIGINAL_POOL_START <= value < ROM_BASE + ORIGINAL_POOL_END for value in nonzero),
        "battle-event pointer still targets the Japanese source pool",
    )

    map_entries: dict[int, tuple[int, int]] = {}
    for index in range(MAP_LOOKUP_ENTRIES):
        offset = MAP_LOOKUP_START + index * MAP_ENTRY_SIZE
        key, target, original_end = struct.unpack_from("<III", rom, offset)
        map_entries[key] = (target, original_end)
    required_map_keys = (0x08F54344, 0x08F54343, 0x08F54360, 0x08F5435F)
    gate(all(key in map_entries for key in required_map_keys), "reported map-script key missing from runtime lookup")

    screenshot_rows = []
    for number, scope, record_id, expected_ko in SCREENSHOTS:
        row = records.get(record_id)
        gate(row is not None, f"screenshot {number} record missing: {record_id}")
        gate(row.get("source_scope") == scope, f"screenshot {number} scope mismatch")
        gate(row.get("translation_status") == "translated", f"screenshot {number} is not translated")
        translation = str(row.get("translation_ko") or "")
        gate(expected_ko in translation, f"screenshot {number} Korean text mismatch")
        screenshot_rows.append(
            {
                "screenshot": number,
                "scope": scope,
                "record_id": record_id,
                "source_text": row.get("source_text"),
                "translation_ko": translation,
                "runtime_contract": (
                    "49-cell battle-event owner table relocated"
                    if scope == "battle_event_dialogue"
                    else "existing map-script runtime lookup preserved"
                ),
            }
        )

    output = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_event_dialogue_reported_path_audit",
        "candidate": {
            "path": str(candidate_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(rom),
        },
        "battle_event_table": {
            "file_offset": f"0x{TABLE_START:08X}",
            "shape": [256, 23],
            "cells": TABLE_CELLS,
            "nonzero_entries": len(nonzero),
            "unique_targets": len(set(nonzero)),
            "all_targets_in_new_allocation": True,
            "japanese_pool_targets_remaining": 0,
            "original_japanese_pool_preserved": patch_manifest["verification"]["original_japanese_pool_unchanged"],
        },
        "map_script_regression": {
            "lookup_table_file_offset": f"0x{MAP_LOOKUP_START:08X}",
            "lookup_entries": MAP_LOOKUP_ENTRIES,
            "reported_text_and_opcode_keys": [f"0x{key:08X}" for key in required_map_keys],
            "all_reported_keys_present": True,
        },
        "reported_screenshots": screenshot_rows,
        "verification": {
            "result": "PASS",
            "reported_screenshots_covered": len(screenshot_rows),
            "battle_event_similar_cases_covered": len(nonzero),
            "unexpected_changed_byte_count": patch_manifest["verification"]["unexpected_changed_byte_count"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["verification"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
