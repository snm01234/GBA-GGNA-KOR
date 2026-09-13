#!/usr/bin/env python3
"""Build the complete advance-local Stage-2 production reference manifest.

This tool intentionally separates three checkpoints:

* 3,948 historical compatibility records;
* 3,993 tracked multiline-aware successor records;
* 4,069 production-complete records, adding the 38 runtime fallback
  victory/defeat pairs selected through search-record field +0x14.

The 4,069 layer is the canonical translation-source layer.  Every record must
have source/reference provenance.  Relocation ownership is modeled separately:
ordinary u32 pointers, 18 static length-prefixed-pair literals, 64 runtime
fallback-pair fields, 114 double-NUL-list owner pointers, and one relative-block
base literal.

The ROM is read only.  No candidate ROM is written by this tool.
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

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_direct_pc_literal as dpc  # noqa: E402
import extract_stage2_contract_manifest as tracked  # noqa: E402
import reconstruct_stage2_historical_exact as exact  # noqa: E402
import reconstruct_stage2_target_set as base  # noqa: E402

ROM_BASE = base.ROM_BASE
ROM_SIZE = base.ROM_SIZE
ROM_SHA256 = base.ROM_SHA256

FINAL_RECORDS = 4_069
FINAL_RAW_BYTES = 63_294
FINAL_IDENTITY_SHA256 = "aed8adf6b6dae1377f077235c35988f6d37119f072b64d97c207451882c53808"

FALLBACK_CATEGORY = "runtime_fallback_pair"
FALLBACK_RECORDS = 76
FALLBACK_RAW_BYTES = 1_338

RELATIVE_BASE_FILE = 0x001BF908
RELATIVE_BASE_LITERAL_FILE = 0x0004DC54


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def strict_raw(data: bytes, pointer: int) -> bytes:
    raw = exact.strict_stream(data, pointer)
    check(raw is not None, f"strict text parse failed at 0x{pointer:08X}")
    return raw or b""


def add_reference(
    refs: dict[int, list[dict[str, Any]]],
    pointer: int,
    reference: dict[str, Any],
) -> None:
    refs[pointer].append(reference)


def fallback_lines_and_sources(
    data: bytes,
) -> tuple[set[int], dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    refs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    pair_by_pointer: dict[int, dict[str, Any]] = {}
    targets: set[int] = set()

    for search_index in range(tracked.SEARCH_COUNT):
        pointer_source = tracked.SEARCH_DB + search_index * tracked.SEARCH_STRIDE + tracked.SEARCH_PAIR_FIELD
        pair_pointer = u32(data, pointer_source)
        pair = pair_by_pointer.get(pair_pointer)
        if pair is None:
            pair = tracked.parse_length_prefixed_pair(data, pair_pointer)
            pair_by_pointer[pair_pointer] = pair
        for line_index, line in enumerate(pair["lines"]):
            line_pointer = int(line["line_address"], 16)
            targets.add(line_pointer)
            add_reference(
                refs,
                line_pointer,
                {
                    "source_type": "runtime_fallback_length_prefixed_pair",
                    "family": FALLBACK_CATEGORY,
                    "search_index": search_index,
                    "pair_address": f"0x{pair_pointer:08X}",
                    "line_index": line_index,
                    "pointer_source_file": f"0x{pointer_source:08X}",
                    "patchable_u32": True,
                    "relocation_schema": "length_prefixed_pair_fallback",
                },
            )

    containers = []
    for pair_pointer, pair in sorted(pair_by_pointer.items()):
        source_fields = sorted({
            int(ref["pointer_source_file"], 16)
            for line in pair["lines"]
            for ref in refs[int(line["line_address"], 16)]
            if int(ref["pair_address"], 16) == pair_pointer
        })
        containers.append({
            **pair,
            "container_type": "length_prefixed_pair_fallback",
            "source_pointer_fields": [f"0x{x:08X}" for x in source_fields],
            "source_pointer_field_count": len(source_fields),
        })

    check(len(pair_by_pointer) == 38, f"fallback pair container count drift: {len(pair_by_pointer)}")
    check(len(targets) == FALLBACK_RECORDS, f"fallback line target drift: {len(targets)}")
    check(sum(len(strict_raw(data, p)) for p in targets) == FALLBACK_RAW_BYTES, "fallback raw-byte drift")
    check(len({int(ref["pointer_source_file"], 16) for rows in refs.values() for ref in rows}) == 64,
          "fallback u32 pointer-source count drift")
    return targets, refs, containers


def direct_pc_references(data: bytes) -> dict[int, list[dict[str, Any]]]:
    refs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    draw_calls = [
        off for off in range(0, len(data) - 3, 2)
        if dpc.thumb_bl_target(data, off) == dpc.DRAW_WRAPPER
    ]
    check(len(draw_calls) == dpc.EXPECTED_DRAW_CALLS, "direct-PC draw-call count drift")

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    accepted = 0
    targets: set[int] = set()
    for call_offset in draw_calls:
        candidates: list[tuple[int, int, int]] = []
        start = max(0, call_offset - dpc.LOCAL_LOOKBACK_BYTES)
        for writer_offset in range(start, call_offset, 2):
            literal = dpc.literal_from_ldr_r3(data, writer_offset)
            if literal is None:
                continue
            literal_offset, value = literal
            if not (ROM_BASE <= value < ROM_BASE + len(data)):
                continue
            if dpc.parse_stream(data, value - ROM_BASE) is None:
                continue
            candidates.append((writer_offset, literal_offset, value))
        if not candidates:
            continue
        writer_offset, literal_offset, value = candidates[-1]
        check(
            not dpc.has_later_r3_writer(md, data, writer_offset, call_offset),
            f"direct-PC later r3 writer at call 0x{call_offset:08X}",
        )
        accepted += 1
        targets.add(value)
        add_reference(
            refs,
            value,
            {
                "source_type": "direct_pc_literal",
                "family": "direct_pc_literal",
                "call_file": f"0x{call_offset:08X}",
                "r3_writer_file": f"0x{writer_offset:08X}",
                "pointer_source_file": f"0x{literal_offset:08X}",
                "patchable_u32": True,
                "relocation_schema": "ordinary_u32_stream",
            },
        )
    check(accepted == 121, f"direct-PC accepted call drift: {accepted}")
    check(len(targets) == 67, f"direct-PC target drift: {len(targets)}")
    return refs


def build_reference_map(
    data: bytes,
    production_sets: dict[str, set[int]],
    multiline: dict[str, Any],
    fallback_refs: dict[int, list[dict[str, Any]]],
) -> dict[int, list[dict[str, Any]]]:
    refs: dict[int, list[dict[str, Any]]] = defaultdict(list)

    # Relative 256x3: entries 0..2 are NULL; logical indices 3..767 are 765 pairs.
    relative_containers = tracked.relative_pair_containers(data)
    for pair_index, container in enumerate(relative_containers):
        logical_index = pair_index + 3
        relative_entry = RELATIVE_BASE_FILE + logical_index * 2
        for line_index, address_text in enumerate(container["line_addresses"]):
            pointer = int(address_text, 16)
            add_reference(
                refs,
                pointer,
                {
                    "source_type": "relative_u16_paired_text_table",
                    "family": "relative_256x3_paired_text_table",
                    "pair_index": pair_index,
                    "logical_index": logical_index,
                    "line_index": line_index,
                    "relative_entry_file": f"0x{relative_entry:08X}",
                    "relative_base_file": f"0x{RELATIVE_BASE_FILE:08X}",
                    "patchable_u32": False,
                    "relocation_schema": "relative_pair_block",
                },
            )

    # Fixed producer fields.
    _fixed, fixed_audit = exact.fixed_producer_targets(data)
    for family_name, base_off in (("record16", exact.RECORD16_DB), ("record40", exact.RECORD40_DB)):
        info = fixed_audit[family_name]
        stride = int(info["stride"])
        source_family = "record16_primary_text" if family_name == "record16" else "record40_primary_text"
        for index in info["parseable_indices"]:
            source = base_off + int(index) * stride
            pointer = u32(data, source)
            add_reference(
                refs,
                pointer,
                {
                    "source_type": "producer_database_field",
                    "family": source_family,
                    "record_index": int(index),
                    "pointer_source_file": f"0x{source:08X}",
                    "patchable_u32": True,
                    "relocation_schema": "ordinary_u32_stream",
                },
            )

    # Entity-name pointer fields: source IDs can alias the same record/pointer field.
    id_map = 0x001A4298
    entity_db = 0x0018E2E4
    entity_stride = 0xAC
    for source_id in range(512):
        record_index = u16(data, id_map + source_id * 2)
        source = entity_db + record_index * entity_stride + 4
        pointer = u32(data, source)
        if exact.strict_stream(data, pointer) is None:
            continue
        add_reference(
            refs,
            pointer,
            {
                "source_type": "producer_database_field",
                "family": "entity_name_by_512_id_map",
                "source_id": source_id,
                "record_index": record_index,
                "pointer_source_file": f"0x{source:08X}",
                "patchable_u32": True,
                "relocation_schema": "ordinary_u32_stream",
            },
        )

    # Entity six-subtext slots.
    reachable_entity_records = sorted({u16(data, id_map + source_id * 2) for source_id in range(512)})
    for record_index in reachable_entity_records:
        for selector in range(6):
            source = entity_db + record_index * entity_stride + 0x28 + selector * 0x14
            pointer = u32(data, source)
            if exact.strict_stream(data, pointer) is None:
                continue
            add_reference(
                refs,
                pointer,
                {
                    "source_type": "producer_database_field",
                    "family": "entity_record_six_subtext_slots",
                    "record_index": record_index,
                    "selector": selector,
                    "pointer_source_file": f"0x{source:08X}",
                    "patchable_u32": True,
                    "relocation_schema": "ordinary_u32_stream",
                },
            )

    # Character/unit primary and three subrecords A/B.
    unit_db = 0x001A476C
    unit_stride = 0x78
    for record_index in range(256):
        source = unit_db + record_index * unit_stride + 4
        pointer = u32(data, source)
        if exact.strict_stream(data, pointer) is not None:
            add_reference(refs, pointer, {
                "source_type": "producer_database_field",
                "family": "unit_db_primary_text",
                "record_index": record_index,
                "pointer_source_file": f"0x{source:08X}",
                "patchable_u32": True,
                "relocation_schema": "ordinary_u32_stream",
            })
        for sub_index in range(3):
            for field, family in ((0x24, "unit_db_subrecord_text_A"), (0x2C, "unit_db_subrecord_text_B")):
                source = unit_db + record_index * unit_stride + sub_index * 0x1C + field
                pointer = u32(data, source)
                if exact.strict_stream(data, pointer) is None:
                    continue
                add_reference(refs, pointer, {
                    "source_type": "producer_database_field",
                    "family": family,
                    "record_index": record_index,
                    "sub_index": sub_index,
                    "pointer_source_file": f"0x{source:08X}",
                    "patchable_u32": True,
                    "relocation_schema": "ordinary_u32_stream",
                })

    # ID24 fields.
    id24_base = 0x001C86C8
    for record_index in range(16):
        for field, family in ((0x0C, "id24_record_text_C"), (0x10, "id24_record_text_10"), (0x14, "id24_record_text_14")):
            source = id24_base + record_index * 0x18 + field
            pointer = u32(data, source)
            add_reference(refs, pointer, {
                "source_type": "producer_database_field",
                "family": family,
                "record_index": record_index,
                "pointer_source_file": f"0x{source:08X}",
                "patchable_u32": True,
                "relocation_schema": "ordinary_u32_stream",
            })

    # Normalized 30-entry lookup.
    normalized_base = 0x0018DD68
    for index in range(30):
        source = normalized_base + index * 8
        pointer = u32(data, source)
        add_reference(refs, pointer, {
            "source_type": "producer_database_field",
            "family": "normalized_31_entry_text_table",
            "normalized_index": index,
            "pointer_source_file": f"0x{source:08X}",
            "patchable_u32": True,
            "relocation_schema": "ordinary_u32_stream",
        })

    # Search-record +0x10 and parallel FCE1A0 condition bodies.
    for search_index in range(tracked.SEARCH_COUNT):
        location_source = tracked.SEARCH_DB + search_index * tracked.SEARCH_STRIDE + 0x10
        location = u32(data, location_source)
        add_reference(refs, location, {
            "source_type": "direct_struct_pointer_field",
            "family": "current_search_record_text_10",
            "search_index": search_index,
            "pointer_source_file": f"0x{location_source:08X}",
            "patchable_u32": True,
            "relocation_schema": "ordinary_u32_stream",
        })
        condition_source = 0x00FCE1A0 + search_index * 4
        condition = u32(data, condition_source)
        add_reference(refs, condition, {
            "source_type": "producer_database_field",
            "family": "search_key_to_FCE1A0_text",
            "search_index": search_index,
            "pointer_source_file": f"0x{condition_source:08X}",
            "patchable_u32": True,
            "relocation_schema": "ordinary_u32_stream",
        })

    # Sparse lookup: 23 direct pointer fields + 49 0x10-byte record field0 pointers.
    for index in range(23):
        source = 0x001B4CEC + index * 4
        pointer = u32(data, source)
        add_reference(refs, pointer, {
            "source_type": "producer_database_field",
            "family": "sparse_one_based_byte_text_lookup",
            "input_value": index + 1,
            "pointer_source_file": f"0x{source:08X}",
            "patchable_u32": True,
            "relocation_schema": "ordinary_u32_stream",
        })
    for index in range(49):
        source = 0x001B4D58 + index * 0x10
        pointer = u32(data, source)
        add_reference(refs, pointer, {
            "source_type": "producer_database_field",
            "family": "sparse_record16_text",
            "record_index": index,
            "pointer_source_file": f"0x{source:08X}",
            "patchable_u32": True,
            "relocation_schema": "ordinary_u32_stream",
        })

    # Direct struct 70x8 (after count header) + 30x0x48 field +4.
    for record_index in range(70):
        source = 0x001C94B4 + record_index * 8
        pointer = u32(data, source)
        add_reference(refs, pointer, {
            "source_type": "direct_struct_pointer_field",
            "family": "direct_struct8_text",
            "record_index": record_index,
            "pointer_source_file": f"0x{source:08X}",
            "patchable_u32": True,
            "relocation_schema": "ordinary_u32_stream",
        })
    for record_index in range(30):
        source = 0x001C9B6C + record_index * 0x48 + 4
        pointer = u32(data, source)
        add_reference(refs, pointer, {
            "source_type": "direct_struct_pointer_field",
            "family": "direct_struct72_text",
            "record_index": record_index,
            "pointer_source_file": f"0x{source:08X}",
            "patchable_u32": True,
            "relocation_schema": "ordinary_u32_stream",
        })

    # Indexed ordinary tables other than 1C92E8.
    for base_off, indices, family in (
        (0x00FCE2D8, range(69), "table_FCE2D8_flat69_paired_selection"),
        (0x00FCDF78, range(13), "table_FCDF78_prefix13"),
        (0x00FCE128, range(22), "table_FCE128_22"),
        (0x00FCE2A8, [i for i in range(12) if base.is_rom_ptr(data, u32(data, 0x00FCE2A8 + i * 4))], "table_FCE2A8_sparse12"),
    ):
        for index in indices:
            source = base_off + int(index) * 4
            pointer = u32(data, source)
            add_reference(refs, pointer, {
                "source_type": "indexed_pointer_table",
                "family": family,
                "index": int(index),
                "pointer_source_file": f"0x{source:08X}",
                "patchable_u32": True,
                "relocation_schema": "ordinary_u32_stream",
            })

    # 1C92E8: one owner pointer per double-NUL list; continuation lines are not independently patchable.
    for container in multiline["containers"]:
        source = int(container["pointer_source_file"], 16)
        addresses = [int(x, 16) for x in container["line_addresses"]]
        for line_index, pointer in enumerate(addresses):
            add_reference(refs, pointer, {
                "source_type": "indexed_pointer_double_nul_list",
                "family": "table_1C92E8",
                "entry_index": int(container["entry_index"]),
                "line_index": line_index,
                "line_count": len(addresses),
                "list_start_address": container["list_start_address"],
                "pointer_source_file": f"0x{source:08X}",
                "patchable_u32": line_index == 0,
                "relocation_schema": "double_nul_list",
            })

    # Static 18 override pairs.
    for literal_off in base.OVERRIDE_LITERAL_OFFSETS:
        pair_pointer = u32(data, literal_off)
        pair = tracked.parse_length_prefixed_pair(data, pair_pointer)
        for line_index, line in enumerate(pair["lines"]):
            pointer = int(line["line_address"], 16)
            add_reference(refs, pointer, {
                "source_type": "length_prefixed_pair_literal",
                "family": "state_selected_length_prefixed_pair_variants",
                "pair_address": f"0x{pair_pointer:08X}",
                "line_index": line_index,
                "pointer_source_file": f"0x{literal_off:08X}",
                "patchable_u32": True,
                "relocation_schema": "length_prefixed_pair_override",
            })

    # Direct PC literals are additive references; two targets are owned primarily by indexed tables.
    for pointer, rows in direct_pc_references(data).items():
        refs[pointer].extend(rows)

    # Runtime fallback pairs are the production-completeness addition.
    for pointer, rows in fallback_refs.items():
        refs[pointer].extend(rows)

    return refs


def build_manifest(data: bytes) -> dict[str, Any]:
    tracked_report = tracked.build_manifest(data)
    historical, _audit = exact.historical_primary_sets(data)
    tracked_sets, multiline = exact.multiline_successor_sets(data, historical)
    tracked_targets = set().union(*tracked_sets.values())
    check(len(tracked_targets) == 3_993, "tracked successor record drift")

    fallback_targets, fallback_refs, fallback_containers = fallback_lines_and_sources(data)
    check(not (fallback_targets & tracked_targets), "fallback targets overlap tracked successor")

    final_sets = {name: set(values) for name, values in tracked_sets.items()}
    final_sets[FALLBACK_CATEGORY] = set(fallback_targets)
    final_targets = set().union(*final_sets.values())
    check(len(final_targets) == FINAL_RECORDS, f"final production record count drift: {len(final_targets)}")
    check(exact.raw_bytes_for_targets(data, final_targets) == FINAL_RAW_BYTES, "final production raw-byte drift")
    identity_sha256, _identity_rows = exact.identity_digest(data, final_targets)
    check(identity_sha256 == FINAL_IDENTITY_SHA256, f"final identity drift: {identity_sha256}")

    refs = build_reference_map(data, final_sets, multiline, fallback_refs)
    missing = sorted(final_targets - set(refs))
    extra = sorted(set(refs) - final_targets)
    check(not missing, f"records without source provenance: {len(missing)}")
    check(not extra, f"provenance escaped final record set: {len(extra)}")

    ordinary_u32: set[int] = set()
    override_u32: set[int] = set()
    fallback_u32: set[int] = set()
    double_nul_u32: set[int] = set()
    source_type_counts: Counter[str] = Counter()
    total_reference_rows = 0

    records: list[dict[str, Any]] = []
    fallback_target_set = set(fallback_targets)
    multiline_lines = set(multiline["line_targets"])
    relative_targets = final_sets["relative_text_pair"]
    override_targets = final_sets["state_variant_pair"]

    category_by_pointer = {
        pointer: category
        for category, values in final_sets.items()
        for pointer in values
    }

    for pointer in sorted(final_targets):
        raw = strict_raw(data, pointer)
        reference_rows = refs[pointer]
        for ref in reference_rows:
            source_type_counts[str(ref["source_type"])] += 1
            total_reference_rows += 1
            if not ref.get("patchable_u32"):
                continue
            source_text = ref.get("pointer_source_file")
            if not isinstance(source_text, str):
                continue
            source = int(source_text, 16)
            schema = str(ref.get("relocation_schema"))
            if schema == "length_prefixed_pair_override":
                override_u32.add(source)
            elif schema == "length_prefixed_pair_fallback":
                fallback_u32.add(source)
            elif schema == "double_nul_list":
                double_nul_u32.add(source)
            else:
                ordinary_u32.add(source)

        if pointer in fallback_target_set:
            storage_contract = "nul_stream_length_prefixed_fallback_pair_member"
        elif pointer in multiline_lines:
            storage_contract = "nul_stream_double_nul_list_member"
        elif pointer in relative_targets:
            storage_contract = "nul_stream_u16_relative_pair_member"
        elif pointer in override_targets:
            storage_contract = "nul_stream_length_prefixed_override_pair_member"
        else:
            storage_contract = "nul_stream"

        records.append({
            "record_id": f"GGA-TEXT-{pointer - ROM_BASE:08X}",
            "target_address": f"0x{pointer:08X}",
            "target_file_offset": f"0x{pointer - ROM_BASE:08X}",
            "primary_category": category_by_pointer[pointer],
            "storage_contract": storage_contract,
            "raw_byte_length_including_nul": len(raw),
            "original_raw_sha256": hashlib.sha256(raw).hexdigest(),
            "reference_count": len(reference_rows),
            "references": reference_rows,
            "raw_hex": raw.hex(" ").upper(),
            "translation_ko": "",
            "notes": "",
        })

    # Reproduce the tracked 3,993 relocation owner-field split, then add 64 fallback fields.
    check(len(ordinary_u32) == 3_875, f"ordinary u32 patch-field drift: {len(ordinary_u32)}")
    check(len(override_u32) == 18, f"override u32 patch-field drift: {len(override_u32)}")
    check(len(double_nul_u32) == 114, f"double-NUL owner-field drift: {len(double_nul_u32)}")
    check(len(fallback_u32) == 64, f"fallback u32 patch-field drift: {len(fallback_u32)}")
    record_owned_u32 = ordinary_u32 | override_u32 | double_nul_u32 | fallback_u32
    check(len(record_owned_u32) == 4_071, f"record-owned u32 union drift: {len(record_owned_u32)}")
    check(RELATIVE_BASE_LITERAL_FILE not in record_owned_u32, "relative base literal overlaps record-owned field")
    total_relocation_u32 = len(record_owned_u32) + 1
    check(total_relocation_u32 == 4_072, f"total relocation u32 patch-field drift: {total_relocation_u32}")

    check(sum(row["raw_byte_length_including_nul"] for row in records) == FINAL_RAW_BYTES, "record raw-byte sum drift")
    check(len(records) == FINAL_RECORDS, "final record manifest count drift")

    storage_counts = Counter(row["storage_contract"] for row in records)
    category_counts = Counter(row["primary_category"] for row in records)
    raw_by_category = Counter()
    for row in records:
        raw_by_category[row["primary_category"]] += int(row["raw_byte_length_including_nul"])

    contract_digest_payload = [
        {
            "record_id": row["record_id"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
            "primary_category": row["primary_category"],
            "storage_contract": row["storage_contract"],
            "reference_fingerprint": [
                {
                    key: ref[key]
                    for key in sorted(ref)
                    if key in {
                        "source_type", "family", "pointer_source_file", "relative_entry_file",
                        "call_file", "record_index", "sub_index", "selector", "search_index",
                        "entry_index", "line_index", "pair_index", "logical_index", "relocation_schema",
                    }
                }
                for ref in row["references"]
            ],
        }
        for row in records
    ]
    contract_sha256 = hashlib.sha256(
        json.dumps(contract_digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": 1,
        "scope": "advance-local production-complete Stage-2 record/reference manifest",
        "status": "PRODUCTION_REFERENCE_PROVENANCE_PASS",
        "source": {
            "rom_size": len(data),
            "rom_sha256": hashlib.sha256(data).hexdigest(),
        },
        "checkpoints": {
            "historical": tracked_report["compatibility_checkpoint"],
            "tracked_multiline_successor": tracked_report["production_record_layer"],
            "production_complete": {
                "records": FINAL_RECORDS,
                "raw_bytes": FINAL_RAW_BYTES,
                "identity_sha256": identity_sha256,
                "contract_manifest_sha256": contract_sha256,
                "record_delta_vs_tracked_successor": FINAL_RECORDS - 3_993,
                "raw_byte_delta_vs_tracked_successor": FINAL_RAW_BYTES - 61_956,
            },
        },
        "category_counts": dict(category_counts),
        "raw_bytes_by_category": dict(raw_by_category),
        "storage_contract_counts": dict(storage_counts),
        "reference_audit": {
            "records_with_provenance": len(records),
            "records_without_provenance": 0,
            "total_reference_rows": total_reference_rows,
            "source_type_counts": dict(source_type_counts),
            "record_owned_u32_patch_fields": len(record_owned_u32),
            "ordinary_u32_patch_fields": len(ordinary_u32),
            "override_pair_literal_fields": len(override_u32),
            "fallback_pair_pointer_fields": len(fallback_u32),
            "double_nul_list_pointer_fields": len(double_nul_u32),
            "relative_block_base_literal_fields": 1,
            "relative_block_base_literal_file": f"0x{RELATIVE_BASE_LITERAL_FILE:08X}",
            "total_relocation_u32_patch_fields": total_relocation_u32,
            "tracked_3993_u32_patch_fields_without_relative_base": 4_007,
            "tracked_3993_total_relocation_u32_patch_fields": 4_008,
            "production_4069_incremental_fallback_u32_fields": 64,
        },
        "container_audit": {
            **tracked_report["container_layer"],
            "production_fallback": {
                "pair_containers": len(fallback_containers),
                "line_records": FALLBACK_RECORDS,
                "line_raw_bytes": FALLBACK_RAW_BYTES,
                "container_bytes_with_prefixes": sum(int(row["byte_length_with_prefixes"]) for row in fallback_containers),
                "u32_owner_fields": len(fallback_u32),
            },
        },
        "records": records,
        "fallback_containers": fallback_containers,
        "next_gate": (
            "Rebuild the 32 MiB no-op relocation planner for the 4,069-record layer. "
            "Expected additions versus the tracked 3,993 planner are 38 fallback pair containers / 1,414 payload bytes / 64 u32 owner fields."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == ROM_SIZE, f"ROM size drift: {len(data)}")
    check(digest == ROM_SHA256, f"ROM SHA-256 drift: {digest}")
    report = build_manifest(data)

    if args.summary_only:
        visible = {
            key: report[key]
            for key in (
                "schema_version", "scope", "status", "source", "checkpoints",
                "category_counts", "raw_bytes_by_category", "storage_contract_counts",
                "reference_audit", "container_audit", "next_gate",
            )
        }
    else:
        visible = report

    rendered = json.dumps(visible, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
