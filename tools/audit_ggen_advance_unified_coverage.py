#!/usr/bin/env python3
"""Audit whether the unified translation sheet is missing owner-proven text.

The immutable 2026-08-27 source is owner-proven rendered streams only.
This read-only audit independently reconstructs producer tables, the scenario
directory, UI matrix cells, and draw-literal targets, then classifies every
unified-source exclusion.  Scan candidates are never promoted without a
producer/renderer owner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import analyze_ggen_advance_ui_matrix_expansion as ui  # noqa: E402
import extract_stage2_contract_manifest as tracked  # noqa: E402
import reconstruct_stage2_historical_exact as exact  # noqa: E402
import reconstruct_stage2_target_set as base  # noqa: E402
from ggen_advance_text_codec import ROM_BASE  # noqa: E402

EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_SIZE = 16 * 1024 * 1024
DRAW_CA0 = 0x08000CA0
DRAW_F54 = 0x08000F54

MAIN_DIRECTORY = 0x0021D5B4
MAIN_FIRST_ROW = 1
MAIN_LAST_ROW = 247
MAIN_SLOTS = 22
MAIN_STRIDE_WORDS = 23
DYNAMIC_POINTER_BASE = 0x001F1E6C
DYNAMIC_ROWS = 651
DYNAMIC_COLUMNS = 6
SCENARIO_MAIN = (0x001F5F20, 0x0021D5B1)
SCENARIO_DYNAMIC = (0x001F1A04, 0x001F1E6B)

ID_COMMAND_CATEGORIES = {
    "id_command_name",
    "id_command_effect_summary",
    "id_command_description",
    "inactive_id_command_placeholder",
    "id_command_fallback_text",
}
BATTLE_CATEGORIES = {
    "stage_battle_condition_text",
    "stage_battle_condition_line",
    "stage_battle_condition_static_label",
    "stage_battle_condition_component",
    "stage_battle_condition_target_label",
}


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def hx(offset: int) -> str:
    return f"0x{offset:08X}"


def file_of(pointer: int) -> int:
    return pointer - ROM_BASE


def in_range(offset: int, span: tuple[int, int]) -> bool:
    start, end = span
    return start <= offset < end


def collect_draw_sites(data: bytes, wrapper: int) -> list[int]:
    return [
        offset
        for offset in range(0, len(data) - 3, 2)
        if ui.thumb_bl_target(data, offset) == wrapper
    ]


def pc_literal_targets(data: bytes, calls: list[int]) -> dict[int, list[int]]:
    by_target: dict[int, list[int]] = defaultdict(list)
    for call in calls:
        found = ui.pc_literal_r3(data, call)
        if found is None:
            continue
        _writer, _pool, value = found
        if ROM_BASE <= value < ROM_BASE + len(data):
            by_target[file_of(value)].append(call)
    return dict(by_target)


def reconstruct_production(data: bytes) -> dict[str, Any]:
    historical, _audit = exact.historical_primary_sets(data)
    successor, _multiline = exact.multiline_successor_sets(data, historical)
    production_3993 = set().union(*successor.values())
    check(len(production_3993) == 3993, f"3993 drift: {len(production_3993)}")

    fallback_containers, _override = tracked.stage_condition_containers(data)
    fallback_lines = {
        int(line["line_address"], 16)
        for row in fallback_containers
        for line in row["lines"]
    }
    check(len(fallback_lines) == 76, f"fallback line drift: {len(fallback_lines)}")
    check(not (fallback_lines & production_3993), "fallback overlaps 3993")
    production_4069 = production_3993 | fallback_lines
    check(len(production_4069) == 4069, f"4069 drift: {len(production_4069)}")

    unit_primary, unit_subtext = base.unit_sets(data)
    relative_lines = set()
    for container in tracked.relative_pair_containers(data):
        relative_lines.update(int(addr, 16) for addr in container["line_addresses"])
    check(len(relative_lines) == 1530, f"relative line drift: {len(relative_lines)}")

    return {
        "production_3993": production_3993,
        "fallback_76": fallback_lines,
        "production_4069": production_4069,
        "unit_primary_character": unit_primary,
        "unit_subtext_id_command_ab": unit_subtext,
        "relative_id_command_pairs": relative_lines,
        "id_command_producer_union": unit_subtext | relative_lines,
    }


def reconstruct_scenario(data: bytes) -> dict[str, Any]:
    main_targets: set[int] = set()
    main_pointers = 0
    null_slots = 0
    for row in range(MAIN_FIRST_ROW, MAIN_LAST_ROW + 1):
        for slot in range(1, MAIN_SLOTS + 1):
            pointer_file = MAIN_DIRECTORY + 4 * (MAIN_STRIDE_WORDS * row + slot)
            pointer = u32(data, pointer_file)
            if pointer == 0:
                null_slots += 1
                continue
            check(
                ROM_BASE <= pointer < ROM_BASE + len(data),
                f"invalid scenario pointer at {hx(pointer_file)}",
            )
            target = file_of(pointer)
            check(in_range(target, SCENARIO_MAIN), f"scenario pointer escaped bank: {hx(target)}")
            main_targets.add(target)
            main_pointers += 1

    dynamic_targets: set[int] = set()
    dynamic_pointers = 0
    for row in range(DYNAMIC_ROWS):
        for col in range(DYNAMIC_COLUMNS):
            pointer = u32(data, DYNAMIC_POINTER_BASE + (row * DYNAMIC_COLUMNS + col) * 4)
            if pointer == 0:
                continue
            check(
                ROM_BASE <= pointer < ROM_BASE + len(data),
                f"invalid dynamic pointer row={row} col={col}",
            )
            target = file_of(pointer)
            check(in_range(target, SCENARIO_DYNAMIC), f"dynamic pointer escaped pool: {hx(target)}")
            dynamic_targets.add(target)
            dynamic_pointers += 1

    return {
        "main_unique_targets": main_targets,
        "main_pointer_fields": main_pointers,
        "main_null_slots": null_slots,
        "dynamic_unique_targets": dynamic_targets,
        "dynamic_pointer_fields": dynamic_pointers,
    }


def reconstruct_ui(data: bytes, production_files: set[int]) -> dict[str, Any]:
    from ggen_advance_text_codec import DICT_8X16_BASE, DICT_8X16_END, load_dictionary

    contracts = ui.verify_owner_contracts(data)
    dummy_charmap: dict[int, str] = {}
    dictionary = load_dictionary(data, DICT_8X16_BASE, DICT_8X16_END)
    known = production_files

    f16_rows, f16_info = ui.matrix_family_rows(data, ui.FIXED16_MATRIX, known, dummy_charmap, dictionary)
    f40_rows, f40_info = ui.matrix_family_rows(data, ui.FIXED40_MATRIX, known, dummy_charmap, dictionary)
    sec_rows, sec_info = ui.secondary_family_rows(
        data, ui.FIXED40_SECONDARY, known, dummy_charmap, dictionary
    )
    lit_rows, lit_info = ui.direct_f54_family_rows(
        data, ui.DIRECT_F54_LITERAL, known, dummy_charmap, dictionary
    )

    def files(rows: list[dict[str, Any]], tier: str | None = None) -> set[int]:
        out: set[int] = set()
        for row in rows:
            if "target_file_offset" not in row:
                continue
            if tier is not None and row.get("promotion_tier") != tier:
                continue
            out.add(int(row["target_file_offset"], 16))
        return out

    rendered = (
        files(f16_rows, "owner_proven_rendered")
        | files(f40_rows, "owner_proven_rendered")
        | files(sec_rows)
        | files(lit_rows)
    )
    review_only = files(f16_rows, "review_only") | files(f40_rows, "review_only")
    review_only_intervals: list[tuple[int, int, int]] = []
    for row in f16_rows + f40_rows:
        if row.get("promotion_tier") != "review_only":
            continue
        start = int(row["target_file_offset"], 16)
        length = int(row["raw_byte_length"])
        review_only_intervals.append((start, start + length, start))
    review_only_intervals.sort()
    return {
        "owner_contract": contracts,
        "fixed16_counts": f16_info["counts"],
        "fixed40_counts": f40_info["counts"],
        "secondary_counts": sec_info["counts"],
        "literal_counts": lit_info["counts"],
        "rendered_targets": rendered,
        "review_only_targets": review_only,
        "review_only_unique_not_rendered": review_only - rendered,
        "review_only_also_rendered": len(review_only & rendered),
        "review_only_intervals": review_only_intervals,
    }


def load_unified_indexes(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["records"]
    exclusions = payload["exclusions"]
    canonical: dict[int, dict[str, Any]] = {}
    alias_targets: set[int] = set()
    category_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    intervals: list[tuple[int, int, int]] = []
    for row in records:
        offset = int(row["target_file_offset"], 16)
        length = int(row["original_byte_length"])
        scope = str(row["source_scope"])
        status = str(row["scope_status"])
        category = str(row.get("semantic_category") or "")
        if status == "included":
            canonical[offset] = {
                "record_id": row["record_id"],
                "source_scope": scope,
                "semantic_category": category,
                "length": length,
            }
            intervals.append((offset, offset + length, offset))
            category_counts[category] += 1
            scope_counts[scope] += 1
        elif status == "alias":
            alias_targets.add(offset)
        else:
            raise SystemExit(f"unexpected record scope_status: {status}")

    intervals.sort()
    excl_rows: list[dict[str, Any]] = []
    for row in exclusions:
        excl_rows.append(
            {
                "exclusion_id": row["exclusion_id"],
                "source_scope": row["source_scope"],
                "scope_status": row["scope_status"],
                "reason": row.get("reason", ""),
                "family": row.get("family", ""),
                "target_file_offset": int(row["target_file_offset"], 16),
                "aligned_u32_xref_count": int(row.get("aligned_u32_xref_count") or 0),
                "pointer_xref_count": int(row.get("pointer_xref_count") or 0),
                "source_text": str(row.get("source_text") or "")[:80],
            }
        )
    return {
        "summary": payload.get("summary", {}),
        "coverage_declared": payload.get("coverage", {}),
        "canonical": canonical,
        "alias_targets": alias_targets,
        "intervals": intervals,
        "category_counts": dict(sorted(category_counts.items())),
        "scope_counts": dict(sorted(scope_counts.items())),
        "exclusions": excl_rows,
        "identity": payload.get("identity", {}),
    }


def find_covering_record(intervals: list[tuple[int, int, int]], offset: int) -> tuple[int, int, int] | None:
    lo, hi = 0, len(intervals)
    while lo < hi:
        mid = (lo + hi) // 2
        if intervals[mid][0] <= offset:
            lo = mid + 1
        else:
            hi = mid
    idx = lo - 1
    if idx >= 0:
        start, end, rec = intervals[idx]
        if start <= offset < end:
            return start, end, rec
    return None


def classify_exclusions(
    unified: dict[str, Any],
    ui_info: dict[str, Any],
    scenario: dict[str, Any],
    production_files: set[int],
) -> dict[str, Any]:
    canonical = unified["canonical"]
    intervals = unified["intervals"]
    review_only_ui = ui_info["review_only_unique_not_rendered"]
    rendered_ui = ui_info["rendered_targets"]
    scenario_main = scenario["main_unique_targets"]
    scenario_dyn = scenario["dynamic_unique_targets"]

    counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    remaining: list[dict[str, Any]] = []

    for row in unified["exclusions"]:
        offset = row["target_file_offset"]
        scope = row["source_scope"]
        if scope == "non_scenario_ui":
            if offset in review_only_ui:
                label = "ui_review_only_unrendered_selector"
            elif offset in rendered_ui:
                label = "ui_review_only_but_rendered_contract"
            elif offset in canonical:
                label = "ui_exclusion_duplicates_canonical"
            else:
                label = "ui_review_only_unmatched"
        elif scope == "global_pointer_scan":
            if offset in canonical:
                label = "scan_duplicates_canonical_target"
            elif offset in review_only_ui:
                label = "scan_duplicates_ui_review_only"
            elif offset in rendered_ui:
                label = "scan_duplicates_ui_rendered"
            elif in_range(offset, SCENARIO_MAIN) or offset in scenario_main:
                label = "scan_inside_scenario_main_bank"
            elif in_range(offset, SCENARIO_DYNAMIC) or offset in scenario_dyn:
                label = "scan_inside_scenario_dynamic_pool"
            else:
                covering = find_covering_record(intervals, offset)
                if covering is not None:
                    start, end, rec = covering
                    if start == offset:
                        label = "scan_same_start_as_canonical"
                    else:
                        label = "scan_interior_of_canonical_stream"
                        row = {
                            **row,
                            "covering_record_offset": rec,
                            "covering_record_id": canonical[rec]["record_id"],
                            "interior_delta": offset - start,
                        }
                elif offset in production_files:
                    label = "scan_production_target_not_in_sheet"
                else:
                    label = "scan_unproven_no_owner"
                    remaining.append(row)
        else:
            label = f"unexpected_scope_{scope}"
        counts[label] += 1
        if len(samples[label]) < 8:
            samples[label].append(
                {
                    "exclusion_id": row["exclusion_id"],
                    "target_file_offset": hx(offset),
                    "source_text": row.get("source_text", ""),
                    "family": row.get("family", ""),
                    "aligned_u32_xref_count": row.get("aligned_u32_xref_count", 0),
                    "covering_record_id": row.get("covering_record_id", ""),
                }
            )

    return {
        "counts": dict(sorted(counts.items())),
        "samples": {key: samples[key] for key in sorted(samples)},
        "remaining_unproven": remaining,
        "remaining_unproven_count": len(remaining),
    }


def hex_list(values: set[int], limit: int = 40) -> list[str]:
    ordered = sorted(values)
    return [hx(v) for v in ordered[:limit]]


FONT_RANGES = [
    (0x0008AC40, 0x00093850, "font_12x12_bitmap"),
    (0x00093850, 0x00093FD8, "font_12x12_dictionary"),
    (0x00094028, 0x000A42A8, "font_8x16_bitmap"),
    (0x000A42A8, 0x000A4A2C, "font_8x16_dictionary"),
]


def residual_region(offset: int) -> str:
    if offset < 0x00010000:
        return "vector_or_header"
    for start, end, name in FONT_RANGES:
        if start <= offset < end:
            return name
    if offset < 0x0008AC40:
        return "code_or_early_data"
    if 0x00179E58 <= offset <= 0x001CABDF:
        return "production_payload_range"
    if 0x000A4A2C <= offset < 0x00179E58:
        return "pre_production_data"
    if 0x001CABE0 <= offset < 0x001F1A04:
        return "post_production_pre_scenario"
    if 0x0021D5B1 <= offset < 0x00D00000:
        return "post_scenario_pre_search"
    if 0x001F1A04 <= offset < 0x001F1E6B:
        return "scenario_dynamic_pool"
    if 0x001F5F20 <= offset < 0x0021D5B1:
        return "scenario_main_bank"
    if 0x00D00000 <= offset < 0x00E00000:
        return "search_or_debug_tail"
    if 0x00FC0000 <= offset:
        return "high_table_tail"
    return "other_data"


def explain_draw_literal_miss(data: bytes, offset: int, sheet_files: set[int]) -> dict[str, Any]:
    raw = data[offset : offset + 32]
    first_ptr = u32(data, offset) if offset + 4 <= len(data) else 0
    if b"bstgmain.c" in data[offset : offset + 64] or raw.startswith(b"D1\x00") or raw.startswith(b"D2\x00"):
        return {
            "target_file_offset": hx(offset),
            "verdict": "debug_or_compiler_string_not_game_text",
            "evidence": raw[:24].hex(" "),
            "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in raw[:24]),
            "promote": False,
        }
    if ROM_BASE <= first_ptr < ROM_BASE + len(data):
        pointed = file_of(first_ptr)
        return {
            "target_file_offset": hx(offset),
            "verdict": "pointer_table_not_text_stream",
            "first_u32": hx(first_ptr),
            "first_u32_file": hx(pointed),
            "pointed_target_already_on_sheet": pointed in sheet_files,
            "promote": False,
        }
    return {
        "target_file_offset": hx(offset),
        "verdict": "unresolved_draw_literal",
        "evidence": raw[:24].hex(" "),
        "promote": True,
    }


def classify_remaining_residuals(
    remaining: list[dict[str, Any]],
    review_only_intervals: list[tuple[int, int, int]],
    sheet_files: set[int],
) -> dict[str, Any]:
    bins: Counter[str] = Counter()
    finer: Counter[str] = Counter()
    for row in remaining:
        offset = row["target_file_offset"]
        region = residual_region(offset)
        bins[region] += 1
        covering_review = find_covering_record(review_only_intervals, offset)
        if covering_review is not None and covering_review[0] != offset:
            finer["interior_of_review_only_stream"] += 1
        elif offset in sheet_files:
            finer["unexpected_sheet_hit"] += 1
        else:
            finer[region] += 1
    return {
        "region_counts": dict(sorted(bins.items())),
        "refined_counts": dict(sorted(finer.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=Path("SD Gundam GGeneration Advance (Japan).gba"))
    parser.add_argument(
        "--unified",
        type=Path,
        default=Path("legacy/analysis/ggen_advance_unified_source_20260827.json"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("legacy/analysis/ggen_advance_unified_coverage_audit_20260828.json"),
    )
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"ROM SHA-256 {digest}")

    production = reconstruct_production(data)
    scenario = reconstruct_scenario(data)
    production_files = {file_of(ptr) for ptr in production["production_4069"]}
    ui_info = reconstruct_ui(data, production_files)
    unified = load_unified_indexes(args.unified)

    sheet_files = set(unified["canonical"])
    sheet_cpu = {ROM_BASE + off for off in sheet_files}

    missing_production = production_files - sheet_files
    extra_production_scope = {
        off
        for off, row in unified["canonical"].items()
        if row["source_scope"] == "production" and off not in production_files
    }
    missing_scenario = scenario["main_unique_targets"] - sheet_files
    extra_scenario = {
        off
        for off, row in unified["canonical"].items()
        if row["source_scope"] == "scenario_main" and off not in scenario["main_unique_targets"]
    }
    missing_ui_rendered = ui_info["rendered_targets"] - sheet_files
    extra_ui = {
        off
        for off, row in unified["canonical"].items()
        if row["source_scope"] == "non_scenario_ui" and off not in ui_info["rendered_targets"]
    }

    id_sheet = {
        off
        for off, row in unified["canonical"].items()
        if row["semantic_category"] in ID_COMMAND_CATEGORIES
    }
    id_producer = {file_of(ptr) for ptr in production["id_command_producer_union"]}
    missing_id = id_producer - sheet_files
    battle_sheet = {
        off
        for off, row in unified["canonical"].items()
        if row["semantic_category"] in BATTLE_CATEGORIES
    }

    ca0_calls = collect_draw_sites(data, DRAW_CA0)
    f54_calls = collect_draw_sites(data, DRAW_F54)
    check(len(ca0_calls) == 196, f"CA0 draw drift: {len(ca0_calls)}")
    ca0_literals = pc_literal_targets(data, ca0_calls)
    f54_literals = pc_literal_targets(data, f54_calls)
    missing_ca0_literals = set(ca0_literals) - sheet_files
    missing_f54_literals = set(f54_literals) - sheet_files - ui_info["rendered_targets"]

    classified = classify_exclusions(unified, ui_info, scenario, production_files)
    remaining = classified["remaining_unproven"]
    remaining_in_draw = [
        row
        for row in remaining
        if row["target_file_offset"] in ca0_literals or row["target_file_offset"] in f54_literals
    ]
    residual = classify_remaining_residuals(
        remaining, ui_info["review_only_intervals"], sheet_files
    )
    draw_literal_explanations = [
        explain_draw_literal_miss(data, offset, sheet_files)
        for offset in sorted(missing_ca0_literals | missing_f54_literals)
    ]
    unresolved_draw_literals = [row for row in draw_literal_explanations if row["promote"]]

    review_only_count = sum(1 for row in unified["exclusions"] if row["source_scope"] == "non_scenario_ui")
    scan_count = sum(1 for row in unified["exclusions"] if row["source_scope"] == "global_pointer_scan")

    producer_gaps = missing_production | missing_scenario | missing_ui_rendered | missing_id
    promotion_candidates = sorted(
        producer_gaps
        | {
            int(row["target_file_offset"], 16)
            if isinstance(row["target_file_offset"], str)
            else row["target_file_offset"]
            for row in unresolved_draw_literals
        }
    )

    scan_closed = not unresolved_draw_literals
    judgment = {
        "scenario_event_bank": "closed" if not missing_scenario and not extra_scenario else "gap",
        "id_command_producer_tables": "closed" if not missing_id else "gap",
        "production_4069": "closed" if not missing_production else "gap",
        "ui_owner_proven_rendered": "closed" if not missing_ui_rendered else "gap",
        "ui_review_only": "keep_excluded_no_draw_edge",
        "global_pointer_scan": "no_owner_proven_remainder" if scan_closed else "draw_literal_gap",
        "sheet_promotion_required": len(promotion_candidates) > 0,
    }
    closed = all(
        judgment[key] in {"closed", "keep_excluded_no_draw_edge", "no_owner_proven_remainder"}
        for key in judgment
        if key != "sheet_promotion_required"
    )

    report = {
        "schema_version": 1,
        "scope": "unified translation sheet coverage audit vs independently reconstructed producers",
        "rom_sha256": digest,
        "unified_identity": unified["identity"],
        "declared_coverage": unified["coverage_declared"],
        "sheet": {
            "canonical_records": len(sheet_files),
            "alias_records": len(unified["alias_targets"]),
            "scope_counts": unified["scope_counts"],
            "semantic_category_counts": unified["category_counts"],
            "id_command_in_sheet": len(id_sheet),
            "battle_condition_in_sheet": len(battle_sheet),
            "scenario_main_in_sheet": unified["scope_counts"].get("scenario_main", 0),
        },
        "independent_reconstruction": {
            "production_4069": len(production["production_4069"]),
            "scenario_main_unique": len(scenario["main_unique_targets"]),
            "scenario_main_pointer_fields": scenario["main_pointer_fields"],
            "scenario_main_null_slots": scenario["main_null_slots"],
            "scenario_dynamic_unique": len(scenario["dynamic_unique_targets"]),
            "ui_rendered_unique": len(ui_info["rendered_targets"]),
            "ui_review_only_unique": len(ui_info["review_only_unique_not_rendered"]),
            "ui_review_only_also_rendered": ui_info["review_only_also_rendered"],
            "id_command_producer_unique": len(id_producer),
            "owner_contract_verification": ui_info["owner_contract"],
            "ui_family_counts": {
                "fixed16": ui_info["fixed16_counts"],
                "fixed40": ui_info["fixed40_counts"],
                "secondary": ui_info["secondary_counts"],
                "literal": ui_info["literal_counts"],
            },
        },
        "gaps_vs_sheet": {
            "missing_production_4069": hex_list(missing_production),
            "missing_production_count": len(missing_production),
            "production_scope_not_in_4069": hex_list(extra_production_scope),
            "production_scope_not_in_4069_count": len(extra_production_scope),
            "missing_scenario_main": hex_list(missing_scenario),
            "missing_scenario_main_count": len(missing_scenario),
            "extra_scenario_main": hex_list(extra_scenario),
            "extra_scenario_main_count": len(extra_scenario),
            "missing_ui_rendered": hex_list(missing_ui_rendered),
            "missing_ui_rendered_count": len(missing_ui_rendered),
            "ui_scope_not_in_rendered": hex_list(extra_ui),
            "ui_scope_not_in_rendered_count": len(extra_ui),
            "missing_id_command_producer": hex_list(missing_id),
            "missing_id_command_producer_count": len(missing_id),
            "id_command_sheet_minus_producer_count": len(id_sheet - id_producer),
        },
        "draw_literals": {
            "ca0_call_count": len(ca0_calls),
            "f54_call_count": len(f54_calls),
            "ca0_pc_literal_targets": len(ca0_literals),
            "f54_pc_literal_targets": len(f54_literals),
            "missing_ca0_literal_count": len(missing_ca0_literals),
            "missing_ca0_literals": hex_list(missing_ca0_literals),
            "missing_f54_literal_count": len(missing_f54_literals),
            "missing_f54_literals": hex_list(missing_f54_literals),
            "literal_miss_explanations": draw_literal_explanations,
        },
        "exclusions": {
            "total": len(unified["exclusions"]),
            "review_only_ui_rows": review_only_count,
            "global_scan_rows": scan_count,
            "classification_counts": classified["counts"],
            "samples": classified["samples"],
            "remaining_unproven_count": classified["remaining_unproven_count"],
            "remaining_unproven_residual": residual,
            "remaining_unproven_with_draw_literal": [
                {
                    "exclusion_id": row["exclusion_id"],
                    "target_file_offset": hx(row["target_file_offset"]),
                    "source_text": row.get("source_text", ""),
                }
                for row in remaining_in_draw
            ],
            "remaining_unproven_sample": [
                {
                    "exclusion_id": row["exclusion_id"],
                    "target_file_offset": hx(row["target_file_offset"]),
                    "aligned_u32_xref_count": row.get("aligned_u32_xref_count", 0),
                    "pointer_xref_count": row.get("pointer_xref_count", 0),
                    "source_text": row.get("source_text", ""),
                }
                for row in remaining[:25]
            ],
        },
        "judgment": {
            **judgment,
            "owner_proven_families_closed": closed,
            "promotion_candidate_count": len(promotion_candidates),
            "promotion_candidates": [hx(v) for v in promotion_candidates],
            "conclusion": (
                "Owner-proven scenario, ID-command, production, and rendered-UI families are closed against the unified sheet. "
                "review_only matrix selectors stay excluded (no text draw edge). "
                "CA0/F54 lookback misses are debug strings or pointer tables, not missing game text. "
                "Global pointer-scan remainder is not a missing-text queue."
                if closed and not promotion_candidates
                else "Coverage gaps remain; see gaps_vs_sheet and promotion_candidates."
            ),
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS" if closed and not promotion_candidates else "GAP",
                "output": str(args.out),
                "sheet_canonical": len(sheet_files),
                "exclusions": len(unified["exclusions"]),
                "classification": classified["counts"],
                "gaps": {
                    "production": len(missing_production),
                    "scenario": len(missing_scenario),
                    "ui_rendered": len(missing_ui_rendered),
                    "id_command": len(missing_id),
                    "ca0_literals": len(missing_ca0_literals),
                    "f54_literals": len(missing_f54_literals),
                    "remaining_unproven": classified["remaining_unproven_count"],
                    "remaining_residual": residual,
                    "promotion_candidates": len(promotion_candidates),
                    "draw_literal_explanations": draw_literal_explanations,
                },
                "judgment": report["judgment"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
