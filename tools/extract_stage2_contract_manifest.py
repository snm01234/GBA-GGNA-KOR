#!/usr/bin/env python3
"""Build the advance-local production Stage-2 source-contract manifest.

The canonical production record layer is the multiline-aware successor of the
historical 2026-08-25 checkpoint:

* historical compatibility checkpoint: 3,948 records / 61,350 raw bytes /
  identity 9aeaea91...c389;
* production source-contract layer: 3,993 records / 61,956 raw bytes after
  expanding all 159 visible line streams owned by the 114-entry table_1C92E8
  double-NUL list table.

Containers are deliberately kept separate from line records.  In particular:
* table_1C92E8 owns 114 double-NUL containers but exposes 159 line records;
* the relative 256x3 owner has 765 two-line containers / 1,530 line records;
* stage-condition override/fallback data uses length-prefixed pair containers.

This tool does not yet rebuild every historical pointer/reference object.  It
establishes record identity, source/storage contracts and container provenance
as the base for the advance-local translation extractor.
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

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
import reconstruct_stage2_historical_exact as exact  # noqa: E402
import reconstruct_stage2_target_set as base  # noqa: E402

ROM_BASE = base.ROM_BASE
ROM_SIZE = base.ROM_SIZE
ROM_SHA256 = base.ROM_SHA256
PRODUCTION_RECORDS = 3_993
PRODUCTION_RAW_BYTES = 61_956

SEARCH_DB = 0x00D55888
SEARCH_STRIDE = 0x20
SEARCH_COUNT = 64
SEARCH_PAIR_FIELD = 0x14


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def strict_raw(data: bytes, pointer: int) -> bytes:
    raw = exact.strict_stream(data, pointer)
    check(raw is not None, f"strict stream parse failed at 0x{pointer:08X}")
    return raw or b""


def parse_length_prefixed_pair(data: bytes, pointer: int) -> dict[str, Any]:
    base_off = pointer - ROM_BASE
    check(0 <= base_off < len(data), f"bad pair pointer 0x{pointer:08X}")
    len1 = data[base_off]
    line1 = ROM_BASE + base_off + 1
    raw1 = strict_raw(data, line1)
    check(len(raw1) == len1 + 1, f"pair line1 length drift at 0x{pointer:08X}")

    len2_off = base_off + 1 + len(raw1)
    len2 = data[len2_off]
    line2 = ROM_BASE + len2_off + 1
    raw2 = strict_raw(data, line2)
    check(len(raw2) == len2 + 1, f"pair line2 length drift at 0x{pointer:08X}")
    end_off = len2_off + 1 + len(raw2)
    raw = data[base_off:end_off]
    return {
        "pair_address": f"0x{pointer:08X}",
        "byte_length_with_prefixes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "lines": [
            {
                "line_address": f"0x{line1:08X}",
                "encoded_length_without_nul": len1,
                "raw_byte_length_including_nul": len(raw1),
            },
            {
                "line_address": f"0x{line2:08X}",
                "encoded_length_without_nul": len2,
                "raw_byte_length_including_nul": len(raw2),
            },
        ],
    }


def relative_pair_containers(data: bytes) -> list[dict[str, Any]]:
    base_off = 0x001BF908
    offsets = [struct.unpack_from("<H", data, base_off + i * 2)[0] for i in range(3, 769)]
    check(len(offsets) == 766, "relative offset/sentinel count drift")
    rows: list[dict[str, Any]] = []
    for pair_index in range(765):
        start = base_off + offsets[pair_index]
        boundary = base_off + offsets[pair_index + 1]
        line1 = ROM_BASE + start
        raw1 = strict_raw(data, line1)
        line2 = line1 + len(raw1)
        raw2 = strict_raw(data, line2)
        check(start + len(raw1) + len(raw2) == boundary, f"relative pair boundary drift at {pair_index}")
        rows.append({
            "container_type": "u16_relative_pair",
            "pair_index": pair_index,
            "container_file_start": f"0x{start:08X}",
            "container_file_end_exclusive": f"0x{boundary:08X}",
            "byte_length": boundary - start,
            "line_addresses": [f"0x{line1:08X}", f"0x{line2:08X}"],
        })
    check(sum(row["byte_length"] for row in rows) == 34_449, "relative pair payload byte drift")
    return rows


def stage_condition_containers(data: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fallback_ptrs = {
        u32(data, SEARCH_DB + i * SEARCH_STRIDE + SEARCH_PAIR_FIELD)
        for i in range(SEARCH_COUNT)
    }
    check(len(fallback_ptrs) == 38, f"fallback pair count drift: {len(fallback_ptrs)}")
    fallback = [parse_length_prefixed_pair(data, p) for p in sorted(fallback_ptrs)]
    for row in fallback:
        row["container_type"] = "length_prefixed_pair_fallback"
        row["source"] = "search_record_db+0x14"

    override_ptrs = [u32(data, off) for off in base.OVERRIDE_LITERAL_OFFSETS]
    check(len(set(override_ptrs)) == 18, "override pair uniqueness drift")
    check(not (set(override_ptrs) & fallback_ptrs), "override/fallback pair overlap drift")
    override = [parse_length_prefixed_pair(data, p) for p in override_ptrs]
    for row, literal_off in zip(override, base.OVERRIDE_LITERAL_OFFSETS):
        row["container_type"] = "length_prefixed_pair_override"
        row["source_literal_file_offset"] = f"0x{literal_off:08X}"
    return fallback, override


def build_manifest(data: bytes) -> dict[str, Any]:
    historical, historical_audit = exact.historical_primary_sets(data)
    historical_targets = set().union(*historical.values())
    historical_raw = exact.raw_bytes_for_targets(data, historical_targets)
    historical_identity, _historical_identity_rows = exact.identity_digest(data, historical_targets)
    check(len(historical_targets) == 3_948, "historical compatibility record count drift")
    check(historical_raw == 61_350, "historical compatibility raw-byte drift")
    check(historical_identity == exact.HISTORICAL_IDENTITY_SHA256, "historical compatibility identity drift")

    production, multiline = exact.multiline_successor_sets(data, historical)
    production_targets = set().union(*production.values())
    check(len(production_targets) == PRODUCTION_RECORDS, f"production record count drift: {len(production_targets)}")
    production_raw = exact.raw_bytes_for_targets(data, production_targets)
    check(production_raw == PRODUCTION_RAW_BYTES, f"production raw-byte drift: {production_raw}")
    production_identity, _production_identity_rows = exact.identity_digest(data, production_targets)

    multiline_line_targets = set(multiline["line_targets"])
    relative_targets = production["relative_text_pair"]
    override_targets = production["state_variant_pair"]

    storage_counts: Counter[str] = Counter()
    bytes_by_category: dict[str, int] = defaultdict(int)
    records: list[dict[str, Any]] = []
    for category in exact.EXPECTED_MULTILINE_CATEGORY_COUNTS:
        for pointer in sorted(production[category]):
            raw = strict_raw(data, pointer)
            if pointer in multiline_line_targets:
                contract = "nul_stream_double_nul_list_member"
            elif pointer in relative_targets:
                contract = "nul_stream_u16_relative_pair_member"
            elif pointer in override_targets:
                contract = "nul_stream_length_prefixed_pair_member"
            else:
                contract = "nul_stream"
            storage_counts[contract] += 1
            bytes_by_category[category] += len(raw)
            records.append({
                "record_id": f"GGA-TEXT-{pointer - ROM_BASE:08X}",
                "target_address": f"0x{pointer:08X}",
                "target_file_offset": f"0x{pointer - ROM_BASE:08X}",
                "primary_category": category,
                "storage_contract": contract,
                "raw_byte_length_including_nul": len(raw),
                "original_raw_sha256": hashlib.sha256(raw).hexdigest(),
                "raw_hex": raw.hex(" ").upper(),
                "translation_ko": "",
                "notes": "",
            })

    records.sort(key=lambda row: int(row["target_file_offset"], 16))
    check(len(records) == PRODUCTION_RECORDS, "production manifest record drift")
    check(len({row["record_id"] for row in records}) == PRODUCTION_RECORDS, "production record ID uniqueness drift")
    check(sum(row["raw_byte_length_including_nul"] for row in records) == PRODUCTION_RAW_BYTES, "production manifest raw-byte drift")

    relative = relative_pair_containers(data)
    fallback, override = stage_condition_containers(data)
    table_containers = list(multiline["containers"])

    manifest_digest_payload = [
        {
            "record_id": row["record_id"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
            "primary_category": row["primary_category"],
            "storage_contract": row["storage_contract"],
        }
        for row in records
    ]
    manifest_digest = hashlib.sha256(
        json.dumps(
            manifest_digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": 2,
        "scope": "advance-local production Stage-2 record/container contract manifest",
        "status": "PRODUCTION_RECORD_CONTRACT_PASS",
        "source": {
            "rom_sha256": hashlib.sha256(data).hexdigest(),
            "rom_size": len(data),
        },
        "compatibility_checkpoint": {
            "records": len(historical_targets),
            "raw_bytes": historical_raw,
            "identity_sha256": historical_identity,
            "expected_identity_sha256": exact.HISTORICAL_IDENTITY_SHA256,
            "identity_match": historical_identity == exact.HISTORICAL_IDENTITY_SHA256,
            "fixed_record_text": {
                "record16": {
                    key: value for key, value in historical_audit["fixed"]["record16"].items()
                    if key != "parseable_indices"
                },
                "record40": {
                    key: value for key, value in historical_audit["fixed"]["record40"].items()
                    if key != "parseable_indices"
                },
                "combined_targets": historical_audit["fixed"]["combined_targets"],
                "combined_raw_bytes": historical_audit["fixed"]["combined_raw_bytes"],
            },
        },
        "production_record_layer": {
            "records": len(records),
            "raw_bytes": sum(row["raw_byte_length_including_nul"] for row in records),
            "identity_sha256": production_identity,
            "contract_manifest_sha256": manifest_digest,
            "category_counts": {name: len(production[name]) for name in exact.EXPECTED_MULTILINE_CATEGORY_COUNTS},
            "storage_contract_counts": dict(sorted(storage_counts.items())),
            "raw_bytes_by_category": dict(bytes_by_category),
            "historical_record_delta": len(records) - len(historical_targets),
            "historical_raw_byte_delta": production_raw - historical_raw,
        },
        "container_layer": {
            "table_1C92E8": {
                "containers": len(table_containers),
                "line_records": multiline["line_target_count"],
                "continuation_line_records": multiline["continuation_target_count"],
                "line_raw_bytes": multiline["line_raw_bytes"],
                "blob_bytes_including_double_nul": multiline["blob_bytes_including_double_nul"],
            },
            "relative_256x3": {
                "containers": len(relative),
                "line_records": 1_530,
                "payload_bytes": sum(row["byte_length"] for row in relative),
            },
            "stage_condition": {
                "fallback_pair_containers": len(fallback),
                "fallback_container_bytes": sum(row["byte_length_with_prefixes"] for row in fallback),
                "override_pair_containers": len(override),
                "override_container_bytes": sum(row["byte_length_with_prefixes"] for row in override),
            },
        },
        "records": records,
        "containers": {
            "table_1C92E8": table_containers,
            "relative_256x3": relative,
            "stage_condition_fallback": fallback,
            "stage_condition_override": override,
        },
        "next_gate": (
            "Attach exact pointer/reference provenance to all 3,993 records and reproduce the relocation pointer-field/payload contract. "
            "Only after that should Unicode/charmap export be rebuilt on this production record layer."
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
                "schema_version",
                "scope",
                "status",
                "source",
                "compatibility_checkpoint",
                "production_record_layer",
                "container_layer",
                "next_gate",
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
