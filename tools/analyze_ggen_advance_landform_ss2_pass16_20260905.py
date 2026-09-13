#!/usr/bin/env python3
"""Disassemble LANDFORM resource loader at 0x0801DBxx and find 海 draw."""
from __future__ import annotations

import json
import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

from analyze_direct_pc_literal import thumb_bl_target
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass16_20260905.json"
ROM_BASE = 0x08000000
DRAW = {0x08000CA0, 0x08000D10, 0x08001354, 0x08001298, 0x08000648, 0x0800072C, 0x08001D70}


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def decode_stream(rom, charmap, dict12, off, limit=48):
    if not (0 <= off < len(rom) - 1):
        return None
    try:
        tokens, raw = read_tokens(rom, off, limit=limit)
        if len(raw) > 40 or len(tokens) > 12:
            return None
        slots = expand_to_slots(tokens, dict12)
        text = "".join(charmap.get(s, f"<{s:04X}>") for s in slots)
        return {"text": text, "raw": raw.hex(), "n": len(slots), "offset": hex(off)}
    except Exception:
        return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = False

    start, end = 0x1D800, 0x1E200
    insns = []
    bls = []
    literals = []
    for insn in md.disasm(japan[start:end], ROM_BASE + start):
        row = {"addr": hex(insn.address), "m": insn.mnemonic, "op": insn.op_str}
        insns.append(row)
        off = insn.address - ROM_BASE
        target = thumb_bl_target(japan, off)
        if target:
            bls.append({"addr": hex(insn.address), "target": hex(target), "known": target in DRAW})
        if insn.mnemonic == "ldr" and "pc" in insn.op_str:
            # Thumb-1 pc literal
            if off + 2 <= end:
                half = u16(japan, off)
                if half & 0xF800 == 0x4800:
                    lit = ((off + 4) & ~3) + ((half & 0xFF) << 2)
                    val = u32(japan, lit)
                    decoded = None
                    if ROM_BASE <= val < ROM_BASE + 0x01000000:
                        decoded = decode_stream(japan, charmap, dict12, val - ROM_BASE)
                    literals.append({"insn": hex(insn.address), "lit": hex(lit), "val": hex(val), "decoded": decoded, "op": insn.op_str})

    # Parse bytes at E3064
    hdr = japan[0xE3060:0xE3180]
    # Also dump E3050 as potential map header
    e30 = {
        "hex_e3050": japan[0xE3050:0xE3160].hex(),
        "u16_e3064": [hex(u16(japan, 0xE3064 + i * 2)) for i in range(16)],
        "bytes_e3064": list(japan[0xE3064:0xE3074]),
    }

    # Pointer table scan around the function: any GBA ptr that decodes as 1-4 char 12x12
    short_ptrs = []
    for off in range(start, end, 4):
        val = u32(japan, off)
        if not (ROM_BASE <= val < ROM_BASE + 0x01000000):
            continue
        decoded = decode_stream(japan, charmap, dict12, val - ROM_BASE)
        if decoded and 1 <= decoded["n"] <= 6 and "<" not in decoded["text"]:
            short_ptrs.append({"pool": hex(off), "val": hex(val), **decoded})

    report = {
        "bls": bls,
        "literals": literals,
        "short_ptrs": short_ptrs,
        "e30": e30,
        "insns_head": insns[:40],
        "insns_around_ref": [row for row in insns if int(row["addr"], 16) >= 0x0801DB80][:80],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("bls", json.dumps(bls, indent=2))
    print("literals", json.dumps(literals, ensure_ascii=False, indent=2)[:4000])
    print("short_ptrs", json.dumps(short_ptrs, ensure_ascii=False, indent=2)[:4000])
    print("e30 u16", e30["u16_e3064"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
