"""Build a compact batch for unambiguous Gundam series/brand labels.

The source rows still contain Japanese glyph slots, but the visible pattern
and the canonical Gundam title identify these labels without guessing a prose
sentence.  The batch is deliberately explicit by record id so unresolved
slots in other series labels cannot be swept in accidentally.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_MERGED = Path("analysis/ggen_advance_translation_merged_20260827.json")
DEFAULT_OUTPUT = Path(
    "analysis/ggen_advance_translation_batch_maps/known_series_batch.json"
)

KNOWN_SERIES_TRANSLATIONS = {
    "GGA-TEXT-0018CE08": "기동전사 건담",
    "GGA-TEXT-0018CE12": "기동전사 Z건담",
    "GGA-TEXT-0018CE1D": "기동전사 건담 ZZ",
    "GGA-TEXT-0018CE29": "기동전사 건담 CCA",
    "GGA-TEXT-0018CE37": "기동전사 건담 F91",
    "GGA-TEXT-0018CE46": "기동전사 V건담",
    "GGA-TEXT-0018CE52": "기동무투전 G건담",
    "GGA-TEXT-0018CE60": "신기동전기 건담 W",
    "GGA-TEXT-0018CE80": "기동신세기 건담 X",
    "GGA-TEXT-0018CE96": "기동전사 건담 SEED",
    "GGA-TEXT-0018CEA4": "0080 주머니 속의 전쟁",
    "GGA-TEXT-0018CEC6": "제08MS소대",
    # This row is classified as series_title in the source inventory, but its
    # fixed body is the character label ギレン・ザビ.
    "GGA-TEXT-0018CF02": "기렌 자비",
}


def select_records(merged: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {str(row["record_id"]): row for row in merged.get("records", [])}
    selected: list[dict[str, Any]] = []
    for record_id, translation in KNOWN_SERIES_TRANSLATIONS.items():
        row = by_id.get(record_id)
        if row is None:
            raise SystemExit(f"record is missing from merged source: {record_id}")
        if row.get("translation_status") != "pending":
            raise SystemExit(f"record is not pending: {record_id}")
        if row.get("translation_policy") != "translate":
            raise SystemExit(f"record is not translatable: {record_id}")
        selected.append(
            {
                "record_id": record_id,
                "translation_ko": translation,
                "translation_status": "translated",
                "translator_notes": "canonical Gundam series/brand label; unresolved source glyph slots retained in the source contract",
            }
        )
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)

    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    records = select_records(merged)
    payload = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "Canonical Gundam series and brand labels with explicit record selection.",
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), "record_count": len(records)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
