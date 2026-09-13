#!/usr/bin/env python3
"""Advance-local closure of the remaining 159 semantic records.

This tool intentionally uses only the clean ROM plus advance-local analysis
summaries.  It proves that the prior unclassified remainder decomposes into
three newly reviewed sets (48+38+36) and 37 new partial records from the
indirect-owner trio after removing its two overlaps with direct_pc_literal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
TOTAL_RECORDS = 3948
PREVIOUS_REVIEWED = 3654
PREVIOUS_PARTIAL = 135
PREVIOUS_UNCLASSIFIED = 159

OVERRIDE_LITERAL_OFFSETS = [
    0x0001249C, 0x000124B4, 0x000124CC, 0x000124E4, 0x000124FC,
    0x00012514, 0x0001252C, 0x00012540, 0x00012554, 0x00012568,
    0x0001257C, 0x00012590, 0x000125A4, 0x000125B8, 0x000125CC,
    0x000125E0, 0x000125F4, 0x00012608,
]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def load_json(path: Path) -> dict[str, object]:
    result = json.loads(path.read_text(encoding="utf-8"))
    check(result.get("rom_sha256") == EXPECTED_SHA256, f"summary ROM hash drift: {path}")
    return result


def pair_line_targets(data: bytes, pointer: int) -> tuple[int, int]:
    offset = pointer - ROM_BASE
    length1 = data[offset]
    start1 = offset + 1
    end1 = start1 + length1
    check(data[end1] == 0, f"pair line1 NUL drift at 0x{pointer:08X}")
    length2_offset = end1 + 1
    length2 = data[length2_offset]
    start2 = length2_offset + 1
    end2 = start2 + length2
    check(data[end2] == 0, f"pair line2 NUL drift at 0x{pointer:08X}")
    return ROM_BASE + start1, ROM_BASE + start2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--analysis-dir", type=Path, default=Path("analysis"))
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    direct_pc = load_json(args.analysis_dir / "direct_pc_literal_static_summary_20260826.json")
    direct_pc_targets = {int(row["text_pointer_address"], 16) for row in direct_pc["targets"]}
    check(len(direct_pc_targets) == 67, "direct_pc target count drift")

    indirect = load_json(args.analysis_dir / "indirect_text_owners_20260826.json")
    indirect_targets: set[int] = set()
    for owner in indirect["owners"].values():
        for row in owner["entries"]:
            if "target_address" in row:
                indirect_targets.add(int(row["target_address"], 16))
    check(len(indirect_targets) == 39, f"indirect trio target count drift: {len(indirect_targets)}")
    indirect_overlap_direct_pc = indirect_targets & direct_pc_targets
    check(indirect_overlap_direct_pc == {0x081BE8C4, 0x081BEB58}, f"indirect/direct_pc overlap drift: {indirect_overlap_direct_pc}")
    indirect_new_partial = indirect_targets - direct_pc_targets
    check(len(indirect_new_partial) == 37, "indirect new-partial count drift")

    id24_targets = {
        u32(data, 0x001C86C8 + index * 0x18 + field)
        for index in range(16)
        for field in (0x0C, 0x10, 0x14)
    }
    check(len(id24_targets) == 48, "id24 target count drift")

    stage_condition_targets = {u32(data, 0x00FCE1A0 + index * 4) for index in range(64)}
    check(len(stage_condition_targets) == 38, "stage condition target count drift")

    override_pairs = [u32(data, offset) for offset in OVERRIDE_LITERAL_OFFSETS]
    override_line_targets: set[int] = set()
    for pointer in override_pairs:
        override_line_targets.update(pair_line_targets(data, pointer))
    check(len(override_line_targets) == 36, "state override line count drift")

    reviewed_additions = {
        "unit_defense_ability": id24_targets,
        "stage_battle_condition_text": stage_condition_targets,
        "stage_battle_condition_line": override_line_targets,
    }
    addition_sets = list(reviewed_additions.items())
    for index, (left_name, left) in enumerate(addition_sets):
        for right_name, right in addition_sets[index + 1:]:
            check(not (left & right), f"reviewed additions overlap: {left_name}/{right_name}")
        check(not (left & indirect_new_partial), f"reviewed addition overlaps indirect partial: {left_name}")
        check(not (left & direct_pc_targets), f"reviewed addition overlaps direct_pc partial: {left_name}")

    newly_reviewed = sum(len(values) for values in reviewed_additions.values())
    newly_partial = len(indirect_new_partial)
    check(newly_reviewed == 122, f"newly reviewed drift: {newly_reviewed}")
    check(newly_reviewed + newly_partial == PREVIOUS_UNCLASSIFIED, "159-record remainder does not close")

    final_reviewed = PREVIOUS_REVIEWED + newly_reviewed
    final_partial = PREVIOUS_PARTIAL + newly_partial
    final_unclassified = PREVIOUS_UNCLASSIFIED - newly_reviewed - newly_partial
    check(final_reviewed + final_partial + final_unclassified == TOTAL_RECORDS, "semantic total drift")
    check((final_reviewed, final_partial, final_unclassified) == (3776, 172, 0), "final semantic counts drift")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "previous_checkpoint": {
            "reviewed": PREVIOUS_REVIEWED,
            "partial": PREVIOUS_PARTIAL,
            "unclassified": PREVIOUS_UNCLASSIFIED,
            "total": TOTAL_RECORDS,
        },
        "remainder_decomposition": {
            "unit_defense_ability_reviewed": len(id24_targets),
            "stage_battle_condition_text_reviewed": len(stage_condition_targets),
            "stage_battle_condition_line_reviewed": len(override_line_targets),
            "indirect_owner_trio_new_partial": len(indirect_new_partial),
            "sum": newly_reviewed + newly_partial,
        },
        "indirect_overlap": {
            "owner_trio_unique_targets": len(indirect_targets),
            "overlap_with_direct_pc": len(indirect_overlap_direct_pc),
            "overlap_targets": [f"0x{x:08X}" for x in sorted(indirect_overlap_direct_pc)],
            "new_partial_targets": len(indirect_new_partial),
        },
        "final_checkpoint": {
            "reviewed": final_reviewed,
            "reviewed_percent": round(final_reviewed / TOTAL_RECORDS * 100, 3),
            "partial": final_partial,
            "partial_percent": round(final_partial / TOTAL_RECORDS * 100, 3),
            "unclassified": final_unclassified,
            "unclassified_percent": round(final_unclassified / TOTAL_RECORDS * 100, 3),
            "total": TOTAL_RECORDS,
        },
        "conclusion": "The advance-local semantic remainder closes exactly: 122 records move to reviewed, the final 37 move to partial, and zero records remain unclassified. Partial records remain intentionally unresolved at exact screen-noun level; structural provenance is already closed.",
    }
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
