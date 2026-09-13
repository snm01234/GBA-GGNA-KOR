#!/usr/bin/env python3
"""Find pending sheet rows whose live owners still draw original Japanese.

Focuses on the same intermission/yellow-window family as the 索敵地上 case:
FCE1A0 condition bodies, FCE128 help, FCE2D8 titles, search-record location
names, and other production owners whose current pointer payload still matches
the original JP stream.  Re-decodes 12x12 consumers with the identified 12x12
map instead of the historical 8x16 production decode.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA  # noqa: E402
from build_ggen_advance_unified_rom_poc import (  # noqa: E402
    CHARMAP_12X12_PATH,
    CHARMAP_8X16_PATH,
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    load_dictionary,
    load_identified_slot_to_char,
    raw_hex_bytes,
    tokens_from_bytes,
)
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON  # noqa: E402
from ggen_advance_text_codec import expand_to_slots  # noqa: E402

ROM_BASE = 0x08000000
OUTPUT = ROOT / "analysis" / "ggen_advance_pending_ingame_jp_20260904.json"

PRIORITY_FAMILIES = {
    "search_key_to_FCE1A0_text",
    "table_FCE128_22",
    "table_FCE2D8_flat69_paired_selection",
    "table_FCE2A8_sparse12",
    "current_search_record_text_10",
    "map_system_function_help",
    "stage_battle_condition_text",
    "stage_battle_condition_target_label",
    "stage_location_name",
}

TWELVE_CATEGORIES = {
    "map_system_function_help",
    "stage_battle_condition_text",
    "stage_battle_condition_target_label",
    "stage_battle_condition_line",
    "stage_battle_condition_component",
    "id_command_description",
    "scripted_multiline_text",
    "two_choice_confirmation_dialog_text",
    "configuration_option_text",
}

TABLES = {
    "FCE128": (0x00FCE128, 22),
    "FCE1A0": (0x00FCE1A0, 64),
    "FCE2A8": (0x00FCE2A8, 12),
    "FCE2D8": (0x00FCE2D8, 69),
}


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
    out: list[int] = []
    for owner_id in row.get("owner_ids") or []:
        if not str(owner_id).startswith("OWNER-U32-"):
            continue
        out.append(int(str(owner_id).removeprefix("OWNER-U32-"), 16))
    return out


def looks_hangul_payload(data: bytes) -> bool:
    # Relocated Hangul literals densely use E0xx–E6xx; original JP mixes lower
    # slots and dictionary F0xx.  This is only a hint for reports.
    if not data or data[-1] != 0:
        return False
    body = data[:-1]
    if not body:
        return False
    two = 0
    i = 0
    while i < len(body):
        lead = body[i]
        if lead <= 0xDF:
            i += 1
            continue
        if i + 1 >= len(body):
            return False
        token = (lead << 8) | body[i + 1]
        if 0xE000 <= token <= 0xE6FF:
            two += 1
        i += 2
    return two >= 2


def decode_slots(slots: list[int], charmap: dict[int, str]) -> tuple[str, list[str]]:
    chars: list[str] = []
    missing: list[str] = []
    for slot in slots:
        char = charmap.get(slot)
        if char is None:
            marker = f"<0x{slot:04X}>"
            chars.append(marker)
            missing.append(f"0x{slot:04X}")
        else:
            chars.append(char)
    return "".join(chars), missing


def main() -> int:
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    records = merged["records"]
    by_id = {row["record_id"]: row for row in records}
    main = MAIN_TIP_ROM.read_bytes()
    original = ORIGINAL_ROM.read_bytes()
    dict12 = load_dictionary(original, DICT_12X12_BASE, DICT_12X12_END)
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    map12 = load_identified_slot_to_char(CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)
    map8 = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    map8.update(CORRECTED_LOW_KANA)

    owner_to_record: dict[int, str] = {}
    for row in records:
        for offset in owner_offsets(row):
            owner_to_record.setdefault(offset, row["record_id"])

    table_rows = {}
    for name, (base, count) in TABLES.items():
        entries = []
        for index in range(count):
            offset = base + index * 4
            pointer = u32(main, offset)
            record_id = owner_to_record.get(offset)
            row = by_id.get(record_id) if record_id else None
            live = payload_at(main, pointer)
            orig_raw = raw_hex_bytes(row["raw_hex"]) if row else None
            still_jp = bool(live and orig_raw and live == orig_raw)
            families = list(row.get("source_families") or []) if row else []
            category = str(row.get("semantic_category") or "") if row else ""
            use12 = category in TWELVE_CATEGORIES or "search_key_to_FCE1A0_text" in families or name in {"FCE128", "FCE1A0"}
            decoded = None
            missing = []
            if orig_raw:
                dictionary = dict12 if use12 else dict8
                charmap = map12 if use12 else map8
                slots = expand_to_slots(tokens_from_bytes(orig_raw), dictionary)
                decoded, missing = decode_slots(slots, charmap)
            entries.append(
                {
                    "index": index,
                    "owner": f"0x{offset:08X}",
                    "pointer": f"0x{pointer:08X}",
                    "record_id": record_id,
                    "translation_status": row.get("translation_status") if row else None,
                    "source_decode_status": row.get("source_decode_status") if row else None,
                    "sheet_source_text": row.get("source_text") if row else None,
                    "translation_ko": row.get("translation_ko") if row else None,
                    "semantic_category": category or None,
                    "source_families": families,
                    "still_original_jp": still_jp,
                    "live_looks_hangul": looks_hangul_payload(live) if live else False,
                    "live_hex": live.hex(" ") if live else None,
                    "decoded_12x12_or_8x16": decoded,
                    "unresolved": missing,
                    "closable": bool(decoded and not missing and still_jp),
                }
            )
        table_rows[name] = entries

    pending = [
        row
        for row in records
        if row.get("translation_status") == "pending"
        and row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and owner_offsets(row)
    ]

    still_jp_pending = []
    for row in pending:
        owners = owner_offsets(row)
        orig_raw = raw_hex_bytes(row["raw_hex"])
        live_hits = []
        still = False
        for offset in owners:
            pointer = u32(main, offset)
            live = payload_at(main, pointer)
            match = bool(live and live == orig_raw)
            if match:
                still = True
            live_hits.append(
                {
                    "owner": f"0x{offset:08X}",
                    "pointer": f"0x{pointer:08X}",
                    "match_original": match,
                    "looks_hangul": looks_hangul_payload(live) if live else False,
                }
            )
        if not still:
            continue
        families = list(row.get("source_families") or [])
        category = str(row.get("semantic_category") or "")
        use12 = category in TWELVE_CATEGORIES or bool(PRIORITY_FAMILIES.intersection(families))
        dictionary = dict12 if use12 else dict8
        charmap = map12 if use12 else map8
        slots = expand_to_slots(tokens_from_bytes(orig_raw), dictionary)
        decoded, missing = decode_slots(slots, charmap)
        still_jp_pending.append(
            {
                "record_id": row["record_id"],
                "source_scope": row.get("source_scope"),
                "semantic_category": category,
                "source_families": families,
                "screen_class": row.get("screen_class"),
                "sheet_source_text": row.get("source_text"),
                "sheet_decode_status": row.get("source_decode_status"),
                "translation_ko": row.get("translation_ko") or "",
                "owner_count": len(owners),
                "decoded": decoded,
                "unresolved": missing,
                "closable": not missing,
                "priority": bool(PRIORITY_FAMILIES.intersection(set(families) | {category})),
                "owners": live_hits[:8],
            }
        )

    still_jp_pending.sort(key=lambda item: (not item["priority"], not item["closable"], item["semantic_category"], item["record_id"]))

    summary = {
        "pending_with_owners": len(pending),
        "pending_still_original_jp": len(still_jp_pending),
        "pending_still_jp_closable": sum(1 for item in still_jp_pending if item["closable"]),
        "pending_still_jp_priority": sum(1 for item in still_jp_pending if item["priority"]),
        "pending_still_jp_priority_closable": sum(1 for item in still_jp_pending if item["priority"] and item["closable"]),
        "by_category_still_jp": Counter(item["semantic_category"] for item in still_jp_pending).most_common(),
        "by_category_closable": Counter(item["semantic_category"] for item in still_jp_pending if item["closable"]).most_common(),
    }
    table_summary = {}
    for name, entries in table_rows.items():
        table_summary[name] = {
            "count": len(entries),
            "still_original_jp": sum(1 for item in entries if item["still_original_jp"]),
            "pending_still_jp": sum(
                1 for item in entries if item["still_original_jp"] and item["translation_status"] == "pending"
            ),
            "pending_still_jp_closable": sum(
                1
                for item in entries
                if item["still_original_jp"] and item["translation_status"] == "pending" and item["closable"]
            ),
            "translated_but_still_jp": [
                item["record_id"]
                for item in entries
                if item["still_original_jp"] and item["translation_status"] == "translated"
            ],
        }

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_pending_ingame_jp_20260904",
        "summary": summary,
        "tables": table_summary,
        "priority_table_entries": {
            name: [item for item in entries if item["still_original_jp"]]
            for name, entries in table_rows.items()
        },
        "priority_closable_pending": [item for item in still_jp_pending if item["priority"] and item["closable"]],
        "priority_unresolved_pending": [item for item in still_jp_pending if item["priority"] and not item["closable"]],
        "other_closable_pending_sample": [item for item in still_jp_pending if not item["priority"] and item["closable"]][:80],
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), **summary, "tables": table_summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
