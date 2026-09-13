#!/usr/bin/env python3
"""Check whether the dynamic 12x12 streams align with the known weapon list."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    source_path = Path("legacy/analysis/scenario_event_translation_source_20260827.json")
    master_path = Path("legacy/analysis/stage2_translation_sheet_rows_20260827.json")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    master = json.loads(master_path.read_text(encoding="utf-8"))
    dynamic = sorted(
        source["dynamic"]["records"], key=lambda row: int(row["target_file_offset"], 16)
    )
    weapons = sorted(
        [row for row in master["records"] if row.get("semantic_category") == "weapon_name"],
        key=lambda row: int(row["target_file_offset"], 16),
    )
    if len(dynamic) != len(weapons):
        raise SystemExit(f"count mismatch: dynamic={len(dynamic)} weapons={len(weapons)}")

    fully_aligned: list[int] = []
    skipped: list[dict[str, object]] = []
    slot_to_char: dict[int, str] = {}
    char_to_slot: dict[str, int] = {}
    conflicts: list[dict[str, object]] = []
    samples: list[dict[str, object]] = []
    for index, (dynamic_row, weapon_row) in enumerate(zip(dynamic, weapons)):
        source_text = weapon_row.get("source_text") or weapon_row.get("decoded_text_seed") or ""
        slots = [int(value, 16) for value in dynamic_row["slots"]]
        if "<" not in source_text and ">" not in source_text and len(source_text) == len(slots):
            fully_aligned.append(index)
            for slot, char in zip(slots, source_text):
                if slot in slot_to_char and slot_to_char[slot] != char:
                    conflicts.append(
                        {"kind": "slot", "index": index, "slot": f"0x{slot:04X}",
                         "old": slot_to_char[slot], "new": char}
                    )
                if char in char_to_slot and char_to_slot[char] != slot:
                    conflicts.append(
                        {"kind": "char", "index": index, "char": char,
                         "old": f"0x{char_to_slot[char]:04X}", "new": f"0x{slot:04X}"}
                    )
                slot_to_char[slot] = char
                char_to_slot[char] = slot
        else:
            skipped.append(
                {"index": index, "target": dynamic_row["target_file_offset"],
                 "expected": source_text, "slot_count": len(slots),
                 "expected_length": len(source_text)}
            )
        if index < 20:
            samples.append(
                {"index": index, "target": dynamic_row["target_file_offset"],
                 "expected": source_text, "translation": weapon_row.get("translation_ko", ""),
                 "slots": dynamic_row["slots"]}
            )

    report = {
        "dynamic_count": len(dynamic),
        "weapon_count": len(weapons),
        "fully_aligned_count": len(fully_aligned),
        "skipped_count": len(skipped),
        "conflict_count": len(conflicts),
        "slot_mapping_count": len(slot_to_char),
        "fully_aligned_indices": fully_aligned,
        "skipped": skipped,
        "conflicts": conflicts,
        "slot_to_char": {f"0x{slot:04X}": char for slot, char in sorted(slot_to_char.items())},
        "samples": samples,
    }
    out = Path("legacy/analysis/scenario_event_12x12_alignment_20260827.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "dynamic_count", "weapon_count", "fully_aligned_count", "skipped_count",
        "conflict_count", "slot_mapping_count")}, ensure_ascii=False, indent=2))
    print("samples:")
    print(json.dumps(samples[:8], ensure_ascii=False, indent=2))
    print("first_conflicts:")
    print(json.dumps(conflicts[:12], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
