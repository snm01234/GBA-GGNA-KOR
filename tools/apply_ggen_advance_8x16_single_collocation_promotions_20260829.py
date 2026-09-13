#!/usr/bin/env python3
"""Apply the first reviewed 8x16 single-collocation promotion batch.

Evidence was reviewed against production/UI contexts, same-ROM fully decoded
Japanese, Shift-JIS ordered blocks, and/or the 8x16 bitmap ensemble.  This
script is a reproducible description of the batch; it refuses collisions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS = {
    "0x00B1": ("手", "地球は我々の手によって / 手かげん context; bitmap rank1"),
    "0x00B2": ("出", "最大出力; base Shift-JIS block order; bitmap rank3; same-ROM 最大出力"),
    "0x00BF": ("誰", "もう誰も悲しませはしない / 誰よりも; base Shift-JIS block order"),
    "0x00D5": ("良", "ようし、良い子だ / 良い…; base Shift-JIS block order"),
    "0x0112": ("ぱ", "やられっぱなし fixed phrase; bitmap rank6"),
    "0x0157": ("移", "移動力↑; bitmap rank1"),
    "0x0160": ("員", "全員レベル50; short exact-count ordered interval; bitmap rank4"),
    "0x0165": ("隠", "身を隠す; short exact-count ordered interval"),
    "0x01B7": ("拡", "拡散メガ粒子砲; short exact-count ordered interval; bitmap rank11"),
    "0x01C1": ("楽", "ドンパチ楽しもうじゃないか; bitmap rank9"),
    "0x01C4": ("活", "MSの性能を活かせぬまま; bitmap rank1"),
    "0x01D6": ("甘", "だから甘いというのだ; same-ROM exact phrase; bitmap rank2"),
    "0x01EA": ("器", "ビーム兵器 / 武器; repeated semantic contexts; bitmap rank9"),
    "0x01F8": ("気", "一気にいく; multiple ID-command contexts; bitmap rank2"),
    "0x0206": ("技", "MSの格闘技を見せてやる; same-ROM exact phrase; bitmap rank1"),
    "0x0281": ("犬", "負け犬にはならない; same-ROM exact phrase; bitmap rank1"),
    "0x0297": ("己", "敵を知り、己を知れば; bitmap rank3"),
    "0x029C": ("誇", "オレの誇りのために戦う; bitmap rank1"),
    "0x02AC": ("好", "好きにさせるかよ; bitmap rank7"),
    "0x02CE": ("黒", "黒い三連星; same-ROM exact phrase; bitmap rank1"),
    "0x02E8": ("裁", "EXAMによって裁かれるがいい; same-ROM exact phrase; bitmap rank12"),
    "0x0321": ("失", "なすべきことを見失った; bitmap rank1"),
    "0x0387": ("条", "しつこいのが信条だ; same-ROM 信条; bitmap rank1"),
    "0x039E": ("神", "オレは死神じゃない; bitmap rank1"),
    "0x03D4": ("絶", "絶対に死ぬな; same-ROM exact phrase; bitmap rank4"),
    "0x0437": ("恥", "恥かかすんじゃねぇぞ; same-game corpus; bitmap rank9"),
    "0x0441": ("着", "まだ決着は着いていない; same-ROM 決着; bitmap rank7"),
    "0x04B3": ("認", "貴様らを認めない / 確認; bitmap rank1"),
    "0x054C": ("防", "バルジ攻防戦 / ビーム兵器を防ぐ / defense effects"),
    "0x0573": ("目", "目を覚ませ; same-ROM exact phrase; bitmap rank4"),
    "0x05D6": ("話", "その機体では話にならんな; bitmap rank1"),
    "0x07CE": ("捧", "我が祖国に捧げる; bitmap rank1"),
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
    provenance = payload.setdefault("added_single_collocation_promotions_20260829", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {"to": char, "basis": "reviewed_single_collocation_cross_evidence", "evidence": evidence}
    payload["added_single_collocation_promotions_20260829"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda value: int(value, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promoted": len(PROMOTIONS), "combined_slot_count": len(verified)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
