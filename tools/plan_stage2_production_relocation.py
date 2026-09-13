#!/usr/bin/env python3
"""Plan and verify a 32 MiB no-op relocation for the 4,069-record corpus.

The production corpus has five storage/ownership schemas:

1. the 0x081BF908 u16-relative paired-text block, relocated as one unit;
2. 18 static length-prefixed victory/defeat pair containers;
3. 38 runtime fallback length-prefixed pair containers selected from search
   record field +0x14;
4. 114 double-NUL string-list containers from table_1C92E8;
5. 2,268 ordinary u32-owned NUL streams.

The tool builds a 32 MiB candidate in memory only, patches exactly the proven
owner fields, and verifies a semantic no-op.  It never writes a ROM file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_stage2_production_reference_manifest as manifest  # noqa: E402
import extract_stage2_contract_manifest as tracked  # noqa: E402
import reconstruct_stage2_historical_exact as exact  # noqa: E402
import reconstruct_stage2_target_set as base  # noqa: E402

ROM_BASE = base.ROM_BASE
ROM_SIZE = base.ROM_SIZE
ROM_SHA256 = base.ROM_SHA256
EXPANDED_SIZE = 32 * 1024 * 1024
TEXT_START = 0x01040000
TEXT_END = 0x01240000
STRONG_TAIL_START = 0x00FCED40

RELATIVE_OLD_BASE = 0x001BF908
RELATIVE_OLD_END = 0x001C859C
RELATIVE_BLOCK_SIZE = RELATIVE_OLD_END - RELATIVE_OLD_BASE
EXPECTED_RELATIVE_BLOCK_SIZE = 35_988
EXPECTED_FINAL_PAYLOAD = 65_059
EXPECTED_TOTAL_PATCH_FIELDS = 4_072


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def align_up(value: int, alignment: int = 4) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def gba_address(file_offset: int) -> int:
    return ROM_BASE + file_offset


def raw_pair_bytes(data: bytes, pair_pointer: int) -> bytes:
    row = tracked.parse_length_prefixed_pair(data, pair_pointer)
    off = pair_pointer - ROM_BASE
    size = int(row["byte_length_with_prefixes"])
    return data[off:off + size]


def raw_double_nul_blob(data: bytes, container: dict[str, Any]) -> bytes:
    start = int(container["list_start_address"], 16) - ROM_BASE
    size = int(container["blob_bytes_including_double_nul"])
    return data[start:start + size]


def build_plan(data: bytes) -> dict[str, Any]:
    report = manifest.build_manifest(data)
    records = report["records"]
    record_by_pointer = {int(row["target_address"], 16): row for row in records}
    check(len(record_by_pointer) == manifest.FINAL_RECORDS, "reference manifest record drift")

    # Classify record target ownership.
    relative_targets = {
        pointer for pointer, row in record_by_pointer.items()
        if row["storage_contract"] == "nul_stream_u16_relative_pair_member"
    }
    override_targets = {
        pointer for pointer, row in record_by_pointer.items()
        if row["storage_contract"] == "nul_stream_length_prefixed_override_pair_member"
    }
    fallback_targets = {
        pointer for pointer, row in record_by_pointer.items()
        if row["storage_contract"] == "nul_stream_length_prefixed_fallback_pair_member"
    }
    double_nul_targets = {
        pointer for pointer, row in record_by_pointer.items()
        if row["storage_contract"] == "nul_stream_double_nul_list_member"
    }
    ordinary_targets = set(record_by_pointer) - relative_targets - override_targets - fallback_targets - double_nul_targets

    check(len(relative_targets) == 1530, "relative target count drift")
    check(len(override_targets) == 36, "override target count drift")
    check(len(fallback_targets) == 76, "fallback target count drift")
    check(len(double_nul_targets) == 159, "double-NUL target count drift")
    check(len(ordinary_targets) == 2268, "ordinary target count drift")

    candidate = bytearray(EXPANDED_SIZE)
    candidate[:ROM_SIZE] = data
    allocations: list[dict[str, Any]] = []
    new_target: dict[int, int] = {}
    pair_new_address: dict[int, int] = {}
    fallback_new_address: dict[int, int] = {}
    list_new_address: dict[int, int] = {}
    cursor = TEXT_START
    alignment_padding = 0
    allocated_payload = 0

    def allocate(name: str, category: str, payload: bytes, source: str, notes: str) -> int:
        nonlocal cursor, alignment_padding, allocated_payload
        aligned = align_up(cursor, 4)
        alignment_padding += aligned - cursor
        cursor = aligned
        start = cursor
        end = start + len(payload)
        check(end <= TEXT_END, f"text region overflow while allocating {name}")
        candidate[start:end] = payload
        cursor = end
        allocated_payload += len(payload)
        allocations.append({
            "name": name,
            "category": category,
            "region": "text",
            "file_offset": f"0x{start:08X}",
            "end_exclusive": f"0x{end:08X}",
            "gba_address": f"0x{gba_address(start):08X}",
            "size": len(payload),
            "alignment": 4,
            "source": source,
            "notes": notes,
        })
        return start

    # 1) Relative block: copy table + payload byte-identically.
    check(RELATIVE_BLOCK_SIZE == EXPECTED_RELATIVE_BLOCK_SIZE, "relative block size constant drift")
    relative_payload = data[RELATIVE_OLD_BASE:RELATIVE_OLD_END]
    relative_new_file = allocate(
        "production_relative_pair_block",
        "text-relative-block",
        relative_payload,
        f"0x{RELATIVE_OLD_BASE:08X}-0x{RELATIVE_OLD_END:08X}",
        "256x3 u16-relative paired-token block copied as one unit",
    )
    for pointer in relative_targets:
        old_off = pointer - ROM_BASE
        new_file = relative_new_file + (old_off - RELATIVE_OLD_BASE)
        new_target[pointer] = gba_address(new_file)

    # 2) Static override length-prefixed pairs, literal order.
    override_blob = bytearray()
    override_offsets: dict[int, int] = {}
    for literal_off in base.OVERRIDE_LITERAL_OFFSETS:
        pair_pointer = u32(data, literal_off)
        pair_bytes = raw_pair_bytes(data, pair_pointer)
        override_offsets[pair_pointer] = len(override_blob)
        override_blob.extend(pair_bytes)
    check(len(override_blob) == 726, f"override blob byte drift: {len(override_blob)}")
    override_new_file = allocate(
        "production_override_pairs",
        "text-length-prefixed-override-pairs",
        bytes(override_blob),
        "18 static variants selected by 0x08012408",
        "each container holds two length-prefixed NUL streams",
    )
    for pair_pointer, rel in override_offsets.items():
        pair_file = override_new_file + rel
        pair_new_address[pair_pointer] = gba_address(pair_file)
        pair = tracked.parse_length_prefixed_pair(data, pair_pointer)
        old_pair_file = pair_pointer - ROM_BASE
        for line in pair["lines"]:
            old_line = int(line["line_address"], 16)
            line_delta = (old_line - ROM_BASE) - old_pair_file
            new_target[old_line] = gba_address(pair_file + line_delta)

    # 3) Runtime fallback pair containers, sorted original pointer order.
    fallback_blob = bytearray()
    fallback_offsets: dict[int, int] = {}
    fallback_pair_pointers = sorted({
        u32(data, tracked.SEARCH_DB + i * tracked.SEARCH_STRIDE + tracked.SEARCH_PAIR_FIELD)
        for i in range(tracked.SEARCH_COUNT)
    })
    check(len(fallback_pair_pointers) == 38, "fallback pair pointer count drift")
    for pair_pointer in fallback_pair_pointers:
        pair_bytes = raw_pair_bytes(data, pair_pointer)
        fallback_offsets[pair_pointer] = len(fallback_blob)
        fallback_blob.extend(pair_bytes)
    check(len(fallback_blob) == 1414, f"fallback blob byte drift: {len(fallback_blob)}")
    fallback_new_file = allocate(
        "production_runtime_fallback_pairs",
        "text-length-prefixed-fallback-pairs",
        bytes(fallback_blob),
        "38 unique search-record +0x14 fallback pair containers",
        "64 search records share 38 pair containers; each container holds two length-prefixed NUL streams",
    )
    for pair_pointer, rel in fallback_offsets.items():
        pair_file = fallback_new_file + rel
        fallback_new_address[pair_pointer] = gba_address(pair_file)
        pair = tracked.parse_length_prefixed_pair(data, pair_pointer)
        old_pair_file = pair_pointer - ROM_BASE
        for line in pair["lines"]:
            old_line = int(line["line_address"], 16)
            line_delta = (old_line - ROM_BASE) - old_pair_file
            new_target[old_line] = gba_address(pair_file + line_delta)

    # 4) table_1C92E8 double-NUL lists, owner-table order.
    historical, _audit = exact.historical_primary_sets(data)
    _successor, multiline = exact.multiline_successor_sets(data, historical)
    double_blob = bytearray()
    list_offsets: dict[int, int] = {}
    for container in multiline["containers"]:
        old_start = int(container["list_start_address"], 16)
        payload = raw_double_nul_blob(data, container)
        list_offsets[old_start] = len(double_blob)
        double_blob.extend(payload)
    check(len(double_blob) == 2092, f"double-NUL blob drift: {len(double_blob)}")
    double_new_file = allocate(
        "production_double_nul_lists",
        "text-double-nul-lists",
        bytes(double_blob),
        "114 u32-owned lists selected by 0x080116C4",
        "one to six line streams followed by empty-stream sentinel",
    )
    for container in multiline["containers"]:
        old_start = int(container["list_start_address"], 16)
        list_file = double_new_file + list_offsets[old_start]
        list_new_address[old_start] = gba_address(list_file)
        for line_text in container["line_addresses"]:
            old_line = int(line_text, 16)
            line_delta = old_line - old_start
            new_target[old_line] = gba_address(list_file + line_delta)

    # 5) Ordinary streams, deduplicated by target and sorted by old target.
    ordinary_blob = bytearray()
    ordinary_offsets: dict[int, int] = {}
    for pointer in sorted(ordinary_targets):
        raw = exact.strict_stream(data, pointer)
        check(raw is not None, f"ordinary stream parse failure 0x{pointer:08X}")
        ordinary_offsets[pointer] = len(ordinary_blob)
        ordinary_blob.extend(raw or b"")
    check(len(ordinary_blob) == 24839, f"ordinary blob byte drift: {len(ordinary_blob)}")
    ordinary_new_file = allocate(
        "production_u32_text_streams",
        "text-u32-streams",
        bytes(ordinary_blob),
        "2,268 unique ordinary NUL token streams",
        "deduplicated by original target; all ordinary owners share the relocated target",
    )
    for pointer, rel in ordinary_offsets.items():
        new_target[pointer] = gba_address(ordinary_new_file + rel)

    check(len(new_target) == manifest.FINAL_RECORDS, f"new target map drift: {len(new_target)}")
    check(allocated_payload == EXPECTED_FINAL_PAYLOAD, f"allocated payload drift: {allocated_payload}")

    # Patch ownership fields.
    patch_values: dict[int, tuple[int, str]] = {}

    def set_patch(source_file: int, value: int, kind: str) -> None:
        old = patch_values.get(source_file)
        if old is not None:
            check(old[0] == value, f"conflicting patch value at 0x{source_file:08X}")
            return
        patch_values[source_file] = (value, kind)

    # Ordinary u32 references, including direct PC literals into any relocated record.
    for pointer, row in record_by_pointer.items():
        for ref in row["references"]:
            if not ref.get("patchable_u32"):
                continue
            schema = str(ref.get("relocation_schema"))
            source_text = ref.get("pointer_source_file")
            if not isinstance(source_text, str):
                continue
            source = int(source_text, 16)
            if schema == "ordinary_u32_stream":
                set_patch(source, new_target[pointer], "ordinary_u32_stream")

    # Container owner patches.
    for literal_off in base.OVERRIDE_LITERAL_OFFSETS:
        old_pair = u32(data, literal_off)
        set_patch(literal_off, pair_new_address[old_pair], "override_pair_literal")
    for search_index in range(tracked.SEARCH_COUNT):
        source = tracked.SEARCH_DB + search_index * tracked.SEARCH_STRIDE + tracked.SEARCH_PAIR_FIELD
        old_pair = u32(data, source)
        set_patch(source, fallback_new_address[old_pair], "fallback_pair_pointer")
    for container in multiline["containers"]:
        source = int(container["pointer_source_file"], 16)
        old_start = int(container["list_start_address"], 16)
        set_patch(source, list_new_address[old_start], "double_nul_list_pointer")
    set_patch(manifest.RELATIVE_BASE_LITERAL_FILE, gba_address(relative_new_file), "relative_block_base_literal")

    check(len(patch_values) == EXPECTED_TOTAL_PATCH_FIELDS, f"patch-field count drift: {len(patch_values)}")
    patch_kind_counts: dict[str, int] = {}
    for _source, (_value, kind) in patch_values.items():
        patch_kind_counts[kind] = patch_kind_counts.get(kind, 0) + 1
    check(patch_kind_counts == {
        "ordinary_u32_stream": 3875,
        "override_pair_literal": 18,
        "fallback_pair_pointer": 64,
        "double_nul_list_pointer": 114,
        "relative_block_base_literal": 1,
    }, f"patch-kind split drift: {patch_kind_counts}")

    allowed_patch_bytes: set[int] = set()
    patch_rows = []
    for source, (value, kind) in sorted(patch_values.items()):
        old_value = u32(data, source)
        struct.pack_into("<I", candidate, source, value)
        allowed_patch_bytes.update(range(source, source + 4))
        patch_rows.append({
            "source_file": f"0x{source:08X}",
            "old_value": f"0x{old_value:08X}",
            "new_value": f"0x{value:08X}",
            "kind": kind,
        })

    # Verification: only proven owner fields may change in the original half.
    changed = [i for i, (a, b) in enumerate(zip(data, candidate[:ROM_SIZE])) if a != b]
    unexpected = [i for i in changed if i not in allowed_patch_bytes]
    check(not unexpected, f"unexpected original-half changed bytes: {len(unexpected)}")

    # Original text payloads remain untouched.
    for pointer in record_by_pointer:
        raw = exact.strict_stream(data, pointer)
        check(raw is not None, f"source payload parse drift 0x{pointer:08X}")
        off = pointer - ROM_BASE
        check(candidate[off:off + len(raw or b"")] == raw, f"original text payload changed at 0x{pointer:08X}")

    # Every relocated record reproduces the exact raw NUL stream.
    for pointer, new_addr in new_target.items():
        raw = exact.strict_stream(data, pointer)
        check(raw is not None, f"relocation source parse drift 0x{pointer:08X}")
        new_off = new_addr - ROM_BASE
        check(candidate[new_off:new_off + len(raw or b"")] == raw, f"relocated raw mismatch 0x{pointer:08X}")

    # Whole-container copies are byte-identical too.
    check(candidate[relative_new_file:relative_new_file + len(relative_payload)] == relative_payload,
          "relative block relocated payload mismatch")
    check(candidate[override_new_file:override_new_file + len(override_blob)] == override_blob,
          "override blob relocated payload mismatch")
    check(candidate[fallback_new_file:fallback_new_file + len(fallback_blob)] == fallback_blob,
          "fallback blob relocated payload mismatch")
    check(candidate[double_new_file:double_new_file + len(double_blob)] == double_blob,
          "double-NUL blob relocated payload mismatch")
    check(candidate[ordinary_new_file:ordinary_new_file + len(ordinary_blob)] == ordinary_blob,
          "ordinary blob relocated payload mismatch")

    check(candidate[STRONG_TAIL_START:ROM_SIZE] == data[STRONG_TAIL_START:ROM_SIZE], "strong tail changed")

    output_sha256 = hashlib.sha256(candidate).hexdigest()
    return {
        "schema_version": 1,
        "description": "4,069-record Stage-2 32 MiB no-op relocation plan",
        "source": {
            "rom_size": len(data),
            "rom_sha256": hashlib.sha256(data).hexdigest(),
        },
        "corpus": {
            "records": manifest.FINAL_RECORDS,
            "raw_bytes": manifest.FINAL_RAW_BYTES,
            "relative_pair_block_bytes": len(relative_payload),
            "override_pair_containers": 18,
            "override_pair_blob_bytes": len(override_blob),
            "fallback_pair_containers": 38,
            "fallback_pair_blob_bytes": len(fallback_blob),
            "double_nul_string_lists": 114,
            "double_nul_string_list_streams": 159,
            "double_nul_string_list_blob_bytes": len(double_blob),
            "ordinary_unique_streams": len(ordinary_targets),
            "ordinary_raw_bytes": len(ordinary_blob),
            "total_relocated_payload_bytes": allocated_payload,
        },
        "allocation": {
            "text_region_start": f"0x{TEXT_START:08X}",
            "text_region_end_exclusive": f"0x{TEXT_END:08X}",
            "text_region_capacity": TEXT_END - TEXT_START,
            "allocated_payload": allocated_payload,
            "alignment_padding": alignment_padding,
            "high_water": f"0x{cursor:08X}",
            "remaining_after_high_water": TEXT_END - cursor,
            "payload_utilization_percent": round(allocated_payload * 100 / (TEXT_END - TEXT_START), 4),
            "allocations": allocations,
        },
        "patches": {
            "total_u32_patch_fields": len(patch_values),
            "kind_counts": patch_kind_counts,
            "allowed_patch_byte_positions": len(allowed_patch_bytes),
            "patch_rows": patch_rows,
        },
        "verification": {
            "result": "PASS",
            "output_size": len(candidate),
            "output_sha256": output_sha256,
            "changed_bytes_in_original_half": len(changed),
            "allowed_patch_byte_positions": len(allowed_patch_bytes),
            "unexpected_changed_bytes": len(unexpected),
            "all_relocated_record_payloads_byte_identical": True,
            "all_relocated_container_payloads_byte_identical": True,
            "original_text_payloads_unchanged": True,
            "strong_tail_0xFCED40_unchanged": True,
        },
        "next_gate": (
            "Rebuild Unicode/charmap export against the 4,069-record production manifest. "
            "The relocation reference/payload model is now independently closed under advance."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == ROM_SIZE, f"ROM size drift: {len(data)}")
    check(digest == ROM_SHA256, f"ROM SHA-256 drift: {digest}")
    report = build_plan(data)

    if args.summary_only:
        visible = {
            key: report[key]
            for key in ("schema_version", "description", "source", "corpus", "allocation", "patches", "verification", "next_gate")
        }
        visible["patches"] = {key: value for key, value in report["patches"].items() if key != "patch_rows"}
    else:
        visible = report
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
