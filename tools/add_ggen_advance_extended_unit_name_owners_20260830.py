#!/usr/bin/env python3
"""Promote the verified extended entity-name map into the active source.

The first 512 entries of the entity-name map were already represented by the
unified translation source.  Entries 512..617 are a separate, owner-proven
bank used by the unit catalogue.  This tool reads the audit table produced
from the Japanese ROM, validates every map/record/pointer relationship again,
then adds one canonical workbook record per unique <07FC> stream.

Existing canonical unit-name translations are reused exactly.  Rows whose
canonical counterpart is still pending remain pending; this tool never
invents a translation for an unresolved source glyph.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROM_BASE = 0x08000000
ROM_PATH = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MERGED_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
TRANSLATION_MANIFEST_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_manifest.json"
AUDIT_PATH = ROOT / "analysis" / "ggen_advance_unit_name_tail_audit_20260830.md"

ENTITY_MAP_START = 0x001A4298
ENTITY_MAP_FIRST_EXTENDED_ID = 512
ENTITY_MAP_LAST_EXTENDED_ID = 617
ENTITY_RECORD_BASE = 0x0018E2E4
ENTITY_RECORD_STRIDE = 0xAC
ENTITY_NAME_POINTER_OFFSET = 0x04

RESERVED_SLOTS = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
LEADING_RESERVED_RE = re.compile(r"^<([0-9A-Fa-f]{4})>")
NUMERIC_MARKER_RE = re.compile(r"<([0-9A-Fa-f]{4})>")
HEX_OFFSET_RE = re.compile(r"^0x[0-9A-Fa-f]+$")
BATCH_ID = "extended-unit-name-owners-20260830"


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hex32(value: int) -> str:
    return f"0x{value:08X}"


def parse_hex(value: Any, field: str) -> int:
    text = str(value).strip()
    check(bool(HEX_OFFSET_RE.fullmatch(text)), f"{field} is not a hexadecimal offset: {value!r}")
    return int(text, 16)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read JSON {path}: {exc}")
    check(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def leading_reserved_body(value: str) -> str:
    result = value
    while True:
        match = LEADING_RESERVED_RE.match(result)
        if not match or int(match.group(1), 16) not in RESERVED_SLOTS:
            return result
        result = result[match.end() :]


def parse_audit_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "map ID(s)" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not HEX_OFFSET_RE.fullmatch(cells[2]):
            continue
        map_ids = [int(value) for value in re.findall(r"\d+", cells[0])]
        record_indices = [int(value) for value in re.findall(r"\d+", cells[1])]
        canonical_ids = re.findall(r"GGA-TEXT-[0-9A-F]+", cells[5])
        check(map_ids and record_indices and canonical_ids, f"malformed audit row: {line}")
        rows.append(
            {
                "map_ids": map_ids,
                "record_indices": record_indices,
                "target_file_offset": int(cells[2], 16),
                "source_body": cells[3],
                "reported_translation": "" if cells[4].lower() == "pending" else cells[4],
                "canonical_ids": canonical_ids,
            }
        )
    rows.sort(key=lambda row: row["target_file_offset"])
    check(len(rows) == 85, f"extended unit-name audit row count drift: {len(rows)}")
    check(len({row["target_file_offset"] for row in rows}) == 85, "extended unit-name target offsets are not unique")
    check(sum(len(row["map_ids"]) for row in rows) == 92, "extended unit-name valid map-reference count drift")
    check(sum(len(row["record_indices"]) for row in rows) == 92, "extended entity-record count drift")
    return rows


def raw_stream(rom: bytes, offset: int) -> bytes:
    check(0 <= offset < len(rom), f"stream offset outside ROM: 0x{offset:08X}")
    end = rom.find(b"\x00", offset)
    check(end >= offset, f"unterminated extended unit-name stream: 0x{offset:08X}")
    value = rom[offset : end + 1]
    check(value.startswith(b"\xE7\x1C"), f"extended stream lacks <07FC> prefix: 0x{offset:08X}")
    return value


def identity_rows(
    payload: dict[str, Any],
    *,
    include_map_script: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    records = [
        row
        for row in payload["records"]
        if include_map_script or row.get("source_scope") != "scenario_map_script"
    ]
    owners = [
        owner
        for owner in payload["owners"]
        if include_map_script or "map_event_script_inline" not in (owner.get("families") or [])
    ]
    exclusions = payload["exclusions"]
    return (
        [
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
        ],
        [
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
        ],
        [
            {
                "exclusion_id": row["exclusion_id"],
                "scope_status": row["scope_status"],
                "target_file_offset": row["target_file_offset"],
                "original_raw_sha256": row["original_raw_sha256"],
                "reason": row["reason"],
            }
            for row in exclusions
        ],
    )


def translation_payload_digest(row: dict[str, Any]) -> str:
    return digest(
        {
            "record_id": row["record_id"],
            "batch_id": row["overlay_batch_id"],
            "translation_ko": row["translation_ko"],
            "translation_segments": row.get("translation_segments"),
            "translation_status": row["translation_status"],
            "translation_source": row["translation_source"],
            "source_model": row["source_model"],
            "prompt_version": row["prompt_version"],
            "review_status": row["review_status"],
            "review_count": row["review_count"],
            "reviewed_at": row["reviewed_at"],
            "translator_notes": row["translator_notes"],
            "qa_status": row["qa_status"],
        }
    )


def find_counterpart(records: list[dict[str, Any]], audit_row: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(row.get("record_id")): row for row in records}
    candidates = [by_id[record_id] for record_id in audit_row["canonical_ids"] if record_id in by_id]
    candidates = [
        row
        for row in candidates
        if row.get("source_scope") == "production"
        and row.get("scope_status") == "included"
        and row.get("semantic_category") == "unit_name"
    ]
    check(candidates, f"no canonical unit-name counterpart for {audit_row['source_body']!r}")
    candidates.sort(
        key=lambda row: (
            0 if str(row.get("translation_status")) == "translated" and str(row.get("translation_ko") or "").strip() else 1,
            parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset"),
            str(row["record_id"]),
        )
    )
    return candidates[0]


def build_new_record(
    *,
    source: dict[str, Any],
    counterpart: dict[str, Any],
    row: dict[str, Any],
    raw: bytes,
    owner_ids: list[str],
) -> dict[str, Any]:
    offset = int(row["target_file_offset"])
    record_id = f"GGA-UI-EXT-{offset:08X}"
    # Keep the canonical source spelling (including unresolved numeric slots)
    # so raw-byte provenance remains exact.  The audit table may display a
    # supplemental human-readable glyph, e.g. ヘ for source slot 0x0126.
    source_body = leading_reserved_body(str(counterpart.get("source_text") or ""))
    source_text = f"<07FC>{source_body}"
    unresolved = sorted(
        {f"0x{int(value, 16):04X}" for value in NUMERIC_MARKER_RE.findall(source_text)},
        key=lambda value: int(value, 16),
    )
    reserved = [value for value in unresolved if int(value, 16) in RESERVED_SLOTS]
    translated = bool(str(counterpart.get("translation_ko") or "").strip()) and str(counterpart.get("translation_status")) == "translated"
    reported_translation = str(row["reported_translation"] or "")
    if reported_translation:
        check(translated, f"audit says translated but counterpart is pending: {row['source_body']}")
        check(str(counterpart.get("translation_ko") or "") == reported_translation, f"counterpart translation drift for {row['source_body']}")
    else:
        check(not translated, f"audit says pending but counterpart has translation: {row['source_body']}")

    result = copy.deepcopy(counterpart)
    result.update(
        {
            "record_id": record_id,
            "source_scope": "non_scenario_ui",
            "scope_status": "included",
            "record_kind": "extended_entity_name_text_stream",
            "alias_of": "",
            "target_file_offset": hex32(offset),
            "target_address": hex32(ROM_BASE + offset),
            "original_raw_sha256": sha256_bytes(raw),
            "raw_hex": raw.hex(" ").upper(),
            "original_byte_length": len(raw),
            "source_text": source_text,
            "source_decode_status": "partial" if unresolved else "complete",
            "source_unresolved_slots": unresolved,
            "semantic_category": "unit_name",
            "source_families": ["entity_name_by_extended_id_map"],
            "source_types": ["entity_record_name_pointer"],
            "storage_contract": "nul_stream",
            "relocation_schema": "ordinary_u32_stream",
            "pointer_group": "extended_entity_name_u32_owners",
            "container_id": record_id,
            "translation_unit_id": record_id,
            "context_bundle_id": record_id,
            "screen_class": "production_text",
            "control_signature": [],
            "segments": [],
            "translation_policy": "translate",
            "translation_ko": str(counterpart.get("translation_ko") or "") if translated else "",
            "translation_status": "translated" if translated else "pending",
            "translation_source": str(counterpart.get("translation_source") or "") if translated else "",
            "source_model": str(counterpart.get("source_model") or "") if translated else "",
            "prompt_version": str(counterpart.get("prompt_version") or "") if translated else "",
            "review_status": str(counterpart.get("review_status") or "draft") if translated else "pending",
            "review_count": int(counterpart.get("review_count") or 0) if translated else 0,
            "reviewed_at": str(counterpart.get("reviewed_at") or "") if translated else "",
            "translator_notes": (
                f"reused canonical unit-name counterpart {counterpart['record_id']}; "
                f"owner-proven extended entity-name map IDs {', '.join(str(value) for value in row['map_ids'])}; "
                "preserved leading reserved source marker <07FC>"
                if translated
                else (
                    f"owner-proven extended entity-name map IDs {', '.join(str(value) for value in row['map_ids'])}; "
                    "translation remains pending because the canonical counterpart has unresolved source glyphs"
                )
            ),
            "qa_status": "not_checked",
            "source_record_id": record_id,
            "line_index": None,
            "source_reserved_slots": reserved,
            "baseline_translator_notes": str(counterpart.get("baseline_translator_notes") or ""),
            "pointer_recalc_required": True,
            "owner_ids": sorted(owner_ids),
            "owner_count": len(owner_ids),
            "overlay_batch_id": BATCH_ID,
        }
    )
    result["owner_digest"] = digest(result["owner_ids"])
    result["source_fingerprint"] = digest(
        {
            "rom_sha256": source["sha256"],
            "record_id": record_id,
            "target_file_offset": result["target_file_offset"],
            "original_raw_sha256": result["original_raw_sha256"],
            "container_id": record_id,
            "translation_unit_id": record_id,
            "owner_digest": result["owner_digest"],
        }
    )
    result["translation_payload_sha256"] = translation_payload_digest(result)
    result["extended_entity_map_ids"] = list(row["map_ids"])
    result["extended_entity_record_indices"] = list(row["record_indices"])
    result["canonical_counterpart_record_ids"] = list(row["canonical_ids"])
    return result


def update_summary(payload: dict[str, Any], *, added_translated: int, added_pending: int, added_owners: int) -> None:
    records = payload["records"]
    owners = payload["owners"]
    exclusions = payload["exclusions"]
    summary = payload["summary"]
    scope_counts = Counter(str(row["source_scope"]) for row in records)
    scope_status_counts = Counter(str(row["scope_status"]) for row in records)
    storage_counts = Counter(str(row["storage_contract"]) for row in records)
    summary.update(
        {
            "records_total": len(records),
            "canonical_records": sum(row["scope_status"] == "included" for row in records),
            "alias_records": sum(row["scope_status"] == "alias" for row in records),
            "unique_target_count": len({row["target_file_offset"] for row in records}),
            "owner_count": len(owners),
            "u32_owner_count": sum(owner["owner_kind"] == "u32_pointer" for owner in owners),
            "relative_u16_owner_count": sum(owner["owner_kind"] == "relative_u16_entry" for owner in owners),
            "exclusion_count": len(exclusions),
            "source_scope_counts": dict(sorted(scope_counts.items())),
            "scope_status_counts": dict(sorted(scope_status_counts.items())),
            "storage_contract_counts": dict(sorted(storage_counts.items())),
            "context_bundle_count": len({row["context_bundle_id"] for row in records}),
            "translation_unit_count": len({row["translation_unit_id"] for row in records if row["scope_status"] == "included"}),
            "exclusion_scope_counts": dict(sorted(Counter(str(row["source_scope"]) for row in exclusions).items())),
            "extended_unit_name_tail_records": 85,
            "extended_unit_name_tail_owners": added_owners,
            "extended_unit_name_tail_translated": added_translated,
            "extended_unit_name_tail_pending": added_pending,
        }
    )

    # These two groups intentionally retain their pre/post-merge meanings in
    # the existing manifest: translation_status_counts is the source snapshot,
    # while merged_translation_status_counts is the active overlay result.
    source_counts = dict(summary.get("translation_status_counts", {}))
    source_counts["pending"] = int(source_counts.get("pending", 0)) + 85
    summary["translation_status_counts"] = dict(sorted(source_counts.items()))
    merged_counts = Counter(str(row["translation_status"]) for row in records)
    summary["merged_translation_status_counts"] = dict(sorted(merged_counts.items()))
    payload["merged_translation_status_counts"] = dict(sorted(merged_counts.items()))
    merged_review_counts = Counter(str(row["review_status"]) for row in records)
    summary["merged_review_status_counts"] = dict(sorted(merged_review_counts.items()))
    summary["translated_canonical_records"] = sum(
        row["scope_status"] == "included" and row["translation_policy"] == "translate" and row["translation_status"] == "translated"
        for row in records
    )
    summary["untranslated_canonical_records"] = sum(
        row["scope_status"] == "included" and row["translation_policy"] == "translate" and row["translation_status"] != "translated"
        for row in records
    )
    summary["untranslated_translate_policy_records"] = summary["untranslated_canonical_records"]


def update_translation_manifest(payload: dict[str, Any]) -> None:
    manifest = read_json(TRANSLATION_MANIFEST_PATH)
    merged_counts = dict(payload["merged_translation_status_counts"])
    manifest.update(
        {
            "sha256": sha256_bytes(MERGED_PATH.read_bytes()),
            "source_sha256": sha256_bytes(MERGED_PATH.read_bytes()),
            "record_count": len(payload["records"]),
            "record_identity_sha256": payload["identity"]["record_identity_sha256"],
            "translation_overlay_identity_sha256": payload["identity"].get("translation_overlay_identity_sha256"),
            "record_translation_status_counts": merged_counts,
            "source_summary_translation_status_counts": merged_counts,
        }
    )
    TRANSLATION_MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    rom = ROM_PATH.read_bytes()
    payload = read_json(MERGED_PATH)
    audit_rows = parse_audit_rows(AUDIT_PATH)
    check(len(rom) == 16 * 1024 * 1024, "Japanese ROM size drift")
    check(payload["source"]["sha256"].lower() == sha256_bytes(rom), "merged source ROM SHA drift")

    # The active merged JSON carries the map-script corpus as a later
    # extension.  Its identity has its own fields, so the primary record and
    # owner identities intentionally cover the pre-map-script corpus only.
    old_record_identity, old_owner_identity, old_exclusion_identity = identity_rows(payload, include_map_script=False)
    check(payload["identity"]["record_identity_sha256"] == digest(old_record_identity), "existing record identity drift")
    check(payload["identity"]["owner_identity_sha256"] == digest(old_owner_identity), "existing owner identity drift")
    check(payload["identity"]["exclusion_identity_sha256"] == digest(old_exclusion_identity), "existing exclusion identity drift")

    records: list[dict[str, Any]] = payload["records"]
    owners: list[dict[str, Any]] = payload["owners"]
    existing_record_ids = {str(row["record_id"]) for row in records}
    existing_offsets = {parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset") for row in records}
    existing_owner_ids = {str(owner["owner_id"]) for owner in owners}
    first_ui = next((index for index, row in enumerate(records) if row.get("source_scope") == "non_scenario_ui"), len(records))

    new_records: list[dict[str, Any]] = []
    new_owners: list[dict[str, Any]] = []
    seen_map_ids: set[int] = set()
    seen_record_indices: set[int] = set()
    for item in audit_rows:
        offset = int(item["target_file_offset"])
        check(offset not in existing_offsets, f"extended target already exists in merged source: 0x{offset:08X}")
        for map_id, record_index in zip(item["map_ids"], item["record_indices"]):
            check(ENTITY_MAP_FIRST_EXTENDED_ID <= map_id <= ENTITY_MAP_LAST_EXTENDED_ID, f"map ID outside extension: {map_id}")
            mapped = struct.unpack_from("<H", rom, ENTITY_MAP_START + map_id * 2)[0]
            check(mapped == record_index, f"entity map mismatch at ID {map_id}: {mapped} vs {record_index}")
            check(record_index not in seen_record_indices, f"duplicate extended entity record index: {record_index}")
            seen_map_ids.add(map_id)
            seen_record_indices.add(record_index)
        owner_ids: list[str] = []
        for record_index in item["record_indices"]:
            owner_offset = ENTITY_RECORD_BASE + record_index * ENTITY_RECORD_STRIDE + ENTITY_NAME_POINTER_OFFSET
            pointer_value = struct.unpack_from("<I", rom, owner_offset)[0]
            check(pointer_value == ROM_BASE + offset, f"entity name pointer mismatch at 0x{owner_offset:08X}")
            owner_id = f"OWNER-U32-{owner_offset:08X}"
            check(owner_id not in existing_owner_ids, f"extended owner already exists: {owner_id}")
            owner_ids.append(owner_id)
            new_owners.append(
                {
                    "owner_id": owner_id,
                    "owner_kind": "u32_pointer",
                    "source_file_offset": hex32(owner_offset),
                    "pointer_width": 4,
                    "target_record_ids": [f"GGA-UI-EXT-{offset:08X}"],
                    "target_container_ids": [f"GGA-UI-EXT-{offset:08X}"],
                    "relocation_schemas": ["ordinary_u32_stream"],
                    "source_types": ["entity_record_name_pointer"],
                    "families": ["entity_name_by_extended_id_map"],
                    "synthetic": False,
                }
            )
        raw = raw_stream(rom, offset)
        counterpart = find_counterpart(records, item)
        new_record = build_new_record(source=payload["source"], counterpart=counterpart, row=item, raw=raw, owner_ids=owner_ids)
        check(new_record["record_id"] not in existing_record_ids, f"extended record already exists: {new_record['record_id']}")
        new_records.append(new_record)

    check(len(seen_map_ids) == 92, f"valid extended map ID count drift: {len(seen_map_ids)}")
    check(len(seen_record_indices) == 92, f"unique extended entity record count drift: {len(seen_record_indices)}")
    check(len(new_owners) == 92, f"new owner count drift: {len(new_owners)}")
    check(len({owner["owner_id"] for owner in new_owners}) == 92, "new owner IDs are not unique")

    translated_count = sum(row["translation_status"] == "translated" for row in new_records)
    pending_count = sum(row["translation_status"] == "pending" for row in new_records)
    check((translated_count, pending_count) == (83, 2), f"extended translation status drift: translated={translated_count}, pending={pending_count}")

    payload["records"] = records[:first_ui] + new_records + records[first_ui:]
    payload["owners"] = sorted(owners + new_owners, key=lambda owner: owner["owner_id"])

    new_record_identity, new_owner_identity, exclusion_identity = identity_rows(payload, include_map_script=False)
    new_record_identity_sha = digest(new_record_identity)
    new_owner_identity_sha = digest(new_owner_identity)
    exclusion_identity_sha = digest(exclusion_identity)
    payload["identity"]["record_identity_sha256"] = new_record_identity_sha
    payload["identity"]["owner_identity_sha256"] = new_owner_identity_sha
    payload["identity"]["exclusion_identity_sha256"] = exclusion_identity_sha
    payload["identity"]["manifest_identity_sha256"] = digest(
        {
            "rom_sha256": payload["source"]["sha256"],
            "record_identity_sha256": new_record_identity_sha,
            "owner_identity_sha256": new_owner_identity_sha,
            "exclusion_identity_sha256": exclusion_identity_sha,
        }
    )

    extension_rows = [
        {
            "record_id": row["record_id"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
            "owner_ids": row["owner_ids"],
            "translation_status": row["translation_status"],
            "translation_ko": row["translation_ko"],
        }
        for row in new_records
    ]
    payload["extended_unit_name_tail"] = {
        "schema_version": 1,
        "batch_id": BATCH_ID,
        "map_id_range": [ENTITY_MAP_FIRST_EXTENDED_ID, ENTITY_MAP_LAST_EXTENDED_ID],
        "map_file_range": [hex32(ENTITY_MAP_START + ENTITY_MAP_FIRST_EXTENDED_ID * 2), hex32(ENTITY_MAP_START + (ENTITY_MAP_LAST_EXTENDED_ID + 1) * 2 - 1)],
        "entity_record_pointer_field": {
            "base": hex32(ENTITY_RECORD_BASE),
            "stride": hex32(ENTITY_RECORD_STRIDE),
            "field_offset": hex32(ENTITY_NAME_POINTER_OFFSET),
        },
        "record_count": len(new_records),
        "valid_map_reference_count": len(seen_map_ids),
        "zero_map_reference_count": (ENTITY_MAP_LAST_EXTENDED_ID - ENTITY_MAP_FIRST_EXTENDED_ID + 1) - len(seen_map_ids),
        "owner_count": len(new_owners),
        "translated_count": translated_count,
        "pending_count": pending_count,
        "extension_identity_sha256": digest(extension_rows),
        "audit_source": str(AUDIT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "rom_write_policy": "translated rows are relocated by the unified ROM builder; pending rows retain the Japanese pointer",
    }
    payload.setdefault("coverage", {})["extended_unit_name_tail_records"] = len(new_records)
    payload["coverage"]["extended_unit_name_tail_owner_count"] = len(new_owners)
    payload["coverage"]["extended_unit_name_tail_source"] = "entity-name map IDs 512..617"
    update_summary(payload, added_translated=translated_count, added_pending=pending_count, added_owners=len(new_owners))

    MERGED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(payload)
    print(
        json.dumps(
            {
                "result": "PASS",
                "records_added": len(new_records),
                "translated_added": translated_count,
                "pending_added": pending_count,
                "owners_added": len(new_owners),
                "record_identity_sha256": payload["identity"]["record_identity_sha256"],
                "owner_identity_sha256": payload["identity"]["owner_identity_sha256"],
                "merged_json": str(MERGED_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
