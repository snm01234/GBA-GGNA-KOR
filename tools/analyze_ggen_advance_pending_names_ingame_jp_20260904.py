#!/usr/bin/env python3
"""Audit pending/translated production labels that still draw original Japanese."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA
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
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import expand_to_slots

ROM_BASE = 0x08000000
CATEGORIES = {
    "id_command_name",
    "unit_name",
    "unit_name_alternate",
    "character_name",
    "weapon_name",
    "series_title",
    "id_command_effect_summary",
    "upgrade_part_name",
    "unit_defense_ability",
    "unit_ai_type",
    "scroll_list_label",
}
OUTPUT = ROOT / "analysis" / "ggen_advance_pending_names_ingame_jp_20260904.json"


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def payload_at(rom: bytes, address: int) -> bytes | None:
    offset = address - ROM_BASE
    if not 0 <= offset < len(rom):
        return None
    end = rom.find(0, offset, min(len(rom), offset + 0x120))
    if end < 0:
        return None
    return bytes(rom[offset : end + 1])


def owner_offsets(row: dict) -> list[int]:
    return [
        int(str(owner_id).removeprefix("OWNER-U32-"), 16)
        for owner_id in row.get("owner_ids") or []
        if str(owner_id).startswith("OWNER-U32-")
    ]


def decode_row(row: dict, dict8, dict12, map8, map12) -> tuple[str, list[str], str]:
    raw = raw_hex_bytes(row["raw_hex"])
    use12 = uses_12x12(row)
    dictionary = dict12 if use12 else dict8
    charmap = map12 if use12 else map8
    slots = expand_to_slots(tokens_from_bytes(raw), dictionary)
    chars = []
    missing = []
    for slot in slots:
        char = charmap.get(slot)
        if char is None:
            chars.append(f"<{slot:04X}>")
            missing.append(f"0x{slot:04X}")
        else:
            chars.append(char)
    return "".join(chars), missing, "12x12" if use12 else "8x16"


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

    pending_still = []
    translated_still = []
    by_cat = defaultdict(lambda: {"pending_still": 0, "pending_closable": 0, "translated_still": 0, "translated_still_has_ko": 0})

    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if cat not in CATEGORIES:
            continue
        if row.get("scope_status") != "included" or row.get("translation_policy") != "translate":
            continue
        owners = owner_offsets(row)
        if not owners:
            continue
        orig_raw = raw_hex_bytes(row["raw_hex"])
        still_owners = []
        for offset in owners:
            pointer = u32(main, offset)
            live = payload_at(main, pointer)
            if live == orig_raw:
                still_owners.append(offset)
        if not still_owners:
            continue
        decoded, missing, font = decode_row(row, dict8, dict12, map8, map12)
        item = {
            "record_id": row["record_id"],
            "semantic_category": cat,
            "translation_status": row.get("translation_status"),
            "translation_ko": row.get("translation_ko") or "",
            "sheet_source_text": row.get("source_text"),
            "decoded": decoded,
            "unresolved": missing,
            "font": font,
            "owner_count": len(owners),
            "still_owner_count": len(still_owners),
            "owners": [f"0x{offset:08X}" for offset in still_owners[:12]],
            "translator_notes": row.get("translator_notes") or "",
        }
        stats = by_cat[cat]
        if row.get("translation_status") == "pending":
            stats["pending_still"] += 1
            if not missing:
                stats["pending_closable"] += 1
                pending_still.append(item)
        elif row.get("translation_status") == "translated":
            stats["translated_still"] += 1
            if row.get("translation_ko"):
                stats["translated_still_has_ko"] += 1
            translated_still.append(item)

    pending_still.sort(key=lambda item: (item["semantic_category"], item["record_id"]))
    translated_still.sort(key=lambda item: (item["semantic_category"], item["record_id"]))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_pending_names_ingame_jp_20260904",
        "main_tip_sha256": __import__("hashlib").sha256(main).hexdigest(),
        "map8_slots": len(map8),
        "summary": {cat: dict(stats) for cat, stats in sorted(by_cat.items())},
        "pending_closable": pending_still,
        "translated_still_jp": translated_still,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT),
        "pending_closable": len(pending_still),
        "translated_still_jp": len(translated_still),
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))
    print("\n=== pending closable ===")
    for item in pending_still:
        print(f"{item['record_id']}\t{item['semantic_category']}\t{item['decoded']!r}\tko={item['translation_ko']!r}")
    print("\n=== translated still JP (first 80) ===")
    for item in translated_still[:80]:
        print(f"{item['record_id']}\t{item['semantic_category']}\t{item['decoded']!r}\tko={item['translation_ko']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
