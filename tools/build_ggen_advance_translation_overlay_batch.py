#!/usr/bin/env python3
"""Bind a compact structure-unit translation map to one source snapshot.

Translation authors can keep only ``record_id`` and translation payloads in a
small map.  This helper expands those entries with the immutable source
fingerprints required by ``merge_ggen_advance_translation_overlays.py``.  It
also refuses a partial ``translation_unit_id`` so a batch cannot split a
pointer/length contract by accident.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import merge_ggen_advance_translation_overlays as merge  # noqa: E402


DEFAULT_SOURCE = Path("legacy/analysis/ggen_advance_unified_source_20260827.json")
DEFAULT_OUTPUT = Path("legacy/analysis/ggen_advance_translation_overlays/overlay_batch.json")
PAYLOAD_FIELDS = {
    "record_id",
    "translation_ko",
    "translation_segments",
    "translated_segments",
    "translation_status",
    "translation_source",
    "source_model",
    "prompt_version",
    "review_status",
    "review_count",
    "reviewed_at",
    "translator_notes",
    "qa_status",
}
ROOT_FIELDS = {
    "schema_version",
    "kind",
    "batch_id",
    "translation_source",
    "source_model",
    "prompt_version",
    "review_status",
    "review_count",
    "reviewed_at",
    "translator_notes",
    "qa_status",
    "records",
}


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_mapping(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = merge.load_json(path)
    if isinstance(payload, list):
        check(payload, f"translation map has no records: {path}")
        check(all(isinstance(item, dict) for item in payload), f"translation map contains a non-object: {path}")
        return {}, payload
    check(isinstance(payload, dict), f"translation map root must be an object or list: {path}")
    unknown = sorted(set(payload) - ROOT_FIELDS)
    check(not unknown, f"unknown translation map root fields: {unknown}")
    records = payload.get("records")
    check(isinstance(records, list) and records, f"translation map records must be a non-empty list: {path}")
    check(all(isinstance(item, dict) for item in records), f"translation map records contain a non-object: {path}")
    return payload, records


def value(root: dict[str, Any], item: dict[str, Any], key: str) -> Any:
    if key in item and item[key] is not None:
        return item[key]
    return root.get(key)


def build_overlay(source_path: Path, mapping_path: Path, output_path: Path) -> dict[str, Any]:
    source = merge.load_source(source_path)
    root, compact_records = load_mapping(mapping_path)
    source_by_id = {row["record_id"]: row for row in source["records"]}
    unknown_per_record = [sorted(set(item) - PAYLOAD_FIELDS) for item in compact_records]
    check(not any(unknown_per_record), f"unknown translation map record fields: {unknown_per_record}")

    batch_id = value(root, {}, "batch_id")
    check(isinstance(batch_id, str) and batch_id.strip(), "translation map batch_id is required")
    batch_id = batch_id.strip()
    selected: dict[str, dict[str, Any]] = {}
    for compact in compact_records:
        record_id = compact.get("record_id")
        check(isinstance(record_id, str) and record_id, "translation map record_id is required")
        check(record_id in source_by_id, f"translation map record is not in source: {record_id}")
        check(record_id not in selected, f"duplicate translation map record_id: {record_id}")
        row = source_by_id[record_id]
        check(row.get("scope_status") == "included", f"translation map cannot include alias: {record_id}")
        check(row.get("translation_policy") == "translate", f"translation map record is not translatable: {record_id}")
        selected[record_id] = compact

    unit_members: dict[str, set[str]] = defaultdict(set)
    for row in source["records"]:
        if row.get("scope_status") == "included" and row.get("translation_policy") == "translate":
            unit_members[str(row["translation_unit_id"])].add(str(row["record_id"]))
    selected_by_unit: dict[str, set[str]] = defaultdict(set)
    for record_id in selected:
        selected_by_unit[str(source_by_id[record_id]["translation_unit_id"])].add(record_id)
    for unit_id, record_ids in sorted(selected_by_unit.items()):
        missing = sorted(unit_members[unit_id] - record_ids)
        check(not missing, f"translation map splits translation_unit {unit_id}: missing {missing}")

    overlay_records: list[dict[str, Any]] = []
    for record_id in sorted(selected, key=lambda item: (int(source_by_id[item]["target_file_offset"], 16), item)):
        row = source_by_id[record_id]
        compact = selected[record_id]
        record: dict[str, Any] = {
            "record_id": record_id,
            "source_rom_sha256": source["source"]["sha256"],
            "manifest_identity_sha256": source["identity"]["manifest_identity_sha256"],
            "original_raw_sha256": row["original_raw_sha256"],
            "owner_digest": row["owner_digest"],
            "source_fingerprint": row["source_fingerprint"],
            "target_file_offset": row["target_file_offset"],
            "translation_unit_id": row["translation_unit_id"],
            "context_bundle_id": row["context_bundle_id"],
        }
        if row.get("record_kind") in merge.CONTROLLED_RECORD_KINDS:
            record.update(
                {
                    "record_kind": row["record_kind"],
                    "scope_status": row["scope_status"],
                    "container_id": row["container_id"],
                    "storage_contract": row["storage_contract"],
                    "relocation_schema": row["relocation_schema"],
                    "control_signature": row["control_signature"],
                    "segments_sha256": merge.digest(row.get("segments", [])),
                    "source_unresolved_slots": row["source_unresolved_slots"],
                    "line_break_count": row.get("line_break_count", 0),
                    "dynamic_control_count": row.get("dynamic_control_count", 0),
                    "final_control": row.get("final_control"),
                }
            )
        for field in PAYLOAD_FIELDS - {"record_id"}:
            item_value = value(root, compact, field)
            if item_value is not None:
                record[field] = item_value
        overlay_records.append(record)

    envelope = {
        "schema_version": 1,
        "kind": "ggen_advance_translation_overlay",
        "batch_id": batch_id,
        "source_rom_sha256": source["source"]["sha256"],
        "manifest_identity_sha256": source["identity"]["manifest_identity_sha256"],
        "translation_source": value(root, {}, "translation_source"),
        "source_model": value(root, {}, "source_model"),
        "prompt_version": value(root, {}, "prompt_version"),
        "review_status": value(root, {}, "review_status"),
        "records": overlay_records,
    }
    for field in ("review_count", "reviewed_at", "translator_notes", "qa_status"):
        if root.get(field) is not None:
            envelope[field] = root[field]
    check(envelope["translation_source"] is not None, "translation_source is required")
    check(envelope["review_status"] is not None, "review_status is required")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        fail(f"cannot write overlay {output_path}: {exc}")
    return {
        "result": "PASS",
        "output": str(output_path),
        "batch_id": batch_id,
        "record_count": len(overlay_records),
        "translation_unit_count": len(selected_by_unit),
        "source_rom_sha256": source["source"]["sha256"],
        "manifest_identity_sha256": source["identity"]["manifest_identity_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--map", dest="mapping", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(json.dumps(build_overlay(args.source, args.mapping, args.out), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
