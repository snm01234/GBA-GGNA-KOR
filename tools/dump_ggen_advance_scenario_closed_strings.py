#!/usr/bin/env python3
"""Dump newly slot-complete scenario pending strings for a translation overlay."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402

MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
SCENARIO = ROOT / "analysis" / "scenario_event_translation_source_20260827.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ROOT / "analysis" / "ggen_advance_scenario_pending_closed_strings_20260828.json"


def is_bark(parts: list[str]) -> bool:
    text = "".join(parts)
    return "セリフ" in text and text.count("＠") >= 2


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    charmap = load_map(MAP12)
    charmap.update(CORRECTED_LOW_KANA)
    pending = {
        row["record_id"]: row
        for row in json.loads(MERGED.read_text(encoding="utf-8"))["records"]
        if row.get("source_scope") == "scenario_main"
        and row.get("translation_status") == "pending"
        and row.get("translation_policy") == "translate"
    }
    groups = {"dialogue": defaultdict(list), "bark": defaultdict(list)}
    still = 0
    for record in json.loads(SCENARIO.read_text(encoding="utf-8"))["main"]["records"]:
        if record["record_id"] not in pending:
            continue
        parts: list[str] = []
        missing = False
        for segment in record.get("segments") or []:
            slots = segment.get("slots") or []
            if not slots:
                continue
            chars: list[str] = []
            for raw in slots:
                char = charmap.get(int(str(raw), 16))
                if char is None:
                    missing = True
                    break
                chars.append(char)
            if missing:
                break
            parts.append("".join(chars))
        if missing:
            still += 1
            continue
        bucket = "bark" if is_bark(parts) else "dialogue"
        key = " / ".join(parts)
        groups[bucket][key].append(record["record_id"])
    payload = {
        "dialogue_unique": len(groups["dialogue"]),
        "dialogue_rows": sum(len(v) for v in groups["dialogue"].values()),
        "bark_unique": len(groups["bark"]),
        "bark_rows": sum(len(v) for v in groups["bark"].values()),
        "still_partial": still,
        "dialogue": [
            {"jp": key, "parts": key.split(" / "), "record_ids": ids, "n": len(ids)}
            for key, ids in sorted(groups["dialogue"].items(), key=lambda kv: -len(kv[1]))
        ],
        "bark": [
            {"jp": key, "parts": key.split(" / "), "record_ids": ids, "n": len(ids)}
            for key, ids in sorted(groups["bark"].items(), key=lambda kv: -len(kv[1]))
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("dialogue_unique", "dialogue_rows", "bark_unique", "bark_rows", "still_partial")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
