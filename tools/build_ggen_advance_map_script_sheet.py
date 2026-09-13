#!/usr/bin/env python3
"""Append extracted map-script dialogue onto the unified translation sheet.

The 20260827 unified source file is not rewritten.  Existing overlay identity
stays on the previous merge; this tool copies that merge and adds the new
canonical family as pending rows.

Does not write a ROM and does not invent Korean for unread slots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ROM_BASE = 0x08000000
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hex32(value: int) -> str:
    return f"0x{value:08X}"


def project_segments(row: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, segment in enumerate(row.get("segments") or []):
        result.append(
            {
                "segment_index": index,
                "raw_hex": str(segment.get("raw_hex") or "").upper(),
                "source_text": str(segment.get("source_text") or ""),
                "unresolved_slots": list(segment.get("unresolved_slots") or []),
                "is_text_segment": True,
            }
        )
    return result


def build_record(row: dict[str, Any], rom_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record_id = str(row["record_id"])
    target = int(row["target_file_offset"], 16)
    opcode = int(row["opcode_18_file_offset"], 16)
    unresolved = list(row.get("unresolved_slots") or [])
    segments = project_segments(row)
    owner_id = f"OWNER-INLINE-{opcode:08X}"
    owner_ids = [owner_id]
    record = {
        "record_id": record_id,
        "source_scope": "scenario_map_script",
        "scope_status": "included",
        "record_kind": "map_script_inline_text_stream",
        "alias_of": "",
        "target_file_offset": hex32(target),
        "target_address": hex32(ROM_BASE + target),
        "original_raw_sha256": row["original_raw_sha256"],
        "raw_hex": row["raw_hex"],
        "original_byte_length": int(row["byte_length"]),
        "source_text": str(row.get("source_text_seed") or ""),
        "source_decode_status": "complete" if not unresolved else "partial",
        "source_unresolved_slots": unresolved,
        "semantic_category": "scenario_map_event_text",
        "source_families": ["map_event_script_inline"],
        "source_types": ["inline_print_opcode_18"],
        "storage_contract": "inline_script_nul_stream",
        "relocation_schema": "inline_script_18",
        "pointer_group": "map_script_inline",
        "container_id": record_id,
        "translation_unit_id": record_id,
        "context_bundle_id": f"MAP-SCRIPT-SPEAKER-{row.get('speaker_id') or 'NONE'}",
        "screen_class": "scenario_event_12x12",
        "control_signature": (
            [{"code": "0x18", "role": "print"}]
            + [{"code": "0x00", "role": "line_break"} for _ in segments[1:]]
        ),
        "segments": segments,
        "baseline_translation_ko": "",
        "baseline_translation_status": "not_started" if not unresolved else "needs_charmap_resolution",
        "translation_policy": "translate",
        "translation_ko": "",
        "translation_status": "pending",
        "translation_source": "",
        "source_model": "",
        "prompt_version": "",
        "review_status": "pending",
        "review_count": 0,
        "reviewed_at": "",
        "translator_notes": "",
        "qa_status": "not_checked",
        "source_record_id": record_id,
        "opcode_18_file_offset": hex32(opcode),
        "print_setup": row.get("print_setup") or "",
        "chained_box": bool(row.get("chained_box")),
        "speaker_id": row.get("speaker_id") or "",
        "line_break_count": max(0, len(segments) - 1),
        "dynamic_control_count": 0,
        "final_control": "0x00",
        "pointer_recalc_required": True,
        "owner_ids": owner_ids,
        "owner_count": 1,
        "owner_digest": digest(owner_ids),
        "source_fingerprint": "",
    }
    record["source_fingerprint"] = digest(
        {
            "rom_sha256": rom_sha,
            "record_id": record_id,
            "target_file_offset": record["target_file_offset"],
            "original_raw_sha256": record["original_raw_sha256"],
            "container_id": record["container_id"],
            "translation_unit_id": record["translation_unit_id"],
            "owner_digest": record["owner_digest"],
        }
    )
    owner = {
        "owner_id": owner_id,
        "owner_kind": "inline_print_18",
        "source_file_offset": hex32(opcode),
        "pointer_width": 0,
        "target_record_ids": [record_id],
        "target_container_ids": [record_id],
        "relocation_schemas": ["inline_script_18"],
        "source_types": ["inline_print_opcode_18"],
        "families": ["map_event_script_inline"],
        "synthetic": False,
    }
    return record, owner


def recount(merged: dict[str, Any]) -> None:
    records = merged["records"]
    owners = merged["owners"]
    summary = merged["summary"]
    included = [row for row in records if row.get("scope_status") == "included"]
    aliases = [row for row in records if row.get("scope_status") == "alias"]
    summary["records_total"] = len(records)
    summary["canonical_records"] = len(included)
    summary["alias_records"] = len(aliases)
    summary["unique_target_count"] = len({row["target_file_offset"] for row in records})
    summary["owner_count"] = len(owners)
    summary["u32_owner_count"] = sum(1 for owner in owners if str(owner.get("owner_kind", "")).startswith("u32") or owner.get("pointer_width") == 4)
    summary["source_scope_counts"] = dict(sorted(Counter(str(row["source_scope"]) for row in records).items()))
    summary["scope_status_counts"] = dict(sorted(Counter(str(row.get("scope_status")) for row in records).items()))
    summary["storage_contract_counts"] = dict(sorted(Counter(str(row.get("storage_contract")) for row in included).items()))
    summary["merged_translation_status_counts"] = dict(
        sorted(Counter(str(row.get("translation_status")) for row in records).items())
    )
    summary["merged_review_status_counts"] = dict(
        sorted(Counter(str(row.get("review_status")) for row in records).items())
    )
    summary["translated_canonical_records"] = sum(1 for row in included if row.get("translation_status") == "translated")
    summary["untranslated_canonical_records"] = sum(
        1 for row in included if row.get("translation_status") == "pending"
    )
    summary["translation_unit_count"] = len({row.get("translation_unit_id") for row in included})
    summary["context_bundle_count"] = len({row.get("context_bundle_id") for row in included})


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extract",
        type=Path,
        default=ROOT / "analysis" / "ggen_advance_map_script_translation_source_20260828.json",
    )
    parser.add_argument(
        "--merged-in",
        type=Path,
        default=ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json",
    )
    parser.add_argument(
        "--merged-out",
        type=Path,
        default=ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json",
    )
    parser.add_argument(
        "--addendum-out",
        type=Path,
        default=ROOT / "analysis" / "ggen_advance_map_script_unified_records_20260828.json",
    )
    args = parser.parse_args(argv)

    extract = json.loads(args.extract.read_text(encoding="utf-8"))
    merged = json.loads(args.merged_in.read_text(encoding="utf-8"))
    rom_sha = str(merged["source"]["sha256"]).lower()
    if rom_sha != EXPECTED_SHA256:
        fail(f"merged ROM SHA mismatch: {rom_sha}")
    if str(extract["source"]["sha256"]).lower() != rom_sha:
        fail("extract ROM SHA mismatch")

    existing_ids = {str(row["record_id"]) for row in merged["records"]}
    existing_targets = {str(row["target_file_offset"]) for row in merged["records"] if row.get("scope_status") == "included"}
    existing_owners = {str(owner["owner_id"]) for owner in merged["owners"]}

    new_records: list[dict[str, Any]] = []
    new_owners: list[dict[str, Any]] = []
    for row in extract["records"]:
        record, owner = build_record(row, rom_sha)
        if record["record_id"] in existing_ids:
            fail(f"record_id already in sheet: {record['record_id']}")
        if record["target_file_offset"] in existing_targets:
            fail(f"canonical target collision: {record['target_file_offset']}")
        if owner["owner_id"] in existing_owners:
            fail(f"owner already in sheet: {owner['owner_id']}")
        existing_ids.add(record["record_id"])
        existing_targets.add(record["target_file_offset"])
        existing_owners.add(owner["owner_id"])
        new_records.append(record)
        new_owners.append(owner)

    needles = {
        "nani": "なにっ！\\n敵艦が接近中だと！？",
        "nasuka": "艦種ナスカ級\\nザフトの高速戦艦です",
        "ramiasu": "ラミアス大尉に連絡！\\n「G」の搬入を急がせろ！",
    }
    by_text = {row["source_text"]: row["record_id"] for row in new_records}
    missing = {name: text for name, text in needles.items() if text not in by_text}
    if missing:
        fail(f"screenshot rows missing from sheet: {missing}")

    complete = sum(1 for row in new_records if row["source_decode_status"] == "complete")
    addendum = {
        "schema_version": 1,
        "scope": "map-script inline dialogue addendum to unified translation sheet",
        "parent_merge": str(args.merged_in.name),
        "parent_manifest_identity_sha256": merged["identity"]["manifest_identity_sha256"],
        "source_rom_sha256": rom_sha,
        "extract": str(args.extract.name),
        "summary": {
            "records": len(new_records),
            "complete_decode": complete,
            "partial_decode": len(new_records) - complete,
        },
        "records": new_records,
        "owners": new_owners,
    }
    addendum["identity"] = {
        "record_identity_sha256": digest(
            [
                {
                    "record_id": row["record_id"],
                    "target_file_offset": row["target_file_offset"],
                    "original_raw_sha256": row["original_raw_sha256"],
                }
                for row in new_records
            ]
        ),
        "owner_identity_sha256": digest(
            [{"owner_id": owner["owner_id"], "source_file_offset": owner["source_file_offset"]} for owner in new_owners]
        ),
    }

    merged["records"].extend(new_records)
    merged["owners"].extend(new_owners)
    merged["scope"] = "G Generation Advance unified translation overlay merge plus map-script inline dialogue"
    merged["inputs"]["map_script_event"] = {
        "file": args.extract.name,
        "file_sha256": hashlib.sha256(args.extract.read_bytes()).hexdigest(),
        "report_source_sha256": rom_sha,
        "report_schema_version": 1,
        "record_count": len(new_records),
    }
    merged["identity"]["parent_manifest_identity_sha256"] = merged["identity"]["manifest_identity_sha256"]
    merged["identity"]["map_script_record_identity_sha256"] = addendum["identity"]["record_identity_sha256"]
    recount(merged)

    args.addendum_out.write_text(json.dumps(addendum, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.merged_out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "merged_out": str(args.merged_out),
                "addendum_out": str(args.addendum_out),
                "added_records": len(new_records),
                "complete_decode": complete,
                "partial_decode": len(new_records) - complete,
                "canonical_records": merged["summary"]["canonical_records"],
                "untranslated_canonical_records": merged["summary"]["untranslated_canonical_records"],
                "source_scope_counts": merged["summary"]["source_scope_counts"],
                "immutable_20260827_source_preserved": True,
                "screenshot_record_ids": {name: by_text[text] for name, text in needles.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
