"""Build the next safe unit-name batch with reserved glyph markers.

The remaining Advance unit-name table contains a small, repeatable structure
where the Japanese body is already known but one or more reserved renderer
markers (07F8/07FB/07FC/07FD/07FE) are unresolved.  This helper translates the
visible name body while leaving those marker slots represented by the source
metadata.  It refuses any other unresolved glyph so that a batch cannot turn
an undecoded name into a guess.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_MERGED = Path("analysis/ggen_advance_translation_merged_20260827.json")
DEFAULT_OUTPUT = Path(
    "analysis/ggen_advance_translation_batch_maps/unit_name_reserved_batch.json"
)

RESERVED_SLOTS = {"0X07F8", "0X07FB", "0X07FC", "0X07FD", "0X07FE"}
RESERVED_TAG = re.compile(r"<(?:07F8|07FB|07FC|07FD|07FE)>", re.IGNORECASE)

# These are reviewed names already present elsewhere in the same integrated
# sheet.  The few bodies without a direct duplicate use the same project
# glossary conventions (Ez8 HMC/HAC, GP03, and Medea).
UNIT_TRANSLATIONS = {
    "ザクⅡ ドアン機": "자쿠II 도안전용기",
    "Ez8HMC": "Ez8 HMC",
    "Ez8HAC": "Ez8 HAC",
    "ガザC": "가자 C",
    "BDⅡ": "블루 데스티니 II",
    "BDⅢ": "블루 데스티니 III",
    "ガザD": "가자 D",
    "GP03デンドロビウム": "GP03 덴드로비움",
    "ガザE": "가자 E",
    "メタス": "메타스",
    "サイコガンダム": "사이코 건담",
    "トーラス": "토러스",
    "Zガンダム": "Z건담",
    "ウェーブライダー": "웨이브 라이더",
    "シャイニングガンダム": "샤이닝 건담",
    "∀ガンダム": "턴에이 건담",
    "ガンダムエピオン": "건담 에피온",
    "ミデア": "미데아",
}


def normalize_body(source_text: str) -> tuple[str, bool]:
    """Return the visible Japanese body and whether the <S> marker exists."""
    has_s_marker = "<S>" in source_text
    body = RESERVED_TAG.sub("", source_text)
    body = body.replace("<S>", "")
    return re.sub(r"\s+", " ", body).strip(), has_s_marker


def select_records(merged: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for row in merged.get("records", []):
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        if row.get("semantic_category") != "unit_name":
            continue
        unresolved = {str(slot).upper() for slot in row.get("source_unresolved_slots", [])}
        if not unresolved or unresolved - RESERVED_SLOTS:
            continue
        body, has_s_marker = normalize_body(str(row.get("source_text", "")))
        target = UNIT_TRANSLATIONS.get(body)
        if target is None:
            skipped["unmapped_visible_body"] = skipped.get("unmapped_visible_body", 0) + 1
            continue
        if has_s_marker:
            target += "<S>"
        records.append(
            {
                "record_id": row["record_id"],
                "translation_ko": target,
                "translation_status": "translated",
                "translator_notes": (
                    "reviewed unit-name body translation; preserve reserved source "
                    "marker slots " + ", ".join(sorted(unresolved))
                ),
            }
        )
    records.sort(key=lambda item: (str(item["record_id"])))
    skipped["selected"] = len(records)
    return records, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)

    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    records, stats = select_records(merged)
    if not records:
        raise SystemExit("no safe reserved-marker unit-name records matched")
    payload = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "Reserved-marker unit names; visible body translated, renderer markers retained in source contract.",
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"result": "PASS", "output": str(args.out), "record_count": len(records), "stats": stats},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
