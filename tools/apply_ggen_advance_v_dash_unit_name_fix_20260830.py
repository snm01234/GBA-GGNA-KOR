#!/usr/bin/env python3
"""Apply the user-confirmed V-dash Gundam unit-name correction.

The Japanese ROM stores the same unresolved ``V<07E8>ガンダム`` name in
two original 512-entry name-map streams and one owner-proven extended name
stream.  This follow-up updates all three derived translation rows together,
keeps the source/owner identity intact, and records a chained correction
identity for the workbook and ROM patch steps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MERGED_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
TRANSLATION_MANIFEST_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_manifest.json"
DEFAULT_OUTPUT = MERGED_PATH
DEFAULT_REPORT = ROOT / "analysis" / "ggen_advance_v_dash_unit_name_fix_20260830.json"
BATCH_ID = "user-confirmed-v-dash-unit-name-20260830"
TARGET_RECORD_IDS = (
    "GGA-TEXT-0017A4AB",
    "GGA-TEXT-0017AB31",
    "GGA-UI-EXT-0017B1C1",
)
TARGET_BODY = "V<07E8>ガンダム"
RESERVED_SLOTS = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
LEADING_RESERVED_RE = re.compile(r"^<([0-9A-Fa-f]{4})>")


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


def leading_reserved_body(value: str) -> str:
    result = value
    while True:
        match = LEADING_RESERVED_RE.match(result)
        if not match or int(match.group(1), 16) not in RESERVED_SLOTS:
            return result
        result = result[match.end() :]


def translation_payload_digest(row: dict[str, Any]) -> str:
    return digest(
        {
            "record_id": row["record_id"],
            "batch_id": row["overlay_batch_id"],
            "translation_ko": row.get("translation_ko") or "",
            "translation_segments": row.get("translation_segments"),
            "translation_status": row.get("translation_status") or "",
            "translation_source": row.get("translation_source") or "",
            "source_model": row.get("source_model") or "",
            "prompt_version": row.get("prompt_version") or "",
            "review_status": row.get("review_status") or "",
            "review_count": row.get("review_count") or 0,
            "reviewed_at": row.get("reviewed_at") or "",
            "translator_notes": row.get("translator_notes") or "",
            "qa_status": row.get("qa_status") or "",
        }
    )


def update_extension_summary(payload: dict[str, Any]) -> None:
    rows = [row for row in payload.get("records", []) if str(row.get("record_id", "")).startswith("GGA-UI-EXT-")]
    check(len(rows) == 85, f"extended unit-name row count drift: {len(rows)}")
    extension_rows = [
        {
            "record_id": row["record_id"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
            "owner_ids": row["owner_ids"],
            "translation_status": row["translation_status"],
            "translation_ko": row.get("translation_ko", ""),
        }
        for row in rows
    ]
    tail = payload.setdefault("extended_unit_name_tail", {})
    tail["translated_count"] = sum(row.get("translation_status") == "translated" for row in rows)
    tail["pending_count"] = sum(row.get("translation_status") != "translated" for row in rows)
    tail["extension_identity_sha256"] = digest(extension_rows)


def update_summary(payload: dict[str, Any], correction_identity: str) -> None:
    records = payload.get("records", [])
    summary = payload.setdefault("summary", {})
    merged_statuses = Counter(str(row.get("translation_status", "")) for row in records)
    merged_review_statuses = Counter(str(row.get("review_status", "")) for row in records)
    translated_canonical = [
        row
        for row in records
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and str(row.get("translation_status")) == "translated"
    ]
    untranslated_canonical = [
        row
        for row in records
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and str(row.get("translation_status")) != "translated"
    ]
    summary.update(
        {
            "merged_translation_status_counts": dict(sorted(merged_statuses.items())),
            "merged_review_status_counts": dict(sorted(merged_review_statuses.items())),
            "translated_canonical_records": len(translated_canonical),
            "untranslated_canonical_records": len(untranslated_canonical),
            "untranslated_translate_policy_records": len(untranslated_canonical),
            "translation_overlay_identity_sha256": correction_identity,
            "v_dash_unit_name_correction_records": 3,
        }
    )
    payload["merged_translation_status_counts"] = dict(sorted(merged_statuses.items()))


def update_translation_manifest(payload: dict[str, Any], output_path: Path) -> None:
    if output_path.resolve() != MERGED_PATH.resolve():
        return
    manifest = json.loads(TRANSLATION_MANIFEST_PATH.read_text(encoding="utf-8"))
    merged_counts = dict(payload["merged_translation_status_counts"])
    merged_sha = sha256_bytes(output_path.read_bytes())
    manifest.update(
        {
            "sha256": merged_sha,
            "source_sha256": merged_sha,
            "record_count": len(payload.get("records", [])),
            "record_identity_sha256": payload.get("identity", {}).get("record_identity_sha256"),
            "translation_overlay_identity_sha256": payload.get("identity", {}).get("translation_overlay_identity_sha256"),
            "record_translation_status_counts": merged_counts,
            "source_summary_translation_status_counts": merged_counts,
        }
    )
    TRANSLATION_MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=MERGED_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    payload = json.loads(args.source.read_text(encoding="utf-8"))
    records = payload.get("records")
    check(isinstance(records, list), "merged records are not a list")
    by_id = {str(row.get("record_id")): row for row in records}
    check(len(by_id) == len(records), "duplicate record IDs in merged source")

    table_rows = [
        row
        for row in records
        if row.get("scope_status") == "included"
        and row.get("semantic_category") == "unit_name"
        and any(str(family).startswith("entity_name_by_") for family in row.get("source_families", []))
    ]
    target_rows = [row for row in table_rows if leading_reserved_body(str(row.get("source_text") or "")) == TARGET_BODY]
    check({row["record_id"] for row in target_rows} == set(TARGET_RECORD_IDS), "V-dash unit-name table target set drift")
    check(len(target_rows) == 3, f"expected three V-dash unit-name table rows, got {len(target_rows)}")
    check(all(str(row.get("translation_status")) == "pending" for row in target_rows), "a V-dash target row is no longer pending")
    check(all(not str(row.get("translation_ko") or "").strip() for row in target_rows), "a V-dash target already has translation content")

    parent_identity = str(payload.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    check(parent_identity, "parent translation overlay identity is missing")
    changes: list[dict[str, Any]] = []
    for record_id in TARGET_RECORD_IDS:
        row = by_id[record_id]
        before = {
            "translation_ko": row.get("translation_ko", ""),
            "translation_status": row.get("translation_status", ""),
            "translation_source": row.get("translation_source", ""),
            "review_status": row.get("review_status", ""),
            "review_count": row.get("review_count", 0),
            "reviewed_at": row.get("reviewed_at", ""),
            "overlay_batch_id": row.get("overlay_batch_id", ""),
        }
        row["translation_ko"] = "V대시 건담"
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified"
        row["source_model"] = ""
        row["prompt_version"] = ""
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-08-30"
        row["overlay_batch_id"] = BATCH_ID
        note = str(row.get("translator_notes") or "").rstrip()
        addition = "user-confirmed unit-name mapping: V<07E8>ガンダム → V대시 건담"
        row["translator_notes"] = f"{note}; {addition}".lstrip("; ")
        row["translation_payload_sha256"] = translation_payload_digest(row)
        changes.append(
            {
                "record_id": record_id,
                "source_scope": row.get("source_scope"),
                "source_text": row.get("source_text"),
                "target_file_offset": row.get("target_file_offset"),
                "owner_ids": row.get("owner_ids", []),
                "before": before,
                "after": {
                    "translation_ko": row["translation_ko"],
                    "translation_status": row["translation_status"],
                    "translation_source": row["translation_source"],
                    "review_status": row["review_status"],
                    "review_count": row["review_count"],
                    "reviewed_at": row["reviewed_at"],
                    "overlay_batch_id": row["overlay_batch_id"],
                },
                "translation_payload_sha256": row["translation_payload_sha256"],
            }
        )

    correction_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [
                {"record_id": item["record_id"], "payload": item["translation_payload_sha256"]}
                for item in changes
            ],
        }
    )
    identity = payload.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["user_confirmed_v_dash_unit_name_identity_sha256"] = correction_identity
    identity["translation_overlay_identity_sha256"] = correction_identity
    update_extension_summary(payload)
    update_summary(payload, correction_identity)
    payload["v_dash_unit_name_correction"] = {
        "batch_id": BATCH_ID,
        "parent_snapshot": args.source.name,
        "changed_records": len(changes),
        "translation": "V<07E8>ガンダム → V대시 건담",
        "identity_sha256": correction_identity,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(payload, args.out)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_v_dash_unit_name_fix",
        "batch_id": BATCH_ID,
        "source_snapshot": str(args.source.relative_to(ROOT)).replace("\\", "/"),
        "output_snapshot": str(args.out.relative_to(ROOT)).replace("\\", "/"),
        "identity_sha256": correction_identity,
        "changed_records": changes,
        "post_update_counts": {
            "unit_name_table_pending_records": sum(
                row.get("translation_status") == "pending" for row in table_rows
            ),
            "unit_name_table_pending_unique_sources": len(
                {
                    leading_reserved_body(str(row.get("source_text") or ""))
                    for row in table_rows
                    if row.get("translation_status") == "pending"
                }
            ),
            "merged_translation_status_counts": payload["merged_translation_status_counts"],
        },
        "output_sha256": sha256_bytes(args.out.read_bytes()),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", **payload["v_dash_unit_name_correction"], "report": str(args.report)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
