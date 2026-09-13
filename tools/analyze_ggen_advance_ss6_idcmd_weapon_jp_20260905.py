#!/usr/bin/env python3
"""Locate ss6 ID-command / weapon JP leftovers on current main TIP."""
from __future__ import annotations

import json
import struct
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
)
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON

NEEDLES = ("ECM", "未修得", "最大強", "胸部", "一斉", "ミサイル", "射撃")
CATS = {
    "id_command_name",
    "id_command_effect_summary",
    "id_command_description",
    "inactive_id_command_placeholder",
    "weapon_name",
    "weapon_name_alternate",
    "id_command_fallback_text",
}


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

    cat_status = defaultdict(Counter)
    hits = []
    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if cat in CATS:
            cat_status[cat][str(row.get("translation_status") or "")] += 1
        blob = " ".join([
            str(row.get("source_text") or ""),
            str(row.get("translation_ko") or ""),
            str(row.get("semantic_category") or ""),
            str(row.get("translator_notes") or ""),
        ])
        if not any(n in blob for n in NEEDLES) and cat not in {"inactive_id_command_placeholder"}:
            continue
        if cat not in CATS and not any(n in blob for n in NEEDLES):
            continue
        decoded, missing, font = decode_row(row, dict8, dict12, map8, map12)
        textish = decoded + str(row.get("source_text") or "") + str(row.get("translation_ko") or "")
        if cat != "inactive_id_command_placeholder" and not any(n in textish for n in NEEDLES):
            continue
        owners = owner_offsets(row)
        orig_raw = raw_hex_bytes(row["raw_hex"])
        live = []
        for off in owners:
            ptr = u32(main, off)
            pay = payload_at(main, ptr)
            live.append({
                "owner": hex(off),
                "ptr": hex(ptr),
                "still_jp": pay == orig_raw,
                "live_len": None if pay is None else len(pay),
            })
        if cat == "inactive_id_command_placeholder":
            continue  # counted in status; sample later
        hits.append({
            "record_id": row["record_id"],
            "cat": cat,
            "status": row.get("translation_status"),
            "policy": row.get("translation_policy"),
            "ko": row.get("translation_ko") or "",
            "decoded": decoded,
            "source_text": row.get("source_text"),
            "unresolved": missing,
            "font": font,
            "raw_hex": row.get("raw_hex"),
            "offset": row.get("target_file_offset"),
            "live": live,
        })

    # sample inactive placeholders
    inact = []
    for row in merged["records"]:
        if row.get("semantic_category") != "inactive_id_command_placeholder":
            continue
        decoded, missing, font = decode_row(row, dict8, dict12, map8, map12)
        owners = owner_offsets(row)
        orig_raw = raw_hex_bytes(row["raw_hex"])
        still = 0
        for off in owners:
            if payload_at(main, u32(main, off)) == orig_raw:
                still += 1
        inact.append((decoded, row.get("translation_status"), row.get("translation_ko") or "", missing, still, row["record_id"], row.get("raw_hex")))
        if len(inact) >= 8:
            break

    decoded_set = Counter()
    still_total = 0
    n = 0
    for row in merged["records"]:
        if row.get("semantic_category") != "inactive_id_command_placeholder":
            continue
        decoded, missing, font = decode_row(row, dict8, dict12, map8, map12)
        decoded_set[decoded] += 1
        n += 1
        orig_raw = raw_hex_bytes(row["raw_hex"])
        for off in owner_offsets(row):
            if payload_at(main, u32(main, off)) == orig_raw:
                still_total += 1

    out = ADVANCE_ROOT / "analysis" / "ggen_advance_ss6_idcmd_weapon_jp_20260905.json"
    payload = {
        "cat_status": {k: dict(v) for k, v in sorted(cat_status.items())},
        "hits": hits,
        "inactive_samples": [
            {
                "decoded": d,
                "status": st,
                "ko": ko,
                "unresolved": miss,
                "still": still,
                "record_id": rid,
                "raw_hex": raw,
            }
            for d, st, ko, miss, still, rid, raw in inact
        ],
        "inactive_unique": decoded_set.most_common(10),
        "inactive_n": n,
        "inactive_still_owner_hits": still_total,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", out)
    print("CAT STATUS")
    for cat, counts in sorted(cat_status.items()):
        print(cat, dict(counts))
    print("hits", len(hits))
    print("inactive unique", decoded_set.most_common(10), "n", n, "still", still_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
