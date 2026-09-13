#!/usr/bin/env python3
"""Build one immutable source manifest for G Generation Advance text work.

The advance-local project historically kept three useful inventories apart:

* the 4,069-record production translation master;
* the scenario/event main bank and its dynamic fragment owners; and
* owner-proven non-scenario UI records.

This tool joins those inventories without joining their translation state.  A
record is one unique text stream, while pointer fields are normalized into a
separate owner index.  Dynamic fragments and duplicate UI targets remain in
the manifest as aliases, so they cannot silently acquire a second translation.
Global pointer-scan candidates and non-rendered UI cells are retained as
explicit exclusions rather than being promoted as text.

The ROM and all input reports are read-only.  No translation, font, pointer,
or ROM bytes are generated here.  The resulting JSON is the immutable input
snapshot for parallel LLM translation overlays.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROM_BASE = 0x08000000
DEFAULT_ROM = Path("SD Gundam GGeneration Advance (Japan).gba")
DEFAULT_PRODUCTION = Path("legacy/analysis/stage2_translation_sheet_rows_20260827.json")
DEFAULT_SCENARIO = Path("legacy/analysis/scenario_event_translation_source_20260827.json")
DEFAULT_ALIGNMENT = Path("legacy/analysis/scenario_event_12x12_alignment_20260827.json")
DEFAULT_UI_EXPANSION = Path("legacy/analysis/non_scenario_ui_matrix_expansion_20260827.json")
DEFAULT_SCAN_AUDIT = Path("legacy/analysis/non_scenario_expansion_audit_20260827.json")
DEFAULT_OUTPUT = Path("legacy/analysis/ggen_advance_unified_source_20260827.json")

HEX_RE = re.compile(r"^0x[0-9a-fA-F]+$")
ALLOWED_TRANSLATION_POLICIES = {
    "translate",
    "preserve_literal",
    "preserve_by_default",
    "preserve_roundtrip",
}


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def parse_hex(value: Any, *, field: str = "value") -> int:
    if isinstance(value, bool):
        fail(f"{field} is boolean")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if HEX_RE.fullmatch(text):
        return int(text, 16)
    if text.isdigit():
        return int(text, 10)
    fail(f"{field} is not numeric: {value!r}")


def hex32(value: int) -> str:
    return f"0x{value:08X}"


def hex16(value: int) -> str:
    return f"0x{value:04X}"


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc}")
    check(isinstance(payload, dict), f"JSON root must be an object: {path}")
    return payload


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        fail(f"cannot hash {path}: {exc}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def source_sha(payload: dict[str, Any], label: str) -> str:
    source = payload.get("source")
    candidates: list[Any] = []
    if isinstance(source, dict):
        candidates.extend([source.get("sha256"), source.get("rom_sha256")])
    candidates.extend([payload.get("rom_sha256"), payload.get("source_sha256")])
    values = {str(value).lower() for value in candidates if value}
    check(len(values) == 1, f"{label} has no unique source SHA-256: {sorted(values)}")
    return next(iter(values))


def report_source_descriptor(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    return {
        "file": path.name,
        "file_sha256": sha256_file(path),
        "report_source_sha256": source_sha(payload, path.name),
        "report_schema_version": payload.get("schema_version"),
    }


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def source_text_of(row: dict[str, Any]) -> str:
    for key in ("source_text", "decoded_text_seed", "source_text_seed"):
        value = row.get(key)
        if isinstance(value, str):
            return value
    return ""


def raw_sha_of(row: dict[str, Any]) -> str:
    for key in ("original_raw_sha256", "raw_sha256", "raw_sha"):
        value = row.get(key)
        if value:
            return str(value).lower()
    raw_hex = row.get("raw_hex")
    check(isinstance(raw_hex, str), f"record has no raw SHA or raw_hex: {row.get('record_id')}")
    try:
        return sha256_bytes(bytes.fromhex(raw_hex.replace(" ", "")))
    except ValueError as exc:
        fail(f"invalid raw_hex in {row.get('record_id')}: {exc}")


def raw_hex_of(row: dict[str, Any]) -> str:
    value = row.get("raw_hex") or row.get("original_raw_hex") or ""
    return str(value).upper()


def file_offset_of(row: dict[str, Any]) -> int:
    for key in ("target_file_offset", "target_offset"):
        if row.get(key) is not None:
            return parse_hex(row[key], field=f"{row.get('record_id')}.{key}")
    fail(f"record has no target file offset: {row.get('record_id')}")


def unresolved_slots_of(row: dict[str, Any]) -> list[str]:
    values = row.get("unresolved_slots")
    if values is None:
        values = row.get("source_unresolved_slots")
    result: list[str] = []
    for value in as_list(values):
        if value in (None, ""):
            continue
        number = parse_hex(value, field="unresolved_slot")
        result.append(hex16(number))
    return sorted(set(result), key=lambda item: int(item, 16))


def source_families_of(row: dict[str, Any]) -> list[str]:
    values = row.get("source_families")
    if values is None:
        values = row.get("source_families_text", "")
    if isinstance(values, str):
        values = [part for part in values.split(",") if part]
    return sorted({str(value) for value in as_list(values) if value})


def source_types_of(row: dict[str, Any]) -> list[str]:
    values = row.get("source_types")
    return sorted({str(value) for value in as_list(values) if value})


def target_address(row: dict[str, Any], offset: int) -> int:
    value = row.get("target_address") or row.get("pointer_value")
    if value is None:
        return ROM_BASE + offset
    address = parse_hex(value, field=f"{row.get('record_id')}.target_address")
    check(address == ROM_BASE + offset, f"target address mismatch in {row.get('record_id')}")
    return address


def controls_signature(controls: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for control in controls:
        code = control.get("code")
        check(code is not None, "control has no code")
        item: dict[str, Any] = {"code": str(code)}
        if "argument" in control:
            item["argument"] = control["argument"]
        result.append(item)
    return result


def segment_projection(segments: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, segment in enumerate(as_list(segments)):
        check(isinstance(segment, dict), f"segment {index} is not an object")
        result.append(
            {
                "segment_index": index,
                "raw_hex": str(segment.get("raw_hex", "")).upper(),
                "source_text": str(segment.get("source_text", "")),
                "unresolved_slots": unresolved_slots_of(segment),
                "is_text_segment": bool(segment.get("raw_hex", "").replace(" ", "") not in {"", "00"}),
            }
        )
    return result


def pointer_source_values(row: dict[str, Any]) -> list[int]:
    """Extract pointer-field offsets from the several audit report shapes."""
    values: list[Any] = []
    for key in (
        "pointer_source_file",
        "pointer_file_offset",
        "pointer_sources_file",
        "pointer_sources_files",
        "pointer_source_files",
    ):
        if key in row:
            values.extend(as_list(row[key]))
    for owner in as_list(row.get("owner_fields")):
        if isinstance(owner, dict):
            for key in ("pointer_file_offset", "pointer_source_file", "pointer_source_file_offset"):
                if owner.get(key) is not None:
                    values.append(owner[key])
                    break
    result = sorted({parse_hex(value, field="pointer_source_file") for value in values})
    return result


class UnifiedBuilder:
    def __init__(self, rom_sha256: str) -> None:
        self.rom_sha256 = rom_sha256
        self.records: list[dict[str, Any]] = []
        self.record_by_id: dict[str, dict[str, Any]] = {}
        self.canonical_by_target: dict[int, str] = {}
        self.owner_by_id: dict[str, dict[str, Any]] = {}
        self.exclusions: list[dict[str, Any]] = []
        self.source_counts: Counter[str] = Counter()
        self.scope_counts: Counter[str] = Counter()
        self.status_counts: Counter[str] = Counter()

    def add_owner(
        self,
        *,
        kind: str,
        source_offset: int,
        target_record_id: str,
        target_container_id: str,
        relocation_schema: str,
        source_type: str,
        family: str,
        pointer_width: int,
        synthetic: bool = False,
    ) -> str:
        prefix = "U32" if kind == "u32_pointer" else "U16"
        owner_id = f"OWNER-{prefix}-{source_offset:08X}"
        owner = self.owner_by_id.get(owner_id)
        if owner is None:
            owner = {
                "owner_id": owner_id,
                "owner_kind": kind,
                "source_file_offset": hex32(source_offset),
                "pointer_width": pointer_width,
                "target_record_ids": [],
                "target_container_ids": [],
                "relocation_schemas": [],
                "source_types": [],
                "families": [],
                "synthetic": synthetic,
            }
            self.owner_by_id[owner_id] = owner
        else:
            check(owner["owner_kind"] == kind, f"owner kind conflict at {owner_id}")
            check(owner["pointer_width"] == pointer_width, f"owner width conflict at {owner_id}")
            check(owner["synthetic"] == synthetic, f"owner synthetic flag conflict at {owner_id}")
        owner["target_record_ids"] = sorted(set(owner["target_record_ids"]) | {target_record_id})
        owner["target_container_ids"] = sorted(set(owner["target_container_ids"]) | {target_container_id})
        owner["relocation_schemas"] = sorted(set(owner["relocation_schemas"]) | {relocation_schema})
        owner["source_types"] = sorted(set(owner["source_types"]) | {source_type})
        owner["families"] = sorted(set(owner["families"]) | {family})
        return owner_id

    def add_record(
        self,
        record: dict[str, Any],
        *,
        owners: list[str],
        canonical: bool,
    ) -> None:
        record_id = str(record["record_id"])
        check(record_id not in self.record_by_id, f"duplicate unified record_id: {record_id}")
        target = parse_hex(record["target_file_offset"], field=f"{record_id}.target_file_offset")
        if canonical:
            prior = self.canonical_by_target.get(target)
            check(prior is None, f"canonical target collision 0x{target:08X}: {prior} vs {record_id}")
            self.canonical_by_target[target] = record_id
        record["owner_ids"] = sorted(set(owners))
        record["owner_count"] = len(record["owner_ids"])
        record["owner_digest"] = digest(record["owner_ids"])
        record["source_fingerprint"] = digest(
            {
                "rom_sha256": self.rom_sha256,
                "record_id": record_id,
                "target_file_offset": record["target_file_offset"],
                "original_raw_sha256": record["original_raw_sha256"],
                "container_id": record["container_id"],
                "translation_unit_id": record["translation_unit_id"],
                "owner_digest": record["owner_digest"],
            }
        )
        self.records.append(record)
        self.record_by_id[record_id] = record
        self.source_counts[str(record["source_scope"])] += 1
        self.scope_counts[str(record["scope_status"])] += 1
        self.status_counts[str(record["translation_status"])] += 1

    def add_exclusion(self, row: dict[str, Any]) -> None:
        exclusion_id = str(row["exclusion_id"])
        if any(item["exclusion_id"] == exclusion_id for item in self.exclusions):
            fail(f"duplicate exclusion_id: {exclusion_id}")
        self.exclusions.append(row)


def base_record(
    *,
    record_id: str,
    source_scope: str,
    scope_status: str,
    record_kind: str,
    target_offset: int,
    raw_sha256: str,
    raw_hex: str,
    byte_length: int,
    source_text: str,
    unresolved_slots: list[str],
    semantic_category: str,
    source_families: list[str],
    source_types: list[str],
    storage_contract: str,
    relocation_schema: str,
    pointer_group: str,
    container_id: str,
    translation_unit_id: str,
    context_bundle_id: str,
    screen_class: str,
    control_signature: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    baseline_translation_ko: str,
    baseline_translation_status: str,
    translation_policy: str,
    alias_of: str = "",
) -> dict[str, Any]:
    check(translation_policy in ALLOWED_TRANSLATION_POLICIES | {"alias"}, f"unknown translation policy: {translation_policy}")
    initial_status = "alias" if scope_status == "alias" else (
        "preserve" if translation_policy != "translate" else "pending"
    )
    return {
        "record_id": record_id,
        "source_scope": source_scope,
        "scope_status": scope_status,
        "record_kind": record_kind,
        "alias_of": alias_of,
        "target_file_offset": hex32(target_offset),
        "target_address": hex32(ROM_BASE + target_offset),
        "original_raw_sha256": raw_sha256,
        "raw_hex": raw_hex,
        "original_byte_length": byte_length,
        "source_text": source_text,
        "source_decode_status": "complete" if not unresolved_slots else "partial",
        "source_unresolved_slots": unresolved_slots,
        "semantic_category": semantic_category,
        "source_families": source_families,
        "source_types": source_types,
        "storage_contract": storage_contract,
        "relocation_schema": relocation_schema,
        "pointer_group": pointer_group,
        "container_id": container_id,
        "translation_unit_id": translation_unit_id,
        "context_bundle_id": context_bundle_id,
        "screen_class": screen_class,
        "control_signature": control_signature,
        "segments": segments,
        "baseline_translation_ko": baseline_translation_ko,
        "baseline_translation_status": baseline_translation_status,
        "translation_policy": translation_policy if scope_status != "alias" else "alias",
        "translation_ko": "",
        "translation_status": initial_status,
        "translation_source": "",
        "source_model": "",
        "prompt_version": "",
        "review_status": "pending" if scope_status != "alias" else "alias",
        "review_count": 0,
        "reviewed_at": "",
        "translator_notes": "",
        "qa_status": "not_checked",
    }


def normalize_production(
    builder: UnifiedBuilder,
    payload: dict[str, Any],
) -> None:
    rows = payload.get("records")
    check(isinstance(rows, list), "production master records must be a list")
    relative_base_added = False
    for row in rows:
        check(isinstance(row, dict), "production record must be an object")
        record_id = str(row["record_id"])
        offset = file_offset_of(row)
        address = target_address(row, offset)
        refs = [ref for ref in as_list(row.get("references")) if isinstance(ref, dict)]
        source_families = source_families_of(row)
        source_types = source_types_of(row)
        storage = str(row.get("storage_contract", ""))
        check(storage, f"production record has no storage_contract: {record_id}")
        schema = str(row.get("relocation_schema", ""))
        if not schema:
            schema = next(
                (
                    str(ref.get("relocation_schema"))
                    for ref in refs
                    if ref.get("relocation_schema")
                ),
            ) or "ordinary_u32_stream"

        target_container = record_id
        translation_unit = record_id
        context_bundle = record_id
        line_index: int | None = None
        if storage == "nul_stream_u16_relative_pair_member":
            ref = next((item for item in refs if item.get("pair_index") is not None), {})
            pair_index = int(ref.get("pair_index", 0))
            target_container = f"PROD-RELATIVE-{pair_index:04d}"
            translation_unit = target_container
            context_bundle = target_container
            line_index = int(ref["line_index"]) if ref.get("line_index") is not None else None
            if not relative_base_added:
                base_owner = builder.add_owner(
                    kind="u32_pointer",
                    source_offset=0x001BF908 - 0x001BF908 + 0x0004DC54,
                    target_record_id=target_container,
                    target_container_id="PROD-RELATIVE-BLOCK",
                    relocation_schema="relative_block_base_literal",
                    source_type="relative_block_base_literal",
                    family="relative_256x3_paired_text_table",
                    pointer_width=4,
                    synthetic=True,
                )
                # The expression above intentionally resolves to the literal
                # file offset 0x0004DC54; keep the assertion close to the
                # synthetic owner so a future refactor cannot move it silently.
                check(base_owner == "OWNER-U32-0004DC54", "relative base owner identity drift")
                relative_base_added = True
        elif storage == "nul_stream_double_nul_list_member":
            ref = next((item for item in refs if item.get("list_start_address")), {})
            list_start = parse_hex(ref.get("list_start_address", offset), field=f"{record_id}.list_start_address")
            target_container = f"PROD-DOUBLE-{list_start:08X}"
            translation_unit = target_container
            context_bundle = target_container
            line_index = int(ref["line_index"]) if ref.get("line_index") is not None else None
        elif "length_prefixed" in storage:
            ref = next((item for item in refs if item.get("pair_address")), {})
            pair_address = parse_hex(ref.get("pair_address", offset + ROM_BASE), field=f"{record_id}.pair_address")
            target_container = f"PROD-PAIR-{pair_address:08X}"
            translation_unit = target_container
            context_bundle = target_container
            line_index = int(ref["line_index"]) if ref.get("line_index") is not None else None

        owners: list[str] = []
        for ref in refs:
            if ref.get("patchable_u32") and ref.get("pointer_source_file") is not None:
                source_offset = parse_hex(ref["pointer_source_file"], field=f"{record_id}.pointer_source_file")
                owners.append(
                    builder.add_owner(
                        kind="u32_pointer",
                        source_offset=source_offset,
                        target_record_id=record_id,
                        target_container_id=target_container,
                        relocation_schema=str(ref.get("relocation_schema", schema)),
                        source_type=str(ref.get("source_type", "unknown")),
                        family=str(ref.get("family", source_families[0] if source_families else "unknown")),
                        pointer_width=4,
                    )
                )
            if ref.get("relative_entry_file") is not None:
                entry_offset = parse_hex(ref["relative_entry_file"], field=f"{record_id}.relative_entry_file")
                owners.append(
                    builder.add_owner(
                        kind="relative_u16_entry",
                        source_offset=entry_offset,
                        target_record_id=record_id,
                        target_container_id=target_container,
                        relocation_schema=str(ref.get("relocation_schema", "relative_pair_block")),
                        source_type=str(ref.get("source_type", "relative_u16")),
                        family=str(ref.get("family", "relative_256x3_paired_text_table")),
                        pointer_width=2,
                    )
                )

        policy = str(row.get("translation_policy", "translate"))
        baseline_status = str(row.get("translation_status", ""))
        record = base_record(
            record_id=record_id,
            source_scope="production",
            scope_status="included",
            record_kind="text_stream",
            target_offset=offset,
            raw_sha256=raw_sha_of(row),
            raw_hex=raw_hex_of(row),
            byte_length=int(row.get("original_byte_length", row.get("raw_byte_length_including_nul", 0))),
            source_text=source_text_of(row),
            unresolved_slots=unresolved_slots_of(row),
            semantic_category=str(row.get("semantic_category", row.get("primary_category", "unknown"))),
            source_families=source_families,
            source_types=source_types,
            storage_contract=storage,
            relocation_schema=schema,
            pointer_group=str(row.get("pointer_group", context_bundle)),
            container_id=target_container,
            translation_unit_id=translation_unit,
            context_bundle_id=context_bundle,
            screen_class="production_text",
            control_signature=[],
            segments=[],
            baseline_translation_ko=str(row.get("translation_ko", "")),
            baseline_translation_status=baseline_status,
            translation_policy=policy,
        )
        record.update(
            {
                "source_record_id": record_id,
                "line_index": line_index,
                "source_reserved_slots": [str(item) for item in as_list(row.get("reserved_slots"))],
                "baseline_translator_notes": str(row.get("translator_notes", "")),
                "pointer_recalc_required": bool(row.get("pointer_recalc_required", False)),
            }
        )
        builder.add_record(record, owners=owners, canonical=True)


def normalize_scenario_main(builder: UnifiedBuilder, payload: dict[str, Any]) -> None:
    main = payload.get("main")
    check(isinstance(main, dict), "scenario main section missing")
    rows = main.get("records")
    check(isinstance(rows, list), "scenario main records must be a list")
    for row in rows:
        check(isinstance(row, dict), "scenario main record must be an object")
        record_id = str(row["record_id"])
        offset = file_offset_of(row)
        controls = controls_signature([item for item in as_list(row.get("controls")) if isinstance(item, dict)])
        first_row = int(row.get("first_directory_row", 0))
        first_slot = int(row.get("first_directory_slot", 0))
        bundle = f"SCENARIO-MAIN-ROW-{first_row:03d}" if first_row else f"SCENARIO-MAIN-{offset:08X}"
        owners: list[str] = []
        for owner in as_list(row.get("owner_fields")):
            if not isinstance(owner, dict) or owner.get("pointer_file_offset") is None:
                continue
            source_offset = parse_hex(owner["pointer_file_offset"], field=f"{record_id}.pointer_file_offset")
            owners.append(
                builder.add_owner(
                    kind="u32_pointer",
                    source_offset=source_offset,
                    target_record_id=record_id,
                    target_container_id=record_id,
                    relocation_schema="scenario_directory_u32",
                    source_type="scenario_directory_pointer",
                    family="main_scenario_event",
                    pointer_width=4,
                )
            )
        record = base_record(
            record_id=record_id,
            source_scope="scenario_main",
            scope_status="included",
            record_kind="scenario_controlled_text_stream",
            target_offset=offset,
            raw_sha256=raw_sha_of(row),
            raw_hex=raw_hex_of(row),
            byte_length=int(row.get("byte_length", 0)),
            source_text=str(row.get("source_text_seed", source_text_of(row))),
            unresolved_slots=unresolved_slots_of(row),
            semantic_category="scenario_event_text",
            source_families=["main_scenario_event"],
            source_types=["scenario_directory_pointer"],
            storage_contract="scenario_control_stream",
            relocation_schema="scenario_directory_u32",
            pointer_group="scenario_main_directory",
            container_id=record_id,
            translation_unit_id=record_id,
            context_bundle_id=bundle,
            screen_class="scenario_event_12x12",
            control_signature=controls,
            segments=segment_projection(row.get("segments")),
            baseline_translation_ko="",
            baseline_translation_status="not_started",
            translation_policy="translate",
        )
        record.update(
            {
                "source_record_id": record_id,
                "directory_row": first_row,
                "directory_slot": first_slot,
                "line_break_count": int(row.get("line_break_count", 0)),
                "dynamic_control_count": int(row.get("dynamic_control_count", 0)),
                "final_control": str(row.get("final_control", "")),
                "pointer_recalc_required": True,
            }
        )
        builder.add_record(record, owners=owners, canonical=True)


def normalize_dynamic_aliases(
    builder: UnifiedBuilder,
    scenario_payload: dict[str, Any],
    production_payload: dict[str, Any],
    alignment_payload: dict[str, Any],
) -> None:
    dynamic = scenario_payload.get("dynamic")
    check(isinstance(dynamic, dict), "scenario dynamic section missing")
    dynamic_rows = [row for row in as_list(dynamic.get("records")) if isinstance(row, dict)]
    production_weapons = [
        row
        for row in as_list(production_payload.get("records"))
        if isinstance(row, dict) and row.get("semantic_category") == "weapon_name"
    ]
    dynamic_rows.sort(key=file_offset_of)
    production_weapons.sort(key=file_offset_of)
    check(len(dynamic_rows) == len(production_weapons), "dynamic/weapon alias cardinality drift")
    check(len(dynamic_rows) == int(alignment_payload.get("dynamic_count", len(dynamic_rows))), "alignment dynamic count drift")
    check(len(production_weapons) == int(alignment_payload.get("weapon_count", len(production_weapons))), "alignment weapon count drift")
    fully_aligned = {int(value) for value in as_list(alignment_payload.get("fully_aligned_indices"))}
    samples = {
        int(item.get("index")): item
        for item in as_list(alignment_payload.get("samples"))
        if isinstance(item, dict) and item.get("index") is not None
    }
    for index, (dynamic_row, weapon_row) in enumerate(zip(dynamic_rows, production_weapons)):
        record_id = str(dynamic_row["record_id"])
        canonical_id = str(weapon_row["record_id"])
        check(canonical_id in builder.record_by_id, f"dynamic alias canonical missing: {canonical_id}")
        offset = file_offset_of(dynamic_row)
        owners: list[str] = []
        for owner in as_list(dynamic_row.get("owner_fields")):
            if not isinstance(owner, dict) or owner.get("pointer_file_offset") is None:
                continue
            source_offset = parse_hex(owner["pointer_file_offset"], field=f"{record_id}.pointer_file_offset")
            owners.append(
                builder.add_owner(
                    kind="u32_pointer",
                    source_offset=source_offset,
                    target_record_id=canonical_id,
                    target_container_id=canonical_id,
                    relocation_schema="scenario_dynamic_u32",
                    source_type="scenario_dynamic_pointer",
                    family="dynamic_fragment_pool",
                    pointer_width=4,
                )
            )
        sample = samples.get(index, {})
        alignment_status = "fully_aligned" if index in fully_aligned else "positional_unresolved"
        record = base_record(
            record_id=record_id,
            source_scope="scenario_dynamic",
            scope_status="alias",
            record_kind="dynamic_fragment_alias",
            target_offset=offset,
            raw_sha256=raw_sha_of(dynamic_row),
            raw_hex=raw_hex_of(dynamic_row),
            byte_length=int(dynamic_row.get("byte_length", 0)),
            source_text=str(dynamic_row.get("source_text_seed", source_text_of(dynamic_row))),
            unresolved_slots=unresolved_slots_of(dynamic_row),
            semantic_category="weapon_name_alias",
            source_families=["dynamic_fragment_pool"],
            source_types=["scenario_dynamic_pointer"],
            storage_contract="scenario_dynamic_stream",
            relocation_schema="scenario_dynamic_u32",
            pointer_group="scenario_dynamic_matrix",
            container_id=canonical_id,
            translation_unit_id=canonical_id,
            context_bundle_id=f"SCENARIO-DYNAMIC-{index:03d}",
            screen_class="scenario_event_12x12",
            control_signature=[],
            segments=[],
            baseline_translation_ko=str(builder.record_by_id[canonical_id].get("baseline_translation_ko", "")),
            baseline_translation_status=str(builder.record_by_id[canonical_id].get("baseline_translation_status", "")),
            translation_policy="alias",
            alias_of=canonical_id,
        )
        record.update(
            {
                "source_record_id": record_id,
                "alias_reason": "dynamic_fragment_content_alignment_to_existing_weapon_name",
                "alias_alignment_index": index,
                "alias_alignment_status": alignment_status,
                "alias_expected_source": str(sample.get("expected", "")),
                "pointer_recalc_required": True,
            }
        )
        builder.add_record(record, owners=owners, canonical=False)


def normalize_ui_expansion(builder: UnifiedBuilder, payload: dict[str, Any]) -> None:
    rows = [row for row in as_list(payload.get("records")) if isinstance(row, dict)]
    rendered = [row for row in rows if str(row.get("promotion_tier", "")) == "owner_proven_rendered"]
    review_only = [row for row in rows if str(row.get("promotion_tier", "")) != "owner_proven_rendered"]
    for row in sorted(rendered, key=file_offset_of):
        offset = file_offset_of(row)
        family = str(row.get("family", "unknown"))
        existing_id = builder.canonical_by_target.get(offset, "")
        record_id = f"GGA-UI-{offset:08X}"
        owners: list[str] = []
        for source_offset in pointer_source_values(row):
            owners.append(
                builder.add_owner(
                    kind="u32_pointer",
                    source_offset=source_offset,
                    target_record_id=existing_id or record_id,
                    target_container_id=existing_id or record_id,
                    relocation_schema=("direct_f54_literal" if family == "direct_f54_literal_ui" else "ui_owner_proven_u32"),
                    source_type="owner_proven_ui_pointer",
                    family=family,
                    pointer_width=4,
                )
            )
        alias = bool(existing_id)
        if alias:
            existing = builder.record_by_id[existing_id]
            ui_sha = raw_sha_of(row)
            check(ui_sha == existing["original_raw_sha256"], f"UI/prod raw conflict at 0x{offset:08X}")
        record_index = row.get("record_index")
        context_key = (
            f"{int(record_index):04d}"
            if record_index is not None
            else f"{offset:08X}"
        )
        record = base_record(
            record_id=record_id,
            source_scope="non_scenario_ui",
            scope_status="alias" if alias else "included",
            record_kind="owner_proven_ui_alias" if alias else "owner_proven_ui_text_stream",
            target_offset=offset,
            raw_sha256=raw_sha_of(row),
            raw_hex=raw_hex_of(row),
            byte_length=int(row.get("raw_byte_length", 0)),
            source_text=str(row.get("decoded_text_seed", source_text_of(row))),
            unresolved_slots=unresolved_slots_of(row),
            semantic_category=str(row.get("semantic_category", "configuration_option_text")),
            source_families=[family],
            source_types=["owner_proven_ui_pointer"],
            storage_contract="nul_stream",
            relocation_schema="direct_f54_literal" if family == "direct_f54_literal_ui" else "ui_owner_proven_u32",
            pointer_group=f"ui_{family}",
            container_id=existing_id or record_id,
            translation_unit_id=existing_id or record_id,
            context_bundle_id=f"UI-{family}-{context_key}",
            screen_class="fixed_ui",
            control_signature=[],
            segments=[],
            baseline_translation_ko=str(builder.record_by_id[existing_id].get("baseline_translation_ko", "")) if alias else "",
            baseline_translation_status=str(builder.record_by_id[existing_id].get("baseline_translation_status", "")) if alias else "not_started",
            translation_policy="alias" if alias else "translate",
            alias_of=existing_id,
        )
        record.update(
            {
                "source_record_id": record_id,
                "ui_family": family,
                "record_index": row.get("record_index"),
                "selector": row.get("selector"),
                "owner_contract": str(row.get("owner_contract", "rendered_owner_proven")),
                "promotion_tier": str(row.get("promotion_tier", "owner_proven_rendered")),
                "font_mode": str(row.get("font_mode", "8x16")),
                "pointer_recalc_required": True,
            }
        )
        builder.add_record(record, owners=owners, canonical=not alias)

    for row in sorted(review_only, key=file_offset_of):
        offset = file_offset_of(row)
        existing_id = builder.canonical_by_target.get(offset, "")
        candidate_id = f"GGA-UI-REVIEW-{offset:08X}"
        builder.add_exclusion(
            {
                "exclusion_id": candidate_id,
                "source_scope": "non_scenario_ui",
                "scope_status": "review_only",
                "reason": "owner_contract_exists_but_selector_is_not_proven_rendered",
                "record_id": candidate_id,
                "alias_of": existing_id,
                "target_file_offset": hex32(offset),
                "target_address": hex32(ROM_BASE + offset),
                "original_raw_sha256": raw_sha_of(row),
                "raw_hex": raw_hex_of(row),
                "source_text": str(row.get("decoded_text_seed", source_text_of(row))),
                "unresolved_slots": unresolved_slots_of(row),
                "family": str(row.get("family", "unknown")),
                "promotion_tier": str(row.get("promotion_tier", "review_only")),
                "font_mode": str(row.get("font_mode", "8x16")),
                "pointer_source_count": len(pointer_source_values(row)),
                "pointer_sources_digest": digest([hex32(value) for value in pointer_source_values(row)]),
            }
        )


def add_global_scan_exclusions(
    builder: UnifiedBuilder,
    payload: dict[str, Any] | None,
) -> None:
    if payload is None:
        return
    candidates = [row for row in as_list(payload.get("candidates")) if isinstance(row, dict)]
    known_targets = set(builder.canonical_by_target)
    for row in sorted(candidates, key=file_offset_of):
        offset = file_offset_of(row)
        if offset in known_targets:
            continue
        candidate_id = f"GGA-CANDIDATE-{offset:08X}"
        pointer_sources = [
            parse_hex(value, field=f"{candidate_id}.pointer_source")
            for value in as_list(row.get("pointer_sources_file"))
        ]
        builder.add_exclusion(
            {
                "exclusion_id": candidate_id,
                "source_scope": "global_pointer_scan",
                "scope_status": "excluded_unproven",
                "reason": "strict_token_candidate_without_proven_producer_renderer_owner",
                "record_id": candidate_id,
                "alias_of": "",
                "target_file_offset": hex32(offset),
                "target_address": hex32(ROM_BASE + offset),
                "original_raw_sha256": raw_sha_of(row),
                "raw_hex": raw_hex_of(row),
                "source_text": str(row.get("decoded_text_seed", source_text_of(row))),
                "unresolved_slots": unresolved_slots_of(row),
                "region": str(row.get("region", "")),
                "pointer_xref_count": int(row.get("pointer_xref_count", 0)),
                "aligned_u32_xref_count": int(row.get("aligned_u32_xref_count", 0)),
                "pointer_source_count": len(pointer_sources),
                "pointer_sources_digest": digest([hex32(value) for value in pointer_sources]),
            }
        )


def finalize(builder: UnifiedBuilder, input_descriptors: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    records = sorted(
        builder.records,
        key=lambda row: (
            {"production": 0, "scenario_main": 1, "scenario_dynamic": 2, "non_scenario_ui": 3}.get(row["source_scope"], 9),
            parse_hex(row["target_file_offset"]),
            row["record_id"],
        ),
    )
    owners = sorted(builder.owner_by_id.values(), key=lambda row: row["owner_id"])
    exclusions = sorted(builder.exclusions, key=lambda row: (parse_hex(row["target_file_offset"]), row["exclusion_id"]))

    record_identity_rows = [
        {
            "record_id": row["record_id"],
            "source_scope": row["source_scope"],
            "scope_status": row["scope_status"],
            "alias_of": row["alias_of"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
            "container_id": row["container_id"],
            "translation_unit_id": row["translation_unit_id"],
            "owner_digest": row["owner_digest"],
        }
        for row in records
    ]
    owner_identity_rows = [
        {
            "owner_id": owner["owner_id"],
            "owner_kind": owner["owner_kind"],
            "source_file_offset": owner["source_file_offset"],
            "pointer_width": owner["pointer_width"],
            "target_record_ids": owner["target_record_ids"],
            "target_container_ids": owner["target_container_ids"],
            "relocation_schemas": owner["relocation_schemas"],
        }
        for owner in owners
    ]
    exclusion_identity_rows = [
        {
            "exclusion_id": row["exclusion_id"],
            "scope_status": row["scope_status"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
            "reason": row["reason"],
        }
        for row in exclusions
    ]
    record_identity_sha = digest(record_identity_rows)
    owner_identity_sha = digest(owner_identity_rows)
    exclusion_identity_sha = digest(exclusion_identity_rows)
    manifest_identity_sha = digest(
        {
            "rom_sha256": source["sha256"],
            "record_identity_sha256": record_identity_sha,
            "owner_identity_sha256": owner_identity_sha,
            "exclusion_identity_sha256": exclusion_identity_sha,
        }
    )

    canonical_records = [row for row in records if row["scope_status"] == "included"]
    aliases = [row for row in records if row["scope_status"] == "alias"]
    unique_targets = {parse_hex(row["target_file_offset"]) for row in records}
    summary = {
        "records_total": len(records),
        "canonical_records": len(canonical_records),
        "alias_records": len(aliases),
        "unique_target_count": len(unique_targets),
        "owner_count": len(owners),
        "u32_owner_count": sum(owner["owner_kind"] == "u32_pointer" for owner in owners),
        "relative_u16_owner_count": sum(owner["owner_kind"] == "relative_u16_entry" for owner in owners),
        "exclusion_count": len(exclusions),
        "source_scope_counts": dict(sorted(builder.source_counts.items())),
        "scope_status_counts": dict(sorted(builder.scope_counts.items())),
        "translation_status_counts": dict(sorted(builder.status_counts.items())),
        "storage_contract_counts": dict(
            sorted(Counter(str(row["storage_contract"]) for row in records).items())
        ),
        "context_bundle_count": len({row["context_bundle_id"] for row in records}),
        "translation_unit_count": len({row["translation_unit_id"] for row in canonical_records}),
        "exclusion_scope_counts": dict(
            sorted(Counter(str(row["source_scope"]) for row in exclusions).items())
        ),
    }
    return {
        "schema_version": 1,
        "scope": "G Generation Advance unified immutable translation source",
        "source": source,
        "inputs": input_descriptors,
        "identity": {
            "manifest_identity_sha256": manifest_identity_sha,
            "record_identity_sha256": record_identity_sha,
            "owner_identity_sha256": owner_identity_sha,
            "exclusion_identity_sha256": exclusion_identity_sha,
        },
        "summary": summary,
        "schema_fields": [
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
            "source_decode_status",
            "source_unresolved_slots",
            "semantic_category",
            "source_families",
            "source_types",
            "storage_contract",
            "relocation_schema",
            "pointer_group",
            "container_id",
            "translation_unit_id",
            "context_bundle_id",
            "screen_class",
            "control_signature",
            "segments",
            "owner_ids",
            "owner_digest",
            "source_fingerprint",
            "baseline_translation_ko",
            "baseline_translation_status",
            "translation_policy",
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
        ],
        "owner_schema_fields": [
            "owner_id",
            "owner_kind",
            "source_file_offset",
            "pointer_width",
            "target_record_ids",
            "target_container_ids",
            "relocation_schemas",
            "source_types",
            "families",
            "synthetic",
        ],
        "records": records,
        "owners": owners,
        "exclusions": exclusions,
    }


def build_report(
    rom_path: Path,
    production_path: Path,
    scenario_path: Path,
    alignment_path: Path,
    ui_path: Path,
    scan_audit_path: Path | None,
) -> dict[str, Any]:
    try:
        rom = rom_path.read_bytes()
    except OSError as exc:
        fail(f"cannot read ROM {rom_path}: {exc}")
    rom_sha = sha256_bytes(rom)
    production = load_json(production_path)
    scenario = load_json(scenario_path)
    alignment = load_json(alignment_path)
    ui = load_json(ui_path)
    scan_audit = load_json(scan_audit_path) if scan_audit_path is not None else None

    input_payloads = {
        "production_master": production,
        "scenario_event": scenario,
        "non_scenario_ui_expansion": ui,
    }
    if scan_audit is not None:
        input_payloads["non_scenario_scan_audit"] = scan_audit
    for label, payload in input_payloads.items():
        check(source_sha(payload, label) == rom_sha, f"{label} ROM SHA mismatch")

    builder = UnifiedBuilder(rom_sha)
    normalize_production(builder, production)
    normalize_scenario_main(builder, scenario)
    normalize_dynamic_aliases(builder, scenario, production, alignment)
    normalize_ui_expansion(builder, ui)
    add_global_scan_exclusions(builder, scan_audit)

    # Every alias must resolve to a canonical record.  This is deliberately a
    # final gate because aliases are assembled by three independent inputs.
    for row in builder.records:
        if row["scope_status"] == "alias":
            target = row.get("alias_of", "")
            check(target in builder.record_by_id, f"alias target missing: {row['record_id']} -> {target}")
            check(builder.record_by_id[target]["scope_status"] == "included", f"alias target is not canonical: {target}")

    source = {
        "file": rom_path.name,
        "size": len(rom),
        "sha256": rom_sha,
    }
    descriptors = {
        "production_master": report_source_descriptor(production_path, production),
        "scenario_event": report_source_descriptor(scenario_path, scenario),
        "scenario_alignment": {
            "file": alignment_path.name,
            "file_sha256": sha256_file(alignment_path),
            "report_schema_version": alignment.get("schema_version"),
            "dynamic_count": alignment.get("dynamic_count"),
            "weapon_count": alignment.get("weapon_count"),
            "fully_aligned_count": len(as_list(alignment.get("fully_aligned_indices"))),
            "conflict_count": alignment.get("conflict_count"),
        },
        "non_scenario_ui_expansion": report_source_descriptor(ui_path, ui),
    }
    if scan_audit_path is not None and scan_audit is not None:
        descriptors["non_scenario_scan_audit"] = report_source_descriptor(scan_audit_path, scan_audit)
    report = finalize(builder, descriptors, source)
    report["coverage"] = {
        "production_records": len(as_list(production.get("records"))),
        "scenario_main_records": len(as_list(scenario.get("main", {}).get("records"))),
        "scenario_dynamic_aliases": len(as_list(scenario.get("dynamic", {}).get("records"))),
        "ui_owner_proven_rendered": sum(
            str(row.get("promotion_tier", "")) == "owner_proven_rendered"
            for row in as_list(ui.get("records"))
            if isinstance(row, dict)
        ),
        "ui_review_only": sum(
            str(row.get("promotion_tier", "")) != "owner_proven_rendered"
            for row in as_list(ui.get("records"))
            if isinstance(row, dict)
        ),
        "global_scan_candidates": len(as_list(scan_audit.get("candidates"))) if scan_audit else 0,
        "global_scan_candidates_excluded": sum(
            row.get("source_scope") == "global_pointer_scan" for row in report["exclusions"]
        ),
        "known_target_policy": "only owner-proven rendered records are canonical; aliases and unproven candidates are never independently translated",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--production", type=Path, default=DEFAULT_PRODUCTION)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT)
    parser.add_argument("--ui-expansion", type=Path, default=DEFAULT_UI_EXPANSION)
    parser.add_argument("--scan-audit", type=Path, default=DEFAULT_SCAN_AUDIT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-scan-audit", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    scan_path = None if args.no_scan_audit else args.scan_audit
    report = build_report(
        args.rom,
        args.production,
        args.scenario,
        args.alignment,
        args.ui_expansion,
        scan_path,
    )
    if not args.summary_only:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    visible = {
        "result": "PASS",
        "output": str(args.out),
        "source": report["source"],
        "identity": report["identity"],
        "summary": report["summary"],
        "coverage": report["coverage"],
    }
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
