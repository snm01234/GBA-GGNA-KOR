#!/usr/bin/env python3
"""Merge parallel LLM/human translation overlays into the unified source.

The unified source is immutable.  This tool only copies translation payloads
onto a new derived JSON report after checking the source ROM hash, manifest
identity, per-record fingerprints, pointer ownership, and controlled-stream
framing.  It deliberately has no code path that writes a ROM or changes the
source manifest.

An overlay is either a JSON envelope::

    {
      "schema_version": 1,
      "kind": "ggen_advance_translation_overlay",
      "batch_id": "scenario-0001",
      "source_rom_sha256": "...",
      "manifest_identity_sha256": "...",
      "translation_source": "llm",
      "source_model": "...",
      "prompt_version": "...",
      "records": [
        {
          "record_id": "...",
          "original_raw_sha256": "...",
          "owner_digest": "...",
          "source_fingerprint": "...",
          "target_file_offset": "0x...",
          "translation_ko": "...",
          "translation_status": "translated",
          "review_status": "draft"
        }
      ]
    }

or JSONL with one record per line.  JSONL records must carry the same
metadata themselves unless a metadata line (an object without ``record_id``)
precedes them.  Scenario controlled streams use ``translation_segments``;
their list length and non-text slots are checked against the source framing.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import (  # noqa: E402
    ADVANCE_ROOT,
    TRANSLATION_MERGED_JSON,
    UNIFIED_SOURCE,
)


DEFAULT_SOURCE = UNIFIED_SOURCE
DEFAULT_OUTPUT = TRANSLATION_MERGED_JSON

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ALLOWED_TRANSLATION_SOURCES = {
    "human",
    "llm",
    "user_verified",
    "curated_project_data",
}
ALLOWED_REVIEW_STATUSES = {
    "draft",
    "pending",
    "needs_review",
    "approved",
    "user_verified",
}
ALLOWED_TRANSLATION_STATUSES = {
    "draft",
    "pending",
    "translated",
    "needs_review",
}

CONTROLLED_RECORD_KINDS = frozenset(
    {
        "scenario_controlled_text_stream",
        "map_script_inline_text_stream",
        "battle_event_controlled_text_stream",
    }
)

# These are the values that identify the original byte/pointer/structure
# contract.  They are never accepted as writable overlay fields.
IDENTITY_FIELDS = (
    "record_id",
    "target_file_offset",
    "original_raw_sha256",
    "owner_digest",
    "source_fingerprint",
    "translation_unit_id",
    "context_bundle_id",
)
OPTIONAL_STRUCTURE_FIELDS = (
    "record_kind",
    "scope_status",
    "container_id",
    "storage_contract",
    "relocation_schema",
    "control_signature",
    "control_signature_sha256",
    "segments_sha256",
    "source_unresolved_slots",
    "line_break_count",
    "dynamic_control_count",
    "final_control",
)

OVERLAY_RECORD_FIELDS = set(
    IDENTITY_FIELDS
    + OPTIONAL_STRUCTURE_FIELDS
    + (
        "identity",
        "source_rom_sha256",
        "source_sha256",
        "manifest_identity_sha256",
        "source_manifest_identity_sha256",
        "batch_id",
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
    )
)

ENVELOPE_FIELDS = {
    "schema_version",
    "kind",
    "batch_id",
    "source_rom_sha256",
    "source_sha256",
    "manifest_identity_sha256",
    "source_manifest_identity_sha256",
    "translation_source",
    "source_model",
    "prompt_version",
    "review_status",
    "review_count",
    "reviewed_at",
    "translator_notes",
    "qa_status",
    "generated_at",
    "agent_id",
    "range",
    "notes",
    "defaults",
    "records",
}


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        fail(f"cannot read or hash overlay {path}: {exc}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc}")


def load_source(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    check(isinstance(payload, dict), f"source root must be an object: {path}")
    check(payload.get("schema_version") == 1, "unsupported unified source schema_version")
    source = payload.get("source")
    identity = payload.get("identity")
    records = payload.get("records")
    check(isinstance(source, dict), "unified source.source is missing")
    check(isinstance(identity, dict), "unified source.identity is missing")
    check(isinstance(records, list), "unified source.records must be a list")
    rom_sha = source.get("sha256")
    manifest_sha = identity.get("manifest_identity_sha256")
    check(isinstance(rom_sha, str) and SHA256_RE.fullmatch(rom_sha), "invalid unified source ROM SHA-256")
    check(isinstance(manifest_sha, str) and SHA256_RE.fullmatch(manifest_sha), "invalid unified source manifest identity")
    seen: set[str] = set()
    for row in records:
        check(isinstance(row, dict), "unified source record is not an object")
        record_id = row.get("record_id")
        check(isinstance(record_id, str) and record_id, "unified source record has no record_id")
        check(record_id not in seen, f"duplicate source record_id: {record_id}")
        seen.add(record_id)
        check(row.get("scope_status") in {"included", "alias"}, f"invalid source scope_status: {record_id}")
        check(isinstance(row.get("source_fingerprint"), str), f"source fingerprint missing: {record_id}")
        check(isinstance(row.get("owner_digest"), str), f"owner digest missing: {record_id}")
        check(isinstance(row.get("translation_unit_id"), str) and row["translation_unit_id"], f"translation unit missing: {record_id}")
        check(isinstance(row.get("context_bundle_id"), str) and row["context_bundle_id"], f"context bundle missing: {record_id}")
    by_id = {row["record_id"]: row for row in records}
    for row in records:
        if row["scope_status"] == "alias":
            alias_of = row.get("alias_of")
            check(alias_of in by_id, f"alias target missing in source: {row['record_id']} -> {alias_of}")
            check(by_id[alias_of].get("scope_status") == "included", f"alias target is not canonical: {row['record_id']}")
    return payload


def hash_value(value: Any, field: str) -> str:
    check(isinstance(value, str) and SHA256_RE.fullmatch(value), f"{field} is not a SHA-256")
    return value.lower()


def numeric_offset(value: Any, field: str) -> int:
    if isinstance(value, bool) or value is None:
        fail(f"{field} is not a numeric file offset")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
    except ValueError:
        fail(f"{field} is not a numeric file offset: {value!r}")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalized_slots(value: Any, field: str) -> list[str]:
    result: list[str] = []
    for item in as_list(value):
        check(isinstance(item, str), f"{field} contains a non-string slot")
        text = item.strip().upper()
        check(re.fullmatch(r"0X[0-9A-F]{4}", text) is not None, f"{field} contains invalid slot: {item!r}")
        result.append("0x" + text[2:])
    return sorted(set(result), key=lambda item: int(item, 16))


def source_sha(source_payload: dict[str, Any]) -> str:
    return str(source_payload["source"]["sha256"]).lower()


def manifest_sha(source_payload: dict[str, Any]) -> str:
    return str(source_payload["identity"]["manifest_identity_sha256"]).lower()


def structure_digest(row: dict[str, Any], field: str) -> str:
    return digest(row.get(field, []))


def overlay_paths(values: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        path = value.resolve()
        if path.is_dir():
            candidates = sorted(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix.lower() in {".json", ".jsonl"}
            )
        else:
            candidates = [path]
        for candidate in candidates:
            candidate = candidate.resolve()
            check(candidate not in seen, f"overlay path supplied twice: {candidate}")
            check(candidate.is_file(), f"overlay file does not exist: {candidate}")
            seen.add(candidate)
            result.append(candidate)
    return result


def parse_overlay(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    file_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        meta: dict[str, Any] = {}
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                fail(f"invalid JSONL {path}:{line_number}: {exc}")
            check(isinstance(item, dict), f"JSONL item is not an object: {path}:{line_number}")
            if "record_id" in item:
                records.append(item)
            else:
                check("records" not in item, f"JSONL metadata line cannot contain records: {path}:{line_number}")
                meta.update(item)
        check(records, f"overlay has no records: {path}")
        return {"path": path, "file_sha256": file_hash, "meta": meta, "records": records}

    payload = load_json(path)
    if isinstance(payload, list):
        check(payload, f"overlay has no records: {path}")
        check(all(isinstance(item, dict) for item in payload), f"overlay list contains a non-object: {path}")
        return {"path": path, "file_sha256": file_hash, "meta": {}, "records": payload}
    check(isinstance(payload, dict), f"overlay root must be an object or list: {path}")
    if "records" in payload:
        records = payload["records"]
        check(isinstance(records, list) and records, f"overlay records must be a non-empty list: {path}")
        check(all(isinstance(item, dict) for item in records), f"overlay records contain a non-object: {path}")
        meta = {key: value for key, value in payload.items() if key != "records"}
    else:
        check("record_id" in payload, f"overlay object has neither records nor record_id: {path}")
        records = [payload]
        meta = {}
    return {"path": path, "file_sha256": file_hash, "meta": meta, "records": records}


def doc_value(meta: dict[str, Any], item: dict[str, Any], key: str) -> Any:
    identity = item.get("identity")
    if isinstance(identity, dict) and key in identity:
        return identity[key]
    if key in item and item[key] is not None:
        return item[key]
    defaults = meta.get("defaults")
    if isinstance(defaults, dict) and key in defaults:
        return defaults[key]
    return meta.get(key)


def metadata_value(meta: dict[str, Any], item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = doc_value(meta, item, key)
        if value is not None:
            return value
    return None


def validate_envelope(meta: dict[str, Any], path: Path) -> None:
    unknown = sorted(set(meta) - ENVELOPE_FIELDS)
    check(not unknown, f"unknown overlay envelope fields in {path.name}: {unknown}")
    if "schema_version" in meta:
        check(meta["schema_version"] == 1, f"unsupported overlay schema_version in {path.name}")
    if "kind" in meta:
        check(meta["kind"] in {"ggen_advance_translation_overlay", "ggen_advance_translation_overlay_meta"}, f"invalid overlay kind in {path.name}")


def validate_identity(
    item: dict[str, Any],
    row: dict[str, Any],
    *,
    rom_sha: str,
    source_manifest_sha: str,
    meta: dict[str, Any],
) -> None:
    unknown = sorted(set(item) - OVERLAY_RECORD_FIELDS)
    check(not unknown, f"unknown overlay record fields for {row['record_id']}: {unknown}")
    record_id = item.get("record_id")
    check(record_id == row["record_id"], f"record_id mismatch: {record_id!r} vs {row['record_id']}")

    item_rom = metadata_value(meta, item, "source_rom_sha256", "source_sha256")
    check(item_rom is not None, f"overlay ROM SHA missing for {record_id}")
    check(hash_value(item_rom, f"{record_id}.source_rom_sha256") == rom_sha, f"overlay ROM SHA mismatch for {record_id}")
    item_manifest = metadata_value(meta, item, "manifest_identity_sha256", "source_manifest_identity_sha256")
    check(item_manifest is not None, f"overlay manifest identity missing for {record_id}")
    check(hash_value(item_manifest, f"{record_id}.manifest_identity_sha256") == source_manifest_sha, f"overlay manifest identity mismatch for {record_id}")

    for field in ("original_raw_sha256", "owner_digest", "source_fingerprint"):
        value = doc_value(meta, item, field)
        check(value is not None, f"{field} missing for {record_id}")
        check(hash_value(value, f"{record_id}.{field}") == str(row[field]).lower(), f"{field} mismatch for {record_id}")
    for field in ("translation_unit_id", "context_bundle_id"):
        value = doc_value(meta, item, field)
        check(value is not None, f"{field} missing for {record_id}")
        check(value == row[field], f"{field} mismatch for {record_id}")
    value = doc_value(meta, item, "target_file_offset")
    check(value is not None, f"target_file_offset missing for {record_id}")
    check(numeric_offset(value, f"{record_id}.target_file_offset") == numeric_offset(row["target_file_offset"], f"{record_id}.source_target_file_offset"), f"target_file_offset mismatch for {record_id}")

    for field in OPTIONAL_STRUCTURE_FIELDS:
        if field not in item and not (isinstance(item.get("identity"), dict) and field in item["identity"]):
            continue
        value = doc_value(meta, item, field)
        expected = row.get(field)
        if field in {"control_signature_sha256", "segments_sha256"}:
            expected_digest = structure_digest(row, "control_signature" if field.startswith("control") else "segments")
            check(hash_value(value, f"{record_id}.{field}") == expected_digest, f"{field} mismatch for {record_id}")
        elif field == "source_unresolved_slots":
            check(normalized_slots(value, f"{record_id}.{field}") == normalized_slots(expected, f"source.{record_id}.{field}"), f"{field} mismatch for {record_id}")
        elif field == "control_signature":
            check(value == expected, f"control_signature mismatch for {record_id}")
        elif field == "line_break_count" or field == "dynamic_control_count":
            check(value == expected, f"{field} mismatch for {record_id}")
        else:
            check(value == expected, f"{field} mismatch for {record_id}")


def validate_text(value: Any, field: str, *, allow_newline: bool = False) -> str:
    check(isinstance(value, str), f"{field} must be a string")
    check("\x00" not in value, f"NUL is not allowed in {field}")
    if not allow_newline:
        check("\r" not in value and "\n" not in value, f"line break is not allowed in {field}; use translation_segments")
    check(not any(ord(char) < 0x20 and char not in "\t\r\n" for char in value), f"control byte is not allowed in {field}")
    return value


def resolve_translation_fields(
    item: dict[str, Any],
    meta: dict[str, Any],
    row: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    record_id = row["record_id"]
    translation_source = metadata_value(meta, item, "translation_source")
    check(translation_source in ALLOWED_TRANSLATION_SOURCES, f"invalid translation_source for {record_id}: {translation_source!r}")
    source_model = metadata_value(meta, item, "source_model")
    prompt_version = metadata_value(meta, item, "prompt_version")
    if translation_source == "llm":
        check(isinstance(source_model, str) and source_model.strip(), f"source_model required for LLM record {record_id}")
        check(isinstance(prompt_version, str) and prompt_version.strip(), f"prompt_version required for LLM record {record_id}")
    source_model = str(source_model or "")
    prompt_version = str(prompt_version or "")

    review_status = str(metadata_value(meta, item, "review_status") or "draft")
    check(review_status in ALLOWED_REVIEW_STATUSES, f"invalid review_status for {record_id}: {review_status!r}")
    translation_status_given = metadata_value(meta, item, "translation_status")
    translation_status = str(translation_status_given or "")
    if translation_status:
        check(translation_status in ALLOWED_TRANSLATION_STATUSES, f"invalid translation_status for {record_id}: {translation_status!r}")
    review_count_value = metadata_value(meta, item, "review_count")
    review_count = 0 if review_count_value is None else review_count_value
    check(isinstance(review_count, int) and not isinstance(review_count, bool) and review_count >= 0, f"invalid review_count for {record_id}")
    reviewed_at_value = metadata_value(meta, item, "reviewed_at")
    reviewed_at = "" if reviewed_at_value is None else validate_text(reviewed_at_value, f"{record_id}.reviewed_at", allow_newline=False)
    translator_notes_value = metadata_value(meta, item, "translator_notes")
    translator_notes = "" if translator_notes_value is None else validate_text(translator_notes_value, f"{record_id}.translator_notes", allow_newline=True)
    qa_status_value = metadata_value(meta, item, "qa_status")
    qa_status = "not_checked" if qa_status_value is None else validate_text(qa_status_value, f"{record_id}.qa_status")

    segment_keys = [key for key in ("translation_segments", "translated_segments") if key in item]
    check(len(segment_keys) <= 1, f"use only one of translation_segments/translated_segments for {record_id}")
    is_controlled = row.get("record_kind") in CONTROLLED_RECORD_KINDS
    translation_segments: list[str] | None = None
    translation_ko_value = item.get("translation_ko")

    if is_controlled:
        source_segments = row.get("segments")
        check(isinstance(source_segments, list), f"scenario source segments missing for {record_id}")
        if segment_keys:
            raw_segments = item[segment_keys[0]]
            check(isinstance(raw_segments, list), f"{segment_keys[0]} must be a list for {record_id}")
            check(len(raw_segments) == len(source_segments), f"scenario segment count mismatch for {record_id}")
            translation_segments = []
            for index, (source_segment, target_segment) in enumerate(zip(source_segments, raw_segments)):
                check(isinstance(source_segment, dict), f"source segment {index} is not an object for {record_id}")
                target_text = validate_text(target_segment, f"{record_id}.translation_segments[{index}]")
                if not bool(source_segment.get("is_text_segment")):
                    check(target_text == "", f"non-text scenario segment {index} changed for {record_id}")
                translation_segments.append(target_text)
            nonempty_segments = [
                value
                for source_segment, value in zip(source_segments, translation_segments)
                if bool(source_segment.get("is_text_segment")) and value
            ]
            derived_display = "\n".join(nonempty_segments)
            if translation_ko_value is not None:
                translation_ko = validate_text(translation_ko_value, f"{record_id}.translation_ko", allow_newline=True)
                check(translation_ko == derived_display, f"translation_ko disagrees with translation_segments for {record_id}")
            else:
                translation_ko = derived_display
        else:
            translation_ko = "" if translation_ko_value is None else validate_text(translation_ko_value, f"{record_id}.translation_ko", allow_newline=True)
            check(not translation_ko, f"scenario translation requires translation_segments for {record_id}")
    else:
        check(not segment_keys, f"translation_segments are only valid for controlled scenario records: {record_id}")
        translation_ko = "" if translation_ko_value is None else validate_text(translation_ko_value, f"{record_id}.translation_ko")

    has_content = bool(translation_ko.strip()) or bool(translation_segments and any(value.strip() for value in translation_segments))
    if not translation_status:
        translation_status = "translated" if has_content else "needs_review"
    if review_status in {"approved", "user_verified"}:
        check(has_content, f"approved overlay has no translation content for {record_id}")
        check(review_count >= 1, f"approved overlay needs review_count >= 1 for {record_id}")
        check(reviewed_at.strip(), f"approved overlay needs reviewed_at for {record_id}")
        check(translation_status == "translated", f"approved overlay must have translated status for {record_id}")
    if mode == "approved":
        check(review_status in {"approved", "user_verified"}, f"approved merge received unapproved record {record_id}")
    if translation_status == "translated":
        check(has_content, f"translated status has no content for {record_id}")
    check(review_status not in {"approved", "user_verified"} or translation_source in ALLOWED_TRANSLATION_SOURCES, f"approved source invalid for {record_id}")

    result = {
        "translation_ko": translation_ko,
        "translation_status": translation_status,
        "translation_source": str(translation_source),
        "source_model": source_model,
        "prompt_version": prompt_version,
        "review_status": review_status,
        "review_count": review_count,
        "reviewed_at": reviewed_at,
        "translator_notes": translator_notes,
        "qa_status": qa_status,
    }
    if translation_segments is not None:
        result["translation_segments"] = translation_segments
    return result


def validate_and_normalize_record(
    item: dict[str, Any],
    meta: dict[str, Any],
    source_by_id: dict[str, dict[str, Any]],
    *,
    rom_sha: str,
    source_manifest_sha: str,
    mode: str,
) -> dict[str, Any]:
    record_id = item.get("record_id")
    check(isinstance(record_id, str) and record_id, "overlay record has no record_id")
    check(record_id in source_by_id, f"overlay record is not in unified source: {record_id}")
    row = source_by_id[record_id]
    check(row.get("scope_status") == "included", f"aliases/exclusions cannot be translated independently: {record_id}")
    check(row.get("translation_policy") == "translate", f"source record is not translatable: {record_id}")
    validate_identity(item, row, rom_sha=rom_sha, source_manifest_sha=source_manifest_sha, meta=meta)
    batch_id = metadata_value(meta, item, "batch_id")
    check(isinstance(batch_id, str) and batch_id.strip(), f"batch_id missing for {record_id}")
    return {
        "record_id": record_id,
        "batch_id": batch_id.strip(),
        **resolve_translation_fields(item, meta, row, mode=mode),
    }


def enforce_batch_and_duplicate_gates(
    docs: list[dict[str, Any]],
    source_by_id: dict[str, dict[str, Any]],
    *,
    rom_sha: str,
    source_manifest_sha: str,
    mode: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, list[str]]]:
    patches: dict[str, dict[str, Any]] = {}
    batch_to_file: dict[str, dict[str, Any]] = {}
    file_descriptors: list[dict[str, Any]] = []
    for doc in docs:
        path = doc["path"]
        meta = doc["meta"]
        validate_envelope(meta, path)
        file_records: list[dict[str, Any]] = []
        file_batches: set[str] = set()
        for item in doc["records"]:
            normalized = validate_and_normalize_record(
                item,
                meta,
                source_by_id,
                rom_sha=rom_sha,
                source_manifest_sha=source_manifest_sha,
                mode=mode,
            )
            record_id = normalized["record_id"]
            check(record_id not in patches, f"duplicate overlay record_id across batches/files: {record_id}")
            batch_id = normalized["batch_id"]
            file_batches.add(batch_id)
            patches[record_id] = normalized
            file_records.append(normalized)
        check(len(file_batches) == 1, f"one overlay file must contain exactly one batch_id: {path.name}")
        batch_id = next(iter(file_batches))
        check(batch_id not in batch_to_file, f"duplicate batch_id across overlay files: {batch_id}")
        descriptor = {
            "file": path.name,
            "file_sha256": doc["file_sha256"],
            "batch_id": batch_id,
            "record_count": len(file_records),
            "record_ids": sorted(item["record_id"] for item in file_records),
        }
        batch_to_file[batch_id] = descriptor
        file_descriptors.append(descriptor)

    unit_members: dict[str, set[str]] = defaultdict(set)
    for row in source_by_id.values():
        if row.get("scope_status") == "included" and row.get("translation_policy") == "translate":
            unit_members[str(row["translation_unit_id"])].add(str(row["record_id"]))
    patched_by_unit: dict[str, list[str]] = defaultdict(list)
    for record_id in patches:
        patched_by_unit[str(source_by_id[record_id]["translation_unit_id"])].append(record_id)
    for unit_id, patched_ids in sorted(patched_by_unit.items()):
        members = unit_members[unit_id]
        missing = sorted(members - set(patched_ids))
        check(not missing, f"partial translation_unit {unit_id}; missing records: {missing}")
    return patches, sorted(file_descriptors, key=lambda item: (item["batch_id"], item["file"])), patched_by_unit


def translation_payload_digest(patch: dict[str, Any]) -> str:
    return digest(
        {
            "record_id": patch["record_id"],
            "batch_id": patch["batch_id"],
            "translation_ko": patch["translation_ko"],
            "translation_segments": patch.get("translation_segments"),
            "translation_status": patch["translation_status"],
            "translation_source": patch["translation_source"],
            "source_model": patch["source_model"],
            "prompt_version": patch["prompt_version"],
            "review_status": patch["review_status"],
            "review_count": patch["review_count"],
            "reviewed_at": patch["reviewed_at"],
            "translator_notes": patch["translator_notes"],
            "qa_status": patch["qa_status"],
        }
    )


def merge_payload(
    source_payload: dict[str, Any],
    patches: dict[str, dict[str, Any]],
    file_descriptors: list[dict[str, Any]],
    patched_by_unit: dict[str, list[str]],
    *,
    source_path: Path,
    mode: str,
) -> dict[str, Any]:
    result = copy.deepcopy(source_payload)
    source_by_id = {row["record_id"]: row for row in source_payload["records"]}
    immutable_before = {
        record_id: {
            key: copy.deepcopy(source_by_id[record_id].get(key))
            for key in (
                "record_id",
                "source_scope",
                "scope_status",
                "record_kind",
                "alias_of",
                "target_file_offset",
                "target_address",
                "original_raw_sha256",
                "raw_hex",
                "original_byte_length",
                "source_text",
                "source_unresolved_slots",
                "storage_contract",
                "relocation_schema",
                "container_id",
                "translation_unit_id",
                "context_bundle_id",
                "control_signature",
                "segments",
                "owner_ids",
                "owner_digest",
                "source_fingerprint",
            )
        }
        for record_id in source_by_id
    }
    overlay_identity_rows: list[dict[str, Any]] = []
    for row in result["records"]:
        patch = patches.get(row["record_id"])
        if patch is None:
            continue
        for field in (
            "translation_ko",
            "translation_status",
            "translation_source",
            "source_model",
            "prompt_version",
            "review_status",
            "review_count",
            "reviewed_at",
            "translator_notes",
            "qa_status",
        ):
            row[field] = patch[field]
        if "translation_segments" in patch:
            row["translation_segments"] = patch["translation_segments"]
        row["overlay_batch_id"] = patch["batch_id"]
        row["translation_payload_sha256"] = translation_payload_digest(patch)
        overlay_identity_rows.append(
            {
                "record_id": row["record_id"],
                "translation_payload_sha256": row["translation_payload_sha256"],
            }
        )

    for row in result["records"]:
        record_id = row["record_id"]
        current = {
            key: copy.deepcopy(row.get(key))
            for key in immutable_before[record_id]
        }
        check(current == immutable_before[record_id], f"immutable source field changed during merge: {record_id}")
    overlay_identity_sha = digest(sorted(overlay_identity_rows, key=lambda item: item["record_id"]))
    source_identity = result["identity"]
    result["identity"] = dict(source_identity)
    result["identity"]["translation_overlay_identity_sha256"] = overlay_identity_sha
    result["scope"] = "G Generation Advance unified translation overlay merge"
    result["merge"] = {
        "schema_version": 1,
        "source_manifest": source_path.name,
        "source_manifest_identity_sha256": manifest_sha(source_payload),
        "source_rom_sha256": source_sha(source_payload),
        "mode": mode,
        "overlay_files": file_descriptors,
        "batch_count": len(file_descriptors),
        "accepted_record_count": len(patches),
        "translation_unit_count": len(patched_by_unit),
        "translation_overlay_identity_sha256": overlay_identity_sha,
        "immutable_source_preserved": True,
        "rom_write_performed": False,
    }
    summary = dict(result.get("summary", {}))
    merged_statuses = Counter(str(row.get("translation_status", "")) for row in result["records"])
    merged_review_statuses = Counter(str(row.get("review_status", "")) for row in result["records"])
    translated_canonical = [
        row
        for row in result["records"]
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and str(row.get("translation_status")) == "translated"
    ]
    summary.update(
        {
            "overlay_record_count": len(patches),
            "overlay_translation_unit_count": len(patched_by_unit),
            "merged_translation_status_counts": dict(sorted(merged_statuses.items())),
            "merged_review_status_counts": dict(sorted(merged_review_statuses.items())),
            "translated_canonical_records": len(translated_canonical),
            "untranslated_canonical_records": sum(
                row.get("scope_status") == "included"
                and row.get("translation_policy") == "translate"
                and str(row.get("translation_status")) != "translated"
                for row in result["records"]
            ),
            "translation_overlay_identity_sha256": overlay_identity_sha,
        }
    )
    result["summary"] = summary
    fields = list(result.get("schema_fields", []))
    for field in (
        "translation_segments",
        "overlay_batch_id",
        "translation_payload_sha256",
    ):
        if field not in fields:
            fields.append(field)
    result["schema_fields"] = fields
    return result


def summary_view(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "result": "PASS",
        "source": result["source"],
        "identity": result["identity"],
        "merge": result.get("merge", {}),
        "summary": result["summary"],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        fail(f"cannot write merged output {path}: {exc}")


def run(source_path: Path, overlay_values: list[Path], output_path: Path, *, mode: str, summary_only: bool) -> dict[str, Any]:
    source_payload = load_source(source_path)
    rom_sha = source_sha(source_payload)
    source_manifest_sha = manifest_sha(source_payload)
    source_by_id = {row["record_id"]: row for row in source_payload["records"]}
    paths = overlay_paths(overlay_values)
    docs = [parse_overlay(path) for path in paths]
    patches, file_descriptors, patched_by_unit = enforce_batch_and_duplicate_gates(
        docs,
        source_by_id,
        rom_sha=rom_sha,
        source_manifest_sha=source_manifest_sha,
        mode=mode,
    )
    result = merge_payload(
        source_payload,
        patches,
        file_descriptors,
        patched_by_unit,
        source_path=source_path,
        mode=mode,
    )
    if not summary_only:
        write_json(output_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--overlay", type=Path, action="append", default=[], help="overlay JSON/JSONL file or directory; repeatable")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mode", choices=("draft", "approved"), default="draft")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.source, args.overlay, args.out, mode=args.mode, summary_only=args.summary_only)
    print(json.dumps(summary_view(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
