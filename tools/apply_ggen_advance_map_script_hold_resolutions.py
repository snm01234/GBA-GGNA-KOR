#!/usr/bin/env python3
"""Resolve the last four map-script 12x12 slots after source/glyph review."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

PROMOTION_BATCH: dict[str, str] = {
    "0x0360": "獅",  # オーブの獅子の娘
    "0x03B7": "春",  # 青春してて結構
    "0x0585": "納",  # 納得できない／ホコを納めよ
    "0x065C": "娘",  # 獅子の娘／小娘
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
    provenance = payload.setdefault("added_map_script_hold_resolutions_20260828", {})
    evidence = {
        "0x0360": "original glyph matches 獅; phrase オーブの獅子の娘",
        "0x03B7": "original glyph shape is 春; phrase 青春してて結構",
        "0x0585": "original glyph matches 納; both 納得 and ホコを納めよ use the same slot",
        "0x065C": "original glyph matches 娘; phrases 獅子の娘 and 小娘",
    }
    for slot, char in PROMOTION_BATCH.items():
        provenance[slot] = {
            "to": char,
            "basis": "manual_source_phrase_plus_original_glyph_review",
            "evidence": evidence[slot],
        }
    payload["added_map_script_hold_resolutions_20260828"] = {
        key: provenance[key] for key in sorted(provenance, key=lambda item: int(item, 16))
    }
    payload.pop("held_map_script_source_review_20260828", None)
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
