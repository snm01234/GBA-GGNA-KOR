#!/usr/bin/env python3
"""Dump the current production/UI 8x16 remaining unique-slot catalog.

Read-only helper used by the 2026-08-29 remaining-slot analysis split.
Writes every remaining unique slot (currently ~683) with hold reason,
semantic-category mix, decoded sample frames, and parallel-work buckets.
Does not modify charmap/source/ROM.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import audit_ggen_advance_8x16_remaining_current as audit

ROOT = Path(__file__).resolve().parent.parent
OUT_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_remaining_683_catalog_20260829.json"
QUARANTINE = {0x03D9, 0x0101, 0x05F2, 0x0514, 0x0652}

SHORT_LABEL_CATEGORIES = {
    "series_title",
    "stage_location_name",
    "stage_code",
    "unit_name",
    "unit_name_alternate",
    "weapon_name",
    "weapon_name_alias",
    "character_name",
    "upgrade_part_name",
    "unit_defense_ability",
    "unit_ai_type",
}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged", type=Path, default=audit.MERGED_DEFAULT)
    ap.add_argument("--map8", type=Path, default=audit.MAP8_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    for path in (args.merged, args.map8, args.out):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    fixed = audit.load_map(args.map8)
    slot_freq: Counter[int] = Counter()
    slot_scopes: dict[int, Counter[str]] = defaultdict(Counter)
    slot_cats: dict[int, Counter[str]] = defaultdict(Counter)
    single_frames: dict[int, Counter[str]] = defaultdict(Counter)
    samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    decoded_samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    partial_rows = 0
    closed_rows = 0
    excluded = 0

    for row in merged.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        scope = str(row.get("source_scope", ""))
        if scope not in {"production", "non_scenario_ui"}:
            continue
        if str(row.get("semantic_category", "")) in audit.NON_8X16_CATEGORIES:
            excluded += 1
            continue
        unresolved: list[int] = []
        seen: set[int] = set()
        for raw in row.get("source_unresolved_slots", []):
            try:
                slot = int(str(raw), 16)
            except (TypeError, ValueError):
                continue
            if slot in audit.RESERVED or slot in fixed or slot in seen:
                continue
            seen.add(slot)
            unresolved.append(slot)
        if not unresolved:
            closed_rows += 1
            continue
        partial_rows += 1
        frame = audit.decode(str(row.get("source_text", "")), fixed).replace("\n", " / ")
        category = str(row.get("semantic_category", ""))
        for slot in unresolved:
            slot_freq[slot] += 1
            slot_scopes[slot][scope] += 1
            slot_cats[slot][category] += 1
            if len(decoded_samples[slot]) < 8:
                decoded_samples[slot].append({
                    "record_id": row.get("record_id"),
                    "scope": scope,
                    "semantic_category": category,
                    "decoded_text": frame,
                    "unresolved_count": len(unresolved),
                    "unresolved_slots": [f"0x{item:04X}" for item in unresolved],
                })
        if len(unresolved) == 1:
            slot = unresolved[0]
            single_frames[slot][frame] += 1
            if len(samples[slot]) < 6:
                samples[slot].append({
                    "record_id": row.get("record_id"),
                    "scope": scope,
                    "semantic_category": category,
                    "decoded_text": frame,
                })

    holds: list[dict[str, Any]] = []
    hold_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    for slot, count in slot_freq.most_common():
        frames = single_frames.get(slot, Counter())
        if not frames:
            reason = "no_single_unknown"
        elif len(frames) == 1:
            reason = "single_collocation"
        else:
            reason = "mixed_frames_held"
        cats = slot_cats[slot]
        short_label_hits = sum(cats[cat] for cat in SHORT_LABEL_CATEGORIES if cat in cats)
        quarantined = slot in QUARANTINE
        if quarantined:
            bucket = "quarantine"
        elif reason == "single_collocation":
            bucket = "single_collocation"
        elif reason == "mixed_frames_held":
            bucket = "mixed_frames"
        elif short_label_hits >= max(1, count // 2):
            bucket = "no_single_unknown_short_label"
        elif count >= 20:
            bucket = "no_single_unknown_high_freq"
        elif count >= 5:
            bucket = "no_single_unknown_mid_freq"
        else:
            bucket = "no_single_unknown_low_freq"
        hold_counts[reason] += 1
        bucket_counts[bucket] += 1
        holds.append({
            "slot": f"0x{slot:04X}",
            "pending_records": count,
            "scopes": dict(slot_scopes[slot]),
            "semantic_categories": dict(cats),
            "hold_reason": reason,
            "quarantined": quarantined,
            "bucket": bucket,
            "short_label_hits": short_label_hits,
            "single_frame_count": len(frames),
            "top_frames": [frame for frame, _ in frames.most_common(6)],
            "samples": samples.get(slot, []),
            "decoded_samples": decoded_samples.get(slot, []),
        })

    buckets: dict[str, list[str]] = defaultdict(list)
    for item in holds:
        buckets[item["bucket"]].append(item["slot"])

    payload = {
        "schema_version": 1,
        "verified_8x16_slots": len(fixed),
        "pending_8x16_rows": partial_rows,
        "newly_fully_decoded_pending_rows": closed_rows,
        "remaining_unique_text_slots": len(slot_freq),
        "excluded_non_8x16_rows": excluded,
        "hold_counts": dict(hold_counts),
        "bucket_counts": dict(bucket_counts),
        "quarantine_slots": [f"0x{slot:04X}" for slot in sorted(QUARANTINE)],
        "working_unique_slots": len(slot_freq) - sum(1 for slot in QUARANTINE if slot in slot_freq),
        "buckets": {key: value for key, value in buckets.items()},
        "slots": holds,
        "notes": [
            "Read-only catalog of current remaining unique 8x16 production/UI slots.",
            "configuration_option_text is excluded (renderer-proven 12x12).",
            "quarantine slots are inventory-only and must not be auto-promoted.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "out": str(args.out.relative_to(ROOT)),
        "remaining_unique_text_slots": payload["remaining_unique_text_slots"],
        "hold_counts": payload["hold_counts"],
        "bucket_counts": payload["bucket_counts"],
        "working_unique_slots": payload["working_unique_slots"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
