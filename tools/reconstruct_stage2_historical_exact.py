#!/usr/bin/env python3
"""Reconstruct the exact historical Stage-2 checkpoint and its multiline successor.

This tool separates two checkpoints that were previously conflated in the
progress document:

1. Historical export checkpoint (2026-08-25):
   3,948 unique target records / 61,350 raw bytes / identity SHA-256
   9aeaea91...c389.  table_1C92E8 contributes one record per owning pointer,
   i.e. only the first NUL stream of each 114-entry double-NUL list.

2. Later tracked multiline-aware extractor behavior:
   table_1C92E8 expands every visible NUL stream inside the 114 lists.  This adds
   45 continuation-line target records and 606 raw bytes, yielding 3,993 records
   / 61,956 raw bytes.  This is a source-contract improvement, not evidence that
   the earlier 3,948 checkpoint was reconstructed incorrectly.

The missing rule that closes the historical checkpoint is fixed_record_text:
record16 and record40 producers read field +0 across their accessor domains and
retain only parseable text pointers.  They yield 193 + 401 = 594 targets.
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

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
import reconstruct_stage2_target_set as base  # noqa: E402

ROM_BASE = base.ROM_BASE
ROM_SIZE = base.ROM_SIZE
ROM_SHA256 = base.ROM_SHA256
HISTORICAL_RECORDS = 3_948
HISTORICAL_RAW_BYTES = 61_350
HISTORICAL_IDENTITY_SHA256 = base.EXPECTED_RECORD_IDENTITY_SHA256

RECORD16_DB = 0x001ABF6C
RECORD16_COUNT = 256
RECORD16_STRIDE = 0x10
RECORD40_DB = 0x001AFB5C
RECORD40_END = 0x001B4CEC
RECORD40_STRIDE = 0x28
RECORD40_COUNT = (RECORD40_END - RECORD40_DB) // RECORD40_STRIDE

TABLE_1C92E8 = 0x001C92E8
TABLE_1C92E8_COUNT = 114

EXPECTED_HISTORICAL_CATEGORY_COUNTS = dict(base.EXPECTED_PRIMARY_COUNTS)
EXPECTED_MULTILINE_CATEGORY_COUNTS = {
    **EXPECTED_HISTORICAL_CATEGORY_COUNTS,
    "indexed_text_table": EXPECTED_HISTORICAL_CATEGORY_COUNTS["indexed_text_table"] + 45,
}


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def strict_stream(data: bytes, pointer: int) -> bytes | None:
    if not base.is_rom_ptr(data, pointer):
        return None
    try:
        end, _tokens = base.parse_nul_stream(data, pointer)
    except SystemExit:
        return None
    start = pointer - ROM_BASE
    return data[start:end]


def fixed_producer_targets(data: bytes) -> tuple[set[int], dict[str, Any]]:
    def scan(base_off: int, count: int, stride: int) -> tuple[set[int], list[int]]:
        targets: set[int] = set()
        indices: list[int] = []
        for index in range(count):
            pointer = u32(data, base_off + index * stride)
            if strict_stream(data, pointer) is None:
                continue
            targets.add(pointer)
            indices.append(index)
        return targets, indices

    f16, f16_indices = scan(RECORD16_DB, RECORD16_COUNT, RECORD16_STRIDE)
    f40, f40_indices = scan(RECORD40_DB, RECORD40_COUNT, RECORD40_STRIDE)
    check(RECORD40_COUNT == 522, f"record40 domain drift: {RECORD40_COUNT}")
    check(len(f16) == 193, f"record16 parseable target drift: {len(f16)}")
    check(len(f40) == 401, f"record40 parseable target drift: {len(f40)}")
    check(not (f16 & f40), "record16/record40 target overlap drift")
    combined = f16 | f40
    check(len(combined) == 594, f"fixed producer union drift: {len(combined)}")
    return combined, {
        "record16": {
            "base_file": f"0x{RECORD16_DB:08X}",
            "accessor_domain_records": RECORD16_COUNT,
            "stride": RECORD16_STRIDE,
            "text_field": 0,
            "parseable_targets": len(f16),
            "parseable_indices": f16_indices,
            "raw_bytes": sum(len(strict_stream(data, p) or b"") for p in f16),
        },
        "record40": {
            "base_file": f"0x{RECORD40_DB:08X}",
            "domain_end_file": f"0x{RECORD40_END:08X}",
            "accessor_domain_records": RECORD40_COUNT,
            "stride": RECORD40_STRIDE,
            "text_field": 0,
            "parseable_targets": len(f40),
            "parseable_indices": f40_indices,
            "raw_bytes": sum(len(strict_stream(data, p) or b"") for p in f40),
        },
        "combined_targets": len(combined),
        "combined_raw_bytes": sum(len(strict_stream(data, p) or b"") for p in combined),
    }


def historical_primary_sets(data: bytes) -> tuple[dict[str, set[int]], dict[str, Any]]:
    relative = base.relative_text_pair_targets(data)
    fixed, fixed_audit = fixed_producer_targets(data)
    unit_primary, unit_subtext = base.unit_sets(data)
    entity_name, entity_subtext = base.entity_sets(data)
    indexed = base.indexed_targets(data)
    direct_struct = base.direct_struct_targets(data)
    search = base.search_targets(data)
    sparse = base.sparse_targets(data)
    direct_pc_raw = base.direct_pc_targets(data)
    id24 = base.id24_targets(data)
    state_variant = base.state_variant_targets(data)
    normalized = base.normalized_targets(data)

    pre_direct_union = (
        relative | fixed | unit_subtext | entity_name | indexed |
        entity_subtext | unit_primary | direct_struct | search | sparse
    )
    direct_literal = direct_pc_raw - pre_direct_union
    check(len(direct_pc_raw & pre_direct_union) == 2, "direct-PC overlap count drift")
    check(len(direct_literal) == 65, f"direct literal drift: {len(direct_literal)}")

    primary = {
        "relative_text_pair": relative,
        "fixed_record_text": fixed,
        "unit_subtext": unit_subtext,
        "entity_name": entity_name,
        "indexed_text_table": indexed,
        "entity_subtext": entity_subtext,
        "unit_primary": unit_primary,
        "direct_struct_text": direct_struct,
        "search_record": search,
        "sparse_lookup": sparse,
        "direct_literal": direct_literal,
        "id24_record": id24,
        "state_variant_pair": state_variant,
        "normalized_lookup": normalized,
    }
    counts = {name: len(primary[name]) for name in EXPECTED_HISTORICAL_CATEGORY_COUNTS}
    check(counts == EXPECTED_HISTORICAL_CATEGORY_COUNTS, f"historical category drift: {counts}")
    overlaps = base.pairwise_overlaps(primary)
    check(not overlaps, f"historical category overlap drift: {overlaps}")
    return primary, {
        "fixed": fixed_audit,
        "direct_pc_raw_targets": len(direct_pc_raw),
        "direct_pc_earlier_family_overlap": len(direct_pc_raw & pre_direct_union),
        "direct_pc_primary_targets": len(direct_literal),
        "direct_pc_overlap_targets": [f"0x{x:08X}" for x in sorted(direct_pc_raw & pre_direct_union)],
    }


def raw_bytes_for_targets(data: bytes, targets: set[int]) -> int:
    total = 0
    for pointer in targets:
        raw = strict_stream(data, pointer)
        check(raw is not None, f"non-text target in final set 0x{pointer:08X}")
        total += len(raw)
    return total


def identity_digest(data: bytes, targets: set[int]) -> tuple[str, list[dict[str, str]]]:
    payload: list[dict[str, str]] = []
    for pointer in sorted(targets):
        off = pointer - ROM_BASE
        raw = strict_stream(data, pointer)
        check(raw is not None, f"identity target parse failure 0x{pointer:08X}")
        payload.append({
            "record_id": f"GGA-TEXT-{off:08X}",
            "target_file_offset": f"0x{off:08X}",
            "original_raw_sha256": hashlib.sha256(raw).hexdigest(),
        })
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest(), payload


def table_1c92e8_multiline(data: bytes) -> dict[str, Any]:
    starts = [u32(data, TABLE_1C92E8 + i * 4) for i in range(TABLE_1C92E8_COUNT)]
    check(len(set(starts)) == TABLE_1C92E8_COUNT, "table_1C92E8 start target uniqueness drift")
    lines: set[int] = set()
    continuation_lines: set[int] = set()
    containers: list[dict[str, Any]] = []
    blob_bytes = 0

    for index, pointer in enumerate(starts):
        cur = pointer - ROM_BASE
        line_addresses: list[int] = []
        line_bytes = 0
        first = True
        while data[cur] != 0:
            address = ROM_BASE + cur
            raw = strict_stream(data, address)
            check(raw is not None, f"table_1C92E8 line parse drift at entry {index}")
            lines.add(address)
            if not first:
                continuation_lines.add(address)
            line_addresses.append(address)
            line_bytes += len(raw)
            cur += len(raw)
            first = False
        # cur points at the second NUL terminator.
        blob_len = cur + 1 - (pointer - ROM_BASE)
        blob_bytes += blob_len
        containers.append({
            "entry_index": index,
            "pointer_source_file": f"0x{TABLE_1C92E8 + index * 4:08X}",
            "list_start_address": f"0x{pointer:08X}",
            "line_count": len(line_addresses),
            "line_addresses": [f"0x{x:08X}" for x in line_addresses],
            "line_raw_bytes": line_bytes,
            "blob_bytes_including_double_nul": blob_len,
        })

    check(len(lines) == 159, f"table_1C92E8 line target drift: {len(lines)}")
    check(len(continuation_lines) == 45, f"table_1C92E8 continuation drift: {len(continuation_lines)}")
    check(blob_bytes == 2092, f"table_1C92E8 blob byte drift: {blob_bytes}")
    line_raw_bytes = raw_bytes_for_targets(data, lines)
    check(line_raw_bytes == 1978, f"table_1C92E8 line raw byte drift: {line_raw_bytes}")
    return {
        "start_targets": set(starts),
        "line_targets": lines,
        "continuation_targets": continuation_lines,
        "containers": containers,
        "start_target_count": len(set(starts)),
        "line_target_count": len(lines),
        "continuation_target_count": len(continuation_lines),
        "line_raw_bytes": line_raw_bytes,
        "blob_bytes_including_double_nul": blob_bytes,
    }


def multiline_successor_sets(
    data: bytes,
    historical: dict[str, set[int]],
) -> tuple[dict[str, set[int]], dict[str, Any]]:
    multiline = table_1c92e8_multiline(data)
    starts = set(multiline["start_targets"])
    lines = set(multiline["line_targets"])
    check(starts <= historical["indexed_text_table"], "multiline start target escaped indexed family")

    successor = {name: set(values) for name, values in historical.items()}
    successor["indexed_text_table"] = (successor["indexed_text_table"] - starts) | lines
    counts = {name: len(successor[name]) for name in EXPECTED_MULTILINE_CATEGORY_COUNTS}
    check(counts == EXPECTED_MULTILINE_CATEGORY_COUNTS, f"multiline category drift: {counts}")
    overlaps = base.pairwise_overlaps(successor)
    check(not overlaps, f"multiline category overlap drift: {overlaps}")
    all_targets = set().union(*successor.values())
    check(len(all_targets) == 3993, f"multiline record union drift: {len(all_targets)}")
    check(raw_bytes_for_targets(data, all_targets) == 61956, "multiline raw-byte total drift")
    return successor, multiline


def summarize_categories(data: bytes, primary: dict[str, set[int]]) -> dict[str, Any]:
    return {
        name: {
            "records": len(targets),
            "raw_bytes": raw_bytes_for_targets(data, targets),
        }
        for name, targets in primary.items()
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--include-record-identities", action="store_true")
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == ROM_SIZE, f"ROM size drift: {len(data)}")
    check(digest == ROM_SHA256, f"ROM SHA-256 drift: {digest}")

    historical, audit = historical_primary_sets(data)
    historical_targets = set().union(*historical.values())
    check(len(historical_targets) == HISTORICAL_RECORDS, "historical record union drift")
    historical_raw = raw_bytes_for_targets(data, historical_targets)
    check(historical_raw == HISTORICAL_RAW_BYTES, f"historical raw-byte drift: {historical_raw}")
    historical_identity, identity_rows = identity_digest(data, historical_targets)
    check(
        historical_identity == HISTORICAL_IDENTITY_SHA256,
        f"historical identity digest drift: {historical_identity}",
    )

    successor, multiline = multiline_successor_sets(data, historical)
    successor_targets = set().union(*successor.values())
    successor_identity, successor_identity_rows = identity_digest(data, successor_targets)

    report = {
        "schema_version": 1,
        "scope": "advance-local exact historical Stage-2 reconstruction plus tracked multiline successor projection",
        "rom_sha256": digest,
        "historical_checkpoint": {
            "status": "EXACT_PASS",
            "records": len(historical_targets),
            "raw_bytes": historical_raw,
            "identity_sha256": historical_identity,
            "expected_identity_sha256": HISTORICAL_IDENTITY_SHA256,
            "identity_match": historical_identity == HISTORICAL_IDENTITY_SHA256,
            "category_counts": {name: len(values) for name, values in historical.items()},
            "category_audit": summarize_categories(data, historical),
            "fixed_producer_audit": audit["fixed"],
            "direct_pc_audit": {key: value for key, value in audit.items() if key != "fixed"},
            "identity_serialization": (
                "target-address ascending; each row = record_id,target_file_offset,original_raw_sha256; "
                "json.dumps(ensure_ascii=False, sort_keys=True, separators=(',', ':'))"
            ),
        },
        "multiline_successor": {
            "status": "CONTRACT_PROJECTION_PASS",
            "records": len(successor_targets),
            "raw_bytes": raw_bytes_for_targets(data, successor_targets),
            "identity_sha256": successor_identity,
            "category_counts": {name: len(values) for name, values in successor.items()},
            "category_audit": summarize_categories(data, successor),
            "table_1C92E8": {
                key: value
                for key, value in multiline.items()
                if key not in {"start_targets", "line_targets", "continuation_targets", "containers"}
            },
            "record_delta_vs_historical": len(successor_targets) - len(historical_targets),
            "raw_byte_delta_vs_historical": raw_bytes_for_targets(data, successor_targets) - historical_raw,
            "basis": (
                "Tracked follow-up extractor expands every NUL stream in each table_1C92E8 double-NUL list; "
                "the contemporary exporter semantic status gate totals 3,470 reviewed + 523 unclassified = 3,993."
            ),
        },
        "table_1C92E8_containers": multiline["containers"],
        "record_identities": (
            {
                "historical": identity_rows,
                "multiline_successor": successor_identity_rows,
            }
            if args.include_record_identities
            else None
        ),
        "conclusion": (
            "The historical 3,948 / 61,350 / 9aeaea... checkpoint is now reproduced exactly. "
            "Its former 2,985-byte mismatch was entirely caused by an incorrect fixed_record_text reconstruction. "
            "A later tracked source-contract change expands table_1C92E8 from 114 owning starts to 159 line records, "
            "producing a distinct 3,993-record successor that must not be conflated with the historical checkpoint."
        ),
    }

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
