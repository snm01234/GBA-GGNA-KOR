#!/usr/bin/env python3
"""Restore Marker Clan translations that were incorrectly changed to Mirai Yashima.

The correction is deliberately source-gated: only records whose Japanese
source contains マーカー・クラン or マーカ・クラン are changed.  Records
whose Japanese source is ミライ／ミライ・ヤシマ are never touched.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "analysis" / "ggen_advance_translation_merged_20260842.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_translation_merged_20260843.json"
DEFAULT_REPORT = ROOT / "analysis" / "ggen_advance_marker_clan_restoration_20260830.json"
BATCH_ID = "marker-clan-source-gated-restoration-20260830"
MARKER_SOURCE = re.compile(r"マーカ(?:ー)?・クラン")
MIRAI_SOURCE = re.compile(r"ミライ(?:・ヤシマ)?")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402


def update_payload_hash(row: dict[str, Any]) -> None:
    patch = {
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
    row["translation_payload_sha256"] = translation_payload_digest(patch)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    merged = json.loads(args.source.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    protected_mirai: list[str] = []

    for row in merged.get("records") or []:
        source = str(row.get("source_text") or "")
        before = str(row.get("translation_ko") or "")
        if MIRAI_SOURCE.search(source):
            protected_mirai.append(str(row.get("record_id") or ""))
            continue
        if not MARKER_SOURCE.search(source) or "미라이 야시마" not in before:
            continue

        before_segments = copy.deepcopy(row.get("translation_segments"))
        row["translation_ko"] = before.replace("미라이 야시마", "마커 클랜")
        if isinstance(row.get("translation_segments"), list):
            row["translation_segments"] = [
                str(part).replace("미라이 야시마", "마커 클랜")
                for part in row["translation_segments"]
            ]
            row["translation_ko"] = "\n".join(part for part in row["translation_segments"] if part)

        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-08-30"
        row["overlay_batch_id"] = BATCH_ID
        note = str(row.get("translator_notes") or "").replace(
            " or Mirai Yashima name", ""
        ).rstrip()
        row["translator_notes"] = (
            note + "; source-gated restoration: マーカー／マーカ・クラン → 마커 클랜"
        ).lstrip("; ")
        update_payload_hash(row)
        changes.append({
            "record_id": row["record_id"],
            "source_scope": row.get("source_scope"),
            "source_text": source,
            "translation_before": before,
            "translation_after": row["translation_ko"],
            "translation_segments_before": before_segments,
            "translation_segments_after": row.get("translation_segments"),
            "translation_payload_sha256": row.get("translation_payload_sha256"),
        })

    if len(changes) != 24:
        raise SystemExit(f"gate failed: expected exactly 24 source-gated restorations, got {len(changes)}")
    if any(MIRAI_SOURCE.search(item["source_text"]) for item in changes):
        raise SystemExit("gate failed: a true Mirai source entered the restoration set")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    correction_identity = digest({
        "parent": parent_identity,
        "batch_id": BATCH_ID,
        "records": [
            {"record_id": item["record_id"], "payload": item["translation_payload_sha256"]}
            for item in changes
        ],
    })
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["marker_clan_restoration_identity_sha256"] = correction_identity
    identity["translation_overlay_identity_sha256"] = correction_identity

    map_changes = [item for item in changes if item.get("source_scope") in {"scenario_main", "scenario_map_script"}]
    parent_map_identity = str(identity.get("map_script_translation_overlay_identity_sha256") or "")
    map_identity = digest({
        "parent": parent_map_identity,
        "batch_id": BATCH_ID,
        "records": [
            {"record_id": item["record_id"], "payload": item["translation_payload_sha256"]}
            for item in map_changes
        ],
    })
    identity["parent_map_script_translation_overlay_identity_sha256"] = parent_map_identity
    identity["marker_clan_restoration_map_script_identity_sha256"] = map_identity
    identity["map_script_translation_overlay_identity_sha256"] = map_identity

    summary = merged.setdefault("summary", {})
    summary["translation_overlay_identity_sha256"] = correction_identity
    summary["marker_clan_restoration_records"] = len(changes)
    merged["marker_clan_restoration"] = {
        "batch_id": BATCH_ID,
        "parent_snapshot": args.source.name,
        "changed_records": len(changes),
        "production_records": sum(item.get("source_scope") == "production" for item in changes),
        "scenario_records": len(map_changes),
        "true_mirai_source_records_protected": len(protected_mirai),
        "identity_sha256": correction_identity,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_marker_clan_source_gated_restoration",
        "source_snapshot": str(args.source.relative_to(ROOT)).replace("\\", "/"),
        "output_snapshot": str(args.out.relative_to(ROOT)).replace("\\", "/"),
        "batch_id": BATCH_ID,
        "identity_sha256": correction_identity,
        "selection_rule": "Japanese source matches マーカー・クラン or マーカ・クラン and Korean contains 미라이 야시마",
        "protected_rule": "Japanese source containing ミライ or ミライ・ヤシマ is never changed",
        "changed_records": changes,
        "protected_mirai_record_ids": protected_mirai,
        "output_sha256": sha256(args.out.read_bytes()).hexdigest(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", **merged["marker_clan_restoration"], "report": str(args.report)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
