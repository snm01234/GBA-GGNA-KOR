#!/usr/bin/env python3
"""Promote map-script slots whose 12x12 glyph and corpus context agree.

The batch is intentionally limited to the audit class
``context_and_glyph_agree``.  Context-only, conflict, and hold slots remain
in the unresolved queue for a later review pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

# Generated from legacy/analysis/ggen_advance_map_script_unresolved_slot_audit_20260828_context_repairs.json
# after the context-repair pass.  Every entry is an unresolved slot, so an
# existing value is treated as a collision rather than silently overwritten.
PROMOTION_BATCH: dict[str, str] = {
    "0x0154": "偉",
    "0x01E3": "刈",
    "0x01E8": "勧",
    "0x01F4": "歓",
    "0x025A": "挟",
    "0x026E": "禁",
    "0x0270": "緊",
    "0x02BF": "幻",
    "0x02CD": "股",
    "0x02E6": "喉",
    "0x0309": "酷",
    "0x033A": "削",
    "0x0340": "擦",
    "0x036A": "飼",
    "0x03B9": "准",
    "0x03BE": "順",
    "0x03C3": "署",
    "0x03F9": "植",
    "0x0415": "震",
    "0x042C": "澄",
    "0x042D": "寸",
    "0x0457": "折",
    "0x0473": "措",
    "0x047B": "僧",
    "0x0491": "騒",
    "0x04A7": "孫",
    "0x04C5": "托",
    "0x04D1": "嘆",
    "0x04DC": "壇",
    "0x04DE": "暖",
    "0x04F8": "貯",
    "0x04FA": "兆",
    "0x0550": "盗",
    "0x058F": "拝",
    "0x0599": "剥",
    "0x059B": "拍",
    "0x05B4": "煩",
    "0x05C3": "疲",
    "0x05E1": "婦",
    "0x05F8": "服",
    "0x0634": "忙",
    "0x0642": "摩",
    "0x0655": "脈",
    "0x0683": "幽",
    "0x0687": "裕",
    "0x0692": "揺",
    "0x069C": "翼",
    "0x06C0": "隣",
    "0x06CE": "裂",
    "0x06D1": "憐",
    "0x06D6": "露",
    "0x06EA": "嗅",
    "0x06F7": "舐",
    "0x06FA": "贖",
    "0x06FB": "踪",
    "0x0703": "擁",
    "0x0704": "融",
    "0x0705": "征",
    "0x0709": "八",
    "0x070A": "湧",
    "0x0711": "轍",
    "0x0714": "牌",
    "0x0789": "録",
    "0x079C": "灯",
    "0x07A4": "怯",
    "0x07A5": "勤",
    "0x07A8": "侍",
    "0x07AA": "倉",
    "0x07AC": "卑",
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
    provenance = payload.setdefault("added_map_script_context_glyph_agree_20260828", {})
    for slot, char in PROMOTION_BATCH.items():
        provenance[slot] = {
            "to": char,
            "basis": "context_and_glyph_agree",
            "audit": "legacy/analysis/ggen_advance_map_script_unresolved_slot_audit_20260828_context_repairs.json",
        }
    payload["added_map_script_context_glyph_agree_20260828"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda item: int(item, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "applied": len(applied),
                "already_present": len(already_present),
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
