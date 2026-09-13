#!/usr/bin/env python3
"""Build the 4,069-row production translation-master schema.

The master layers reviewed semantic roles and translation policy on top of the
advance-local Unicode seed export.  It does not guess unresolved Japanese
characters and does not modify the ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_stage2_production_reference_manifest as manifest  # noqa: E402
import export_stage2_production_unicode_seed as unicode_export  # noqa: E402

ROM_BASE = manifest.ROM_BASE
UNIT_DB = 0x001A476C
UNIT_STRIDE = 0x78
SUBRECORD_STRIDE = 0x1C
SUBRECORD_TEXT_A = 0x24

CONFIRM_TARGETS = {0x081BE7BE, 0x081BE7C7, 0x081BE7CA}
DIRECT_ID_FALLBACK = {0x081BE746, 0x081BE7B4}
GENERIC_UI_SYMBOL = {0x081BE755, 0x081BEA3C}
ID_COMMAND_ROW_FALLBACK = 0x081BE74E
EMPTY_SELECTION = 0x081BE7A3
SHARED_LIST_HEADING = 0x081BEA75
CONFIG_SUBMENU_LABELS = {0x081BEB0E, 0x081BEB27, 0x081BEB3C, 0x081BEB46}
CHARACTER_LIST_STATE_MARKER = 0x081BEB6C
ORPHAN_ONLY = {
    0x081BEA51, 0x081BEA5E, 0x081BEA67, 0x081BEB6F,
    0x081BEBC5, 0x081BEE68, 0x081BEE6F, 0x081BEE7A,
}


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 4], "little")


def families(row: dict[str, Any]) -> set[str]:
    return {str(x) for x in row["source_families"]}


def direct_pc_calls(row: dict[str, Any]) -> list[int]:
    return [
        int(ref["call_file"], 16) + ROM_BASE
        for ref in row["references"]
        if ref.get("source_type") == "direct_pc_literal" and isinstance(ref.get("call_file"), str)
    ]


def relative_slot_present(data: bytes, row: dict[str, Any]) -> bool:
    rel_refs = [ref for ref in row["references"] if ref.get("source_type") == "relative_u16_paired_text_table"]
    check(len(rel_refs) == 1, f"relative record provenance drift: {row['record_id']}")
    logical = int(rel_refs[0]["logical_index"])
    record_index = logical // 3
    sub_index = logical % 3
    source = UNIT_DB + record_index * UNIT_STRIDE + sub_index * SUBRECORD_STRIDE + SUBRECORD_TEXT_A
    return u32(data, source) != 0


def direct_literal_semantic(row: dict[str, Any]) -> tuple[str, str]:
    target = int(row["target_address"], 16)
    calls = direct_pc_calls(row)
    if target in DIRECT_ID_FALLBACK:
        return "id_command_fallback_text", "legacy/analysis/direct_pc_semantic_clusters_static_summary_20260826.json"
    if target in GENERIC_UI_SYMBOL:
        return "generic_ui_symbol", "legacy/analysis/direct_pc_semantic_clusters_static_summary_20260826.json"
    if target in CONFIG_SUBMENU_LABELS:
        return "unit_configuration_submenu_label", "legacy/analysis/configuration_residual_text_static_summary_20260826.json"
    if target == CHARACTER_LIST_STATE_MARKER:
        return "character_list_state_marker", "legacy/analysis/configuration_residual_text_static_summary_20260826.json"
    if target in CONFIRM_TARGETS:
        return "two_choice_confirmation_dialog_text", "legacy/analysis/final_direct_pc_residuals_static_summary_20260826.json"
    if target == ID_COMMAND_ROW_FALLBACK:
        return "id_command_row_fallback", "legacy/analysis/final_direct_pc_residuals_static_summary_20260826.json"
    if target == EMPTY_SELECTION:
        return "selector_empty_state_message", "legacy/analysis/final_direct_pc_residuals_static_summary_20260826.json"
    if target == SHARED_LIST_HEADING:
        return "shared_list_heading", "legacy/analysis/final_direct_pc_residuals_static_summary_20260826.json"
    if target in ORPHAN_ONLY:
        return "statically_unreferenced_nine_row_menu_label", "legacy/analysis/final_direct_pc_residuals_static_summary_20260826.json"
    if any(0x0805F16A <= call <= 0x0805F25A for call in calls):
        return "unit_configuration_action_label", "legacy/analysis/direct_pc_semantic_clusters_static_summary_20260826.json"
    if any(0x0806457E <= call <= 0x080645EE for call in calls):
        return "map_system_selector_static_label", "legacy/analysis/direct_pc_semantic_clusters_static_summary_20260826.json"
    if any(0x080654FC <= call <= 0x08065562 for call in calls):
        return "map_system_selector_help", "legacy/analysis/direct_pc_semantic_clusters_static_summary_20260826.json"
    if any(0x0806AF00 <= call <= 0x0806B500 or 0x08073300 <= call <= 0x08074400 for call in calls):
        return "stage_battle_condition_static_label", "legacy/analysis/direct_pc_semantic_clusters_static_summary_20260826.json"
    raise SystemExit(f"gate failed: direct literal semantic role not closed for {row['record_id']} {row['target_address']}")


def semantic_for_row(data: bytes, row: dict[str, Any]) -> tuple[str, str]:
    primary = str(row["primary_category"])
    fs = families(row)

    if primary == "entity_name":
        return "unit_name", "reviewed parent semantic + advance closure"
    if primary == "entity_subtext":
        return "weapon_name", "reviewed parent semantic + advance closure"
    if primary == "unit_primary":
        return "character_name", "reviewed parent semantic + advance closure"
    if primary == "unit_subtext":
        if "unit_db_subrecord_text_A" in fs:
            return "id_command_name", "reviewed parent semantic"
        if "unit_db_subrecord_text_B" in fs:
            return "id_command_effect_summary", "reviewed parent semantic"
        raise SystemExit(f"gate failed: unknown unit_subtext family for {row['record_id']}")
    if primary == "fixed_record_text":
        if "record16_primary_text" in fs:
            return "character_name", "historical fixed producer semantic"
        if "record40_primary_text" in fs:
            return "unit_name", "historical fixed producer semantic"
        raise SystemExit(f"gate failed: unknown fixed family for {row['record_id']}")
    if primary == "sparse_lookup":
        return "series_title", "reviewed parent semantic"
    if primary == "normalized_lookup":
        return "upgrade_part_name", "reviewed parent semantic"
    if primary == "search_record":
        if "current_search_record_text_10" in fs:
            return "stage_location_name", "reviewed parent semantic"
        if "search_key_to_FCE1A0_text" in fs:
            return "stage_battle_condition_text", "legacy/analysis/stage_condition_text_static_summary_20260826.json"
        raise SystemExit(f"gate failed: unknown search family for {row['record_id']}")
    if primary == "id24_record":
        return "unit_defense_ability", "legacy/analysis/id24_defense_ability_static_summary_20260826.json"
    if primary == "state_variant_pair" or primary == manifest.FALLBACK_CATEGORY:
        return "stage_battle_condition_line", "legacy/analysis/stage_condition_text_static_summary_20260826.json"
    if primary == "relative_text_pair":
        if relative_slot_present(data, row):
            return "id_command_description", "caller-gated relative pair semantic"
        return "inactive_id_command_placeholder", "caller-gated relative pair semantic"
    if primary == "direct_struct_text":
        if "direct_struct8_text" in fs:
            return "scroll_list_label", "legacy/analysis/direct_struct8_text_static_summary_20260826.json"
        if "direct_struct72_text" in fs:
            return "stage_code", "reviewed parent semantic"
        raise SystemExit(f"gate failed: unknown direct_struct family for {row['record_id']}")
    if primary == "indexed_text_table":
        if "table_1C92E8" in fs:
            return "scripted_multiline_text", "legacy/analysis/table_1c92e8_static_summary_20260826.json"
        if "table_FCE2D8_flat69_paired_selection" in fs:
            return "stage_battle_condition_component", "legacy/analysis/stage_condition_component_tables_static_summary_20260826.json"
        if "table_FCDF78_prefix13" in fs:
            return "unit_ai_type", "legacy/analysis/fcdf78_ai_type_static_summary_20260826.json"
        if "table_FCE128_22" in fs:
            return "map_system_function_help", "legacy/analysis/fce128_function_help_static_summary_20260826.json"
        if "table_FCE2A8_sparse12" in fs:
            return "stage_battle_condition_target_label", "legacy/analysis/stage_condition_component_tables_static_summary_20260826.json"
        raise SystemExit(f"gate failed: unknown indexed family for {row['record_id']}: {sorted(fs)}")
    if primary == "direct_literal":
        return direct_literal_semantic(row)
    raise SystemExit(f"gate failed: no semantic mapping for primary category {primary}")


def translation_policy(semantic: str) -> str:
    if semantic == "inactive_id_command_placeholder":
        return "preserve_roundtrip"
    if semantic == "statically_unreferenced_nine_row_menu_label":
        return "preserve_by_default"
    if semantic == "generic_ui_symbol":
        return "preserve_literal"
    return "translate"


def build_master(data: bytes) -> dict[str, Any]:
    exported = unicode_export.build_export(data)
    rows: list[dict[str, Any]] = []
    semantic_counts: Counter[str] = Counter()
    policy_counts: Counter[str] = Counter()
    decode_counts: Counter[str] = Counter()

    for source in exported["records"]:
        semantic, evidence = semantic_for_row(data, source)
        policy = translation_policy(semantic)
        semantic_counts[semantic] += 1
        policy_counts[policy] += 1
        decode_counts[source["decode_status"]] += 1
        row = dict(source)
        row.update({
            "semantic_category": semantic,
            "semantic_review_status": "reviewed",
            "semantic_evidence": evidence,
            "translation_policy": policy,
            "translation_status": "not_started" if policy == "translate" else "preserve",
            "source_decode_complete": source["decode_status"] == "complete",
            "needs_charmap_resolution": bool(source["unresolved_slots"]),
            "translation_ko": "",
            "translator_notes": "",
            "qa_status": "not_checked",
        })
        rows.append(row)

    check(len(rows) == manifest.FINAL_RECORDS, "translation master row count drift")
    check(sum(semantic_counts.values()) == manifest.FINAL_RECORDS, "semantic count total drift")
    check(all(row["semantic_review_status"] == "reviewed" for row in rows), "semantic review closure drift")

    # Caller-gated ID-command invariant from the established 256x3 structure.
    check(semantic_counts["id_command_description"] == 862, "active ID-command description drift")
    check(semantic_counts["inactive_id_command_placeholder"] == 668, "inactive ID-command placeholder drift")
    check(semantic_counts["scripted_multiline_text"] == 159, "multiline semantic count drift")
    check(semantic_counts["stage_battle_condition_line"] == 112, "stage condition line count drift")

    master_payload = [
        {
            "record_id": row["record_id"],
            "original_raw_sha256": row["original_raw_sha256"],
            "semantic_category": row["semantic_category"],
            "translation_policy": row["translation_policy"],
        }
        for row in rows
    ]
    schema_digest = hashlib.sha256(
        json.dumps(master_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    translate_rows = [row for row in rows if row["translation_policy"] == "translate"]
    preserve_rows = [row for row in rows if row["translation_policy"] != "translate"]
    translate_complete = sum(row["source_decode_complete"] for row in translate_rows)

    return {
        "schema_version": 1,
        "scope": "G Generation Advance production translation master seed",
        "source": exported["source"],
        "record_identity_sha256": manifest.FINAL_IDENTITY_SHA256,
        "master_schema_sha256": schema_digest,
        "summary": {
            "records": len(rows),
            "semantic_reviewed": len(rows),
            "semantic_partial": 0,
            "semantic_unclassified": 0,
            "translation_policy_counts": dict(policy_counts),
            "semantic_category_counts": dict(semantic_counts),
            "decode_status_counts": dict(decode_counts),
            "translate_records": len(translate_rows),
            "preserve_records": len(preserve_rows),
            "translate_records_with_complete_source_decode": translate_complete,
            "translate_records_needing_charmap_resolution": len(translate_rows) - translate_complete,
        },
        "schema_fields": {
            "identity": ["record_id", "target_file_offset", "original_raw_sha256"],
            "source": ["decoded_text_seed", "decode_status", "unresolved_slots", "raw_hex", "tokens", "slots"],
            "provenance": ["primary_category", "semantic_category", "semantic_evidence", "references"],
            "translation": ["translation_policy", "translation_status", "translation_ko", "translator_notes"],
            "qa": ["source_decode_complete", "needs_charmap_resolution", "qa_status"],
        },
        "records": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    data = args.rom.read_bytes()
    check(len(data) == 16 * 1024 * 1024, "ROM size drift")
    check(hashlib.sha256(data).hexdigest() == manifest.ROM_SHA256, "ROM hash drift")
    report = build_master(data)
    visible = {
        key: report[key]
        for key in ("schema_version", "scope", "source", "record_identity_sha256", "master_schema_sha256", "summary", "schema_fields")
    } if args.summary_only else report
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
