#!/usr/bin/env python3
"""Extract map-script prints from 0x00FC0000+ (omitted extra-session bank)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import extract_ggen_advance_map_script_dialogue as extract_mod
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA
from ggen_advance_project_paths import ORIGINAL_ROM

OUT = ROOT / "analysis" / "ggen_advance_map_script_extrabank_extract_20260910.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    extract_mod.BANK_START = 0x00FBFF00
    extract_mod.BANK_END = 0x00FD0000
    charmap = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
    payload = extract_mod.extract(ORIGINAL_ROM, charmap)
    extra = [
        row
        for row in payload["records"]
        if int(row["target_file_offset"], 16) >= 0x00FC0000
    ]
    payload["records"] = extra
    payload["bank"]["file_range"] = "0x00FC0000-0x00FD0000"
    payload["summary"]["records"] = len(extra)
    payload["summary"]["complete_decode"] = sum(1 for row in extra if not row.get("unresolved_slots"))
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("records", len(extra))
    keys = ("ニムバス", "ドアン", "カジマ", "女", "だがっ", "敗北", "くくく", "選ばれ")
    for row in extra:
        text = str(row.get("source_text_seed") or "")
        speaker = row.get("speaker_id")
        if any(key in text for key in keys) or speaker in ("0x005F", "0x007F", "0x002C"):
            print(row["record_id"], speaker, text.replace("\\n", " / "))


if __name__ == "__main__":
    main()
