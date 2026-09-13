#!/usr/bin/env python3
"""Merge parallel pending-translation overlays into the derived merged sheet.

Only patches analysis/ggen_advance_translation_merged_*.json.  Unified source
and ROM are not written.  Duplicate record_ids refuse.  Empty KO refuses.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260830.json"
OUT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260831.json"
OVERLAY_DIR = ROOT / "analysis" / "ggen_advance_translation_overlays"
OVERLAYS = [OVERLAY_DIR / f"pending_parallel_ko_{index:02d}_20260829.json" for index in range(1, 9)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    missing = [str(path.relative_to(ROOT)) for path in OVERLAYS if not path.exists()]
    if missing:
        print(json.dumps({"result": "WAIT", "missing_overlays": missing}, ensure_ascii=False, indent=2))
        return 2

    compact: list[dict] = []
    seen: set[str] = set()
    dupes: list[str] = []
    skipped_jp: list[str] = []
    per_agent: dict[str, int] = {}
    for path in OVERLAYS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        skipped_jp.extend(str(item) for item in payload.get("skipped_jp") or [])
        count = 0
        for item in payload.get("records") or []:
            record_id = str(item.get("record_id") or "")
            ko = str(item.get("translation_ko") or "").strip()
            if not record_id or not ko:
                print(json.dumps({"result": "FAIL", "reason": "empty record_id or translation_ko", "file": str(path.name)}, ensure_ascii=False, indent=2))
                return 1
            if record_id in seen:
                dupes.append(record_id)
                continue
            seen.add(record_id)
            compact.append(item)
            count += 1
        per_agent[str(payload.get("agent") or path.stem)] = count
    if dupes:
        print(json.dumps({"result": "FAIL", "duplicate_record_ids": dupes[:20], "count": len(dupes)}, ensure_ascii=False, indent=2))
        return 1

    merged = json.loads(MERGED.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    unknown = [item["record_id"] for item in compact if item["record_id"] not in by_id]
    if unknown:
        print(json.dumps({"result": "FAIL", "unknown_record_ids": unknown[:20], "count": len(unknown)}, ensure_ascii=False, indent=2))
        return 1

    applied = 0
    already = 0
    for item in compact:
        row = by_id[item["record_id"]]
        if row.get("scope_status") != "included" or row.get("translation_policy") != "translate":
            print(json.dumps({"result": "FAIL", "reason": "not canonical translate", "record_id": item["record_id"]}, ensure_ascii=False, indent=2))
            return 1
        if row.get("translation_status") == "translated" and str(row.get("translation_ko") or "").strip():
            already += 1
            continue
        row["translation_ko"] = item["translation_ko"]
        row["translation_status"] = "translated"
        row["review_status"] = item.get("review_status") or "draft"
        row["translation_source"] = item.get("translation_source") or "curated_project_data"
        row["translator_notes"] = item.get("translator_notes") or "parallel pending 20260829"
        row["overlay_batch_id"] = "pending-parallel-20260829"
        applied += 1

    statuses = Counter(str(row.get("translation_status", "")) for row in merged["records"])
    translated_canonical = sum(
        1
        for row in merged["records"]
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and row.get("translation_status") == "translated"
    )
    pending_canonical = sum(
        1
        for row in merged["records"]
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and row.get("translation_status") != "translated"
    )
    summary = merged.setdefault("summary", {})
    summary["translated_canonical_records"] = translated_canonical
    summary["untranslated_translate_policy_records"] = pending_canonical
    merged["merged_translation_status_counts"] = dict(sorted(statuses.items()))
    summary["merged_translation_status_counts"] = dict(sorted(statuses.items()))
    summary["added_pending_parallel_translations"] = applied

    OUT_MERGED.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "applied": applied,
                "already_translated_skipped": already,
                "per_agent": per_agent,
                "skipped_jp": len(skipped_jp),
                "translated_canonical_records": translated_canonical,
                "untranslated_translate_policy_records": pending_canonical,
                "merged": str(OUT_MERGED.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
