#!/usr/bin/env python3
"""Promote remaining leftover=1 8x16 slots from original-ROM bitmaps."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS: dict[str, tuple[str, str]] = {
    "0x00EC": ("L", "8x16 bitmap L; leftover1 PLOT / L1宙域 / L5宙域 / L3コロニー"),
    "0x00F1": ("U", "8x16 bitmap U; leftover1 UNIT flag"),
    "0x01CA": ("寒", "8x16 bitmap 宀 roof; leftover1 寒い時代だと思わんか; 良は既に0x00D5"),
    "0x01DC": ("還", "8x16 bitmap 辶; leftover1 砲撃/射撃帰還しない"),
    "0x0221": ("去", "8x16 bitmap 去; leftover1 みじめな過去の遺物"),
    "0x0276": ("弾", "8x16 bitmap 弾; leftover1 実弾を防ぐ; dup of 0x00C0 allowed"),
    "0x0294": ("個", "8x16 bitmap 亻+固; leftover1 俺個人の意思だ; not 一"),
    "0x030D": ("志", "8x16 bitmap 士+心; leftover1 俺の意志でお前を殺す"),
    "0x0332": ("取", "8x16 bitmap 耳+又; leftover1 受け取れ / 手間取っては"),
    "0x0389": ("状", "8x16 bitmap 丬+犬; leftover1 フラグ状況の確認"),
    "0x03B0": ("数", "8x16 bitmap 数; leftover1 弾数を0/回復"),
    "0x03CF": ("接", "8x16 bitmap 扌; leftover1 近接 / 間接なし"),
    "0x0427": ("達", "8x16 bitmap 辶; leftover1 俺達は軍人だ"),
    "0x0452": ("長", "8x16 bitmap 長; leftover1 隊長の仇 / 艦長"),
    "0x047D": ("都", "8x16 bitmap 阝; leftover1 月都市 + idcmd 都合"),
    "0x048E": ("当", "8x16 bitmap 当; leftover1 該当無し empty-selector"),
    "0x04F0": ("避", "8x16 bitmap 辶+辟; leftover1 回避する; dup of 0x05C8 allowed"),
    "0x0515": ("部", "8x16 bitmap 阝; leftover1 間抜けは部隊に必要ない"),
    "0x052C": ("別", "8x16 bitmap 刂; leftover1 別行動中 / 別れは…"),
    "0x055A": ("未", "8x16 bitmap 未; leftover1 未行動にする"),
    "0x05A1": ("翼", "8x16 bitmap 羽; leftover1 光の翼"),
    "0x05B0": ("漏", "8x16 bitmap 氵 not 暴; leftover1 漏れ弾なんか来るな"),
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
    provenance = payload.setdefault("added_bitmap_remaining_leftover1_20260907", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {
            "to": char,
            "basis": "original_rom_8x16_bitmap_plus_leftover1",
            "evidence": evidence,
        }
    payload["added_bitmap_remaining_leftover1_20260907"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda value: int(value, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promoted": len(PROMOTIONS), "combined_slot_count": len(verified)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
