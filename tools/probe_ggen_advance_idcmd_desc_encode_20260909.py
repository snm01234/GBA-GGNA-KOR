#!/usr/bin/env python3
"""Probe live relative-pair ID-command description encoding."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))

import build_ggen_advance_unified_rom_poc as unified
from ggen_advance_painted_glyph_identity import load_galmuri12, recover_unique_12x12_slots
from ggen_advance_project_paths import MAIN_TIP_ROM, TRANSLATION_MERGED_JSON
from patch_ggen_advance_map_script_inline_poc import encode_map_korean_line, load_identified_12x12

ROM_BASE = 0x08000000
RELATIVE_BASE_LITERAL = 0x0004DC54
RELATIVE_OLD_BASE = 0x001BF908
SAMPLE = "GGA-TEXT-001C0ED1"


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def owner_u16(row):
    for owner in row.get("owner_ids") or []:
        if str(owner).startswith("OWNER-U16-"):
            return int(str(owner).removeprefix("OWNER-U16-"), 16)
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rom = MAIN_TIP_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    row = next(r for r in merged["records"] if r["record_id"] == SAMPLE)
    owner = owner_u16(row)
    base = u32(rom, RELATIVE_BASE_LITERAL) - ROM_BASE
    rel = owner - RELATIVE_OLD_BASE
    off = u16(rom, base + rel)
    nxt = u16(rom, base + rel + 2)
    blob = rom[base + off: base + nxt]
    print("base", hex(base), "owner", hex(owner), "rel", hex(rel), "off", hex(off), "next", hex(nxt), "blob", blob.hex(" ").upper(), "len", len(blob))
    ko = row["translation_ko"]
    print("ko", ko, len(ko))
    hangul = {ch for ch in ko if "가" <= ch <= "힣"}
    font = load_galmuri12()
    recovered = recover_unique_12x12_slots(rom, font, hangul)
    identified = load_identified_12x12()
    verified = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    a, miss_a = unified.encode_korean_text(ko, recovered, verified_charmap=verified, strict_punctuation=True)
    b, miss_b = encode_map_korean_line(ko, recovered, identified)
    print("recovered", recovered)
    print("encode_korean", None if a is None else a.hex(" ").upper(), miss_a, "match_prefix", False if a is None else blob.startswith(a))
    print("encode_map", None if b is None else b.hex(" ").upper(), miss_b, "match_prefix", False if b is None else blob.startswith(b))
    # split pair
    nul = blob.find(0)
    print("line1", blob[:nul+1].hex(" ").upper(), "line2", blob[nul+1:].hex(" ").upper())


if __name__ == "__main__":
    main()
