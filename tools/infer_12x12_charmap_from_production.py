#!/usr/bin/env python3
"""Infer additional 12x12 identities from complete production rows."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    master = json.loads(Path("legacy/analysis/stage2_translation_sheet_rows_20260827.json").read_text(encoding="utf-8"))
    dictionary = json.loads(Path("legacy/analysis/dictionary_comparison_20260827.json").read_text(encoding="utf-8"))
    seed = json.loads(Path("font_tables/ggen_advance_japanese_charmap_seed_20260826.json").read_text(encoding="utf-8"))
    bijection = dictionary["slot_bijection_8x16_to_12x12"]

    slot_votes: defaultdict[int, Counter[str]] = defaultdict(Counter)
    used_rows: list[str] = []
    rejected_rows: list[dict[str, object]] = []
    for row in master["records"]:
        if not row.get("source_decode_complete"):
            continue
        source = str(row.get("source_text") or "")
        slots = [int(value, 16) for value in row.get("slots", [])]
        if not source or "<" in source or ">" in source or len(source) != len(slots):
            rejected_rows.append({"record_id": row.get("record_id"), "reason": "length_or_marker", "source": source})
            continue
        used_rows.append(str(row["record_id"]))
        for slot, char in zip(slots, source):
            slot_votes[slot][char] += 1

    stable_8x16: dict[int, str] = {}
    ambiguous_8x16: dict[int, dict[str, int]] = {}
    for slot, votes in slot_votes.items():
        if len(votes) == 1:
            stable_8x16[slot] = next(iter(votes))
        else:
            top = votes.most_common()
            if len(top) >= 2 and top[0][1] > top[1][1]:
                stable_8x16[slot] = top[0][0]
            ambiguous_8x16[slot] = dict(top)

    transferred: dict[int, str] = {}
    for small_slot, char in stable_8x16.items():
        large_label = bijection.get(f"0x{small_slot:04X}")
        if large_label is not None:
            transferred[int(large_label, 16)] = char

    seed_mapping = {int(slot, 16): char for slot, char in seed["verified_charmap"].items()}
    conflicts = []
    for slot, char in transferred.items():
        if slot in seed_mapping and seed_mapping[slot] != char:
            conflicts.append({"slot": f"0x{slot:04X}", "seed": seed_mapping[slot], "inferred": char})

    report = {
        "complete_source_row_count": len(used_rows),
        "slot_observation_count": len(slot_votes),
        "stable_8x16_slot_count": len(stable_8x16),
        "ambiguous_8x16_slot_count": len(ambiguous_8x16),
        "transferred_12x12_slot_count": len(transferred),
        "seed_conflict_count": len(conflicts),
        "stable_8x16": {f"0x{slot:04X}": char for slot, char in sorted(stable_8x16.items())},
        "transferred_12x12": {f"0x{slot:04X}": char for slot, char in sorted(transferred.items())},
        "ambiguous_8x16": {f"0x{slot:04X}": votes for slot, votes in sorted(ambiguous_8x16.items())},
        "seed_conflicts": conflicts,
        "sample_row_ids": used_rows[:20],
    }
    out = Path("legacy/analysis/production_inferred_12x12_charmap_20260827.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "complete_source_row_count", "slot_observation_count", "stable_8x16_slot_count",
        "ambiguous_8x16_slot_count", "transferred_12x12_slot_count", "seed_conflict_count")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
