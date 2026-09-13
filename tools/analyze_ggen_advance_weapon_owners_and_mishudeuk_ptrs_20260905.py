#!/usr/bin/env python3
"""Map pending weapons to unit names and find extra 未修得 literal loads."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA
from analyze_ggen_advance_pending_names_ingame_jp_20260904 import owner_offsets, payload_at, u32
from build_ggen_advance_unified_rom_poc import (
    CHARMAP_8X16_PATH,
    DICT_8X16_BASE,
    DICT_8X16_END,
    load_dictionary,
    load_identified_slot_to_char,
    tokens_from_bytes,
)
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import expand_to_slots

ROM_BASE = 0x08000000
ENTITY_DB = 0x0018E2E4
ENTITY_STRIDE = 0xAC
CAND = ADVANCE_ROOT / "outputs/20260905_ggen_advance_idcmd_ecm_mishudeuk/ggen_advance_idcmd_ecm_mishudeuk_candidate_20260905.gba"
OUT = ADVANCE_ROOT / "legacy/analysis/ggen_advance_weapon_owners_mishudeuk_ptrs_20260905.json"
PENDING = [
    "GGA-TEXT-00179E89",
    "GGA-TEXT-00179F5A",
    "GGA-TEXT-0017A061",
    "GGA-TEXT-0017A1C9",
    "GGA-TEXT-0017A1D9",
    "GGA-TEXT-0017A3D1",
    "GGA-TEXT-0017A513",
    "GGA-TEXT-0017A5CB",
    "GGA-TEXT-0017A5D9",
    "GGA-TEXT-0017A5E4",
    "GGA-TEXT-0017A707",
    "GGA-TEXT-0017A756",
    "GGA-TEXT-0017ACC9",
    "GGA-TEXT-0017AD25",
    "GGA-TEXT-0017ADC2",
]
LITS = (0x0001FF74, 0x0003A9B4, 0x0001F4A8, 0x0006C53C)


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def decode_name(rom: bytes, dict8, map8, ptr: int) -> str:
    raw = payload_at(rom, ptr)
    if not raw:
        return ""
    slots = expand_to_slots(tokens_from_bytes(raw[:-1]), dict8)
    return "".join(map8.get(slot, f"<{slot:04X}>") for slot in slots)


def entity_from_owner(owner: int) -> dict[str, int] | None:
    for rec in range(400):
        base = ENTITY_DB + rec * ENTITY_STRIDE
        if owner == base + 4:
            return {"rec": rec, "kind": "name", "slot": -1}
        for slot in range(8):
            field = base + 0x28 + slot * 0x14
            if field == owner:
                return {"rec": rec, "kind": "weapon", "slot": slot}
    return None


def ldr_sites_for_literal(rom: bytes, lit_off: int) -> list[str]:
    hits = []
    for off in range(0, min(len(rom), 0x200000), 2):
        h = u16(rom, off)
        if h & 0xF800 != 0x4800:
            continue
        lit = ((off + 4) & ~3) + ((h & 0xFF) << 2)
        if lit == lit_off:
            hits.append({"site": hex(off), "rd": (h >> 8) & 7, "insn": hex(h)})
    return hits


def main() -> int:
    rom = CAND.read_bytes()
    original = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    map8 = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    map8.update(CORRECTED_LOW_KANA)
    by_id = {row["record_id"]: row for row in merged["records"]}
    name_owner_to_row = {}
    for row in merged["records"]:
        if row.get("semantic_category") not in {"unit_name", "unit_name_alternate"}:
            continue
        for owner in owner_offsets(row):
            name_owner_to_row[owner] = {
                "record_id": row["record_id"],
                "source_text": row.get("source_text"),
                "ko": row.get("translation_ko") or "",
                "status": row.get("translation_status"),
            }
    name_by_rec = {}
    for rec in range(400):
        name_off = ENTITY_DB + rec * ENTITY_STRIDE + 4
        ptr = u32(rom, name_off)
        info = {
            "ptr": hex(ptr) if 0x08000000 <= ptr < 0x0A000000 else hex(ptr),
            "decoded": decode_name(rom, dict8, map8, ptr) if 0x08000000 <= ptr < 0x0A000000 else "",
            "sheet": name_owner_to_row.get(name_off),
        }
        name_by_rec[rec] = info

    weapons = []
    for record_id in PENDING:
        row = by_id[record_id]
        owners = owner_offsets(row)
        units = []
        for owner in owners:
            info = entity_from_owner(owner)
            rec = None if info is None else info["rec"]
            units.append({
                "owner": hex(owner),
                "entity": info,
                "unit_name": None if rec is None else name_by_rec.get(rec),
            })
        weapons.append({
            "record_id": record_id,
            "source_text": row.get("source_text"),
            "ko": row.get("translation_ko") or "",
            "raw_hex": row.get("raw_hex"),
            "units": units,
        })

    ptrs = {}
    for off in LITS:
        ptrs[hex(off)] = {
            "value": hex(u32(rom, off)),
            "ldr_sites": ldr_sites_for_literal(rom, off),
            "nearby": rom[off - 16 : off + 20].hex(" ").upper(),
        }

    OUT.write_text(json.dumps({"mishudeuk_lits": ptrs, "weapons": weapons}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "weapons": len(weapons)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
