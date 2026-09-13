#!/usr/bin/env python3
"""Promote leftover=1/2 ID-command slots from bitmap wave 2."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS: dict[str, tuple[str, str]] = {
    "0x0272": ("血", "8x16 bitmap 血; 熱き血潮を我が血として"),
    "0x0349": ("十", "8x16 bitmap 十; 十分速いさ"),
    "0x0353": ("熟", "8x16 bitmap 熟; leftover1 ……未熟！"),
    "0x036D": ("小", "8x16 bitmap 小; 第4小隊"),
    "0x03A1": ("辛", "8x16 bitmap 辛; leftover1 別れは辛いものだが"),
    "0x0409": ("速", "8x16 bitmap 辶; 十分速いさ; 強 already 0x022F"),
    "0x0422": ("第", "8x16 bitmap 第; 不死身の第4小隊"),
    "0x044E": ("潮", "8x16 bitmap 潮; 熱き血潮"),
    "0x045C": ("通", "8x16 bitmap 辶+甬; 都合通り / 通用しない; not よ/使"),
    "0x0498": ("同", "8x16 bitmap 同; 同じ技は通用しない"),
    "0x05A3": ("頼", "8x16 bitmap 頼; leftover1 頼りない艦長"),
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified = dict(payload["verified_charmap"])
    collisions = [ {"slot": s, "current": verified[s], "new": c} for s, (c, _) in PROMOTIONS.items() if s in verified and verified[s] != c ]
    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1
    for slot, (char, _e) in PROMOTIONS.items():
        verified[slot] = char
    payload["verified_charmap"] = {k: verified[k] for k in sorted(verified, key=lambda v: int(v, 16))}
    payload["combined_slot_count"] = len(verified)
    provenance = payload.setdefault("added_bitmap_remaining_wave2_20260907", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {"to": char, "basis": "original_rom_8x16_bitmap_plus_idcmd_frames", "evidence": evidence}
    payload["added_bitmap_remaining_wave2_20260907"] = {k: provenance[k] for k in sorted(provenance, key=lambda v: int(v, 16))}
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promoted": len(PROMOTIONS), "combined_slot_count": len(verified)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
