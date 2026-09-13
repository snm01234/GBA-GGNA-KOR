#!/usr/bin/env python3
"""Dump pending ID-command names, pending weapons, and 未修得 candidates."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA
from analyze_ggen_advance_pending_names_ingame_jp_20260904 import decode_row, owner_offsets, payload_at, u32
from build_ggen_advance_unified_rom_poc import (
    CHARMAP_8X16_PATH,
    CHARMAP_12X12_PATH,
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    load_dictionary,
    load_identified_slot_to_char,
    raw_hex_bytes,
    tokens_from_bytes,
    uses_12x12,
)
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import expand_to_slots

SLOT_RE = re.compile(r"<([0-9A-Fa-f]{4})>")
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_ss6_pending_names_detail_20260905.json"


def main() -> int:
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    main = MAIN_TIP_ROM.read_bytes()
    original = ORIGINAL_ROM.read_bytes()
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(original, DICT_12X12_BASE, DICT_12X12_END)
    map8 = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    map8.update(CORRECTED_LOW_KANA)
    map12 = load_identified_slot_to_char(CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)

    pending_names = []
    pending_weapons = []
    leftover1 = defaultdict(list)
    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if row.get("translation_status") != "pending":
            continue
        if cat not in {"id_command_name", "weapon_name", "unit_name", "unit_name_alternate"}:
            continue
        decoded, missing, font = decode_row(row, dict8, dict12, map8, map12)
        owners = owner_offsets(row)
        orig_raw = raw_hex_bytes(row["raw_hex"])
        still = sum(1 for off in owners if payload_at(main, u32(main, off)) == orig_raw)
        item = {
            "record_id": row["record_id"],
            "cat": cat,
            "decoded": decoded,
            "source_text": row.get("source_text"),
            "ko": row.get("translation_ko") or "",
            "unresolved": missing,
            "font": font,
            "still_jp_owners": still,
            "owner_count": len(owners),
            "raw_hex": row.get("raw_hex"),
            "offset": row.get("target_file_offset"),
        }
        if cat == "id_command_name":
            pending_names.append(item)
        elif cat == "weapon_name":
            pending_weapons.append(item)
        if len(set(missing)) == 1:
            leftover1[missing[0]].append({"decoded": decoded, "cat": cat, "record_id": row["record_id"]})

    # inactive: decode as 12x12 AND 8x16, dump live
    inact = next(r for r in merged["records"] if r.get("semantic_category") == "inactive_id_command_placeholder")
    raw = raw_hex_bytes(inact["raw_hex"])
    owners = owner_offsets(inact)
    live_ptr = u32(main, owners[0]) if owners else 0
    live = payload_at(main, live_ptr)
    slots8 = expand_to_slots(tokens_from_bytes(raw), dict8)
    slots12 = expand_to_slots(tokens_from_bytes(raw), dict12)
    dec8 = "".join(map8.get(s, f"<{s:04X}>") for s in slots8)
    dec12 = "".join(map12.get(s, f"<{s:04X}>") for s in slots12)

    # search all records whose decoded 8x16/12x12 contains 未 or 修得-like
    candidates = []
    for row in merged["records"]:
        src = str(row.get("source_text") or "") + str(row.get("translation_ko") or "")
        if "未修" in src or "未修得" in src or "미습" in src:
            candidates.append({
                "record_id": row["record_id"],
                "cat": row.get("semantic_category"),
                "status": row.get("translation_status"),
                "policy": row.get("translation_policy"),
                "source_text": row.get("source_text"),
                "ko": row.get("translation_ko"),
            })

    report = {
        "pending_id_command_name": pending_names,
        "pending_weapon_name": pending_weapons,
        "leftover1": {
            slot: {"count": len(rows), "frames": sorted({r["decoded"] for r in rows}), "cats": sorted({r["cat"] for r in rows})}
            for slot, rows in sorted(leftover1.items(), key=lambda kv: -len(kv[1]))
        },
        "inactive_example": {
            "record_id": inact["record_id"],
            "owners": [hex(o) for o in owners[:6]],
            "live_ptr": hex(live_ptr),
            "live_hex": None if live is None else live.hex(" "),
            "orig_hex": raw.hex(" "),
            "same": live == raw,
            "dec8": dec8,
            "dec12": dec12,
            "slots8": [hex(s) for s in slots8],
            "slots12": [hex(s) for s in slots12],
        },
        "weixiu_candidates": candidates,
        "counts": {
            "pending_id_command_name": len(pending_names),
            "pending_weapon_name": len(pending_weapons),
            "still_jp_id_names": sum(1 for r in pending_names if r["still_jp_owners"]),
            "still_jp_weapons": sum(1 for r in pending_weapons if r["still_jp_owners"]),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "counts": report["counts"],
        "leftover1_slots": len(leftover1),
        "inactive_same": report["inactive_example"]["same"],
        "inactive_live_ptr": report["inactive_example"]["live_ptr"],
        "inactive_dec12": dec12,
        "inactive_dec8": dec8,
        "weixiu": len(candidates),
        "weapon_decoded": [w["decoded"] for w in pending_weapons],
        "l1_047E": leftover1.get("0x047E"),
        "l1_0515": leftover1.get("0x0515"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
