#!/usr/bin/env python3
"""Apply the first contradiction-free LIS constant-offset 8x16 batch.

The batch is generated from tools/analyze_ggen_advance_8x16_lis_constant_offset.py
with min_support=3.  Every source run is contradiction-free against all already
verified 8x16 slots in its span.  0x0247 is intentionally held because an
independent Shift-JIS Viterbi pass disagrees.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS = {
    "0x0163": "飲",
    "0x0164": "陰",
    "0x01B6": "各",
    "0x0233": "橋",
    "0x0234": "況",
    "0x0235": "狂",
    "0x0236": "狭",
    "0x023D": "驚",
    "0x023E": "暁",
    "0x0245": "禁",
    "0x02FD": "画",
    "0x02FF": "唾",
    "0x03B7": "成",
    "0x03D5": "舌",
    "0x03D7": "千",
    "0x03D8": "占",
    "0x04BB": "把",
    "0x04C0": "馬",
    "0x04C1": "廃",
    "0x04C3": "排",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    args = ap.parse_args()
    args.map.resolve().relative_to(ROOT.resolve())
    payload = json.loads(args.map.read_text(encoding="utf-8"))
    cmap = payload["verified_charmap"]
    conflicts = {
        slot: {"existing": cmap[slot], "proposed": char}
        for slot, char in PROMOTIONS.items()
        if slot in cmap and cmap[slot] != char
    }
    if conflicts:
        raise SystemExit(f"conflicts: {conflicts}")
    for slot, char in PROMOTIONS.items():
        cmap[slot] = char
    payload["verified_charmap"] = dict(sorted(cmap.items(), key=lambda item: int(item[0], 16)))
    payload["combined_slot_count"] = len(cmap)
    payload["added_lis_constant_offset_promotions_20260829"] = {
        slot: {
            "to": char,
            "basis": "contradiction_free_lis_constant_offset_run",
            "evidence": "tools/analyze_ggen_advance_8x16_lis_constant_offset.py; min_support=3; safe-run calibration 49/49 before batch",
        }
        for slot, char in PROMOTIONS.items()
    }
    args.map.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promotions": len(PROMOTIONS), "combined_slot_count": len(cmap)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
