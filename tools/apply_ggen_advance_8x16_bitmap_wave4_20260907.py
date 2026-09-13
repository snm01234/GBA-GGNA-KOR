#!/usr/bin/env python3
"""Promote wave-4 ID-command 8x16 slots from original-ROM bitmaps."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS: dict[str, tuple[str, str]] = {
    "0x0111": ("づ", "8x16 つ+dakuten; IoU 0.833 vs つ 0x0032; ず already 0x0029; ひざまづいて"),
    "0x0198": ("火", "8x16 火 (大+sparks); leftover1 火消しの輩; not 根/星"),
    "0x021A": ("泣", "8x16 氵+立; 泣き叫びなさい"),
    "0x032B": ("抵", "8x16 扌+氐; leftover2 抵抗者; dup of 0x0465 allowed"),
    "0x034F": ("宿", "8x16 宀+佰; 血塗られた宿命"),
    "0x03E3": ("謂", "8x16 言+胃; 所謂は…; 業 already 0x023F"),
    "0x0479": ("塗", "8x16 氵+余; 血塗られた"),
    "0x054F": ("抗", "8x16 IoU 0.55 vs 抗 0x02B5; leftover2 抵抗者; dup allowed"),
    "0x0801": ("叫", "8x16 口+丩; 泣き叫びなさい"),
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified = dict(payload["verified_charmap"])
    collisions = [
        {"slot": slot, "current": verified[slot], "new": char}
        for slot, (char, _evidence) in PROMOTIONS.items()
        if slot in verified and verified[slot] != char
    ]
    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1
    for slot, (char, _evidence) in PROMOTIONS.items():
        verified[slot] = char
    payload["verified_charmap"] = {key: verified[key] for key in sorted(verified, key=lambda value: int(value, 16))}
    payload["combined_slot_count"] = len(verified)
    provenance = payload.setdefault("added_bitmap_wave4_20260907", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {
            "to": char,
            "basis": "original_rom_8x16_bitmap_plus_idcmd_frames",
            "evidence": evidence,
        }
    payload["added_bitmap_wave4_20260907"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda value: int(value, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promoted": len(PROMOTIONS), "combined_slot_count": len(verified)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
