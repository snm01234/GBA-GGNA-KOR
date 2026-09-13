#!/usr/bin/env python3
"""Read-only current 8x16 pending/slot audit using the live supplement."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MERGED_DEFAULT = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"
MAP8_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
# Renderer proof: fixed16/fixed40 option matrices initialize the draw object
# through 0x080004B8, which sets object+0x64 bit0.  0x08001238 dispatches
# bit0=1 to the 12x12 renderer (0x08001354), so these rows are not 8x16.
NON_8X16_CATEGORIES = {"configuration_option_text"}
SLOT_RE = re.compile(r"<([0-9A-Fa-f]{4})>")


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(k), 16): str(v) for k, v in payload["verified_charmap"].items()}


def decode(source: str, charmap: dict[int, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        slot = int(match.group(1), 16)
        return charmap.get(slot, match.group(0)) if slot not in RESERVED else match.group(0)
    return SLOT_RE.sub(repl, source)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged", type=Path, default=MERGED_DEFAULT)
    ap.add_argument("--map8", type=Path, default=MAP8_DEFAULT)
    ap.add_argument("--top", type=int, default=80)
    args = ap.parse_args(argv)
    for path in (args.merged, args.map8):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    fixed = load_map(args.map8)
    row_classes = Counter()
    row_classes_by_scope: dict[str, Counter[str]] = defaultdict(Counter)
    slot_freq: Counter[int] = Counter()
    slot_scopes: dict[int, Counter[str]] = defaultdict(Counter)
    single_frames: dict[int, Counter[str]] = defaultdict(Counter)
    single_samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    partial_rows = 0
    closed_rows = 0
    excluded_non_8x16_rows = 0

    for row in merged.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        scope = str(row.get("source_scope", ""))
        if scope not in {"production", "non_scenario_ui"}:
            continue
        if str(row.get("semantic_category", "")) in NON_8X16_CATEGORIES:
            excluded_non_8x16_rows += 1
            continue
        unresolved = []
        seen = set()
        for raw in row.get("source_unresolved_slots", []):
            try:
                slot = int(str(raw), 16)
            except (TypeError, ValueError):
                continue
            if slot in RESERVED or slot in fixed or slot in seen:
                continue
            seen.add(slot)
            unresolved.append(slot)
        if not unresolved:
            closed_rows += 1
            row_classes["fully_decoded"] += 1
            row_classes_by_scope[scope]["fully_decoded"] += 1
            continue
        partial_rows += 1
        if len(unresolved) == 1:
            kind = "single_unknown_text_slot"
        elif len(unresolved) <= 3:
            kind = "few_unknown_text_slots"
        else:
            kind = "many_unknown_text_slots"
        row_classes[kind] += 1
        row_classes_by_scope[scope][kind] += 1
        for slot in unresolved:
            slot_freq[slot] += 1
            slot_scopes[slot][scope] += 1
        if len(unresolved) == 1:
            slot = unresolved[0]
            frame = decode(str(row.get("source_text", "")), fixed).replace("\n", " / ")
            single_frames[slot][frame] += 1
            if len(single_samples[slot]) < 6:
                single_samples[slot].append({
                    "record_id": row.get("record_id"),
                    "scope": scope,
                    "semantic_category": row.get("semantic_category"),
                    "decoded_text": frame,
                })

    holds = []
    hold_counts = Counter()
    for slot, count in slot_freq.most_common():
        frames = single_frames.get(slot, Counter())
        if not frames:
            reason = "no_single_unknown"
        elif len(frames) == 1:
            reason = "single_collocation"
        else:
            reason = "mixed_frames_held"
        hold_counts[reason] += 1
        holds.append({
            "slot": f"0x{slot:04X}",
            "pending_records": count,
            "scopes": dict(slot_scopes[slot]),
            "hold_reason": reason,
            "single_frame_count": len(frames),
            "top_frames": [frame for frame, _ in frames.most_common(4)],
            "samples": single_samples.get(slot, []),
        })

    payload = {
        "schema_version": 1,
        "verified_8x16_slots": len(fixed),
        "pending_8x16_rows": partial_rows,
        "newly_fully_decoded_pending_rows": closed_rows,
        "classification": dict(row_classes),
        "classification_by_scope": {scope: dict(counts) for scope, counts in row_classes_by_scope.items()},
        "remaining_unique_text_slots": len(slot_freq),
        "excluded_non_8x16_rows": excluded_non_8x16_rows,
        "excluded_non_8x16_categories": sorted(NON_8X16_CATEGORIES),
        "hold_counts": dict(hold_counts),
        "high_frequency_remaining_slots": holds[: args.top],
        "single_collocation_slots": [item for item in holds if item["hold_reason"] == "single_collocation"],
        "mixed_frames_slots": [item for item in holds if item["hold_reason"] == "mixed_frames_held"],
        "notes": [
            "Read-only; no source/charmap/ROM changes.",
            "configuration_option_text is excluded from 8x16 counts: 0x080004B8 sets renderer object bit0=1 and 0x08001238 dispatches that mode to 0x08001354 (12x12).",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
