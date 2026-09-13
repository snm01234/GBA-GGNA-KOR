#!/usr/bin/env python3
"""Build a larger, deterministic batch map from reviewed short-label data.

This helper selects only still-pending records whose current Advance source can
be translated by the reviewed project glossary/transliteration rules.  It
never guesses unresolved glyphs or scenario prose, and it does not modify the
immutable source or the merged report.  The resulting compact map is then
bound to source fingerprints by ``build_ggen_advance_translation_overlay_batch``.
"""
from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path
from typing import Any


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

# The translation helper imports the stage-2 builder for the full ROM build,
# but its reviewed short-label maps are independent of capstone/runtime data.
# Keep this batch-map utility usable with the bundled lightweight Python.
sys.modules.setdefault("build_stage2_translation_master", types.SimpleNamespace())

import build_ggen_advance_translation_master as translation  # noqa: E402


DEFAULT_MERGED = Path("analysis/ggen_advance_translation_merged_20260827.json")
DEFAULT_OUTPUT = Path("analysis/ggen_advance_translation_batch_maps/curated_batch.json")


def parse_offset(row: dict[str, Any]) -> int:
    value = row.get("target_file_offset", "0")
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        return 0


def select_records(
    merged: dict[str, Any], categories: set[str], max_records: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    exact, compact = translation.curated_translation_maps()
    candidates: list[dict[str, Any]] = []
    rows_by_id = {str(row["record_id"]): row for row in merged.get("records", [])}
    considered = 0
    skipped: dict[str, int] = {}
    for row in merged.get("records", []):
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        if str(row.get("semantic_category", "")) not in categories:
            continue
        considered += 1
        source = str(row.get("source_text", ""))
        working = dict(row)
        working["decoded_text_seed"] = source
        working["unresolved_slots"] = row.get("source_unresolved_slots", [])
        rendered, status, note = translation.source_translation(working, exact, compact)
        if status not in {"translated", "translated_partial_charmap_preserved", "translated_same"}:
            skipped[status] = skipped.get(status, 0) + 1
            continue
        if not rendered.strip():
            skipped["empty_translation"] = skipped.get("empty_translation", 0) + 1
            continue
        candidates.append(
            {
                "record_id": row["record_id"],
                "translation_ko": rendered,
                "translation_status": "translated",
                "translator_notes": note,
            }
        )
    candidates.sort(key=lambda item: (parse_offset(rows_by_id[item["record_id"]]), item["record_id"]))
    selected = candidates[:max_records]
    skipped["selected"] = len(selected)
    skipped["considered"] = considered
    skipped["available_translated"] = len(candidates)
    return selected, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--categories", nargs="+", required=True)
    parser.add_argument("--max-records", type=int, default=500)
    args = parser.parse_args(argv)
    if args.max_records <= 0:
        raise SystemExit("--max-records must be positive")
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    records, stats = select_records(merged, set(args.categories), args.max_records)
    if not records:
        raise SystemExit("no safe pending short-label records matched the requested categories")
    payload = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), "record_count": len(records), "stats": stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
