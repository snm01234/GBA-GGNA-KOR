#!/usr/bin/env python3
"""Find the live 未修得 consumer and identify remaining pending weapon names."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA
from analyze_ggen_advance_pending_names_ingame_jp_20260904 import decode_row, owner_offsets, payload_at, u32
from build_ggen_advance_unified_rom_poc import (
    CHARMAP_8X16_PATH,
    CHARMAP_12X12_PATH,
    DICT_8X16_BASE,
    DICT_8X16_END,
    load_dictionary,
    load_identified_slot_to_char,
    raw_hex_bytes,
    tokens_from_bytes,
)
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import expand_to_slots

ROM_BASE = 0x08000000
UNIT_DB = 0x001A476C
UNIT_STRIDE = 0x78
ENTITY_DB = 0x0018E2E4
ENTITY_STRIDE = 0xAC
JP_RAW = bytes.fromhex("E4 7A E2 5F E3 BE 00")
KO_ADDR = 0x09304020
OLD_JP_COPY = 0x09052818
ORIG_ADDR = 0x081BE74E
CAND = ADVANCE_ROOT / "outputs/20260905_ggen_advance_idcmd_ecm_mishudeuk/ggen_advance_idcmd_ecm_mishudeuk_candidate_20260905.gba"
OUT = ADVANCE_ROOT / "legacy/analysis/ggen_advance_mishudeuk_and_pending_weapons_20260905.json"
WEAPON_GLOSSARY = ADVANCE_ROOT / "data/weapon_names_ko.json"


def find_raw(rom: bytes, needle: bytes) -> list[int]:
    out = []
    start = 0
    while True:
        at = rom.find(needle, start)
        if at < 0:
            return out
        out.append(at)
        start = at + 1


def pointer_hits(rom: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    return find_raw(rom, needle)


def is_rom_ptr(value: int) -> bool:
    return 0x08000000 <= value < 0x0A000000


def decode_payload(rom: bytes, dict8, map8, address: int) -> str:
    raw = payload_at(rom, address)
    if raw is None:
        return ""
    slots = expand_to_slots(tokens_from_bytes(raw[:-1] if raw.endswith(b"\x00") else raw), dict8)
    return "".join(map8.get(slot, f"<{slot:04X}>") for slot in slots)


def main() -> int:
    original = ORIGINAL_ROM.read_bytes()
    main = MAIN_TIP_ROM.read_bytes()
    cand = CAND.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    map8 = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    map8.update(CORRECTED_LOW_KANA)
    glossary = json.loads(WEAPON_GLOSSARY.read_text(encoding="utf-8"))
    gloss_jp = [row["jp"] for row in glossary.get("entries", [])]

    jp_locs_orig = find_raw(original, JP_RAW)
    jp_locs_main = find_raw(main, JP_RAW)
    jp_locs_cand = find_raw(cand, JP_RAW)

    ptr_sets = {}
    for label, rom, addrs in (
        ("main", main, [ORIG_ADDR, OLD_JP_COPY, KO_ADDR]),
        ("cand", cand, [ORIG_ADDR, OLD_JP_COPY, KO_ADDR]),
    ):
        ptr_sets[label] = {hex(addr): [hex(x) for x in pointer_hits(rom, addr)] for addr in addrs}

    # Any U32 whose payload equals JP_RAW
    jp_payload_ptrs_cand = []
    for off in range(0, len(cand) - 4, 4):
        value = u32(cand, off)
        if not is_rom_ptr(value):
            continue
        file_off = value - ROM_BASE
        if 0 <= file_off < len(cand) - 7 and cand[file_off : file_off + 7] == JP_RAW:
            jp_payload_ptrs_cand.append(hex(off))

    # Character 167 (ECM owner)
    rec167 = UNIT_DB + 167 * UNIT_STRIDE
    char167 = {
        "record_base": hex(rec167),
        "cmd_name_ptrs": {},
    }
    for cmd, field in enumerate((0x24, 0x40, 0x5C)):
        off = rec167 + field
        ptr = u32(cand, off)
        char167["cmd_name_ptrs"][f"cmd{cmd}"] = {
            "owner": hex(off),
            "ptr": hex(ptr),
            "payload": None if not is_rom_ptr(ptr) else payload_at(cand, ptr).hex(" ").upper(),
            "decoded": None if not is_rom_ptr(ptr) else decode_payload(cand, dict8, map8, ptr),
        }

    # Count how many character-DB name fields still point at JP 未修得
    db_jp = []
    db_ko = []
    db_other_zero = 0
    for i in range(256):
        base = UNIT_DB + i * UNIT_STRIDE
        for cmd, field in enumerate((0x24, 0x40, 0x5C)):
            off = base + field
            ptr = u32(cand, off)
            if ptr == 0:
                db_other_zero += 1
                continue
            if not is_rom_ptr(ptr):
                continue
            file_off = ptr - ROM_BASE
            if cand[file_off : file_off + 7] == JP_RAW:
                db_jp.append({"unit": i, "cmd": cmd, "owner": hex(off), "ptr": hex(ptr)})
            elif ptr == KO_ADDR:
                db_ko.append({"unit": i, "cmd": cmd, "owner": hex(off)})

    # Entity weapon pointers to pending weapons
    by_id = {row["record_id"]: row for row in merged["records"]}
    pending_weapons = []
    leftover_frames = defaultdict(list)
    for row in merged["records"]:
        if row.get("semantic_category") != "weapon_name":
            continue
        if row.get("record_id") == "GGA-TEXT-00179F7B":
            continue
        if row.get("translation_status") != "pending":
            continue
        decoded, missing, font = decode_row(row, dict8, dict8, map8, map8)
        owners = owner_offsets(row)
        live = []
        for owner in owners:
            ptr = u32(cand, owner)
            live.append({"owner": hex(owner), "ptr": hex(ptr), "payload": payload_at(cand, ptr).hex(" ").upper() if is_rom_ptr(ptr) else None})
        pending_weapons.append({
            "record_id": row["record_id"],
            "source_text": row.get("source_text"),
            "decoded": decoded,
            "unresolved": missing,
            "raw_hex": row.get("raw_hex"),
            "owner_count": len(owners),
            "live": live,
            "translation_ko": row.get("translation_ko") or "",
        })
        if len(set(missing)) == 1:
            leftover_frames[missing[0]].append({"decoded": decoded, "record_id": row["record_id"], "cat": "weapon_name"})

    # leftover=1 across name categories for those weapon slots
    weapon_slots = sorted({slot for row in pending_weapons for slot in row["unresolved"]})
    slot_frames = defaultdict(list)
    for row in merged["records"]:
        if row.get("scope_status") != "included":
            continue
        decoded, missing, font = decode_row(row, dict8, dict8, map8, map8)
        for slot in missing:
            if slot in weapon_slots:
                slot_frames[slot].append({
                    "record_id": row["record_id"],
                    "cat": row.get("semantic_category"),
                    "decoded": decoded,
                    "status": row.get("translation_status"),
                })

    # translated weapons containing ヒート / 砲 / ボルト
    translated_hits = []
    for row in merged["records"]:
        if row.get("semantic_category") != "weapon_name" or row.get("translation_status") != "translated":
            continue
        src = str(row.get("source_text") or "")
        ko = str(row.get("translation_ko") or "")
        if any(token in src + ko for token in ("ヒート", "ホーク", "ロッド", "口径", "加農", "全弾", "石破", "ボルト", "ウェポン", "ビームカノン", "主砲")):
            translated_hits.append({"record_id": row["record_id"], "src": src, "ko": ko})

    # code around fallback draws
    def dump16(rom, off):
        return rom[off : off + 32].hex(" ").upper()

    report = {
        "jp_raw_hex": JP_RAW.hex(" ").upper(),
        "jp_raw_locations": {
            "original": [hex(x) for x in jp_locs_orig],
            "main": [hex(x) for x in jp_locs_main],
            "candidate": [hex(x) for x in jp_locs_cand],
        },
        "pointers_to_known_addrs": ptr_sets,
        "cand_u32_still_pointing_at_jp_raw": {
            "count": len(jp_payload_ptrs_cand),
            "owners_sample": jp_payload_ptrs_cand[:80],
        },
        "character_167": char167,
        "character_db_name_fields": {
            "pointing_at_jp_weixiu": len(db_jp),
            "pointing_at_ko_mishudeuk": len(db_ko),
            "zero": db_other_zero,
            "jp_sample": db_jp[:20],
        },
        "draw_literals": {
            "0x1F4A8_cand": hex(u32(cand, 0x1F4A8)),
            "0x6C53C_cand": hex(u32(cand, 0x6C53C)),
            "bytes_1F3E0": dump16(cand, 0x1F3E0),
            "bytes_6C450": dump16(cand, 0x6C450),
        },
        "pending_weapons": pending_weapons,
        "weapon_slot_frames": {
            slot: {
                "count": len(rows),
                "cats": sorted({r["cat"] for r in rows}),
                "decoded_unique": sorted({r["decoded"] for r in rows})[:12],
                "records": rows[:12],
            }
            for slot, rows in sorted(slot_frames.items(), key=lambda kv: -len(kv[1]))
        },
        "translated_weapon_hits": translated_hits,
        "glossary_hits": [jp for jp in gloss_jp if any(x in jp for x in ("ヒート", "ヒ－ト", "口径", "加農", "全弾", "石破", "ボルト", "ホーク", "主砲", "ウェポン"))],
        "counts": {
            "pending_weapons": len(pending_weapons),
            "jp_db_name_fields": len(db_jp),
            "ko_db_name_fields": len(db_ko),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "jp_raw_locs_cand": [hex(x) for x in jp_locs_cand],
        "ptr_orig_cand": ptr_sets["cand"].get(hex(ORIG_ADDR)),
        "ptr_oldjp_cand": ptr_sets["cand"].get(hex(OLD_JP_COPY)),
        "ptr_ko_cand": ptr_sets["cand"].get(hex(KO_ADDR)),
        "u32_still_jp": len(jp_payload_ptrs_cand),
        "db_jp": len(db_jp),
        "db_ko": len(db_ko),
        "char167": char167,
        "pending": len(pending_weapons),
        "weapon_decoded": [w["decoded"] for w in pending_weapons],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
