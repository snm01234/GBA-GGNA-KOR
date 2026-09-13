#!/usr/bin/env python3
"""Apply reviewed 12x12 context/glyph corrections to the canonical charmap.

These are corrections to slots that were already present in the reviewed map,
not new guesses.  Every change is guarded by the expected old value and is
recorded separately so the earlier promotion provenance remains auditable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

# The old values are deliberately part of the batch: a rerun must fail rather
# than silently applying a repair to a drifted or different charmap.
REPAIR_BATCH: dict[str, tuple[str, str]] = {
    "0x0046": ("ふ", "べ"),
    "0x0200": ("堕", "還"),
    "0x0186": ("遺", "怨"),
    "0x0237": ("益", "久"),
    "0x023C": ("棺", "宮"),
    "0x03C7": ("壁", "女"),
    "0x03B0": ("全", "銃"),
    "0x04E7": ("捨", "置"),
    "0x03AB": ("十", "充"),
    "0x0492": ("党", "像"),
}

EVIDENCE: dict[str, str] = {
    "0x0046": "map-script corpus: 比べて/すべく/選べる/選べない/調べて/しかるべき; ふ remains on separate 0x012E",
    "0x0200": "map-script corpus: 奪還/生還/帰還; bitmap and collocation agree",
    "0x0186": "map-script corpus: 怨恨/怨み/私怨; 遺 remains on separate 0x0160",
    "0x0237": "map-script corpus: 久々/久しぶり/永久; bitmap agrees",
    "0x023C": "map-script corpus: 宮殿/子宮; true 棺 remains on separate 0x01F3",
    "0x03C7": "map-script corpus: 女王/彼女/女性/少女/侍女; atlas separates 壁 on 0x060D",
    "0x03B0": "map-script corpus: 銃を向ける/銃を撃って; bitmap agrees",
    "0x04E7": "map-script corpus: 放置/配置/位置/処置/装置/設置/置いて; atlas separates 捨 on 0x0383",
    "0x03AB": "map-script corpus: 補充/充実/補充兵; bitmap agrees and 0x0244 carries 給",
    "0x0492": "map-script corpus: 想像もつかない/想像以上; bitmap agrees and 0x0548 carries 党",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified: dict[str, str] = payload["verified_charmap"]
    conflicts: list[str] = []
    already_fixed: list[str] = []
    applied: dict[str, dict[str, str]] = {}
    for slot, (old, new) in REPAIR_BATCH.items():
        current = verified.get(slot)
        if current == new:
            already_fixed.append(slot)
        elif current != old:
            conflicts.append(f"{slot}: expected {old!r}, found {current!r}")
        else:
            verified[slot] = new
            applied[slot] = {"from": old, "to": new}
    if conflicts:
        print(json.dumps({"result": "FAIL", "conflicts": conflicts}, ensure_ascii=False, indent=2))
        return 1

    payload["verified_charmap"] = {
        key: verified[key] for key in sorted(verified, key=lambda item: int(item, 16))
    }
    repairs = payload.setdefault("context_repairs_20260828", {})
    for slot, change in REPAIR_BATCH.items():
        old, new = change
        repairs[slot] = {
            "from": old,
            "to": new,
            "basis": "corpus_context_plus_12x12_glyph_verification",
            "evidence": EVIDENCE[slot],
        }
    payload["context_repairs_20260828"] = {
        key: repairs[key] for key in sorted(repairs, key=lambda item: int(item, 16))
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "applied": len(applied),
                "already_fixed": len(already_fixed),
                "verified_charmap": len(payload["verified_charmap"]),
                "changes": applied,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
