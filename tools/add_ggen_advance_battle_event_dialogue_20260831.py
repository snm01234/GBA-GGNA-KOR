#!/usr/bin/env python3
"""Add the omitted 256x23 battle-event dialogue table to the active source."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402
from ggen_advance_text_codec import (  # noqa: E402
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

ROM_BASE = 0x08000000
ROM_PATH = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MERGED_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
MANIFEST_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_manifest.json"
TRANSLATIONS_PATH = ROOT / "integrated" / "translation" / "ggen_advance_battle_event_dialogue_ko_20260831.json"
CHARMAP_PATH = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

TABLE_START = 0x00D34588
TABLE_ROWS = 256
TABLE_COLUMNS = 23
STRING_START = 0x00D34130
STRING_END = TABLE_START
BATCH_ID = "battle-event-dialogue-complete-20260831"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hex32(value: int) -> str:
    return f"0x{value:08X}"


def raw_hex(value: bytes) -> str:
    return value.hex(" ").upper()


def identity_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    records = [row for row in payload["records"] if row.get("source_scope") != "scenario_map_script"]
    owners = [
        owner
        for owner in payload["owners"]
        if "map_event_script_inline" not in (owner.get("families") or [])
    ]
    return (
        [
            {
                "record_id": row["record_id"],
                "source_scope": row["source_scope"],
                "scope_status": row["scope_status"],
                "alias_of": row["alias_of"],
                "target_file_offset": row["target_file_offset"],
                "original_raw_sha256": row["original_raw_sha256"],
                "container_id": row["container_id"],
                "translation_unit_id": row["translation_unit_id"],
                "owner_digest": row["owner_digest"],
            }
            for row in records
        ],
        [
            {
                "owner_id": owner["owner_id"],
                "owner_kind": owner["owner_kind"],
                "source_file_offset": owner["source_file_offset"],
                "pointer_width": owner["pointer_width"],
                "target_record_ids": owner["target_record_ids"],
                "target_container_ids": owner["target_container_ids"],
                "relocation_schemas": owner["relocation_schemas"],
            }
            for owner in owners
        ],
        [
            {
                "exclusion_id": row["exclusion_id"],
                "scope_status": row["scope_status"],
                "target_file_offset": row["target_file_offset"],
                "original_raw_sha256": row["original_raw_sha256"],
                "reason": row["reason"],
            }
            for row in payload["exclusions"]
        ],
    )


def translation_payload_digest(row: dict[str, Any]) -> str:
    return digest(
        {
            "record_id": row["record_id"],
            "batch_id": row["overlay_batch_id"],
            "translation_ko": row["translation_ko"],
            "translation_segments": row["translation_segments"],
            "translation_status": row["translation_status"],
            "translation_source": row["translation_source"],
            "source_model": row["source_model"],
            "prompt_version": row["prompt_version"],
            "review_status": row["review_status"],
            "review_count": row["review_count"],
            "reviewed_at": row["reviewed_at"],
            "translator_notes": row["translator_notes"],
            "qa_status": row["qa_status"],
        }
    )


SOURCE_CORRECTIONS = {
    "アイナ…もう手段を選ふない": "アイナ…もう手段を選ばない",
    "俺は…粗可能を……": "俺は…不可能を……",
    "弱民どもにその才能を": "愚民どもにその才能を",
}


def parse_record(
    rom: bytes,
    target: int,
    dictionary: list[list[int]],
    charmap: dict[int, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bytes, list[str]]:
    cursor = target
    segments: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    decoded: list[str] = []
    while True:
        tokens, raw = read_tokens(rom, cursor)
        slots = expand_to_slots(tokens, dictionary)
        text = "".join(charmap.get(slot, f"<{slot:04X}>") for slot in slots)
        text = SOURCE_CORRECTIONS.get(text, text)
        decoded.append(text)
        segments.append(
            {
                "segment_index": len(segments),
                "raw_hex": raw_hex(raw),
                "source_text": text,
                "unresolved_slots": [],
                "is_text_segment": bool(text),
            }
        )
        cursor += len(raw)
        code = rom[cursor]
        cursor += 1
        control: dict[str, Any] = {"code": f"0x{code:02X}"}
        if code in (0x05, 0x06):
            control["argument"] = rom[cursor]
            cursor += 1
        controls.append(control)
        if code == 0x01:
            break
        check(code in (0x02, 0x03, 0x05, 0x06), f"unknown battle-event control 0x{code:02X} at 0x{cursor-1:08X}")
    return segments, controls, rom[target:cursor], decoded


def update_summary(payload: dict[str, Any], added: int) -> None:
    records = payload["records"]
    owners = payload["owners"]
    summary = payload["summary"]
    summary.update(
        {
            "records_total": len(records),
            "canonical_records": sum(row["scope_status"] == "included" for row in records),
            "alias_records": sum(row["scope_status"] == "alias" for row in records),
            "unique_target_count": len({row["target_file_offset"] for row in records}),
            "owner_count": len(owners),
            "u32_owner_count": sum(owner["owner_kind"] == "u32_pointer" for owner in owners),
            "relative_u16_owner_count": sum(owner["owner_kind"] == "relative_u16_entry" for owner in owners),
            "source_scope_counts": dict(sorted(Counter(str(row["source_scope"]) for row in records).items())),
            "scope_status_counts": dict(sorted(Counter(str(row["scope_status"]) for row in records).items())),
            "storage_contract_counts": dict(sorted(Counter(str(row["storage_contract"]) for row in records).items())),
            "context_bundle_count": len({row["context_bundle_id"] for row in records}),
            "translation_unit_count": len({row["translation_unit_id"] for row in records if row["scope_status"] == "included"}),
            "battle_event_dialogue_records": added,
            "battle_event_dialogue_owners": added,
            "battle_event_dialogue_translated": added,
        }
    )
    source_counts = dict(summary.get("translation_status_counts", {}))
    source_counts["pending"] = int(source_counts.get("pending", 0)) + added
    summary["translation_status_counts"] = dict(sorted(source_counts.items()))
    merged_counts = Counter(str(row["translation_status"]) for row in records)
    review_counts = Counter(str(row["review_status"]) for row in records)
    summary["merged_translation_status_counts"] = dict(sorted(merged_counts.items()))
    summary["merged_review_status_counts"] = dict(sorted(review_counts.items()))
    payload["merged_translation_status_counts"] = dict(sorted(merged_counts.items()))
    summary["translated_canonical_records"] = sum(
        row["scope_status"] == "included" and row["translation_policy"] == "translate" and row["translation_status"] == "translated"
        for row in records
    )
    summary["untranslated_canonical_records"] = sum(
        row["scope_status"] == "included" and row["translation_policy"] == "translate" and row["translation_status"] != "translated"
        for row in records
    )
    summary["untranslated_translate_policy_records"] = summary["untranslated_canonical_records"]
    summary["overlay_record_count"] = int(summary.get("overlay_record_count", 0)) + added
    summary["overlay_translation_unit_count"] = int(summary.get("overlay_translation_unit_count", 0)) + added


def main() -> int:
    rom = ROM_PATH.read_bytes()
    payload = json.loads(MERGED_PATH.read_text(encoding="utf-8"))
    translations = json.loads(TRANSLATIONS_PATH.read_text(encoding="utf-8"))
    check(sha256_bytes(rom) == translations["source_rom_sha256"], "translation source ROM SHA drift")
    check(payload["source"]["sha256"] == translations["source_rom_sha256"], "merged source ROM SHA drift")
    check(translations["batch_id"] == BATCH_ID, "battle-event batch ID drift")

    old_record_rows, old_owner_rows, old_exclusion_rows = identity_rows(payload)
    check(payload["identity"]["record_identity_sha256"] == digest(old_record_rows), "existing record identity drift")
    check(payload["identity"]["owner_identity_sha256"] == digest(old_owner_rows), "existing owner identity drift")
    check(payload["identity"]["exclusion_identity_sha256"] == digest(old_exclusion_rows), "existing exclusion identity drift")

    dictionary = load_dictionary(rom, DICT_12X12_BASE, DICT_12X12_END)
    charmap = load_map(CHARMAP_PATH)
    charmap.update(CORRECTED_LOW_KANA)
    translation_by_cell = {(int(row["row"]), int(row["column"])): row for row in translations["records"]}
    check(len(translation_by_cell) == 49, f"translation cell count drift: {len(translation_by_cell)}")

    existing_record_ids = {row["record_id"] for row in payload["records"]}
    existing_owner_ids = {owner["owner_id"] for owner in payload["owners"]}
    new_records: list[dict[str, Any]] = []
    new_owners: list[dict[str, Any]] = []
    seen_cells: set[tuple[int, int]] = set()
    for row_index in range(TABLE_ROWS):
        for column_index in range(TABLE_COLUMNS):
            owner_offset = TABLE_START + (row_index * TABLE_COLUMNS + column_index) * 4
            pointer = struct.unpack_from("<I", rom, owner_offset)[0]
            if pointer == 0:
                continue
            target = pointer - ROM_BASE
            check(STRING_START <= target < STRING_END, f"unexpected table target at 0x{owner_offset:08X}: 0x{pointer:08X}")
            cell = (row_index, column_index)
            check(cell in translation_by_cell, f"missing translation for battle-event cell {cell}")
            seen_cells.add(cell)
            source = translation_by_cell[cell]
            segments, controls, raw, decoded = parse_record(rom, target, dictionary, charmap)
            check(decoded == source["source_segments"], f"source decode drift at cell {cell}: {decoded!r}")
            translated = list(source["translation_segments"])
            check(len(translated) == len(segments), f"translation segment count drift at cell {cell}")
            check(all("\n" not in text and len(text) <= 15 for text in translated), f"translation width exceeds 15 cells at {cell}")

            record_id = f"GGA-BATTLEEVENT-{target:08X}"
            owner_id = f"OWNER-U32-{owner_offset:08X}"
            check(record_id not in existing_record_ids, f"battle-event record already exists: {record_id}")
            check(owner_id not in existing_owner_ids, f"battle-event owner already exists: {owner_id}")
            owner_ids = [owner_id]
            owner_digest = digest(owner_ids)
            record = {
                "record_id": record_id,
                "source_scope": "battle_event_dialogue",
                "scope_status": "included",
                "record_kind": "battle_event_controlled_text_stream",
                "alias_of": "",
                "target_file_offset": hex32(target),
                "target_address": hex32(pointer),
                "original_raw_sha256": sha256_bytes(raw),
                "raw_hex": raw_hex(raw),
                "original_byte_length": len(raw),
                "source_text": "\n".join(decoded).rstrip("\n"),
                "source_decode_status": "complete",
                "source_unresolved_slots": [],
                "semantic_category": "battle_event_dialogue",
                "source_families": ["battle_event_dialogue_table_256x23"],
                "source_types": ["battle_event_dialogue_pointer"],
                "storage_contract": "scenario_control_stream",
                "relocation_schema": "battle_event_table_u32",
                "pointer_group": "battle_event_dialogue_table",
                "container_id": record_id,
                "translation_unit_id": record_id,
                "context_bundle_id": f"BATTLE-EVENT-ROW-{row_index:03d}",
                "screen_class": "battle_event_12x12",
                "control_signature": controls,
                "segments": segments,
                "translation_policy": "translate",
                "baseline_translation_ko": "",
                "baseline_translation_status": "not_started",
                "translation_ko": "\n".join(translated).rstrip("\n"),
                "translation_segments": translated,
                "translation_status": "translated",
                "translation_source": "curated_project_data",
                "source_model": "",
                "prompt_version": "",
                "review_status": "draft",
                "review_count": 0,
                "reviewed_at": "",
                "translator_notes": "complete 256x23 battle-event table audit; natural Korean; control framing preserved",
                "qa_status": "not_checked",
                "source_record_id": record_id,
                "line_break_count": sum(control["code"] == "0x03" for control in controls),
                "dynamic_control_count": sum(control["code"] in {"0x05", "0x06"} for control in controls),
                "final_control": controls[-1]["code"],
                "pointer_recalc_required": True,
                "owner_ids": owner_ids,
                "owner_count": 1,
                "owner_digest": owner_digest,
                "directory_row": row_index,
                "directory_slot": column_index,
                "overlay_batch_id": BATCH_ID,
            }
            record["source_fingerprint"] = digest(
                {
                    "rom_sha256": payload["source"]["sha256"],
                    "record_id": record_id,
                    "target_file_offset": record["target_file_offset"],
                    "original_raw_sha256": record["original_raw_sha256"],
                    "container_id": record_id,
                    "translation_unit_id": record_id,
                    "owner_digest": owner_digest,
                }
            )
            record["translation_payload_sha256"] = translation_payload_digest(record)
            new_records.append(record)
            new_owners.append(
                {
                    "owner_id": owner_id,
                    "owner_kind": "u32_pointer",
                    "source_file_offset": hex32(owner_offset),
                    "pointer_width": 4,
                    "target_record_ids": [record_id],
                    "target_container_ids": [record_id],
                    "relocation_schemas": ["battle_event_table_u32"],
                    "source_types": ["battle_event_dialogue_pointer"],
                    "families": ["battle_event_dialogue_table_256x23"],
                    "synthetic": False,
                }
            )

    check(seen_cells == set(translation_by_cell), "translation map contains cells absent from ROM table")
    check(len(new_records) == len(new_owners) == 49, "battle-event extraction count drift")
    payload["records"].extend(sorted(new_records, key=lambda row: int(row["target_file_offset"], 16)))
    payload["owners"] = sorted(payload["owners"] + new_owners, key=lambda owner: owner["owner_id"])

    record_rows, owner_rows, exclusion_rows = identity_rows(payload)
    record_sha = digest(record_rows)
    owner_sha = digest(owner_rows)
    exclusion_sha = digest(exclusion_rows)
    payload["identity"]["record_identity_sha256"] = record_sha
    payload["identity"]["owner_identity_sha256"] = owner_sha
    payload["identity"]["exclusion_identity_sha256"] = exclusion_sha
    payload["identity"]["manifest_identity_sha256"] = digest(
        {
            "rom_sha256": payload["source"]["sha256"],
            "record_identity_sha256": record_sha,
            "owner_identity_sha256": owner_sha,
            "exclusion_identity_sha256": exclusion_sha,
        }
    )
    extension_rows = [
        {
            "record_id": row["record_id"],
            "target_file_offset": row["target_file_offset"],
            "translation_payload_sha256": row["translation_payload_sha256"],
            "owner_ids": row["owner_ids"],
        }
        for row in new_records
    ]
    extension_identity = digest(extension_rows)
    parent_overlay = payload["identity"].get("translation_overlay_identity_sha256", "")
    overlay_identity = digest({"parent": parent_overlay, "battle_event_dialogue": extension_identity})
    payload["identity"]["parent_battle_event_translation_overlay_identity_sha256"] = parent_overlay
    payload["identity"]["battle_event_dialogue_identity_sha256"] = extension_identity
    payload["identity"]["translation_overlay_identity_sha256"] = overlay_identity
    payload["battle_event_dialogue"] = {
        "schema_version": 1,
        "batch_id": BATCH_ID,
        "table_file_offset": hex32(TABLE_START),
        "table_shape": [TABLE_ROWS, TABLE_COLUMNS],
        "record_count": len(new_records),
        "owner_count": len(new_owners),
        "translated_count": len(new_records),
        "extension_identity_sha256": extension_identity,
        "translation_source": str(TRANSLATIONS_PATH.relative_to(ROOT)).replace("\\", "/"),
        "rom_write_policy": "relocate every translated controlled stream and patch only its 256x23 table u32 owner",
    }
    payload.setdefault("coverage", {})["battle_event_dialogue_records"] = len(new_records)
    payload["coverage"]["battle_event_dialogue_owner_count"] = len(new_owners)
    update_summary(payload, len(new_records))
    payload["summary"]["translation_overlay_identity_sha256"] = overlay_identity

    descriptor = {
        "file": TRANSLATIONS_PATH.name,
        "file_sha256": sha256_bytes(TRANSLATIONS_PATH.read_bytes()),
        "batch_id": BATCH_ID,
        "record_count": len(new_records),
        "record_ids": sorted(row["record_id"] for row in new_records),
    }
    merge = payload.setdefault("merge", {})
    merge.setdefault("overlay_files", []).append(descriptor)
    merge["overlay_files"] = sorted(merge["overlay_files"], key=lambda row: (row["batch_id"], row["file"]))
    merge["batch_count"] = len(merge["overlay_files"])
    merge["accepted_record_count"] = int(merge.get("accepted_record_count", 0)) + len(new_records)
    merge["translation_unit_count"] = int(merge.get("translation_unit_count", 0)) + len(new_records)
    merge["translation_overlay_identity_sha256"] = overlay_identity

    MERGED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    merged_sha = sha256_bytes(MERGED_PATH.read_bytes())
    manifest.update(
        {
            "sha256": merged_sha,
            "source_sha256": merged_sha,
            "record_count": len(payload["records"]),
            "record_identity_sha256": record_sha,
            "translation_overlay_identity_sha256": overlay_identity,
            "record_translation_status_counts": payload["merged_translation_status_counts"],
            "source_summary_translation_status_counts": payload["merged_translation_status_counts"],
        }
    )
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "records_added": len(new_records),
                "owners_added": len(new_owners),
                "record_identity_sha256": record_sha,
                "owner_identity_sha256": owner_sha,
                "translation_overlay_identity_sha256": overlay_identity,
                "merged_json_sha256": merged_sha,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
