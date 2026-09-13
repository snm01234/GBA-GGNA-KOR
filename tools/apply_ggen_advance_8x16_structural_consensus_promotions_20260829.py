#!/usr/bin/env python3
"""Apply the first calibrated structural-consensus 8x16 promotion batch.

This script is intentionally explicit and conflict-checking.  It only adds the
20 slots that passed the 2026-08-29 three-channel gate:
- exact dictionary-anchor constant-offset interval,
- agreeing ROM bitmap local-DP mapping,
- proposed character within Windows-font ensemble top 20.

Run only after reviewing tools/analyze_ggen_advance_8x16_structural_consensus.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS = {
    "0x0161": "因",
    "0x0162": "引",
    "0x01B5": "骸",
    "0x01FE": "起",
    "0x0237": "胸",
    "0x023A": "郷",
    "0x023B": "鏡",
    "0x023F": "業",
    "0x0240": "局",
    "0x0242": "極",
    "0x0246": "筋",
    "0x0248": "近",
    "0x02F8": "参",
    "0x02FE": "賛",
    "0x0300": "残",
    "0x0338": "首",
    "0x0392": "伸",
    "0x03B8": "政",
    "0x04BE": "派",
    "0x04C2": "拝",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    args = ap.parse_args()
    args.map.resolve().relative_to(ROOT.resolve())
    payload = json.loads(args.map.read_text(encoding="utf-8"))
    cmap = payload["verified_charmap"]
    conflicts = {slot: (cmap[slot], char) for slot, char in PROMOTIONS.items() if slot in cmap and cmap[slot] != char}
    if conflicts:
        raise SystemExit(f"conflicts: {conflicts}")
    for slot, char in PROMOTIONS.items():
        cmap[slot] = char
    payload["verified_charmap"] = dict(sorted(cmap.items(), key=lambda item: int(item[0], 16)))
    payload["combined_slot_count"] = len(cmap)
    payload["added_structural_consensus_promotions_20260829"] = {
        slot: {
            "to": char,
            "basis": "dictionary_offset_plus_rom_bitmap_dp_plus_windows_font_top20",
            "evidence": "tools/analyze_ggen_advance_8x16_structural_consensus.py; max_offset_gap=23, min_pair_score=0.40, font_rank<=20",
        }
        for slot, char in PROMOTIONS.items()
    }
    args.map.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promotions": len(PROMOTIONS), "combined_slot_count": len(cmap)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
