#!/usr/bin/env python3
"""Audit owner-proven non-scenario UI text families outside the 4,069 set.

The global pointer scan is intentionally only a discovery aid: ordinary ROM
bytes can look like Advance token streams.  This audit promotes a candidate
only when a known accessor helper and a text renderer establish the producer
contract.  The scenario/event banks are excluded explicitly and are never
merged into this report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ggen_advance_text_codec import (  # noqa: E402
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens_strict,
)

EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

# File-offset ranges separated by the scenario/event audit.  A hard gate below
# ensures no promoted UI target can silently enter one of these banks.
SCENARIO_EXCLUSIONS = [
    {"name": "scenario_dynamic_pool", "start": 0x001F1A04, "end": 0x001F1E6B},
    {"name": "scenario_main_bank", "start": 0x001F5F20, "end": 0x0021D5B1},
]

FIXED16_MATRIX = {
    "family": "fixed16_option_matrix",
    "base_file": 0x001AC7FC,
    "count": 137,
    "stride": 0x60,
    "selector_count": 24,
    "rendered_selectors": list(range(6)),
    "semantic_category": "configuration_option_text",
    "font_mode": "12x12",
    "accessor": "0x080122C8",
    "renderer": "0x0807A392-0x0807A47A",
    "renderer_draw": "0x08000F54",
    "owner_evidence": (
        "0x080122C8 masks index/selector to bytes and loads "
        "0x001AC7FC + index*0x60 + selector*4; "
        "0x0807A338 initializes the draw object through 0x080004B8, which sets "
        "object+0x64 bit0=1; 0x08001238 dispatches bit0=1 to the 12x12 "
        "renderer at 0x08001354. 0x0807A392-0x0807A47A then draws selectors "
        "0..5 through 0x08000F54."
    ),
}

FIXED40_MATRIX = {
    "family": "fixed40_option_matrix",
    "base_file": 0x001B168C,
    "count": 174,
    "stride": 0x50,
    "selector_count": 20,
    "rendered_selectors": list(range(5)),
    "semantic_category": "configuration_option_text",
    "font_mode": "12x12",
    "accessor": "0x080123C4",
    "renderer": "0x0807A8AC-0x0807A96A",
    "renderer_draw": "0x08000F54",
    "owner_evidence": (
        "0x080123C4 masks index/selector to bytes and loads "
        "0x001B168C + index*0x50 + selector*4; "
        "0x0807A854 initializes the draw object through 0x080004B8, which sets "
        "object+0x64 bit0=1; 0x08001238 dispatches bit0=1 to the 12x12 "
        "renderer at 0x08001354. 0x0807A8AC-0x0807A96A then draws selectors "
        "0..4 through 0x08000F54."
    ),
}

FIXED40_SECONDARY = {
    "family": "fixed40_secondary_display_text",
    "base_file": 0x001AFB5C,
    "count": 522,
    "stride": 0x28,
    "field_offset": 0x24,
    "semantic_category": "unit_name_alternate",
    "accessor": "0x080123F0",
    "renderer": "0x08074C4A-0x08074CA2",
    "renderer_draw": "0x08000F54",
    "owner_evidence": (
        "0x080123F0 loads 0x001AFB5C + index*0x28 + 0x24; "
        "0x08074C4A-0x08074CA2 first calls 0x08012320 for the same "
        "record index, then 0x080123F0, then draws the returned stream "
        "through 0x08000F54."
    ),
}

DIRECT_F54_LITERAL = {
    "family": "direct_f54_literal_ui",
    "semantic_category": "ui_menu_or_status_text",
    "targets_and_calls": {
        0x001BE7AA: [0x0006DF14],
        0x001BE783: [0x0007459C, 0x000749BC, 0x00074ABE, 0x00074C3C, 0x00074C98],
        0x001BEE87: [0x00074D9E],
        0x001BEE8E: [0x00074DBE],
        0x001BEE95: [0x00074DDE],
        0x001BEE9E: [0x00074E00],
    },
    "renderer": "0x08000F54",
    "owner_evidence": (
        "Each listed call site has a preceding Thumb PC-relative LDR into r3 "
        "and a direct BL to 0x08000F54. The literal pool u32 equals the "
        "listed target; no scenario bank is involved."
    ),
}


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def thumb_bl_target(data: bytes, file_offset: int) -> int | None:
    """Decode one Thumb-1 BL at a file offset, if present."""
    if file_offset < 0 or file_offset + 4 > len(data):
        return None
    hi, lo = struct.unpack_from("<HH", data, file_offset)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    displacement = ((hi & 0x07FF) << 12) | ((lo & 0x07FF) << 1)
    if displacement & (1 << 22):
        displacement -= 1 << 23
    return (ROM_BASE + file_offset + 4 + displacement) & 0xFFFFFFFF


def bl_sites(data: bytes, start: int, end_exclusive: int, target: int) -> list[int]:
    return [
        offset
        for offset in range(start & ~1, end_exclusive, 2)
        if thumb_bl_target(data, offset) == target
    ]


def pc_literal_r3(data: bytes, call_offset: int) -> tuple[int, int, int] | None:
    """Return (writer_offset, literal_pool_offset, literal_value) before a draw."""
    for writer in range(max(0, call_offset - 0x20), call_offset, 2):
        halfword = struct.unpack_from("<H", data, writer)[0]
        if halfword & 0xF800 != 0x4800 or ((halfword >> 8) & 0x07) != 3:
            continue
        pool = ((writer + 4) & ~3) + ((halfword & 0xFF) << 2)
        if pool + 4 <= len(data):
            return writer, pool, u32(data, pool)
    return None


def verify_owner_contracts(data: bytes) -> dict[str, Any]:
    """Check the literal bases and the renderer call edges used by this audit."""
    gates = {
        "fixed16_matrix_base_literal": u32(data, 0x00122F0) == ROM_BASE + FIXED16_MATRIX["base_file"],
        "fixed40_matrix_base_literal": u32(data, 0x00123EC) == ROM_BASE + FIXED40_MATRIX["base_file"],
        "fixed40_record_base_literal": u32(data, 0x0012404) == ROM_BASE + FIXED40_SECONDARY["base_file"],
        "fixed16_draw_object_12x12_init": len(bl_sites(data, 0x0007A338, 0x0007A392, 0x080004B8)) == 1,
        "fixed16_accessor_calls": len(bl_sites(data, 0x0007A392, 0x0007A47C, 0x080122C8)) == 6,
        "fixed16_accessor_draw_calls": len(bl_sites(data, 0x0007A392, 0x0007A47C, 0x08000F54)) == 6,
        "fixed40_draw_object_12x12_init": len(bl_sites(data, 0x0007A854, 0x0007A8AC, 0x080004B8)) == 1,
        "fixed40_accessor_calls": len(bl_sites(data, 0x0007A8AC, 0x0007A96E, 0x080123C4)) == 5,
        "fixed40_accessor_draw_calls": len(bl_sites(data, 0x0007A8AC, 0x0007A96E, 0x08000F54)) == 5,
        "fixed40_secondary_record_accessor": len(bl_sites(data, 0x00074C4A, 0x00074CA4, 0x08012320)) == 1,
        "fixed40_secondary_text_accessor": len(bl_sites(data, 0x00074C4A, 0x00074CA4, 0x080123F0)) == 1,
        "fixed40_secondary_draw_call": len(bl_sites(data, 0x00074C4A, 0x00074CA4, 0x08000F54)) == 2,
        "direct_f54_literal_draw_calls": sum(
            len(calls) for calls in DIRECT_F54_LITERAL["targets_and_calls"].values()
        ) == 10,
    }
    failed = [name for name, passed in gates.items() if not passed]
    if failed:
        raise SystemExit(f"owner contract gate failed: {', '.join(failed)}")
    return {
        "result": "PASS",
        "gates": gates,
        "notes": "Thumb BL edge counts and helper base literals match the fixed UI-owner contract.",
    }


def is_rom_ptr(value: int, size: int) -> bool:
    return ROM_BASE <= value < ROM_BASE + size


def excluded_reason(offset: int) -> str | None:
    for row in SCENARIO_EXCLUSIONS:
        if row["start"] <= offset < row["end"]:
            return row["name"]
    return None


def load_known_targets(path: Path) -> set[int]:
    report = json.loads(path.read_text(encoding="utf-8"))
    return {int(row["target_file_offset"], 16) for row in report["records"]}


def load_charmap(path: Path) -> dict[int, str]:
    seed = json.loads(path.read_text(encoding="utf-8"))
    return {int(slot, 16): char for slot, char in seed["verified_charmap"].items()}


def decode_slots(slots: list[int], charmap: dict[int, str]) -> str:
    return "".join(charmap.get(slot, f"<{slot:04X}>") for slot in slots)


def parse_target(
    data: bytes,
    pointer: int,
    charmap: dict[int, str],
    dictionary: list[list[int]],
) -> dict[str, Any] | None:
    if not is_rom_ptr(pointer, len(data)):
        return None
    offset = pointer - ROM_BASE
    excluded = excluded_reason(offset)
    if excluded:
        raise AssertionError(f"UI owner points into excluded {excluded}: 0x{offset:08X}")
    try:
        tokens, raw = read_tokens_strict(data, offset)
        slots = expand_to_slots(tokens, dictionary)
    except (ValueError, IndexError):
        return {"parse_error": "invalid_or_unterminated_token_stream"}
    return {
        "target_file_offset": f"0x{offset:08X}",
        "target_address": f"0x{pointer:08X}",
        "raw_byte_length": len(raw),
        "raw_hex": raw.hex(" ").upper(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "token_count": len(tokens),
        "expanded_units": len(slots),
        "slots": [f"0x{x:04X}" for x in slots],
        "decoded_text_seed": decode_slots(slots, charmap),
        "unresolved_slots": sorted({f"0x{x:04X}" for x in slots if x not in charmap}),
    }


def matrix_family_rows(
    data: bytes,
    spec: dict[str, Any],
    known: set[int],
    charmap: dict[int, str],
    dictionary: list[list[int]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    all_targets: set[int] = set()
    rendered_targets: set[int] = set()
    for index in range(spec["count"]):
        row_base = spec["base_file"] + index * spec["stride"]
        for selector in range(spec["selector_count"]):
            source = row_base + selector * 4
            pointer = u32(data, source)
            if pointer == 0:
                counters["null_cells"] += 1
                continue
            counters["non_null_cells"] += 1
            parsed = parse_target(data, pointer, charmap, dictionary)
            if parsed is None:
                counters["non_rom_pointer_cells"] += 1
                continue
            if "parse_error" in parsed:
                counters["invalid_stream_cells"] += 1
                continue
            target = pointer - ROM_BASE
            all_targets.add(target)
            rendered = selector in spec["rendered_selectors"]
            if rendered:
                rendered_targets.add(target)
            row = {
                **parsed,
                "family": spec["family"],
                "record_index": index,
                "selector": selector,
                "pointer_source_file": f"0x{source:08X}",
                "owner_contract": "rendered_owner_proven" if rendered else "availability_or_unresolved_owner",
                "promotion_tier": "owner_proven_rendered" if rendered else "review_only",
                "semantic_category": spec["semantic_category"],
                "font_mode": spec.get("font_mode", "8x16"),
                "overlaps_production_4069": target in known,
            }
            rows.append(row)
            counters["strict_parseable_cells"] += 1
    counters["all_unique_targets"] = len(all_targets)
    counters["rendered_unique_targets"] = len(rendered_targets)
    counters["rendered_cells"] = sum(
        1 for row in rows if row["promotion_tier"] == "owner_proven_rendered"
    )
    counters["all_overlap_production"] = len(all_targets & known)
    counters["rendered_overlap_production"] = len(rendered_targets & known)
    counters["all_new_targets"] = len(all_targets - known)
    counters["rendered_new_targets"] = len(rendered_targets - known)
    counters["rendered_raw_bytes"] = sum(
        row["raw_byte_length"]
        for row in rows
        if row["promotion_tier"] == "owner_proven_rendered"
    )
    return rows, {
        "family": spec["family"],
        "storage": {
            "base_file": f"0x{spec['base_file']:08X}",
            "count": spec["count"],
            "stride": spec["stride"],
            "selector_count": spec["selector_count"],
            "rendered_selectors": spec["rendered_selectors"],
        },
        "owner": {
            "accessor": spec["accessor"],
            "renderer": spec["renderer"],
            "renderer_draw": spec["renderer_draw"],
            "evidence": spec["owner_evidence"],
        },
        "counts": dict(counters),
        "all_targets": sorted(f"0x{x:08X}" for x in all_targets),
        "rendered_targets": sorted(f"0x{x:08X}" for x in rendered_targets),
    }


def secondary_family_rows(
    data: bytes,
    spec: dict[str, Any],
    known: set[int],
    charmap: dict[int, str],
    dictionary: list[list[int]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    targets: set[int] = set()
    for index in range(spec["count"]):
        source = spec["base_file"] + index * spec["stride"] + spec["field_offset"]
        pointer = u32(data, source)
        if pointer == 0:
            counters["null_cells"] += 1
            continue
        counters["non_null_cells"] += 1
        parsed = parse_target(data, pointer, charmap, dictionary)
        if parsed is None:
            counters["non_rom_pointer_cells"] += 1
            continue
        if "parse_error" in parsed:
            counters["invalid_stream_cells"] += 1
            continue
        target = pointer - ROM_BASE
        targets.add(target)
        rows.append(
            {
                **parsed,
                "family": spec["family"],
                "record_index": index,
                "selector": None,
                "pointer_source_file": f"0x{source:08X}",
                "owner_contract": "rendered_owner_proven",
                "promotion_tier": "owner_proven_rendered",
                "semantic_category": spec["semantic_category"],
                "overlaps_production_4069": target in known,
            }
        )
        counters["strict_parseable_cells"] += 1
    counters["unique_targets"] = len(targets)
    counters["overlap_production"] = len(targets & known)
    counters["new_targets"] = len(targets - known)
    counters["raw_bytes"] = sum(row["raw_byte_length"] for row in rows)
    return rows, {
        "family": spec["family"],
        "storage": {
            "base_file": f"0x{spec['base_file']:08X}",
            "count": spec["count"],
            "stride": spec["stride"],
            "field_offset": f"0x{spec['field_offset']:02X}",
        },
        "owner": {
            "accessor": spec["accessor"],
            "renderer": spec["renderer"],
            "renderer_draw": spec["renderer_draw"],
            "evidence": spec["owner_evidence"],
        },
        "counts": dict(counters),
        "targets": sorted(f"0x{x:08X}" for x in targets),
    }


def direct_f54_family_rows(
    data: bytes,
    spec: dict[str, Any],
    known: set[int],
    charmap: dict[int, str],
    dictionary: list[list[int]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    targets: set[int] = set()
    call_count = 0
    pointer_sources: set[int] = set()
    for target, calls in sorted(spec["targets_and_calls"].items()):
        parsed = parse_target(data, ROM_BASE + target, charmap, dictionary)
        if parsed is None or "parse_error" in parsed:
            raise SystemExit(f"direct F54 target is not strict text: 0x{target:08X}")
        call_rows: list[dict[str, Any]] = []
        for call in calls:
            if thumb_bl_target(data, call) != 0x08000F54:
                raise SystemExit(f"direct F54 draw edge drift at 0x{call:08X}")
            literal = pc_literal_r3(data, call)
            if literal is None or literal[2] != ROM_BASE + target:
                raise SystemExit(f"direct F54 literal edge drift at 0x{call:08X}")
            writer, pool, _value = literal
            pointer_sources.add(pool)
            call_rows.append(
                {
                    "draw_call_file": f"0x{call:08X}",
                    "draw_call_address": f"0x{ROM_BASE + call:08X}",
                    "r3_writer_file": f"0x{writer:08X}",
                    "pointer_source_file": f"0x{pool:08X}",
                    "patchable_u32": True,
                    "relocation_schema": "ordinary_u32_stream",
                }
            )
            call_count += 1
        targets.add(target)
        rows.append(
            {
                **parsed,
                "family": spec["family"],
                "record_index": None,
                "selector": None,
                "pointer_source_file": call_rows[0]["pointer_source_file"],
                "draw_calls": call_rows,
                "owner_contract": "rendered_owner_proven",
                "promotion_tier": "owner_proven_rendered",
                "semantic_category": spec["semantic_category"],
                "overlaps_production_4069": target in known,
            }
        )
    audit = {
        "family": spec["family"],
        "storage": {
            "targets_and_calls": {
                f"0x{target:08X}": [f"0x{call:08X}" for call in calls]
                for target, calls in sorted(spec["targets_and_calls"].items())
            },
            "renderer": spec["renderer"],
        },
        "owner": {
            "renderer": spec["renderer"],
            "evidence": spec["owner_evidence"],
        },
        "counts": {
            "unique_targets": len(targets),
            "draw_call_count": call_count,
            "pointer_source_u32_count": len(pointer_sources),
            "overlap_production": len(targets & known),
            "new_targets": len(targets - known),
            "raw_bytes": sum(row["raw_byte_length"] for row in rows),
        },
        "targets": sorted(f"0x{x:08X}" for x in targets),
    }
    return rows, audit


def target_set(rows: list[dict[str, Any]]) -> set[int]:
    return {int(row["target_file_offset"], 16) for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--report", type=Path, default=Path("legacy/analysis/stage2_translation_sheet_rows_20260827.json"))
    parser.add_argument("--charmap", type=Path, default=Path("font_tables/ggen_advance_japanese_charmap_seed_20260826.json"), help="8x16 charmap for non-matrix families")
    parser.add_argument("--charmap12", type=Path, default=Path("analysis/ggen_advance_12x12_identified_charmap_20260828.json"), help="12x12 charmap for fixed16/fixed40 option matrices")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != EXPECTED_SIZE or digest != EXPECTED_SHA256:
        raise SystemExit(f"unexpected ROM: size={len(data)}, sha256={digest}")
    known = load_known_targets(args.report)
    if len(known) != 4069:
        raise SystemExit(f"production target drift: expected 4069, got {len(known)}")
    charmap8 = load_charmap(args.charmap)
    charmap12 = load_charmap(args.charmap12)
    dictionary8 = load_dictionary(data, DICT_8X16_BASE, DICT_8X16_END)
    dictionary12 = load_dictionary(data, DICT_12X12_BASE, DICT_12X12_END)
    owner_contract = verify_owner_contracts(data)

    # The two option matrices are 12x12.  Their draw routines initialize the
    # render object through 0x080004B8 (bit0=1), and 0x08001238 dispatches
    # bit0=1 to 0x08001354.  The secondary/direct families remain 8x16 until
    # an equally explicit owner-mode proof says otherwise.
    f16_rows, f16_audit = matrix_family_rows(data, FIXED16_MATRIX, known, charmap12, dictionary12)
    f40_rows, f40_audit = matrix_family_rows(data, FIXED40_MATRIX, known, charmap12, dictionary12)
    secondary_rows, secondary_audit = secondary_family_rows(
        data, FIXED40_SECONDARY, known, charmap8, dictionary8
    )
    direct_rows, direct_audit = direct_f54_family_rows(
        data, DIRECT_F54_LITERAL, known, charmap8, dictionary8
    )

    promoted = {
        FIXED16_MATRIX["family"]: target_set(
            [row for row in f16_rows if row["promotion_tier"] == "owner_proven_rendered"]
        ),
        FIXED40_MATRIX["family"]: target_set(
            [row for row in f40_rows if row["promotion_tier"] == "owner_proven_rendered"]
        ),
        FIXED40_SECONDARY["family"]: target_set(secondary_rows),
        DIRECT_F54_LITERAL["family"]: target_set(direct_rows),
    }
    all_families = {
        FIXED16_MATRIX["family"]: target_set(f16_rows),
        FIXED40_MATRIX["family"]: target_set(f40_rows),
        FIXED40_SECONDARY["family"]: target_set(secondary_rows),
        DIRECT_F54_LITERAL["family"]: target_set(direct_rows),
    }
    promoted_union = set().union(*promoted.values())
    all_union = set().union(*all_families.values())
    family_names = list(promoted)
    pairwise: dict[str, int] = {}
    for left_index, left in enumerate(family_names):
        for right in family_names[left_index + 1 :]:
            pairwise[f"{left} ∩ {right}"] = len(promoted[left] & promoted[right])

    samples: dict[str, list[dict[str, Any]]] = {}
    for family, rows in (
        (FIXED16_MATRIX["family"], f16_rows),
        (FIXED40_MATRIX["family"], f40_rows),
        (FIXED40_SECONDARY["family"], secondary_rows),
        (DIRECT_F54_LITERAL["family"], direct_rows),
    ):
        samples[family] = sorted(rows, key=lambda row: int(row["target_file_offset"], 16))[:12]

    output = {
        "schema_version": 1,
        "scope": "owner-proven non-scenario UI expansion outside integrated 4,069 records",
        "source": {
            "file": str(args.rom),
            "size": len(data),
            "sha256": digest,
        },
        "production_reference": {
            "report": str(args.report),
            "target_count": len(known),
            "target_range_note": "The 4,069-row production set is used only as a deduplication baseline; no scenario/event rows are included.",
        },
        "scenario_exclusions": [
            {**row, "start": f"0x{row['start']:08X}", "end": f"0x{row['end']:08X}"}
            for row in SCENARIO_EXCLUSIONS
        ],
        "owner_contract_verification": owner_contract,
        "font_mode_correction": {
            "fixed16_option_matrix": "12x12",
            "fixed40_option_matrix": "12x12",
            "fixed40_secondary_display_text": "8x16_pending_separate_owner_proof",
            "direct_f54_literal_ui": "8x16_pending_separate_owner_proof",
            "evidence": "0x080004B8 sets object+0x64 bit0=1 for both option-matrix draw objects; 0x08001238 routes bit0=1 to 0x08001354 (12x12).",
        },
        "families": {
            FIXED16_MATRIX["family"]: f16_audit,
            FIXED40_MATRIX["family"]: f40_audit,
            FIXED40_SECONDARY["family"]: secondary_audit,
            DIRECT_F54_LITERAL["family"]: direct_audit,
        },
        "promotion_summary": {
            "owner_proven_family_count": len(promoted),
            "owner_proven_unique_targets": len(promoted_union),
            "owner_proven_new_targets_outside_4069": len(promoted_union - known),
            "owner_proven_overlap_4069": len(promoted_union & known),
            "all_strict_unique_targets_before_render_filter": len(all_union),
            "all_strict_new_targets_before_render_filter": len(all_union - known),
            "pairwise_owner_proven_overlaps": pairwise,
            "production_plus_owner_proven_unique_total": len(known | promoted_union),
            "promotion_policy": "Only rendered selectors, the fixed40 secondary draw path, and direct F54 literal callsites are owner-proven. Availability-only matrix selectors remain review_only and are not counted in the expansion total.",
        },
        "samples": samples,
        "records": f16_rows + f40_rows + secondary_rows + direct_rows,
    }

    for row in output["records"]:
        offset = int(row["target_file_offset"], 16)
        if excluded_reason(offset):
            raise SystemExit(f"scenario exclusion leaked into output: {row['target_file_offset']}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["promotion_summary"], ensure_ascii=False, indent=2))
    for family, audit in output["families"].items():
        print(f"{family}: {json.dumps(audit['counts'], ensure_ascii=False, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
