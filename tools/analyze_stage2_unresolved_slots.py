#!/usr/bin/env python3
"""Prioritize unresolved Japanese glyph slots in the 4,069-row translation master."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_stage2_translation_master as master_builder  # noqa: E402
import build_stage2_production_reference_manifest as manifest  # noqa: E402

RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def build_audit(data: bytes) -> dict[str, Any]:
    master = master_builder.build_master(data)
    slot_total: Counter[int] = Counter()
    slot_translate: Counter[int] = Counter()
    slot_preserve: Counter[int] = Counter()
    slot_records: dict[int, set[str]] = defaultdict(set)
    slot_translate_records: dict[int, set[str]] = defaultdict(set)
    slot_semantics: dict[int, Counter[str]] = defaultdict(Counter)
    slot_families: dict[int, Counter[str]] = defaultdict(Counter)
    slot_categories: dict[int, Counter[str]] = defaultdict(Counter)

    translate_unresolved_occurrences = 0
    preserve_unresolved_occurrences = 0
    translate_total_units = 0
    translate_mapped_units = 0

    for row in master["records"]:
        translate = row["translation_policy"] == "translate"
        if translate:
            translate_total_units += int(row["total_units"])
            translate_mapped_units += int(row["mapped_units"])
        semantic = str(row["semantic_category"])
        category = str(row["primary_category"])
        row_families = [str(x) for x in row["source_families"]]
        unresolved_sequence = [int(x, 16) for x in row["slots"] if int(x, 16) in {int(s, 16) for s in row["unresolved_slots"]}]
        # Preserve occurrence multiplicity while unresolved_slots itself is unique-per-row.
        for slot in unresolved_sequence:
            slot_total[slot] += 1
            slot_records[slot].add(row["record_id"])
            slot_semantics[slot][semantic] += 1
            slot_categories[slot][category] += 1
            for family in row_families:
                slot_families[slot][family] += 1
            if translate:
                slot_translate[slot] += 1
                slot_translate_records[slot].add(row["record_id"])
                translate_unresolved_occurrences += 1
            else:
                slot_preserve[slot] += 1
                preserve_unresolved_occurrences += 1

    unresolved_slots = set(slot_total)
    check(len(unresolved_slots) == 1046, f"unresolved slot count drift: {len(unresolved_slots)}")

    translate_slots = {slot for slot, count in slot_translate.items() if count > 0}
    preserve_only_slots = {slot for slot in unresolved_slots if slot_translate[slot] == 0}

    ranked = []
    for slot in sorted(unresolved_slots, key=lambda s: (-slot_translate[s], -slot_total[s], s)):
        ranked.append({
            "slot": f"0x{slot:04X}",
            "translate_occurrences": slot_translate[slot],
            "total_occurrences": slot_total[slot],
            "preserve_occurrences": slot_preserve[slot],
            "translate_record_count": len(slot_translate_records[slot]),
            "total_record_count": len(slot_records[slot]),
            "reserved": slot in RESERVED,
            "top_semantic_categories": [
                {"category": name, "occurrences": count}
                for name, count in slot_semantics[slot].most_common(8)
            ],
            "top_structural_categories": [
                {"category": name, "occurrences": count}
                for name, count in slot_categories[slot].most_common(5)
            ],
            "top_source_families": [
                {"family": name, "occurrences": count}
                for name, count in slot_families[slot].most_common(8)
            ],
        })

    cumulative = 0
    cumulative_rows = []
    nonreserved_ranked = [row for row in ranked if not row["reserved"] and row["translate_occurrences"] > 0]
    for index, row in enumerate(nonreserved_ranked, start=1):
        cumulative += int(row["translate_occurrences"])
        if index in {10, 25, 50, 100, 200, 400, 800} or index == len(nonreserved_ranked):
            cumulative_rows.append({
                "top_slots": index,
                "resolved_translate_occurrences_if_all_mapped": cumulative,
                "share_of_current_translate_unresolved_occurrences_percent": round(
                    cumulative * 100 / translate_unresolved_occurrences, 3
                ) if translate_unresolved_occurrences else 0.0,
                "projected_translate_mapped_percent": round(
                    (translate_mapped_units + cumulative) * 100 / translate_total_units, 3
                ) if translate_total_units else 100.0,
            })

    fallback_rows = [row for row in master["records"] if row["primary_category"] == manifest.FALLBACK_CATEGORY]
    fallback_slots: Counter[int] = Counter()
    for row in fallback_rows:
        unresolved_set = {int(s, 16) for s in row["unresolved_slots"]}
        for slot_text in row["slots"]:
            slot = int(slot_text, 16)
            if slot in unresolved_set:
                fallback_slots[slot] += 1

    return {
        "schema_version": 1,
        "scope": "production translation-priority unresolved Japanese glyph audit",
        "source": master["source"],
        "summary": {
            "master_records": master["summary"]["records"],
            "translate_records": master["summary"]["translate_records"],
            "preserve_records": master["summary"]["preserve_records"],
            "unresolved_unique_slots_total": len(unresolved_slots),
            "unresolved_unique_slots_in_translate_records": len(translate_slots),
            "unresolved_unique_slots_preserve_only": len(preserve_only_slots),
            "translate_unresolved_occurrences": translate_unresolved_occurrences,
            "preserve_unresolved_occurrences": preserve_unresolved_occurrences,
            "translate_total_expanded_units": translate_total_units,
            "translate_current_mapped_units": translate_mapped_units,
            "translate_current_mapped_percent": round(translate_mapped_units * 100 / translate_total_units, 3),
            "reserved_unresolved_slots": len(unresolved_slots & RESERVED),
            "fallback_unresolved_unique_slots": len(fallback_slots),
        },
        "priority_projection": cumulative_rows,
        "top_priority_slots": ranked[:200],
        "preserve_only_slots": [f"0x{x:04X}" for x in sorted(preserve_only_slots)],
        "fallback_top_unresolved_slots": [
            {"slot": f"0x{slot:04X}", "occurrences": count}
            for slot, count in fallback_slots.most_common(100)
        ],
        "next_gate": (
            "Resolve high-frequency non-reserved slots using source-family known plaintext/context first. "
            "Do not assign Unicode from frequency alone."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    data = args.rom.read_bytes()
    check(hashlib.sha256(data).hexdigest() == manifest.ROM_SHA256, "ROM hash drift")
    report = build_audit(data)
    visible = {
        "schema_version": report["schema_version"],
        "scope": report["scope"],
        "source": report["source"],
        "summary": report["summary"],
        "priority_projection": report["priority_projection"],
        "top_priority_slots": report["top_priority_slots"][:50],
        "fallback_top_unresolved_slots": report["fallback_top_unresolved_slots"][:30],
        "next_gate": report["next_gate"],
    } if args.summary_only else report
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
