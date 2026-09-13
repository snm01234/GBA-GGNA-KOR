#!/usr/bin/env python3
"""Second A-grade 8x16 batch after the remaining-683 A12 promotions.

These slots were B/hold until neighboring A12 anchors (回/研/」/回復) made
leftover=1 or dual-compound evidence.  Same-slot collisions refuse.
Duplicate glyphs (回/復) are allowed.  Unified source and ROM are not written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS = {
    "0x0136": ("「", "leftover=1 quotes closed by 」: 「アナタに力を……」 / 「だから甘いというのだ……」"),
    "0x0138": ("＋", "leftover=1 stacked effect glue: 先制攻撃＋威力↑ / 威力↑＋封印 / かばう＋装甲↑"),
    "0x01B9": ("回", "回避+回復 in ID descriptions; duplicate of 回@0x01A3"),
    "0x05C8": ("避", "回避 with 回@0x01B9 across many ID-description frames"),
    "0x05F6": ("復", "回復させます with 回@0x01B9; duplicate of 復@0x0519"),
    "0x01CD": ("完", "leftover=1 味方HP完全回復 / 自分HP完全回復"),
    "0x06CD": ("登", "登場 after independent names: バスク/アプサラス/ジオン軍/グロムリン/アークエンジェル"),
    "0x04CD": ("博", "leftover=1 ミカムラ博士; same-ROM exact ミカムラ博士"),
    "0x0130": ("／", "leftover=1 作戦／戦況; same-ROM menu exact"),
    "0x035E": ("所", "leftover=1 NT研所員 after 研@0x0283"),
    "0x0552": ("夜", "leftover=1 夜明けだ / 夜間 索敵中"),
    "0x0513": ("武", "leftover=1 武装ポッド / 武器を捨て"),
    "0x00CF": ("名", "家名にかけて / 名にかけて / 稲妻の名 / 祖国の名誉"),
    "0x071A": ("紅", "紅い稲妻 in two ID-command frames"),
    "0x024C": ("駆", "戦場を駆ける紅い稲妻 with 紅@0x071A"),
    "0x00AC": ("私", "私の戦争 / 私は軍人 / 私が生きのび / 私に力を / 私とてザビ家"),
    "0x00AF": ("者", "滅び行く者 / 強者 / 科学者 / 愚か者"),
    "0x0531": ("返", "繰り返させません / 怒りを返してくれる"),
    "0x05C6": ("歴", "戦いの歴史 leftover=1 once 返 is set; 史 already known"),
    "0x04F3": ("備", "leftover=1 無防備"),
    "0x00A5": ("言", "言うのなら / 一言 / 足りないと言う / 言葉"),
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
    key = "added_remaining_683_a_grade_promotions_batch2_20260829"
    provenance = payload.setdefault(key, {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {
            "to": char,
            "basis": "reviewed_remaining_683_b_upgrade_after_a12",
            "evidence": evidence,
        }
    payload[key] = {k: provenance[k] for k in sorted(provenance, key=lambda value: int(value, 16))}
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
