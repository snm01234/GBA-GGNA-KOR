#!/usr/bin/env python3
"""Find 12x12 draws in LANDFORM setup callees and parse 0x080E3064."""
from __future__ import annotations

import json
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

from analyze_direct_pc_literal import thumb_bl_target
from analyze_ggen_advance_fixed_word_semantics_20260830 as sem
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass17_20260905.json"
ROM_BASE = 0x08000000
DRAW = {0x08000CA0: "CA0", 0x08000D10: "D10", 0x08001354: "r12", 0x08001298: "r8"}


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def decode_stream(rom, charmap, dict12, off, limit=48):
    if not (0 <= off < len(rom) - 1):
        return None
    try:
        tokens, raw = read_tokens(rom, off, limit=limit)
        if not (1 <= len(tokens) <= 8):
            return None
        slots = expand_to_slots(tokens, dict12)
        text = "".join(charmap.get(s, f"<{s:04X}>") for s in slots)
        return {"text": text, "raw": raw.hex(), "n": len(slots), "offset": hex(off)}
    except Exception:
        return None


def scan_range(japan, lo, hi, charmap, dict12):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    bls = []
    for off in range(lo, hi - 3, 2):
        target = thumb_bl_target(japan, off)
        if target in DRAW:
            bls.append({"addr": hex(ROM_BASE + off), "fn": DRAW[target]})
    literals = []
    for off in range(lo, hi - 1, 2):
        half = u16(japan, off)
        if half & 0xF800 != 0x4800:
            continue
        lit = ((off + 4) & ~3) + ((half & 0xFF) << 2)
        if not (lo <= lit < hi + 0x40):
            continue
        val = u32(japan, lit)
        decoded = None
        if ROM_BASE <= val < ROM_BASE + 0x01000000:
            decoded = decode_stream(japan, charmap, dict12, val - ROM_BASE)
        literals.append({
            "insn": hex(ROM_BASE + off),
            "reg": (half >> 8) & 7,
            "val": hex(val),
            "decoded": decoded,
        })
    insns = []
    for insn in md.disasm(japan[lo:hi], ROM_BASE + lo):
        insns.append(f"{insn.address:08X}: {insn.mnemonic} {insn.op_str}")
        if len(insns) >= 120:
            break
    return {"bls": bls, "literals": literals, "insns": insns}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    parsed = sem.parse_map(japan, 0x080E3064)
    parsed2 = sem.parse_map(japan, 0x080E3060)
    parsed3 = sem.parse_map(japan, 0x080E3058)

    # scan landform setup and callees
    regions = {
        "setup": (0x1D000, 0x1E400),
        "callee_12e8c": (0x12E00, 0x13200),
        "callee_1d09c": (0x1D000, 0x1D800),
        "callee_3050": (0x3000, 0x3300),
        "wide_map_ui": (0x1C000, 0x1F000),
    }
    scanned = {name: scan_range(japan, lo, hi, charmap, dict12) for name, (lo, hi) in regions.items()}

    # Any CA0 in 0x0801C000-0x0801F000 with nearby decoded short strings
    interesting = []
    for row in scanned["wide_map_ui"]["literals"]:
        dec = row.get("decoded")
        if not dec:
            continue
        if "海" in dec["text"] or (dec["n"] <= 4 and "<" not in dec["text"]):
            interesting.append(row)

    report = {
        "parse_e3064": parsed,
        "parse_e3060": parsed2,
        "parse_e3058": parsed3,
        "hex_e3048": japan[0xE3048:0xE3168].hex(),
        "scanned_bls": {k: v["bls"] for k, v in scanned.items()},
        "interesting_lits": interesting,
        "setup_insns": scanned["setup"]["insns"][:80],
        "callee_12e8c_insns": scanned["callee_12e8c"]["insns"][:80],
        "callee_12e8c_lits": scanned["callee_12e8c"]["literals"],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("parse_e3064", json.dumps(parsed, ensure_ascii=False)[:1500])
    print("parse_e3060", parsed2)
    print("parse_e3058", parsed3)
    print("bls", json.dumps(report["scanned_bls"], indent=2)[:3000])
    print("interesting", json.dumps(interesting, ensure_ascii=False, indent=2)[:3000])
    print("12e8c lits", json.dumps(scanned["callee_12e8c"]["literals"], ensure_ascii=False, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
