#!/usr/bin/env python3
"""Reproducible second reviewed 8x16 single-collocation promotion batch.

This file records the reviewed assignments and refuses collisions.  Evidence is
same-ROM text, production/UI table structure, exact phrase closure, and/or the
8x16 bitmap ensemble.  The immutable unified source and ROM are not touched.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS = {
    "0x009B": ("何", "何様のつもりだ / 何てお上手なんでしょ; same-ROM 何様; base Shift-JIS block"),
    "0x010D": ("ぐ", "ビーム兵器を防ぐ repeated unit-defense rows; same-ROM 防ぐ; bitmap top4"),
    "0x010E": ("ご", "……ごあいさつだな; bitmap rank1"),
    "0x011E": ("ゆ", "変わってゆく / あらゆる攻撃を防ぐ; independent contexts; bitmap rank1"),
    "0x0155": ("為", "信じるものの為には; bitmap rank1"),
    "0x016B": ("運", "どんな運命だろうと; same-ROM 運命; bitmap rank1"),
    "0x0192": ("家", "ザビ家 / 家名 / ムーンレィスのための国家; bitmap rank1"),
    "0x01A2": ("身", "分身 static selector; production corpus contains 分身"),
    "0x0238": ("脅", "ジオンの脅威; same-ROM 脅威; bitmap rank1"),
    "0x025D": ("兄", "お兄さまの力になりたい; same-ROM お兄さま; bitmap top10"),
    "0x02AF": ("戦", "戦場 label between moon/crater/city/base terrain labels; same-ROM 戦場"),
    "0x02C3": ("散", "宇宙に散る星 and 散開することはありません context"),
    "0x02D3": ("今", "あたしゃ、今こそ戦うんだ; same-ROM 今こそ戦う; bitmap rank1"),
    "0x02D9": ("仇", "マッシュの仇よ; same-ROM exact マッシュの仇"),
    "0x0302": ("使", "UI status 使用中; repeated production contexts; bitmap top20"),
    "0x0323": ("実", "黒い三連星の実力 / 作戦実行中; same-ROM 実力"),
    "0x033F": ("修", "修正してやるっ; same-ROM exact 修正してやる"),
    "0x0363": ("女", "女だからって / ヘリオポリスの少女 context; same-ROM 女だからって"),
    "0x03CE": ("き", "大きな、力…… fixed phrase"),
    "0x03D6": ("先", "先制攻撃 effect and 二手三手先を; bitmap rank1"),
    "0x03FF": ("増", "悲しみを増やしちゃいけない; bitmap top30"),
    "0x0402": ("造", "static map-system label 改造; bitmap rank1"),
    "0x0429": ("脱", "unit AI type 脱出; same-ROM 脱出; bitmap top20"),
    "0x0469": ("的", "こんな一方的な戦い; bitmap top30"),
    "0x04BF": ("破", "撃破する / ドズル撃破ON / 破壊中 family; same-ROM 撃破する"),
    "0x04D7": ("抜", "間抜け / 戦い抜いて見せる; bitmap rank1"),
    "0x0519": ("復", "味方一人復活 / HP回復 effect family; same-ROM 復活"),
    "0x0525": ("基", "基地 repeated series/location label; project corpus contains 基地"),
    "0x0572": ("抹", "世界が我らを抹殺するから; followed by known 殺"),
    "0x05AF": ("防", "ソロモン攻防戦; independent 0x054C=防 already established"),
    "0x05BC": ("輪", "メビウスの輪から; bitmap top10"),
    "0x05FE": ("全", "1T全能力↑; exact existing production translation corpus"),
}


def main() -> int:
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
    provenance = payload.setdefault("added_single_collocation_promotions_batch2_20260829", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {
            "to": char,
            "basis": "reviewed_single_collocation_cross_evidence_batch2",
            "evidence": evidence,
        }
    payload["added_single_collocation_promotions_batch2_20260829"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda value: int(value, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promoted": len(PROMOTIONS), "combined_slot_count": len(verified)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
