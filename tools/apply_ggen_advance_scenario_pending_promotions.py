#!/usr/bin/env python3
"""Apply leftover-1 scenario 12x12 promotions into the identified charmap.

Does not rewrite the immutable source or build a ROM.  Refuses a slot that
already maps to a different character.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
PROMO_OUT = ROOT / "analysis" / "ggen_advance_scenario_pending_slot_promotions_batch2_20260828.json"

# leftover==1 frames independently agree.  Do not copy 8x16 numbers.
# If the intended kanji is already on another slot, pick the remaining reading
# (遠 not 長, 総 not 乗, 認 not 容, 怒 not 愛, 成 not 果).
BATCH2: dict[str, str] = {
    "0x0722": "瀕",
    "0x0392": "殊",
    "0x0137": "ゾ",
    "0x01B2": "過",
    "0x05DF": "付",
    "0x040E": "真",
    "0x04E9": "遅",
    "0x015F": "違",
    "0x02E7": "好",
    "0x0579": "入",
    "0x04A9": "損",
    "0x054D": "投",
    "0x0506": "調",
    "0x0238": "仇",
    "0x012F": "ぶ",
    "0x0125": "ぎ",
    "0x030F": "込",
    "0x034C": "残",
    "0x0627": "放",
    "0x065F": "迷",
    "0x0580": "念",
    "0x0124": "う",
    "0x05D4": "標",
    "0x024D": "許",
    "0x0123": "い",
    "0x012B": "づ",
    "0x00BA": "守",
    "0x0259": "恐",
    "0x0513": "追",
    "0x048A": "総",
    "0x05A9": "抜",
    "0x051B": "低",
    "0x0559": "討",
    "0x0435": "成",
    "0x01C8": "外",
    "0x01A5": "可",
    "0x0689": "遊",
    "0x06AF": "留",
    "0x057D": "認",
    "0x012C": "ぱ",
    "0x057B": "任",
    "0x0527": "諦",
    "0x01EF": "感",
    "0x018B": "遠",
    "0x063C": "北",
    "0x0562": "得",
    "0x03FD": "触",
    "0x05AC": "分",
    "0x0370": "持",
    "0x0671": "野",
    "0x035A": "志",
    "0x0232": "爪",
    "0x0560": "道",
    "0x064A": "幕",
    "0x05F3": "風",
    "0x02DB": "護",
    "0x0444": "黙",
    "0x04E1": "談",
    "0x051F": "底",
    "0x0659": "務",
    "0x027B": "食",
    "0x0236": "逆",
    "0x036B": "歯",
    "0x04E0": "男",
    "0x038F": "弱",
    "0x055B": "頭",
    "0x00D9": "名",
    "0x0299": "迎",
    "0x0675": "約",
    "0x063A": "謀",
    "0x014D": "安",
    "0x0424": "遂",
    "0x06E1": "話",
    "0x055F": "導",
    "0x013B": "ペ",
    "0x051E": "定",
    "0x043D": "精",
    "0x0260": "胸",
    "0x04B8": "怠",
    "0x041D": "図",
    "0x04E2": "値",
    "0x047C": "語",
    "0x0633": "忘",
    "0x014B": "圧",
    "0x04EF": "着",
    "0x022C": "犠",
    "0x0399": "収",
    "0x0264": "鏡",
    "0x057F": "歩",
    "0x061B": "歩",
    "0x0500": "懲",
    "0x0395": "趣",
    # Corrected by context repair: this slot is 女; 壁 is 0x060D.
    "0x03C7": "女",
    "0x03A3": "衆",
    "0x0537": "点",
    "0x05FB": "複",
    "0x01BF": "戒",
    "0x0160": "遺",
    "0x05B5": "飯",
    "0x05B1": "犯",
    "0x04D6": "短",
    "0x06EE": "彗",
    "0x0484": "掃",
    "0x073F": "陶",
    "0x04E4": "恥",
    "0x037A": "識",
    "0x0284": "訓",
    "0x01DA": "学",
    "0x03D1": "将",
    "0x064E": "万",
    "0x0546": "怒",
    "0x0575": "渋",
    "0x0207": "頑",
    "0x0400": "尻",
    "0x01C0": "械",
    "0x0532": "填",
    "0x0598": "売",
    "0x03FC": "徐",
    "0x0132": "ぺ",
    "0x061E": "母",
    "0x068D": "与",
}

BATCH3: dict[str, str] = {
    "0x04A4": "続",
    "0x0295": "継",
    "0x0612": "叩",
    "0x0615": "返",
    "0x0281": "繰",
    "0x06CA": "歴",
    "0x06B1": "慮",
    "0x066C": "帰",
    "0x0203": "丸",
    "0x041C": "丸",
    "0x015E": "維",
    "0x03AC": "十",
    # Corrected by context repair: this slot is 充; 十 is 0x03AC.
    "0x03AB": "充",
    "0x031E": "死",
    "0x01A6": "島",
    "0x02D9": "誤",
    "0x04CC": "達",
    "0x0681": "友",
    # Corrected by context repair: this slot is 還.
    "0x0200": "還",
    "0x01B8": "解",
    "0x0294": "経",
    "0x02BB": "験",
    "0x02A8": "圏",
    "0x03A9": "醜",
    "0x04B9": "態",
    # Corrected by context repair: this slot is 銃.
    "0x03B0": "銃",
    "0x03B4": "術",
    "0x0152": "位",
    "0x0385": "冷",
    "0x0619": "保",
    "0x03E8": "証",
    # Corrected by context repair: this slot is 怨; 遺 is 0x0160.
    "0x0186": "怨",
    "0x0733": "襟",
    "0x060D": "壁",
    "0x0387": "心",
    # Corrected by context repair: this slot is 像; 党 remains on 0x0548.
    "0x0492": "像",
    "0x053F": "賭",
    "0x05FA": "腹",
    "0x05D8": "評",
    "0x052E": "撤",
    "0x071A": "板",
    "0x05C9": "腕",
    "0x0414": "航",
    "0x0597": "甘",
    "0x01F9": "管",
    # Corrected by context repair: this slot is 久.
    "0x0237": "久",
    "0x0130": "ぷ",
    "0x072C": "堪",
    "0x07A3": "神",
    "0x069A": "抑",
    "0x0417": "刃",
    # Corrected by context repair: this slot is 置; 捨 is 0x0383.
    "0x04E7": "置",
    "0x0420": "推",
    "0x00FC": "5",
    "0x0688": "誘",
    "0x0296": "計",
    "0x0349": "画",
    "0x068C": "余",
}

BATCH4: dict[str, str] = {
    "0x0482": "想",
    "0x045C": "絶",
    "0x03AF": "重",
    "0x065A": "夢",
    "0x048F": "送",
    "0x0477": "素",
    "0x02DA": "誤",
    "0x02E4": "口",
    "0x060E": "別",
    "0x066E": "問",
    "0x049B": "息",
    "0x0724": "姓",
    "0x0174": "噂",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified: dict[str, str] = payload["verified_charmap"]
    added: dict[str, str] = payload.setdefault("added", {})
    batch2: dict[str, str] = payload.setdefault("added_scenario_pending_20260828_batch2", {})
    batch3: dict[str, str] = payload.setdefault("added_scenario_pending_20260828_batch3", {})
    batch4: dict[str, str] = payload.setdefault("added_scenario_pending_20260828_batch4", {})

    collisions: list[str] = []
    applied: dict[str, str] = {}
    skipped_same: list[str] = []
    combined = dict(BATCH2)
    combined.update(BATCH3)
    combined.update(BATCH4)
    for slot, char in combined.items():
        existing = verified.get(slot)
        if existing == char:
            skipped_same.append(slot)
            continue
        if existing is not None and existing != char:
            collisions.append(f"{slot} has {existing!r}, refused {char!r}")
            continue
        verified[slot] = char
        added[slot] = char
        if slot in BATCH4:
            batch4[slot] = char
        elif slot in BATCH3:
            batch3[slot] = char
        else:
            batch2[slot] = char
        applied[slot] = char

    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1

    payload["verified_charmap"] = {
        key: verified[key] for key in sorted(verified, key=lambda s: int(s, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PROMO_OUT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "date": "20260828",
                "font_mode": "12x12",
                "policy": (
                    "leftover==1 frames independently agree; bark-only unique compounds allowed; "
                    "do not copy 8x16 numbers; if the obvious kanji already lives on another "
                    "12x12 slot, keep the remaining reading"
                ),
                "promoted_count": len(applied),
                "verified_charmap_size": len(payload["verified_charmap"]),
                "promoted": applied,
                "already_present": skipped_same,
                "held_conflicts": [],
                "resolved_by_existing_map_or_glyph": [
                    "0x04A4 引き続き/続く/連続/継続 → 続 (引き返し was wrong)",
                    "0x0482 予想/理想/想い → 想",
                    "0x045C 絶望/絶対/根絶やし/絶好 → 絶",
                    "0x03AF 重力/重い/重ね → 重",
                    "0x065A 夢のため/悪い夢 → 夢",
                    "0x048F 送って/転送 → 送",
                    "0x0477 素人/素直/素手 → 素",
                    "0x049B 姑息/息の根 → 息",
                    "0x0724 百姓一揆 → 姓",
                    "0x0174 噂ほどではない → 噂",
                    "0x012F ぶ fills 12x12 しぶと; 8x16 0x0115 stays unpromoted (1 vote)",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "applied": len(applied),
                "already_present": len(skipped_same),
                "verified_charmap": len(payload["verified_charmap"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
