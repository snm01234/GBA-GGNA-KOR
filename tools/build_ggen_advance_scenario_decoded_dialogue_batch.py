#!/usr/bin/env python3
"""Bind slot-complete scenario battle lines to natural Korean.

The immutable source_text still contains the uncorrected low-kana draft.
This helper re-decodes each pending scenario record from its original slot
list with the renderer-verified kana plus the 2026-08-28 exact 12x12 offset
map, then emits only lines whose Japanese is complete and is not an unused
battle-bark template (「〜セリフ」 plus ＠ filler).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_pending_decode as audit  # noqa: E402


DEFAULT_MERGED = Path("analysis/ggen_advance_translation_merged_20260827.json")
DEFAULT_SCENARIO = Path("legacy/analysis/scenario_event_translation_source_20260827.json")
DEFAULT_CHARMAP = Path("legacy/analysis/ggen_advance_12x12_offset_charmap_20260828.json")
DEFAULT_KO = Path("legacy/analysis/ggen_advance_scenario_decoded_dialogue_ko_20260828.json")
DEFAULT_OUTPUT = Path(
    "legacy/analysis/ggen_advance_translation_batch_maps/scenario_decoded_dialogue_0208.json"
)


def decode_record(record: dict[str, Any], charmap: dict[int, str]) -> tuple[list[str], bool]:
    parts: list[str] = []
    missing = False
    for segment in record.get("segments", []):
        slots = segment.get("slots") or []
        if not slots:
            continue
        chars: list[str] = []
        for raw in slots:
            slot = int(str(raw), 16)
            char = charmap.get(slot)
            if char is None:
                missing = True
                chars.append(f"<{slot:04X}>")
            else:
                chars.append(char)
        parts.append("".join(chars))
    return parts, missing


def joined_key(parts: list[str]) -> str:
    return " / ".join(parts)


def build_segments(source_segments: list[dict[str, Any]], ko_lines: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    for segment in source_segments:
        if not segment.get("slots"):
            result.append("")
            continue
        result.append(ko_lines[index])
        index += 1
    if index != len(ko_lines):
        raise SystemExit("Korean line count does not match decoded text segments")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--charmap", type=Path, default=DEFAULT_CHARMAP)
    parser.add_argument("--ko", type=Path, default=DEFAULT_KO)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)

    charmap = audit.load_map(args.charmap)
    charmap.update(audit.CORRECTED_LOW_KANA)
    ko_map = json.loads(args.ko.read_text(encoding="utf-8"))["translations"]
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    pending = {
        row["record_id"]
        for row in merged["records"]
        if row.get("translation_status") == "pending" and row.get("source_scope") == "scenario_main"
    }
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    selected: list[dict[str, Any]] = []
    skipped = {"missing_slots": 0, "template": 0, "no_ko": 0}
    for record in scenario["main"]["records"]:
        if record["record_id"] not in pending:
            continue
        parts, missing = decode_record(record, charmap)
        if missing:
            skipped["missing_slots"] += 1
            continue
        key = joined_key(parts)
        if "セリフ" in key:
            skipped["template"] += 1
            continue
        ko_lines = ko_map.get(key)
        if not isinstance(ko_lines, list) or len(ko_lines) != len(parts):
            skipped["no_ko"] += 1
            continue
        translations = build_segments(record.get("segments", []), ko_lines)
        selected.append(
            {
                "record_id": record["record_id"],
                "translation_segments": translations,
                "translation_ko": "\n".join(line for line in ko_lines if line),
                "translation_status": "translated",
                "translator_notes": "slot-complete 12x12 decode with corrected kana; unused セリフ templates excluded",
            }
        )
    if not selected:
        raise SystemExit(f"no scenario dialogue rows; skipped={skipped}")
    payload = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "Natural Korean for slot-complete scenario battle lines after 2026-08-28 glyph expansion.",
        "records": selected,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), "record_count": len(selected), "skipped": skipped}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
