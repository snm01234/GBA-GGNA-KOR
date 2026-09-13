#!/usr/bin/env python3
"""Apply the final manually reviewed map-script context promotions.

These slots were left after the automated context/glyph and high-context
passes.  Each has a uniquely readable Japanese compound or phrase; the four
remaining collision slots are deliberately kept unresolved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

PROMOTION_BATCH: dict[str, str] = {
    # Context-only candidates left from the high-confidence pass.
    "0x0572": "縄",  # 一筋縄ではいかない
    "0x06D0": "誰",  # 誰のせいですかな
    # Context overrides where an external-font nearest glyph was a false match.
    "0x0109": "Ｕ",  # CPU回り
    "0x015A": "様",  # 様子
    "0x0178": "用",  # 管理運用
    "0x01AE": "現",  # 現実が動く
    "0x01D4": "入",  # 収入
    "0x021C": "知",  # 知っていた
    "0x0289": "方",  # 方向
    "0x02B1": "抑",  # 抑制
    "0x02D2": "2",  # 2時
    "0x02D4": "艦",  # 艦長
    "0x02F1": "違",  # 違和感
    "0x0315": "害",  # 害虫
    "0x0319": "僅",  # 僅少
    "0x0337": "動",  # 動く
    "0x034B": "唾",  # 虫唾
    "0x038D": "説",  # 説明
    "0x03DC": "期",  # 長期化
    "0x044A": "撃",  # 出撃
    "0x050B": "御",  # 御命
    "0x0528": "長",  # 長期化
    "0x0581": "人",  # 人間
    "0x064B": "間",  # 人間
    "0x06E2": "汲",  # 汲んで
    # Paired/collision reads whose surrounding phrase is conclusive.
    "0x020F": "大",  # 大きな声; first source line has a known omitted い
    "0x0225": "鬼",  # 鬼子
    "0x0373": "磁",  # 電磁波
    "0x058A": "波",  # 電磁波障害
    "0x06A2": "波",  # 電磁波が収まらなきゃ
    "0x06C9": "き",  # 大きな声
}

HELD_FOR_SOURCE_REVIEW: dict[str, str] = {
    "0x0360": "獅子/固有名の文脈（オーブの□子の□）を再確認",
    "0x03B7": "青□してて is not a stable lexical reading",
    "0x0585": "納得 and 収める require incompatible values on one slot",
    "0x065C": "固有名 phrase and 小□ (小僧等) contexts compete",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified: dict[str, str] = payload["verified_charmap"]
    collisions: list[str] = []
    applied: dict[str, str] = {}
    already_present: list[str] = []
    for slot, char in PROMOTION_BATCH.items():
        current = verified.get(slot)
        if current == char:
            already_present.append(slot)
        elif current is not None:
            collisions.append(f"{slot} has {current!r}, refused {char!r}")
        else:
            verified[slot] = char
            applied[slot] = char
    if collisions:
        print(json.dumps({"result": "FAIL", "collisions": collisions}, ensure_ascii=False, indent=2))
        return 1

    payload["verified_charmap"] = {
        key: verified[key] for key in sorted(verified, key=lambda item: int(item, 16))
    }
    provenance = payload.setdefault("added_map_script_manual_context_20260828", {})
    for slot, char in PROMOTION_BATCH.items():
        provenance[slot] = {
            "to": char,
            "basis": "manual_source_phrase_review",
            "audit": "legacy/analysis/ggen_advance_map_script_unresolved_slot_audit_20260828_context_repairs.json",
        }
    payload["added_map_script_manual_context_20260828"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda item: int(item, 16))
    }
    payload["held_map_script_source_review_20260828"] = dict(HELD_FOR_SOURCE_REVIEW)
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "applied": len(applied),
                "already_present": len(already_present),
                "held_for_source_review": HELD_FOR_SOURCE_REVIEW,
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
