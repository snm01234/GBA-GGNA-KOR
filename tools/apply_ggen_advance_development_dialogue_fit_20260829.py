#!/usr/bin/env python3
"""Shorten split development-completion dialogue after measured clipping."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_translation_merged_20260842.json"
DEFAULT_REPORT = ROOT / "analysis" / "ggen_advance_development_dialogue_fit_20260829.json"
BATCH_ID = "development-dialogue-measured-fit-20260829"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402


# The game draws each pair as two fixed-width records.  Keep the second record
# to at most ten visible cells so the final syllables are not discarded.
TRANSLATIONS = {
    "GGA-TEXT-001BE97E": "완성됐습니다 기체는",
    "GGA-TEXT-001BE98E": "스톡으로 보냅니다",
    "GGA-TEXT-001BE9A3": "…됐다 기체는",
    "GGA-TEXT-001BE9B2": "스톡으로 보내 둔다",
}


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    merged = json.loads(args.source.read_text(encoding="utf-8"))
    by_id = {str(row.get("record_id")): row for row in merged.get("records") or []}
    missing = sorted(set(TRANSLATIONS) - set(by_id))
    if missing:
        raise SystemExit(f"gate failed: target records missing: {missing}")

    changed = []
    for record_id, translation_ko in TRANSLATIONS.items():
        row = by_id[record_id]
        before = str(row.get("translation_ko") or "")
        if row.get("translation_status") != "translated":
            raise SystemExit(f"gate failed: target is not translated: {record_id}")
        row["translation_ko"] = translation_ko
        row["translation_source"] = "user_verified_runtime_screenshot"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-08-29"
        row["qa_status"] = "runtime_clipping_fixed"
        row["overlay_batch_id"] = BATCH_ID
        row["translator_notes"] = (
            str(row.get("translator_notes") or "").rstrip("; ")
            + "; measured fixed-width dialogue fit: redistributed split sentence"
        ).lstrip("; ")
        update_payload_hash(row)
        changed.append(
            {
                "record_id": record_id,
                "target_file_offset": row.get("target_file_offset"),
                "translation_before": before,
                "translation_after": translation_ko,
                "visible_cells": len(translation_ko),
                "translation_payload_sha256": row["translation_payload_sha256"],
            }
        )

    changed.sort(key=lambda item: item["record_id"])
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    followup_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [
                {"record_id": item["record_id"], "payload": item["translation_payload_sha256"]}
                for item in changed
            ],
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["development_dialogue_fit_identity_sha256"] = followup_identity
    identity["translation_overlay_identity_sha256"] = followup_identity
    summary = merged.setdefault("summary", {})
    summary["translation_overlay_identity_sha256"] = followup_identity
    summary["development_dialogue_fit_records"] = len(changed)
    merged["development_dialogue_fit"] = {
        "batch_id": BATCH_ID,
        "parent_snapshot": args.source.name,
        "report": str(args.report.relative_to(ROOT)).replace("\\", "/"),
        "changed_records": len(changed),
        "identity_sha256": followup_identity,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_development_dialogue_fit",
        "batch_id": BATCH_ID,
        "source_snapshot": str(args.source.relative_to(ROOT)).replace("\\", "/"),
        "output_snapshot": str(args.out.relative_to(ROOT)).replace("\\", "/"),
        "identity_sha256": followup_identity,
        "records": changed,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "changed_records": len(changed), "identity_sha256": followup_identity}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
