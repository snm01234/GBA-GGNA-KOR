#!/usr/bin/env python3
"""Document the reviewed global exact-wildcard 8x16 promotion batch.

The actual project charmap is edited through reviewed project changes; this
script is a reproducible manifest/checker for that batch and intentionally does
not rewrite the ROM or immutable source data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

PROMOTIONS = {
    0x0016: "ぁ",
    0x00D9: "？",
    0x02C0: "基",
    0x042B: "連",
    0x050A: "府",
    0x058E: "遊",
}

EVIDENCE = {
    0x0016: "GGA-TEXT-0017BBC3 => うわぁぁぁ！; exact Tier-A map-script wildcard match; glyph ensemble rank 8",
    0x00D9: "GGA-TEXT-0017B73A => 良いもの……なのですか？; exact Tier-A map-script wildcard match; glyph ensemble rank 1",
    0x02C0: "GGA-TEXT-0018CFA4 => 基地; exact curated-production wildcard match; Janome recognizes 基地 as one dictionary noun",
    0x042B: "GGA-TEXT-0017AD6F => 連装砲; exact curated-production wildcard match; Janome recognizes 連装 as a dictionary noun",
    0x050A: "GGA-TEXT-0017CF61 => 政府高官; exact reviewed scenario-slot wildcard match; glyph ensemble rank 1",
    0x058E: "GGA-TEXT-0017B96E/0017BE02/0017C255/0017C703 => 遊びをやってるつもりか！？ / いつまでガキの遊びを…… / ……遊んであげるからさ！ / 遊びじゃないんだぜ！",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    payload = json.loads(MAP.read_text(encoding="utf-8"))
    cmap = {int(key, 16): value for key, value in payload["verified_charmap"].items()}
    failures = []
    for slot, char in PROMOTIONS.items():
        if cmap.get(slot) != char:
            failures.append(f"0x{slot:04X}: expected {char!r}, got {cmap.get(slot)!r}")
    provenance = payload.get("added_global_exact_wildcard_promotions_20260829", {})
    for slot, char in PROMOTIONS.items():
        row = provenance.get(f"0x{slot:04X}")
        if not isinstance(row, dict) or row.get("to") != char:
            failures.append(f"0x{slot:04X}: missing provenance")
    if payload.get("combined_slot_count") != len(cmap):
        failures.append(
            f"combined_slot_count={payload.get('combined_slot_count')} actual={len(cmap)}"
        )
    if failures:
        print(json.dumps({"result": "FAIL", "failures": failures}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "result": "PASS",
        "promotion_count": len(PROMOTIONS),
        "combined_slot_count": len(cmap),
        "promotions": {f"0x{k:04X}": v for k, v in PROMOTIONS.items()},
        "evidence": {f"0x{k:04X}": v for k, v in EVIDENCE.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
