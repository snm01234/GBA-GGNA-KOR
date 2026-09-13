#!/usr/bin/env python3
"""Apply the user-verified 女の…声……？ correction to the active translation source."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MERGED = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
MANIFEST = ROOT / "integrated" / "translation" / "ggen_advance_translation_manifest.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260902_yuu_voice.json"
CORRECTION = ROOT / "integrated" / "translation" / "ggen_advance_user_verified_dialogue_corrections_20260902.json"
HISTORICAL_OVERLAY = ROOT / "analysis" / "ggen_advance_translation_overlays" / "map_script_complete_8089_context_repairs.json"
RECORD_ID = "GGA-MAPSCRIPT-00F64189"
BATCH_ID = "user-verified-yuu-voice-20260902"
OLD = "벽의…목소리……？"
NEW = "여자의…목소리……？"
NOTE = "user-verified correction: source is 女の…声……？; 0x03C7 is 女, while 壁 is the separate 0x060D slot"

def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()

def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def payload_digest(row: dict[str, Any]) -> str:
    return digest({
        "record_id": row["record_id"], "batch_id": row["overlay_batch_id"],
        "translation_ko": row["translation_ko"], "translation_segments": row.get("translation_segments"),
        "translation_status": row["translation_status"], "translation_source": row["translation_source"],
        "source_model": row["source_model"], "prompt_version": row["prompt_version"],
        "review_status": row["review_status"], "review_count": row["review_count"],
        "reviewed_at": row["reviewed_at"], "translator_notes": row["translator_notes"],
        "qa_status": row["qa_status"],
    })

def restore_historical_overlay() -> None:
    payload = json.loads(HISTORICAL_OVERLAY.read_text(encoding="utf-8"))
    rows = [row for row in payload["records"] if row.get("record_id") == RECORD_ID]
    if len(rows) != 1:
        raise SystemExit(f"gate failed: historical overlay row count is {len(rows)}")
    row = rows[0]
    if row.get("translation_ko") == NEW:
        row.update({
            "translation_ko": OLD, "translation_segments": [OLD], "review_status": "draft",
            "translation_source": "curated_project_data",
            "translator_notes": "slot-complete map-script 12x12 decode; natural Korean; leftover rows excluded",
        })
        HISTORICAL_OVERLAY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif row.get("translation_ko") != OLD:
        raise SystemExit(f"gate failed: unexpected historical translation {row.get('translation_ko')!r}")

def main() -> int:
    restore_historical_overlay()
    merged = json.loads(MERGED.read_text(encoding="utf-8"))
    rows = [row for row in merged["records"] if row.get("record_id") == RECORD_ID]
    if len(rows) != 1:
        raise SystemExit(f"gate failed: canonical row count is {len(rows)}")
    row = rows[0]
    if row.get("source_text") != "女の…声……？":
        raise SystemExit(f"gate failed: corrected Japanese source drift: {row.get('source_text')!r}")
    if row.get("translation_ko") not in {OLD, NEW}:
        raise SystemExit(f"gate failed: unexpected canonical translation {row.get('translation_ko')!r}")

    already_applied = row.get("overlay_batch_id") == BATCH_ID and row.get("translation_ko") == NEW
    if not already_applied:
        parent_identity = str(merged["identity"].get("translation_overlay_identity_sha256") or "")
        parent_map_identity = str(merged["identity"].get("map_script_translation_overlay_identity_sha256") or "")
        row.update({
            "translation_ko": NEW, "translation_segments": [NEW], "translation_source": "user_verified",
            "review_status": "user_verified", "review_count": int(row.get("review_count") or 0) + 1,
            "reviewed_at": "2026-09-02", "translator_notes": NOTE, "overlay_batch_id": BATCH_ID,
        })
        row["translation_payload_sha256"] = payload_digest(row)
        identity_record = [{"record_id": RECORD_ID, "payload": row["translation_payload_sha256"]}]
        correction_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": identity_record})
        map_identity = digest({"parent": parent_map_identity, "batch_id": BATCH_ID, "records": identity_record})
        merged["identity"].update({
            "parent_translation_overlay_identity_sha256": parent_identity,
            "user_verified_yuu_voice_identity_sha256": correction_identity,
            "translation_overlay_identity_sha256": correction_identity,
            "parent_map_script_translation_overlay_identity_sha256": parent_map_identity,
            "user_verified_yuu_voice_map_identity_sha256": map_identity,
            "map_script_translation_overlay_identity_sha256": map_identity,
        })
        merged["summary"]["translation_overlay_identity_sha256"] = correction_identity
        review_counts = Counter(str(item.get("review_status", "")) for item in merged["records"])
        merged["summary"]["merged_review_status_counts"] = dict(sorted(review_counts.items()))
        correction_payload = {
            "schema_version": 1, "kind": "ggen_advance_translation_overlay", "batch_id": BATCH_ID,
            "source_rom_sha256": merged["source"]["sha256"],
            "manifest_identity_sha256": merged["identity"]["manifest_identity_sha256"],
            "translation_source": "user_verified", "review_status": "user_verified",
            "records": [{
                "record_id": RECORD_ID, "original_raw_sha256": row["original_raw_sha256"],
                "owner_digest": row["owner_digest"], "source_fingerprint": row["source_fingerprint"],
                "target_file_offset": row["target_file_offset"], "translation_unit_id": row["translation_unit_id"],
                "context_bundle_id": row["context_bundle_id"], "translation_ko": NEW,
                "translation_segments": [NEW], "translation_status": "translated",
                "translation_source": "user_verified", "source_model": "", "prompt_version": "",
                "review_status": "user_verified", "review_count": row["review_count"],
                "reviewed_at": row["reviewed_at"], "translator_notes": NOTE, "qa_status": row["qa_status"],
            }],
        }
        CORRECTION.write_text(json.dumps(correction_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        descriptor = {
            "file": CORRECTION.name, "file_sha256": file_sha256(CORRECTION), "batch_id": BATCH_ID,
            "record_count": 1, "record_ids": [RECORD_ID],
        }
        merged["merge"]["overlay_files"] = [item for item in merged["merge"]["overlay_files"] if item.get("batch_id") != BATCH_ID] + [descriptor]
        merged["merge"]["overlay_files"] = sorted(merged["merge"]["overlay_files"], key=lambda item: (item["batch_id"], item["file"]))
        merged["merge"]["batch_count"] = len(merged["merge"]["overlay_files"])
        merged["merge"]["accepted_record_count"] = int(merged["merge"].get("accepted_record_count", 0)) + 1
        merged["merge"]["translation_unit_count"] = int(merged["merge"].get("translation_unit_count", 0)) + 1
        merged["merge"]["translation_overlay_identity_sha256"] = correction_identity
        merged["user_verified_yuu_voice"] = {
            "batch_id": BATCH_ID, "record_id": RECORD_ID, "source_text": "女の…声……？",
            "translation_before": OLD, "translation_after": NEW, "identity_sha256": correction_identity,
        }

    encoded = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    MERGED.write_bytes(encoded)
    SNAPSHOT.write_bytes(encoded)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    merged_sha = hashlib.sha256(encoded).hexdigest()
    manifest.update({
        "sha256": merged_sha, "source_sha256": merged_sha,
        "translation_overlay_identity_sha256": merged["identity"]["translation_overlay_identity_sha256"],
        "record_translation_status_counts": dict(sorted(Counter(str(item.get("translation_status", "")) for item in merged["records"]).items())),
        "source_summary_translation_status_counts": merged["summary"]["merged_translation_status_counts"],
    })
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "record_id": RECORD_ID, "translation": NEW, "merged_sha256": merged_sha}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
