#!/usr/bin/env python3
"""Promote 8x16 slots identified from original-ROM glyph bitmaps.

Evidence is leftover=1 ID-command frames plus visual reading of the 8x16
glyph.  12x12 slot numbers are never copied.  Duplicate characters are
allowed when the 8x16 bitmap is an independent atlas drawing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

# slot -> (char, evidence)
PROMOTIONS: dict[str, tuple[str, str]] = {
    "0x009A": ("俺", "8x16 bitmap 亻+奄; leftover1 俺はバカ/俺が守って/俺が俺じゃ"),
    "0x00AA": ("思", "8x16 bitmap 田+心; leftover1 と思っていた/思い/思った/本気で思って"),
    "0x00BC": ("隊", "8x16 bitmap 阝; leftover1 ラル隊/クランプ隊"),
    "0x00C0": ("弾", "8x16 bitmap 弓; leftover1 うろたえ弾/無駄弾"),
    "0x00CD": ("本", "8x16 bitmap 本; leftover1 闘争本能/本気/本作"),
    "0x0146": ("愛", "8x16 bitmap 愛; leftover1/idcmd 愛機"),
    "0x0147": ("悪", "8x16 bitmap 悪; leftover1 悪いこと/悪くちゃ"),
    "0x016A": ("噂", "8x16 bitmap 口+尊; leftover1 噂ほどではない"),
    "0x0170": ("英", "8x16 bitmap 艹+央; leftover1 人の英知"),
    "0x0184": ("屋", "8x16 bitmap 尸; leftover1 戦争屋/ゲリラ屋"),
    "0x018A": ("音", "8x16 bitmap 立+日; leftover1 ぐうの音も出ない"),
    "0x0193": ("科", "8x16 bitmap 禾+斗; leftover1 科学者"),
    "0x019D": ("過", "8x16 bitmap 辶; leftover1 見過ごさば/過去"),
    "0x01A1": ("会", "8x16 bitmap 会; leftover1 会えない"),
    "0x01A4": ("壊", "8x16 bitmap 土; leftover1 破壊する"),
    "0x01BB": ("確", "8x16 bitmap 石; leftover1 確かに終わる"),
    "0x01CC": ("巻", "8x16 bitmap 巻; leftover1 尻…を巻いて逃げる"),
    "0x01D0": ("慣", "8x16 bitmap 忄; leftover1 慣れていく"),
    "0x01F7": ("帰", "8x16 bitmap 帰; leftover1 帰れるところ"),
    "0x0212": ("仇", "8x16 bitmap 亻+九; leftover1 アンディの仇/マッシュの仇; dup of 0x02D9 allowed"),
    "0x0217": ("救", "8x16 bitmap 救; leftover1 ツキに救われた"),
    "0x0219": ("求", "8x16 bitmap 求; leftover1 求めた戦争/要求する"),
    "0x02DA": ("佐", "8x16 bitmap 亻+左; leftover1 大佐が戦って"),
    "0x0316": ("歯", "8x16 bitmap 歯; leftover1 歯向かおう"),
    "0x032C": ("借", "8x16 bitmap 亻+昔; leftover1 ルウムの借りを返して"),
    "0x034D": ("重", "8x16 bitmap 重; leftover1 重要なのは"),
    "0x034E": ("銃", "8x16 bitmap 金; leftover1 銃を撃って/撃ち合う"),
    "0x0399": ("新", "8x16 bitmap 新; leftover1 人類の革新"),
    "0x03A2": ("進", "8x16 bitmap 辶+隹; leftover1 進攻する"),
    "0x03AB": ("術", "8x16 bitmap 行; leftover1 術のひとしずく"),
    "0x03F8": ("相", "8x16 bitmap 木+目; leftover1 相手をして/お相手しよう"),
    "0x03FA": ("蒼", "8x16 bitmap 艹; leftover1 蒼い宇宙"),
    "0x040F": ("存", "8x16 bitmap 存; leftover1 存分に殺し合う"),
    "0x0426": ("叩", "8x16 bitmap 口+卩; leftover1 叩く/叩き込め"),
    "0x0434": ("男", "8x16 bitmap 田+力; leftover1 ボクは男/ザビ家の男"),
    "0x0467": ("程", "8x16 bitmap 禾; leftover1 この程度の攻撃"),
    "0x0480": ("怒", "8x16 bitmap 奴+心 not 雨; leftover1 空を落とす怒り"),
    "0x04A0": ("毒", "8x16 bitmap 毒; leftover1 気の毒だが"),
    "0x04B5": ("熱", "8x16 bitmap 灬 bottom; leftover1 熱くならないで/熱き…を我が; 泣は文法不一致"),
    "0x0507": ("付", "8x16 bitmap 亻+寸; leftover1 染み付いて"),
    "0x0541": ("法", "8x16 bitmap 氵+去; leftover1 ディアナの法の裁き"),
    "0x0562": ("夢", "8x16 bitmap 夢; leftover1 人の夢/私の夢"),
    "0x0580": ("訳", "8x16 bitmap 言; leftover1 掛けさせる訳には"),
    "0x0587": ("優", "8x16 bitmap 亻; leftover1 優先される"),
    "0x058D": ("誘", "8x16 bitmap 言+秀; leftover1 誘ったのはお前"),
    "0x0594": ("誉", "8x16 bitmap 誉; leftover1 祖国の名誉"),
    "0x059C": ("葉", "8x16 bitmap 艹; leftover1 言葉だけじゃ"),
    "0x05AE": ("立", "8x16 bitmap 立; leftover1 戦場に立つ者"),
    "0x05DB": ("腕", "8x16 bitmap 月; leftover1 腕のサエ"),
    "0x0628": ("識", "8x16 bitmap 言; leftover1 事実を認識してください; 謙は文脈不一致"),
    "0x06B0": ("獄", "8x16 vs 12x12 獄@0x030B; leftover1 地獄に引きずり込んで; 獣は地獣で不一致"),
    "0x0800": ("淀", "8x16 bitmap 氵; leftover1 淀みを正す"),
    "0x0803": ("吼", "8x16 bitmap 口+孔; leftover1 ギャンギャン吼えんな"),
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
    provenance = payload.setdefault("added_bitmap_idcmd_leftover1_20260907", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {
            "to": char,
            "basis": "original_rom_8x16_bitmap_plus_idcmd_leftover1",
            "evidence": evidence,
        }
    payload["added_bitmap_idcmd_leftover1_20260907"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda value: int(value, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "promoted": len(PROMOTIONS),
                "combined_slot_count": len(verified),
                "chars": [f"{slot}={char}" for slot, (char, _e) in PROMOTIONS.items()],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
