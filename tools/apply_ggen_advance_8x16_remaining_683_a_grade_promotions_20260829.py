#!/usr/bin/env python3
"""Apply the reviewed 2026-08-29 A-grade 8x16 remaining-slot promotions.

Duplicate glyphs (条@0x0387, 敗@0x04C4) are allowed: they are independent
atlas slots with separate ROM/context evidence.  Same-slot collisions refuse.
Immutable unified source and ROM are not touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS = {
    "0x03F4": ("条", "ROM prefix E314 in 勝利条件：/敗北条件：; duplicate of 信条@0x0387"),
    "0x02A4": ("件", "ROM prefix E1C4, pair with 0x03F4=条"),
    "0x063C": ("北", "ROM prefix E55C in 敗北条件：; 12x12 same number coincidental"),
    "0x0591": ("敗", "ROM prefix E4B1; duplicate of 東方不敗@0x04C4"),
    "0x01A3": ("回", "HP/SP 回復 with 復@0x0519; also 回避 frames"),
    "0x0324": ("射", "射撃 with 撃@0x00A2 across defense/AI/weapon"),
    "0x03B4": ("制", "先制攻撃 + 強制散開/出撃"),
    "0x018C": ("化", "ハイパー化 / 移動力強化 / 強化人間"),
    "0x0137": ("」", "closes <0136>…<0137> quotes; 12x12 0x0137=ゾ"),
    "0x045A": ("追", "キャラ/ユニット/パーツ追加; 加@0x018F"),
    "0x02C6": ("合", "間合い / 撃ち合う / 殺し合う / 都合"),
    "0x0283": ("研", "NT研所員 exact vs scenario speaker; pair 0x035E held"),
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified = dict(payload["verified_charmap"])
    collisions = []
    for slot, (char, _evidence) in PROMOTIONS.items():
        current = verified.get(slot)
        if current is not None and current != char:
            collisions.append({"slot": slot, "current": current, "new": char})
    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1
    for slot, (char, _evidence) in PROMOTIONS.items():
        verified[slot] = char
    payload["verified_charmap"] = {
        key: verified[key] for key in sorted(verified, key=lambda value: int(value, 16))
    }
    payload["combined_slot_count"] = len(verified)
    provenance = payload.setdefault("added_remaining_683_a_grade_promotions_20260829", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {
            "to": char,
            "basis": "reviewed_remaining_683_a_grade_20260829",
            "evidence": evidence,
        }
    payload["added_remaining_683_a_grade_promotions_20260829"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda value: int(value, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"result": "PASS", "promoted": len(PROMOTIONS), "combined_slot_count": len(verified)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
