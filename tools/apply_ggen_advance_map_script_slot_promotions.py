#!/usr/bin/env python3
"""Promote unanimous map-script leftover 12x12 slots.

Only compounds that independently agree in this bank.  Does not copy 8x16
numbers, does not rewrite the immutable unified source, and refuses a slot
that already maps to a different character.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

# leftover frames in legacy/analysis/ggen_advance_map_script_translation_source_20260828.json
# Batch 1: first-pass screenshot compounds.
MAP_SCRIPT_BATCH: dict[str, str] = {
    "0x069F": "絡",
    "0x0243": "級",
    "0x05AF": "搬",
    "0x0483": "捜",
    "0x03BD": "巡",
    "0x0614": "辺",
    "0x0613": "編",
    "0x0351": "司",
    "0x00EE": "『",
    "0x024B": "挙",
    "0x02B8": "遣",
    "0x02C8": "固",
    "0x0375": "耳",
    "0x03C0": "初",
    "0x056F": "那",
    "0x06A3": "覧",
}

# Batch 2: leftover==1 frames independently agree.  Held mixed slots
# (准/少, 父/護, 着/働, 選/生, 禁/視, 設/廃, …) are not listed.
MAP_SCRIPT_BATCH2: dict[str, str] = {
    "0x062A": "胞",  # 同胞
    "0x0496": "修",  # 改修 (12x12 0x039D 修 duplicate)
    "0x05A0": "線",  # 死線の虎 (0x046C 線 duplicate)
    "0x03C5": "諸",  # 諸君
    "0x0322": "再",  # 再チャージ / 再編 / 再生
    "0x0269": "局",  # 結局 / 戦局 / 大局
    "0x01C3": "君",  # 君を危険に (0x0283 君 duplicate)
    "0x06D7": "労",  # ご苦労 / 気苦労
    "0x060B": "陛",  # 陛下
    "0x0557": "到",  # 到着 / 到達
    "0x0554": "答",  # 応答 / 返答 / 問答
    "0x045A": "説",  # 説明 / 演説 / 説得
    "0x0210": "嬉",  # 嬉しい
    "0x0650": "満",  # 満足 / 不足
    "0x043E": "声",  # 声が聞こえた
    "0x0380": "質",  # 質問 / 人質 / 異質
    "0x0217": "母",  # 母艦 (0x061E 母 duplicate)
    "0x0443": "請",  # 要請
    "0x059F": "迫",  # 迫って / 気迫
    "0x0334": "材",  # 資材 / 素材
    "0x01C6": "階",  # 階級 / 段階
    "0x052A": "適",  # 適任 / 適切
    "0x0412": "辛",  # 辛い
    "0x0407": "慎",  # 慎重
    "0x03AA": "住",  # 住む
    "0x027D": "遇",  # 遭遇
    "0x025E": "狂",  # 狂気 / 酔狂
    "0x018C": "汚",  # 汚染 / 汚す / 汚い
    "0x0656": "嫌",  # 嫌だ (0x02AA 嫌 duplicate)
    "0x0454": "跡",  # 追跡
    "0x0668": "滅",  # 消滅 (0x0660 滅 duplicate)
    "0x0631": "坊",  # 坊ちゃん / 坊や
    "0x0630": "静",  # 静観 (0x0447 静 duplicate)
    "0x05C5": "秘",  # 秘密 / 守秘
    "0x0583": "悩",  # 悩んで
    "0x0566": "督",  # 提督
    "0x04D7": "端",  # 極端 / 下っ端
    "0x04C7": "託",  # 結託 / 託された
    "0x04C3": "鷹",  # エンデュミオンの鷹
    "0x04AA": "村",  # 村人 / 村ごと
    "0x04A5": "揃",  # 揃えば / 揃いも揃って
    "0x0313": "婚",  # 婚約 / 結婚
    "0x01E7": "勘",  # 勘違い
    "0x0100": "9",  # F91 / GX-9900
    "0x06C8": "霊",  # 亡霊
    "0x0698": "遥",  # 遥かに
    "0x0661": "免",  # 御免
    "0x06C4": "敵",  # 敵の白いヤツ (0x00CE 敵 duplicate)
    "0x0240": "続",  # 続いて (0x04A4 続 duplicate)
    "0x0143": "ν",  # νガンダムはダテじゃない
    "0x06CB": "線",  # 戦線 (0x046C 線 duplicate)
}

# Batch 3: leftover==1 after batch2 cascade. Mixed compounds still held
# (准/少, 父/護, 呪/縛, 選/生, 禁/視, 設/廃, 間/場, 酷/念, 納/収, 薬/弾, …).
MAP_SCRIPT_BATCH3: dict[str, str] = {
    "0x03E9": "詳",  # 詳しい話 / 詳しい説明
    "0x038B": "捕",  # 捕りられた / 捕るつもり (0x061A 捕 duplicate)
    "0x0204": "含",  # 含まれている / 含め
    "0x0144": "I",  # Iフィールド (0x0102 I duplicate)
    "0x0525": "締",  # 引き締めて
    "0x02AB": "改",  # 改修 (0x00A5 改 duplicate)
    "0x05C7": "費",  # 消費する
    "0x041B": "迅",  # 迅速
    "0x0540": "途",  # 途切れて / 途中
    "0x0153": "依",  # 依然として
    "0x00FE": "8",  # 80M / 80％ (0x00FF 8 duplicate)
    "0x0639": "冒",  # 危険を冒して
    "0x0635": "房",  # 独房
    "0x02F6": "港",  # 寄港中 / 入港
    "0x0431": "凄",  # 凄腕 / 凄まじい
    "0x0377": "辞",  # 世辞 / 辞める
    "0x0198": "覚",  # 覚えて (0x01D5 覚 duplicate)
    "0x0274": "句",  # 文句
    "0x02F9": "硬",  # 強硬的 / 強硬派
    "0x0173": "嘘",  # 嘘は言ってません / 嘘も冗談も
    "0x05EB": "腐",  # 腐った性根 / 腐敗
    "0x0588": "把",  # 把握
    # Corrected by context repair: this slot is 宮; true 棺 is 0x01F3.
    "0x023C": "宮",
    "0x0503": "潮",  # 潮時
    "0x064C": "暗",  # 暗殺 (0x014E 暗 duplicate)
    "0x0150": "駄",  # 無駄に (0x04B2 駄 duplicate)
    "0x0563": "徳",  # 不徳
    "0x019B": "恩",  # 恩も忘れ / 恩だって
    "0x04F3": "忠",  # 忠告 / 忠勇
    "0x03A2": "臭",  # 青臭い
    "0x0450": "律",  # 軍律 (0x06AA 律 duplicate)
    "0x06E7": "僭",  # 僭越
}

# Batch 4: leftover==1 after batch3 cascade. Two independent compounds.
MAP_SCRIPT_BATCH4: dict[str, str] = {
    "0x02AD": "懸",  # 命を懸けた / 懸念
    "0x021F": "記",  # 記憶
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified = {str(slot): str(char) for slot, char in payload["verified_charmap"].items()}
    proposed = dict(MAP_SCRIPT_BATCH)
    proposed.update(MAP_SCRIPT_BATCH2)
    proposed.update(MAP_SCRIPT_BATCH3)
    proposed.update(MAP_SCRIPT_BATCH4)
    applied: dict[str, str] = {}
    skipped_same: list[str] = []
    collisions: list[str] = []
    for slot, char in proposed.items():
        existing = verified.get(slot)
        if existing == char:
            skipped_same.append(slot)
            continue
        if existing is not None and existing != char:
            collisions.append(f"{slot} has {existing!r}, refused {char!r}")
            continue
        verified[slot] = char
        applied[slot] = char
    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1
    payload["verified_charmap"] = {
        key: verified[key] for key in sorted(verified, key=lambda item: int(item, 16))
    }
    payload["added_map_script_20260828"] = {
        key: MAP_SCRIPT_BATCH[key] for key in MAP_SCRIPT_BATCH if key in verified and verified[key] == MAP_SCRIPT_BATCH[key]
    }
    payload["added_map_script_20260828_batch2"] = {
        key: MAP_SCRIPT_BATCH2[key] for key in MAP_SCRIPT_BATCH2 if key in applied or verified.get(key) == MAP_SCRIPT_BATCH2[key]
    }
    payload["added_map_script_20260828_batch3"] = {
        key: MAP_SCRIPT_BATCH3[key] for key in MAP_SCRIPT_BATCH3 if key in applied or verified.get(key) == MAP_SCRIPT_BATCH3[key]
    }
    payload["added_map_script_20260828_batch4"] = {
        key: MAP_SCRIPT_BATCH4[key] for key in MAP_SCRIPT_BATCH4 if key in applied or verified.get(key) == MAP_SCRIPT_BATCH4[key]
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "applied": len(applied),
                "already_present": len(skipped_same),
                "verified_charmap": len(payload["verified_charmap"]),
                "promoted": applied,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
