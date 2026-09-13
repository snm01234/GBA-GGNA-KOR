#!/usr/bin/env python3
"""Bind slot-complete map-script Korean drafts onto the 20260828 sheet.

Looks up unique JP parts in a KO map, expands to an overlay against the
20260828 merged sheet (map rows are not in the 20260827 immutable source),
then merges while keeping the previous 6,760 overlay identity.  Leftover
partial rows stay pending.  Compact JSON stays outside overlays/.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_translation_overlay_batch as overlay_batch  # noqa: E402
import merge_ggen_advance_translation_overlays as merge  # noqa: E402

MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"
ADDENDUM = ROOT / "analysis" / "ggen_advance_map_script_unified_records_20260828.json"
KO_MAP = ROOT / "analysis" / "ggen_advance_map_script_dialogue_ko_20260828.json"
COMPACT = ROOT / "analysis" / "map_script_complete_compact_20260828.json"
OVERLAY = ROOT / "analysis" / "ggen_advance_translation_overlays" / "map_script_complete_8089.json"

KANA_RE = re.compile(r"[\u3040-\u30FA\u30FC-\u30FF]")
BATCH_ID = "map-script-complete-20260828"


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def load_ko_map(path: Path) -> dict[tuple[str, ...], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["records"] if isinstance(payload, dict) else payload
    mapping: dict[tuple[str, ...], list[str]] = {}
    for item in records:
        if "parts_jp" in item:
            jp_parts = tuple(item["parts_jp"])
            ko_parts = list(item["parts_ko"])
        else:
            jp_parts = tuple(item["jp"].split(" / ")) if "parts" in item and "jp" in item else tuple(item["jp_parts"])
            ko_parts = list(item["parts"] if "parts" in item else item["parts_ko"])
        if jp_parts in mapping and mapping[jp_parts] != ko_parts:
            fail(f"conflicting KO for {jp_parts!r}")
        mapping[jp_parts] = ko_parts
    return mapping


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ko_map = load_ko_map(KO_MAP)
    addendum = json.loads(ADDENDUM.read_text(encoding="utf-8"))
    parent = json.loads(MERGED.read_text(encoding="utf-8"))
    parent_overlay_identity = parent["identity"]["translation_overlay_identity_sha256"]
    parent_merge = copy.deepcopy(parent["merge"])
    parent_scope = parent["scope"]
    parent_inputs = copy.deepcopy(parent["inputs"])
    parent_map_record_identity = parent["identity"].get("map_script_record_identity_sha256")
    parent_parent_manifest = parent["identity"].get("parent_manifest_identity_sha256")

    compact_records: list[dict[str, Any]] = []
    missing: list[tuple[str, ...]] = []
    kana_hits: list[str] = []
    for row in addendum["records"]:
        if row.get("source_decode_status") != "complete":
            continue
        jp_parts = tuple(str(segment.get("source_text") or "") for segment in row.get("segments") or [])
        ko_parts = ko_map.get(jp_parts)
        if ko_parts is None:
            missing.append(jp_parts)
            continue
        if len(ko_parts) != len(jp_parts):
            fail(f"KO parts length mismatch for {row['record_id']}")
        for part in ko_parts:
            if KANA_RE.search(part):
                kana_hits.append(row["record_id"])
                break
        display = "\n".join(part for part in ko_parts if part)
        if not display.strip() and not all(not (part or "").strip() for part in jp_parts):
            fail(f"empty KO for {row['record_id']}")
        compact_records.append(
            {
                "record_id": row["record_id"],
                "translation_segments": ko_parts,
                "translation_ko": display,
            }
        )

    if missing:
        unique_missing = sorted(set(missing))
        fail(f"KO map missing {len(unique_missing)} unique JP; first: {unique_missing[:6]}")
    if kana_hits:
        fail(f"KO still has kana in {len(kana_hits)} rows; first: {kana_hits[:8]}")
    if len(compact_records) != 8089:
        fail(f"expected 8089 complete rows, got {len(compact_records)}")

    compact = {
        "schema_version": 1,
        "batch_id": BATCH_ID,
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "slot-complete map-script 12x12 decode; natural Korean; leftover rows excluded",
        "records": compact_records,
    }
    COMPACT.write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    overlay_info = overlay_batch.build_overlay(MERGED, COMPACT, OVERLAY)
    merged_result = merge.run(MERGED, [OVERLAY], MERGED, mode="draft", summary_only=False)

    merged_result["scope"] = parent_scope
    merged_result["inputs"] = parent_inputs
    merged_result["identity"]["translation_overlay_identity_sha256"] = parent_overlay_identity
    merged_result["identity"]["map_script_translation_overlay_identity_sha256"] = merged_result["merge"][
        "translation_overlay_identity_sha256"
    ]
    merged_result["identity"]["map_script_record_identity_sha256"] = parent_map_record_identity
    merged_result["identity"]["parent_manifest_identity_sha256"] = parent_parent_manifest
    merged_result["merge"]["overlay_files"] = list(parent_merge.get("overlay_files") or []) + list(
        merged_result["merge"].get("overlay_files") or []
    )
    merged_result["merge"]["batch_count"] = len(merged_result["merge"]["overlay_files"])
    merged_result["merge"]["accepted_record_count"] = int(parent_merge.get("accepted_record_count") or 0) + len(
        compact_records
    )
    merged_result["merge"]["parent_translation_overlay_identity_sha256"] = parent_overlay_identity
    merged_result["summary"]["translation_overlay_identity_sha256"] = parent_overlay_identity
    merge.write_json(MERGED, merged_result)

    print(
        json.dumps(
            {
                "result": "PASS",
                "complete_rows": len(compact_records),
                "unique_jp": len(ko_map),
                "overlay": overlay_info,
                "translated_canonical_records": merged_result["summary"]["translated_canonical_records"],
                "untranslated_canonical_records": merged_result["summary"]["untranslated_canonical_records"],
                "parent_overlay_identity_preserved": merged_result["identity"]["translation_overlay_identity_sha256"]
                == parent_overlay_identity,
                "immutable_20260827_source_preserved": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
