#!/usr/bin/env python3
"""Fit opening narration to 12x12 width and bind newly extracted map-script Korean.

Adds 17 1C/1D/EE/35/03 prints plus 00 01 18 chained boxes (Armor Schneider)
onto the 20260832 sheet, then writes merged_20260833.json.  Does not write a ROM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

from build_ggen_advance_map_script_sheet import (  # noqa: E402
    EXPECTED_SHA256,
    build_record,
    fail,
    recount,
)

MERGED_IN = ROOT / "analysis" / "ggen_advance_translation_merged_20260832.json"
MERGED_OUT = ROOT / "analysis" / "ggen_advance_translation_merged_20260833.json"
EXTRACT = ROOT / "analysis" / "ggen_advance_map_script_alt_setup_extract_20260829.json"
KO_PATH = ROOT / "analysis" / "ggen_advance_alt_print_setup_ko_20260829.json"

BATCH = "stage1-clip-alt-setup-20260829"
MAX_NARRATION_CELLS = 16

NARRATION_FIT: dict[str, str] = {
    "GGA-TEXT-001C8B0B": "압도적 국력의 연방을 상대로",
    "GGA-TEXT-001C8B1F": "지온의 힘은 20분의 1",
    "GGA-TEXT-001C8C4A": "우주세기 0089 9월중순",
    "GGA-TEXT-001C9279": "「지온 공화국」으로 개칭",
}

PENDING_JP = {
    ("<0355>として……",),
}


def norm_parts(parts: list[str]) -> tuple[str, ...]:
    return tuple(str(part or "") for part in parts)


def apply_translation(row: dict[str, Any], ko_parts: list[str]) -> None:
    segments = list(row.get("segments") or [])
    if len(ko_parts) != len(segments):
        fail(f"KO segment count mismatch for {row['record_id']}: {len(ko_parts)} vs {len(segments)}")
    row["translation_segments"] = list(ko_parts)
    row["translation_ko"] = "\n".join(ko_parts)
    row["translation_status"] = "translated"
    row["translation_policy"] = "translate"
    row["translation_source"] = "curated_project_data"
    row["translator_notes"] = "alt print-setup / 01-chain map dialogue; natural Korean"
    row["overlay_batch_id"] = BATCH


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    extract = json.loads(EXTRACT.read_text(encoding="utf-8"))
    merged = json.loads(MERGED_IN.read_text(encoding="utf-8"))
    ko_payload = json.loads(KO_PATH.read_text(encoding="utf-8"))
    rom_sha = str(merged["source"]["sha256"]).lower()
    if rom_sha != EXPECTED_SHA256:
        fail(f"merged ROM SHA mismatch: {rom_sha}")
    if str(extract["source"]["sha256"]).lower() != rom_sha:
        fail("extract ROM SHA mismatch")

    ko_map: dict[tuple[str, ...], list[str]] = {}
    for item in ko_payload["records"]:
        jp_parts = norm_parts(list(item["jp"]))
        ko_parts = list(item["ko"])
        if jp_parts in ko_map and ko_map[jp_parts] != ko_parts:
            fail(f"conflicting KO for {jp_parts!r}")
        if len(ko_parts) != len(jp_parts):
            fail(f"jp/ko length mismatch for {jp_parts!r}")
        ko_map[jp_parts] = ko_parts

    known: dict[tuple[str, ...], list[str]] = {}
    for row in merged["records"]:
        if row.get("source_scope") != "scenario_map_script":
            continue
        if row.get("translation_status") != "translated":
            continue
        segs = list(row.get("segments") or [])
        trans = list(row.get("translation_segments") or [])
        if segs and trans and len(trans) == len(segs):
            known[norm_parts([str(part.get("source_text") or "") for part in segs])] = trans

    existing_ids = {str(row["record_id"]) for row in merged["records"]}
    existing_targets = {
        str(row["target_file_offset"]) for row in merged["records"] if row.get("scope_status") == "included"
    }
    existing_owners = {str(owner["owner_id"]) for owner in merged["owners"]}

    added = 0
    translated = 0
    reused = 0
    pending = 0
    missing: list[tuple[str, tuple[str, ...]]] = []
    for src in extract["records"]:
        record, owner = build_record(src, rom_sha)
        rid = record["record_id"]
        if rid in existing_ids:
            continue
        if record["target_file_offset"] in existing_targets:
            fail(f"canonical target collision: {record['target_file_offset']}")
        if owner["owner_id"] in existing_owners:
            fail(f"owner already in sheet: {owner['owner_id']}")
        existing_ids.add(rid)
        existing_targets.add(record["target_file_offset"])
        existing_owners.add(owner["owner_id"])
        jp_parts = norm_parts([str(part.get("source_text") or "") for part in record.get("segments") or []])
        ko_parts = ko_map.get(jp_parts) or known.get(jp_parts)
        if ko_parts is None:
            if jp_parts in PENDING_JP or record["source_decode_status"] != "complete":
                if jp_parts in PENDING_JP:
                    pending += 1
                else:
                    missing.append((rid, jp_parts))
            else:
                missing.append((rid, jp_parts))
        else:
            apply_translation(record, ko_parts)
            translated += 1
            if jp_parts in known and jp_parts not in ko_map:
                reused += 1
        merged["records"].append(record)
        merged["owners"].append(owner)
        added += 1

    if missing:
        fail(f"missing KO for {len(missing)} rows; first: {missing[:4]!r}")

    narrated = 0
    for row in merged["records"]:
        rid = str(row.get("record_id") or "")
        ko = NARRATION_FIT.get(rid)
        if not ko:
            continue
        if len(ko) > MAX_NARRATION_CELLS:
            fail(f"narration still too wide: {rid} {len(ko)}")
        row["translation_ko"] = ko
        row["translator_notes"] = "12x12 cinematic line shortened to fit 240px / glyph-width 12"
        row["overlay_batch_id"] = BATCH
        narrated += 1
    if narrated != len(NARRATION_FIT):
        fail(f"narration fit updated {narrated} != {len(NARRATION_FIT)}")

    recount(merged)
    MERGED_OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "merged_out": str(MERGED_OUT),
                "added_records": added,
                "translated_new": translated,
                "reused_existing_ko": reused,
                "pending_new": pending,
                "narration_fit": narrated,
                "canonical_records": merged["summary"]["canonical_records"],
                "translated_canonical_records": merged["summary"]["translated_canonical_records"],
                "untranslated_canonical_records": merged["summary"]["untranslated_canonical_records"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
