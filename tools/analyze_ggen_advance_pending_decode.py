#!/usr/bin/env python3
"""Re-decode pending unified-sheet rows with current Japanese charmaps.

The immutable source keeps unresolved ``<SLOT>`` markers.  This audit applies
font-correct supplements without rewriting that source:

- ``scenario_main`` / ``scenario_dynamic`` use 12x12 maps plus renderer-verified
  compact kana ``0x001D-0x0058``.
- ``production`` / ``non_scenario_ui`` use 8x16 maps.  Reserved leading markers
  ``07F8/07FB/07FC/07FD/07FE/0813`` stay unresolved on purpose.

The report is the next translation-batch input: fully closed rows, remaining
high-frequency slots, and sample recovered Japanese strings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
DEFAULT_MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
DEFAULT_MAP8 = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_pending_decode_audit_20260828.json"

SLOT_RE = re.compile(r"<([0-9A-Fa-f]{4})>")
# Map-script inline dialogue also uses the 12x12 scenario renderer.  Keeping it
# in the same scope makes the game-wide audit include the 326 rows that were
# previously counted as an unsupported/partial scope even after their slots
# were fully identified.
SCENARIO_SCOPES = {"scenario_main", "scenario_dynamic", "scenario_map_script"}
EIGHT_SCOPES = {"production", "non_scenario_ui"}
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}

CORRECTED_LOW_KANA = {
    0x001D: "ぁ", 0x001E: "あ", 0x001F: "い", 0x0020: "う",
    0x0021: "ぇ", 0x0022: "え", 0x0023: "ぉ", 0x0024: "お",
    0x0025: "か", 0x0026: "が", 0x0027: "き", 0x0028: "く",
    0x0029: "け", 0x002A: "げ", 0x002B: "こ", 0x002C: "さ",
    0x002D: "し", 0x002E: "じ", 0x002F: "す", 0x0030: "ず",
    0x0031: "せ", 0x0032: "そ", 0x0033: "ぞ", 0x0034: "た",
    0x0035: "だ", 0x0036: "ち", 0x0037: "っ", 0x0038: "つ",
    0x0039: "て", 0x003A: "で", 0x003B: "と", 0x003C: "ど",
    0x003D: "な", 0x003E: "に", 0x003F: "ぬ", 0x0040: "ね",
    0x0041: "の", 0x0042: "は", 0x0043: "ば", 0x0044: "ひ",
    0x0045: "び", 0x0046: "ふ", 0x0047: "ま", 0x0048: "み",
    0x0049: "む", 0x004A: "め", 0x004B: "も", 0x004C: "ゃ",
    0x004D: "や", 0x004E: "ゅ", 0x004F: "ょ", 0x0050: "よ",
    0x0051: "ら", 0x0052: "り", 0x0053: "る", 0x0054: "れ",
    0x0055: "ろ", 0x0056: "わ", 0x0057: "を", 0x0058: "ん",
}


def load_map(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(slot), 16): str(char) for slot, char in payload.get("verified_charmap", {}).items()}


def merge_maps(paths: list[Path], *, apply_kana: bool) -> dict[int, str]:
    combined: dict[int, str] = {}
    for path in paths:
        combined.update(load_map(path))
    if apply_kana:
        combined.update(CORRECTED_LOW_KANA)
    return combined


def decode_text(source: str, charmap: dict[int, str]) -> tuple[str, list[int]]:
    missing: list[int] = []

    def replace(match: re.Match[str]) -> str:
        slot = int(match.group(1), 16)
        if slot in RESERVED:
            missing.append(slot)
            return match.group(0)
        char = charmap.get(slot)
        if char is None:
            missing.append(slot)
            return match.group(0)
        return char

    decoded = SLOT_RE.sub(replace, source)
    # Preserve order while uniquing.
    seen: set[int] = set()
    unique: list[int] = []
    for slot in missing:
        if slot not in seen:
            seen.add(slot)
            unique.append(slot)
    return decoded, unique


def remaining_slots(row: dict[str, Any], charmap: dict[int, str]) -> list[int]:
    leftover: list[int] = []
    seen: set[int] = set()
    for raw in row.get("source_unresolved_slots", []):
        try:
            slot = int(str(raw), 16)
        except (TypeError, ValueError):
            continue
        if slot in RESERVED:
            leftover.append(slot)
            seen.add(slot)
            continue
        if slot in charmap or slot in seen:
            continue
        seen.add(slot)
        leftover.append(slot)
    return leftover


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--map12", type=Path, action="append", default=[])
    parser.add_argument("--map8", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-limit", type=int, default=80)
    args = parser.parse_args(argv)

    map12_paths = args.map12 or [DEFAULT_MAP12]
    map8_paths = args.map8 or [DEFAULT_MAP8]
    map12 = merge_maps(map12_paths, apply_kana=True)
    map8 = merge_maps(map8_paths, apply_kana=False)

    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    pending_counts: Counter[str] = Counter()
    closed_counts: Counter[str] = Counter()
    reserved_only_counts: Counter[str] = Counter()
    still_partial: Counter[str] = Counter()
    closed_by_category: Counter[str] = Counter()
    slot_freq: Counter[int] = Counter()
    slot_scope: dict[int, Counter[str]] = defaultdict(Counter)
    slot_category: dict[int, Counter[str]] = defaultdict(Counter)
    newly_closed: list[dict[str, Any]] = []
    reserved_only: list[dict[str, Any]] = []
    decoded_samples: list[dict[str, Any]] = []

    for row in merged.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        scope = str(row.get("source_scope", ""))
        category = str(row.get("semantic_category", ""))
        pending_counts[scope] += 1
        if scope in SCENARIO_SCOPES:
            charmap = map12
        elif scope in EIGHT_SCOPES:
            charmap = map8
        else:
            still_partial[scope] += 1
            continue
        leftover = remaining_slots(row, charmap)
        decoded, marker_missing = decode_text(str(row.get("source_text", "")), charmap)
        leftover_set = set(leftover) | set(marker_missing)
        leftover = sorted(leftover_set)
        text_leftover = [slot for slot in leftover if slot not in RESERVED]
        sample = {
            "record_id": row.get("record_id"),
            "source_scope": scope,
            "semantic_category": category,
            "source_text": row.get("source_text"),
            "decoded_text": decoded,
            "remaining_slots": [f"0x{slot:04X}" for slot in leftover],
        }
        if not leftover:
            closed_counts[scope] += 1
            closed_by_category[f"{scope}:{category}"] += 1
            if len(newly_closed) < args.sample_limit:
                newly_closed.append(sample)
            elif len(decoded_samples) < args.sample_limit:
                decoded_samples.append(sample)
            continue
        if not text_leftover:
            reserved_only_counts[scope] += 1
            closed_by_category[f"{scope}:{category}:reserved_prefix"] += 1
            if len(reserved_only) < args.sample_limit:
                reserved_only.append(sample)
            continue
        still_partial[scope] += 1
        for slot in text_leftover:
            slot_freq[slot] += 1
            slot_scope[slot][scope] += 1
            slot_category[slot][category] += 1
        if len(decoded_samples) < args.sample_limit and SLOT_RE.sub("", decoded) != str(row.get("source_text", "")):
            decoded_samples.append(sample)

    ranked_slots = []
    for slot, count in slot_freq.most_common(80):
        ranked_slots.append({
            "slot": f"0x{slot:04X}",
            "pending_records": count,
            "scopes": dict(slot_scope[slot]),
            "top_categories": [
                {"category": name, "records": n}
                for name, n in slot_category[slot].most_common(6)
            ],
        })

    projection = []
    cumulative = 0
    total_partial = sum(still_partial.values()) or 1
    covered = 0
    for index, (slot, count) in enumerate(slot_freq.most_common(), start=1):
        covered += count
        if index in {10, 25, 50, 100, 200} or index == len(slot_freq):
            projection.append({
                "top_slots": index,
                "occurrence_coverage": round(100.0 * covered / max(1, sum(slot_freq.values())), 3),
            })

    payload = {
        "schema_version": 1,
        "merged": str(args.merged),
        "map12_files": [str(path) for path in map12_paths],
        "map8_files": [str(path) for path in map8_paths],
        "map12_slot_count": len(map12),
        "map8_slot_count": len(map8),
        "pending_translate": dict(pending_counts),
        "fully_decoded": dict(closed_counts),
        "reserved_prefix_only": dict(reserved_only_counts),
        "still_partial": dict(still_partial),
        "fully_decoded_total": sum(closed_counts.values()),
        "reserved_prefix_only_total": sum(reserved_only_counts.values()),
        "still_partial_total": sum(still_partial.values()),
        "remaining_unique_text_slots": len(slot_freq),
        "remaining_text_slot_occurrences": int(sum(slot_freq.values())),
        "closed_by_category": dict(closed_by_category.most_common()),
        "high_frequency_remaining_slots": ranked_slots,
        "coverage_projection": projection,
        "newly_closed_samples": newly_closed,
        "reserved_prefix_samples": reserved_only,
        "partial_improved_samples": decoded_samples,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "map12_slots": len(map12),
        "map8_slots": len(map8),
        "pending_translate": dict(pending_counts),
        "fully_decoded": dict(closed_counts),
        "reserved_prefix_only": dict(reserved_only_counts),
        "still_partial": dict(still_partial),
        "remaining_unique_text_slots": len(slot_freq),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
