#!/usr/bin/env python3
"""Bind fully-decoded pending rows to curated Korean maps. No ROM write."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402

DEFAULT_SOURCE = ROOT / "analysis" / "ggen_advance_unified_source_20260827.json"
DEFAULT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
DEFAULT_SCENARIO = ROOT / "analysis" / "scenario_event_translation_source_20260827.json"
DEFAULT_MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
DEFAULT_CLEAN = ROOT / "analysis" / "_tmp_fd_clean.json"


def decode_parts(record: dict[str, Any], charmap: dict[int, str]) -> tuple[list[str], list[str], bool]:
    """Return (all_segment_texts_or_empty, text_parts, missing)."""
    all_segs: list[str] = []
    text_parts: list[str] = []
    missing = False
    for segment in record.get("segments", []):
        slots = segment.get("slots") or []
        if not slots:
            all_segs.append("")
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
        text = "".join(chars)
        all_segs.append(text)
        text_parts.append(text)
    return all_segs, text_parts, missing


def joined_key(parts: list[str]) -> str:
    return " / ".join(parts)


def build_segments(all_segs: list[str], ko_lines: list[str]) -> list[str]:
    result: list[str] = []
    index = 0
    for seg in all_segs:
        if not seg:
            result.append("")
            continue
        result.append(ko_lines[index])
        index += 1
    if index != len(ko_lines):
        raise SystemExit(f"Korean line count {len(ko_lines)} does not match text segments {index}")
    return result


def load_ko_maps(paths: list[Path]) -> dict[str, list[str]]:
    combined: dict[str, list[str]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        block = payload.get("translations", payload)
        for key, value in block.items():
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise SystemExit(f"bad translation for {key!r} in {path}")
            if key in combined and combined[key] != value:
                raise SystemExit(f"conflicting Korean for {key!r}")
            combined[key] = value
    return combined


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--charmap", type=Path, default=DEFAULT_MAP12)
    parser.add_argument("--clean", type=Path, default=DEFAULT_CLEAN)
    parser.add_argument("--ko", type=Path, action="append", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--scopes", nargs="+", default=["scenario_main", "production"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    charmap = load_map(args.charmap)
    charmap.update(CORRECTED_LOW_KANA)
    ko_map = load_ko_maps(args.ko)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    source = json.loads(args.source.read_text(encoding="utf-8"))
    scenario_by_id = {
        row["record_id"]: row
        for row in json.loads(args.scenario.read_text(encoding="utf-8"))["main"]["records"]
    }
    source_by_id = {row["record_id"]: row for row in source["records"]}

    pending_ok = {
        row["record_id"]: row
        for row in merged["records"]
        if row.get("translation_status") == "pending" and row.get("translation_policy") == "translate"
    }
    unit_members: dict[str, set[str]] = {}
    for row in source["records"]:
        if row.get("scope_status") == "included" and row.get("translation_policy") == "translate":
            unit_members.setdefault(str(row["translation_unit_id"]), set()).add(row["record_id"])

    clean = json.loads(args.clean.read_text(encoding="utf-8"))
    selected: list[dict[str, Any]] = []
    skipped = {"no_ko": 0, "scope": 0, "missing": 0, "unit": 0, "len": 0, "not_pending": 0}
    selected_ids: set[str] = set()

    for item in clean["strings"]:
        if item["scope"] not in args.scopes:
            skipped["scope"] += 1
            continue
        key = item["decoded"]
        ko_lines = ko_map.get(key)
        if not isinstance(ko_lines, list):
            skipped["no_ko"] += 1
            continue
        for rec in item["records"]:
            record_id = rec["record_id"]
            if record_id not in pending_ok:
                skipped["not_pending"] += 1
                continue
            row = pending_ok[record_id]
            if item["scope"] == "scenario_main":
                src = scenario_by_id.get(record_id)
                if src is None:
                    skipped["missing"] += 1
                    continue
                all_segs, text_parts, missing = decode_parts(src, charmap)
                if missing:
                    skipped["missing"] += 1
                    continue
                if joined_key(text_parts) != key:
                    skipped["missing"] += 1
                    continue
                if len(ko_lines) != len(text_parts):
                    skipped["len"] += 1
                    continue
                translations = build_segments(all_segs, ko_lines)
                selected.append(
                    {
                        "record_id": record_id,
                        "translation_segments": translations,
                        "translation_ko": "\n".join(line for line in ko_lines if line),
                        "translation_status": "translated",
                        "translator_notes": "slot-complete decode; natural Korean; unused bark and bijection residue excluded",
                    }
                )
                selected_ids.add(record_id)
            else:
                if len(ko_lines) != 1:
                    skipped["len"] += 1
                    continue
                selected.append(
                    {
                        "record_id": record_id,
                        "translation_ko": ko_lines[0],
                        "translation_status": "translated",
                        "translator_notes": "slot-complete decode; natural Korean; bijection residue excluded",
                    }
                )
                selected_ids.add(record_id)

    # Drop records whose translation_unit is only partially selected.
    keep: list[dict[str, Any]] = []
    dropped_units = 0
    selected_by_id = {item["record_id"]: item for item in selected}
    seen_units: set[str] = set()
    for record_id in list(selected_ids):
        unit = str(source_by_id[record_id]["translation_unit_id"])
        if unit in seen_units:
            continue
        seen_units.add(unit)
        members = unit_members[unit]
        pending_members = {mid for mid in members if mid in pending_ok}
        if not pending_members.issubset(selected_ids):
            dropped_units += 1
            skipped["unit"] += len(pending_members & selected_ids)
            continue
        for mid in pending_members:
            keep.append(selected_by_id[mid])

    if not keep:
        raise SystemExit(f"no records; skipped={skipped}")
    payload = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "Natural Korean for fully decoded pending rows; Gundam terms; honorifics kept per speaker.",
        "records": sorted(keep, key=lambda item: item["record_id"]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "record_count": len(keep),
        "dropped_units": dropped_units,
        "skipped": skipped,
        "ko_keys": len(ko_map),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
