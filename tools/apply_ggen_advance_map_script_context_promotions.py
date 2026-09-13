#!/usr/bin/env python3
"""Promote high-confidence map-script context candidates.

This is the next queue after the context-and-glyph-agree batch.  Only entries
labelled ``high`` by the unresolved-slot audit are applied; the two medium
confidence one-off readings (0x0572 and 0x06D0) stay held for glyph review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

# Generated from the post-confirmed-promotion audit.  Each reading is backed
# by one or more complete Japanese compounds in the map-script corpus.
PROMOTION_BATCH: dict[str, str] = {
    "0x00E5": "―",
    "0x00FD": "6",
    "0x012D": "ぴ",
    "0x0135": "ょ",
    "0x0161": "勤",
    "0x018A": "縁",
    "0x0193": "宇",
    "0x01AF": "荷",
    "0x01CB": "口",
    "0x01CD": "骸",
    "0x01E6": "夢",
    "0x01F1": "念",
    "0x01FB": "緩",
    "0x0214": "忌",
    "0x026F": "筋",
    "0x028F": "恵",
    "0x0291": "敬",
    "0x02EF": "拘",
    "0x0306": "克",
    "0x031D": "査",
    "0x033F": "拶",
    "0x034A": "賛",
    "0x0357": "屍",
    "0x0362": "紙",
    "0x0364": "至",
    "0x036F": "慈",
    "0x037B": "七",
    "0x037E": "室",
    "0x0388": "当",
    "0x039C": "宙",
    "0x03C8": "牲",
    "0x03CD": "召",
    "0x03D8": "把",
    "0x03E7": "衝",
    "0x0401": "伸",
    "0x0410": "親",
    "0x0451": "力",
    "0x0458": "設",
    "0x046E": "探",
    "0x0471": "善",
    "0x048B": "聡",
    "0x04A2": "賊",
    "0x04ED": "犠",
    "0x04FD": "殴",
    "0x0502": "め",
    "0x0505": "聴",
    "0x0520": "姿",
    "0x0526": "隊",
    "0x052B": "優",
    "0x0539": "殿",
    "0x055C": "働",
    "0x0596": "倍",
    "0x05A2": "縛",
    "0x05CC": "連",
    "0x0608": "柄",
    "0x060A": "閉",
    "0x0621": "避",
    "0x0625": "抱",
    "0x062C": "訪",
    "0x0649": "毎",
    "0x0657": "民",
    "0x0664": "妄",
    "0x0667": "網",
    "0x0670": "幕",
    "0x0676": "薬",
    "0x067D": "唯",
    "0x0691": "和",
    "0x06BA": "瞭",
    "0x0710": "憎",
    "0x0715": "い",
    "0x0716": "購",
    "0x07A2": "ぽ",
    "0x07AF": "廷",
}

HELD_FOR_LATER: dict[str, str] = {
    "0x0572": "縄",  # 一筋縄では…; one medium-confidence occurrence
    "0x06D0": "誰",  # 誰の…; one medium-confidence occurrence
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
    provenance = payload.setdefault("added_map_script_context_20260828", {})
    for slot, char in PROMOTION_BATCH.items():
        provenance[slot] = {
            "to": char,
            "basis": "high_confidence_context_candidate",
            "audit": "legacy/analysis/ggen_advance_map_script_unresolved_slot_audit_20260828_context_repairs.json",
        }
    payload["added_map_script_context_20260828"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda item: int(item, 16))
    }
    payload["held_map_script_context_medium_20260828"] = dict(HELD_FOR_LATER)
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "applied": len(applied),
                "already_present": len(already_present),
                "held_for_later": HELD_FOR_LATER,
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
