#!/usr/bin/env python3
"""Build a large short-label batch after applying an exact supplemental map.

The unified source stays immutable.  This helper replaces only unresolved
``<slot>`` markers that are present in an exact supplemental 12x12 charmap,
then delegates wording to the reviewed name/glossary translator.  It is
intended for 500-1000-record structure batches; rows that remain ambiguous,
malformed, or untranslated are skipped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
sys.modules.setdefault("build_stage2_translation_master", types.SimpleNamespace())

import build_ggen_advance_translation_master as translation  # noqa: E402


DEFAULT_MERGED = Path("analysis/ggen_advance_translation_merged_20260827.json")
DEFAULT_CHARMAP = Path("legacy/analysis/ggen_advance_12x12_unicode_charmap_20260827.json")
DEFAULT_OUTPUT = Path("analysis/ggen_advance_translation_batch_maps/decoded_name_batch.json")
DEFAULT_CATEGORIES = {
    "character_name",
    "unit_name",
    "unit_name_alternate",
    "weapon_name",
    "unit_defense_ability",
    "upgrade_part_name",
    "series_title",
    "stage_location_name",
    "stage_battle_condition_component",
    "stage_code",
}
SLOT_RE = re.compile(r"<([0-9A-Fa-f]{4})>")


def parse_offset(row: dict[str, Any]) -> int:
    try:
        return int(str(row.get("target_file_offset", "0")), 16)
    except (TypeError, ValueError):
        return 0


def load_charmap(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        f"0x{int(str(slot), 16):04X}": str(char)
        for slot, char in payload.get("verified_charmap", {}).items()
        if isinstance(char, str)
    }


def decode_markers(source: str, charmap: dict[str, str]) -> tuple[str | None, list[str]]:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        slot = "0x" + match.group(1).upper()
        char = charmap.get(slot)
        if char is None:
            missing.add(slot)
            return match.group(0)
        return char

    decoded = SLOT_RE.sub(replace, source)
    if missing or SLOT_RE.search(decoded):
        return None, sorted(missing)
    # Nested/foreign markup is not a Japanese glyph and is not safe to guess.
    if "<" in decoded or ">" in decoded:
        return None, []
    return decoded, []


def select_records(
    merged: dict[str, Any], charmap: dict[str, str], categories: set[str], max_records: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    exact, compact = translation.curated_translation_maps()
    candidates: list[tuple[int, dict[str, Any]]] = []
    stats: Counter[str] = Counter()
    for row in merged.get("records", []):
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        if str(row.get("semantic_category", "")) not in categories:
            continue
        stats["considered"] += 1
        decoded, missing = decode_markers(str(row.get("source_text", "")), charmap)
        if decoded is None:
            stats["unresolved_or_malformed"] += 1
            continue
        working = dict(row)
        working["decoded_text_seed"] = decoded
        working["unresolved_slots"] = []
        rendered, status, note = translation.source_translation(working, exact, compact)
        if status not in {"translated", "translated_same", "translated_partial_charmap_preserved"}:
            stats[status] += 1
            continue
        if not rendered.strip():
            stats["empty_translation"] += 1
            continue
        candidates.append(
            (
                parse_offset(row),
                {
                    "record_id": row["record_id"],
                    "translation_ko": rendered,
                    "translation_status": "translated",
                    "translator_notes": f"exact supplemental 12x12 decode; {note}",
                },
            )
        )
    candidates.sort(key=lambda item: (item[0], item[1]["record_id"]))
    selected = [item for _, item in candidates[:max_records]]
    stats["available_translated"] = len(candidates)
    stats["selected"] = len(selected)
    return selected, dict(stats)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--charmap", type=Path, default=DEFAULT_CHARMAP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--categories", nargs="+", default=sorted(DEFAULT_CATEGORIES))
    parser.add_argument("--max-records", type=int, default=1000)
    args = parser.parse_args(argv)
    if args.max_records <= 0:
        raise SystemExit("--max-records must be positive")
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    records, stats = select_records(merged, load_charmap(args.charmap), set(args.categories), args.max_records)
    if not records:
        raise SystemExit(f"no exact decoded name records; stats={stats}")
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
