#!/usr/bin/env python3
"""Statically verify the G Generation Advance 32 MiB translation PoC."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROM_BASE = 0x08000000
ORIGINAL_SIZE = 16 * 1024 * 1024
EXPANDED_SIZE = 32 * 1024 * 1024
TEXT_START = 0x01040000
TEXT_END = 0x01240000
STRONG_TAIL = 0x00FCED40
READY_STATUSES = {"translated", "translated_same", "translated_partial_charmap_preserved"}


def fail(message: str) -> None:
    raise RuntimeError(message)


def h(value: str) -> int:
    return int(value, 16)


def raw_hex(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))


def u32(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(blob):
        fail(f"u32 read outside image at 0x{offset:08X}")
    return struct.unpack_from("<I", blob, offset)[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("original", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("report", type=Path)
    args = ap.parse_args()

    original = args.original.read_bytes()
    candidate = args.candidate.read_bytes()
    report: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8"))
    plan = report["pointer_plan"]
    verification = plan["verification"]
    rows = report["records"]

    checks: dict[str, Any] = {}
    if len(original) != ORIGINAL_SIZE:
        fail(f"original ROM size drift: {len(original)}")
    if len(candidate) != EXPANDED_SIZE:
        fail(f"candidate ROM size drift: {len(candidate)}")
    original_sha = hashlib.sha256(original).hexdigest()
    if original_sha != report["source"]["sha256"]:
        fail("original SHA-256 does not match translation report")
    candidate_sha = hashlib.sha256(candidate).hexdigest()
    if candidate_sha != verification["output_sha256"]:
        fail("candidate SHA-256 does not match translation report")
    checks["image_size_and_sha256"] = "PASS"

    patches = plan["pointer_recalculation"]["owner_patches"]
    allowed_positions: set[int] = set()
    pointer_mismatches: list[str] = []
    for patch in patches:
        source = h(patch["source_file"])
        expected = h(patch["new_value"])
        allowed_positions.update(range(source, source + 4))
        actual = u32(candidate, source)
        if actual != expected:
            pointer_mismatches.append(
                f"0x{source:08X}: expected 0x{expected:08X}, got 0x{actual:08X}"
            )
    if pointer_mismatches:
        fail("owner pointer mismatch: " + pointer_mismatches[0])
    checks["owner_u32_fields"] = len(patches)

    changed = [
        index
        for index, (before, after) in enumerate(zip(original, candidate[: len(original)]))
        if before != after
    ]
    unexpected = [index for index in changed if index not in allowed_positions]
    if unexpected:
        fail(f"unexpected changes in original half: {len(unexpected)}")
    if candidate[STRONG_TAIL:ORIGINAL_SIZE] != original[STRONG_TAIL:ORIGINAL_SIZE]:
        fail("strong tail changed")
    checks["original_half_patch_scope"] = {
        "changed_bytes": len(changed),
        "allowed_patch_bytes": len(allowed_positions),
        "unexpected_changed_bytes": 0,
        "strong_tail_0xFCED40_unchanged": True,
    }

    allocations = plan["allocations"]
    previous_end = TEXT_START
    allocation_by_name: dict[str, dict[str, Any]] = {}
    for allocation in allocations:
        start = h(allocation["file_offset"])
        end = h(allocation["end_exclusive"])
        if start < TEXT_START or end > TEXT_END or end < start:
            fail(f"allocation outside text region: {allocation['name']}")
        if start < previous_end:
            fail(f"overlapping allocation: {allocation['name']}")
        if end - start != allocation["size"]:
            fail(f"allocation size mismatch: {allocation['name']}")
        allocation_by_name[allocation["name"]] = allocation
        previous_end = end
    checks["text_allocations"] = {
        "count": len(allocations),
        "high_water": plan["text_region"]["high_water"],
        "within_0x01040000_0x01240000": True,
    }

    relative = allocation_by_name["translated_relative_pair_block"]
    relative_start = h(relative["file_offset"])
    relative_size = int(relative["size"])
    table_count = 769
    table_bytes = 2 * table_count
    offsets = list(struct.unpack_from("<" + "H" * table_count, candidate, relative_start))
    if offsets[:3] != [0, 0, 0]:
        fail("relative table sentinel entries changed")
    if offsets != sorted(offsets):
        fail("relative table offsets are not monotonic")
    if offsets[-1] != relative_size - 1:
        fail(
            f"relative table final offset mismatch: 0x{offsets[-1]:04X} "
            f"!= 0x{relative_size - 1:04X}"
        )
    if any(value < table_bytes or value >= relative_size for value in offsets[3:]):
        fail("relative table points outside its payload")
    checks["relative_u16_table"] = {
        "values": table_count,
        "recalculated_values": plan["containers"]["relative_pair_block"]["u16_offset_values_recalculated"],
        "monotonic": True,
        "sentinel_entries": 3,
    }

    # Every manifest row has a translated_raw_hex value.  For ordinary streams,
    # follow the newly patched u32 owner and compare the actual candidate bytes
    # with that row payload.  This checks the data and pointer together.
    ordinary_checked = 0
    ordinary_missing_owner: list[str] = []
    ordinary_mismatches: list[str] = []
    for row in rows:
        if row["storage_contract"] != "nul_stream":
            continue
        refs = [
            ref
            for ref in row.get("references", [])
            if ref.get("patchable_u32") and ref.get("relocation_schema") == "ordinary_u32_stream"
        ]
        if not refs:
            ordinary_missing_owner.append(row["record_id"])
            continue
        source = h(refs[0]["pointer_source_file"])
        target_address = u32(candidate, source)
        target_offset = target_address - ROM_BASE
        payload = raw_hex(row["translated_raw_hex"])
        if target_offset < 0 or target_offset + len(payload) > len(candidate):
            ordinary_mismatches.append(f"{row['record_id']}: target outside candidate")
        elif candidate[target_offset : target_offset + len(payload)] != payload:
            ordinary_mismatches.append(f"{row['record_id']}: payload mismatch")
        ordinary_checked += 1
    if ordinary_missing_owner:
        fail(f"ordinary rows without owner pointers: {len(ordinary_missing_owner)}")
    if ordinary_mismatches:
        fail(ordinary_mismatches[0])
    checks["ordinary_stream_payloads"] = {
        "rows_checked": ordinary_checked,
        "ready_rows": sum(row["translation_status"] in READY_STATUSES for row in rows),
        "all_payloads_match": True,
    }

    # The original text payloads are retained in place; moved copies are what
    # the patched pointers consume.  This also catches accidental overwrites of
    # unresolved/preserve rows in the original half.
    original_payload_mismatches: list[str] = []
    for row in rows:
        offset = h(row["target_file_offset"])
        payload = raw_hex(row["raw_hex"])
        if original[offset : offset + len(payload)] != payload:
            original_payload_mismatches.append(row["record_id"])
        if candidate[offset : offset + len(payload)] != payload:
            original_payload_mismatches.append(row["record_id"] + ":candidate")
    if original_payload_mismatches:
        fail("original text payload changed: " + original_payload_mismatches[0])
    checks["original_text_payloads_unchanged"] = True

    result = {
        "result": "PASS",
        "candidate_sha256": candidate_sha,
        "checks": checks,
        "report_verification": verification,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
