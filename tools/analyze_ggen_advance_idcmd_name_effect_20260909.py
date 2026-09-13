#!/usr/bin/env python3
"""Measure ID-command list name/effect columns from ss4/ss6 and list long strings."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON

OUT = ROOT / "outputs" / "20260909_idcmd_full_audit"


def visible_len(text: str) -> int:
    return len(text.replace("\n", ""))


def uniq_cat(merged, cat, min_len=0):
    uniq = defaultdict(list)
    for row in merged["records"]:
        if row.get("semantic_category") != cat:
            continue
        if row.get("translation_status") != "translated":
            continue
        ko = str(row.get("translation_ko") or "")
        if visible_len(ko) < min_len:
            continue
        uniq[(str(row.get("source_text") or ""), ko)].append(row["record_id"])
    items = [
        {
            "jp": jp,
            "ko": ko,
            "jp_len": visible_len(jp),
            "ko_len": visible_len(ko),
            "count": len(ids),
            "sample": ids[0],
        }
        for (jp, ko), ids in uniq.items()
    ]
    items.sort(key=lambda r: (-r["ko_len"], r["ko"]))
    return items


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    print("NAMES >=16")
    for item in uniq_cat(merged, "id_command_name", 16):
        print(f"  {item['ko_len']:2d} x{item['count']:3d} {item['ko']!r}")
    print("\nEFFECTS >=8")
    for item in uniq_cat(merged, "id_command_effect_summary", 8):
        print(f"  {item['ko_len']:2d} x{item['count']:3d} {item['ko']!r} <= {item['jp']!r}")
    print("\nDESC ==17 unique")
    desc17 = uniq_cat(merged, "id_command_description", 17)
    print("count unique at >=17", len(desc17), "records", sum(i["count"] for i in desc17))
    # remaining exactly 17
    for item in desc17[:30]:
        print(f"  {item['ko_len']:2d}/{item['jp_len']:2d} x{item['count']:3d} {item['ko']!r}")


if __name__ == "__main__":
    main()
