#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_names_ingame_jp_20260904 import owner_offsets, u32
from build_ggen_advance_unified_rom_poc import CHARMAP_8X16_PATH, load_dictionary, load_identified_slot_to_char
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import DICT_8X16_BASE, DICT_8X16_END

ENTITY_DB = 0x0018E2E4
STRIDE = 0xAC
OUT = ROOT / "analysis" / "ggen_advance_weapon_siblings_20260905.json"


def main() -> int:
    orig = ORIGINAL_ROM.read_bytes()
    rom = MAIN_TIP_ROM.read_bytes()
    dictionary = load_dictionary(orig, DICT_8X16_BASE, DICT_8X16_END)
    mapping = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    idx = 0xED
    slots = dictionary[idx]
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_owner = {}
    for row in merged["records"]:
        if row.get("semantic_category") != "weapon_name":
            continue
        for owner in owner_offsets(row):
            by_owner[owner] = row
    owners = json.loads((ROOT / "analysis" / "ggen_advance_weapon_owners_mishudeuk_ptrs_20260905.json").read_text(encoding="utf-8"))
    out = []
    for item in owners["weapons"]:
        rec = item["units"][0]["entity"]["rec"]
        weapons = []
        for slot in range(7):
            off = ENTITY_DB + rec * STRIDE + 0x28 + slot * 0x14
            ptr = u32(rom, off)
            row = by_owner.get(off)
            weapons.append(
                {
                    "slot": slot,
                    "ptr": hex(ptr),
                    "rid": None if row is None else row["record_id"],
                    "src": None if row is None else row.get("source_text"),
                    "ko": None if row is None else row.get("translation_ko"),
                    "status": None if row is None else row.get("translation_status"),
                }
            )
        out.append({"pending": item["record_id"], "rec": rec, "weapons": weapons})
    report = {
        "dict_f0ed_slots": [f"0x{slot:04X}" for slot in slots],
        "dict_f0ed_decoded": "".join(mapping.get(slot, f"<{slot:04X}>") for slot in slots),
        "siblings": out,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "dict": report["dict_f0ed_decoded"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
