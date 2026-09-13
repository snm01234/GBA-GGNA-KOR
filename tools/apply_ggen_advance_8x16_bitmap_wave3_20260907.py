#!/usr/bin/env python3
"""Promote wave-3 ID-command 8x16 slots from original-ROM bitmaps."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS: dict[str, tuple[str, str]] = {
    "0x00DE": ("「", "8x16 corner bracket; 「……来ないで！」; dup of 0x0136 allowed"),
    "0x00DF": ("」", "8x16 corner bracket; dup of 0x0137 allowed"),
    "0x010F": ("ざ", "8x16 hiragana ざ; ふざけ/わざわざ/ひざまず"),
    "0x0114": ("ふ", "8x16 hiragana ふ; おふざけでない"),
    "0x011C": ("む", "8x16 hiragana む; 目ん玉ひんむいて"),
    "0x0131": ("〜", "8x16 wave dash; 独立しちまうぞ〜〜"),
    "0x0195": ("果", "8x16 果; pair 結→結果だよ"),
    "0x01DF": ("丸", "8x16 丸; 面目丸潰れ"),
    "0x0210": ("逆", "8x16 辶; 時代に逆らった"),
    "0x0223": ("巨", "8x16 巨; 青い巨星; not 彗"),
    "0x0243": ("玉", "8x16 玉; 目ん玉"),
    "0x024E": ("愚", "8x16 心 bottom; 愚か者"),
    "0x025C": ("刑", "8x16 刂; 処刑なのだよ"),
    "0x0271": ("結", "8x16 糸; 結果だよ"),
    "0x02F5": ("案", "8x16 案; 己で案しろ; 起 already 0x01FE"),
    "0x0330": ("弱", "8x16 弓+弓; この野弱もの collocation held"),
    "0x035C": ("処", "8x16 処; 処刑"),
    "0x0367": ("消", "8x16 氵+肖; ごう慢さを消え"),
    "0x0370": ("承", "8x16 承; 無理は承知"),
    "0x0374": ("消", "8x16 消; この辺で消えて; dup of 0x0367 allowed"),
    "0x037E": ("障", "8x16 阝+章; leftover1 大事に障る"),
    "0x0381": ("冗", "8x16 冗; 冗談じゃないよ"),
    "0x0386": ("情", "8x16 忄+青; 戦いは非情さ"),
    "0x038E": ("ま", "8x16 hiragana ま; dup of 0x0041 allowed"),
    "0x0396": ("心", "8x16 心; 宇宙には心が満ちてる"),
    "0x03AD": ("酔", "8x16 酉; 酔っ払い運転手"),
    "0x03C5": ("青", "8x16 青; 青い巨星"),
    "0x03C6": ("静", "8x16 静; 冷静だ"),
    "0x03DD": ("洗", "8x16 氵+先; 洗礼を受けろ"),
    "0x0408": ("足", "8x16 足; 足りない"),
    "0x0435": ("談", "8x16 言+炎; 冗談"),
    "0x045D": ("潰", "8x16 氵+貴; 丸潰れ"),
    "0x046F": ("天", "8x16 天; 天命"),
    "0x0472": ("転", "8x16 転; 運転手"),
    "0x0478": ("吐", "8x16 口+土; leftover1 血を吐き出せ"),
    "0x04AB": ("野", "8x16 野; pair 弱 collocation held"),
    "0x04C7": ("配", "8x16 配; 革命の気配"),
    "0x04F1": ("非", "8x16 非; 戦いは非情さ"),
    "0x050F": ("父", "8x16 父; 父さま母さま"),
    "0x0517": ("輩", "8x16 輩; 戦争屋輩… collocation held"),
    "0x0530": ("辺", "8x16 辶; この辺で消えて"),
    "0x0539": ("母", "8x16 母; 父さま母さま"),
    "0x0556": ("慢", "8x16 忄; ごう慢さ"),
    "0x0557": ("満", "8x16 氵; 心が満ちてる"),
    "0x05A9": ("理", "8x16 理; 無理は承知"),
    "0x05C1": ("冷", "8x16 冷; 冷静だ"),
    "0x05C2": ("礼", "8x16 礼; 洗礼"),
    "0x06E5": ("命", "8x16 命; 天命; dup of 0x00D0 allowed"),
    "0x06EE": ("攻", "8x16 攻; 攻撃します; dup of 0x02B7 allowed"),
    "0x06F0": ("撃", "8x16 撃; 攻撃します; dup of 0x00A2 allowed"),
    "0x0717": ("独", "8x16 独; 独立しちまうぞ"),
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified = dict(payload["verified_charmap"])
    collisions = [{"slot": s, "current": verified[s], "new": c} for s, (c, _) in PROMOTIONS.items() if s in verified and verified[s] != c]
    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1
    for slot, (char, _e) in PROMOTIONS.items():
        verified[slot] = char
    payload["verified_charmap"] = {k: verified[k] for k in sorted(verified, key=lambda v: int(v, 16))}
    payload["combined_slot_count"] = len(verified)
    provenance = payload.setdefault("added_bitmap_wave3_20260907", {})
    for slot, (char, evidence) in PROMOTIONS.items():
        provenance[slot] = {"to": char, "basis": "original_rom_8x16_bitmap_plus_idcmd_frames", "evidence": evidence}
    payload["added_bitmap_wave3_20260907"] = {k: provenance[k] for k in sorted(provenance, key=lambda v: int(v, 16))}
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "promoted": len(PROMOTIONS), "combined_slot_count": len(verified)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
