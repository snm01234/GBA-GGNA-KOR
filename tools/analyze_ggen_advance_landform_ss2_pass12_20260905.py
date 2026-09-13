#!/usr/bin/env python3
"""Pointer-hunt every 海 payload and stitch LANDFORM 回避 4x2 for painting."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass12_20260905.json"
PREVIEW = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_landform" / "landform_evade_src.png"
GFX = 0x000E3154
ROM_BASE = 0x08000000
EVADE = (55, 56, 57, 58, 67, 68, 69, 70)


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def rgb555(v):
    return tuple(((v >> s) & 31) * 255 // 31 for s in (0, 5, 10))


def decode_tile(raw):
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + x // 2]
            out[y][x] = (packed >> (4 * (x & 1))) & 15
    return out


def find_all(hay, needle, limit=16):
    hits = []
    start = 0
    while len(hits) < limit:
        pos = hay.find(needle, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
    return hits


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    rom = MAIN_TIP_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    ewram = state[0x21000:0x61000]
    iwram = state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + 0x8000]
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    payloads = find_all(japan, bytes.fromhex("E0 E1 00"), 40)
    pointed = []
    for off in payloads:
        addr = ROM_BASE + off
        needle = struct.pack("<I", addr)
        refs = {
            "jp": [hex(h) for h in find_all(japan, needle, 8)],
            "main": [hex(h) for h in find_all(rom, needle, 8)],
            "ewram": [hex(h) for h in find_all(ewram, needle, 8)],
            "iwram": [hex(h) for h in find_all(iwram, needle, 8)],
        }
        if any(refs.values()):
            try:
                tokens, raw = read_tokens(japan, off, limit=24)
                slots = expand_to_slots(tokens, dict12)
                text = "".join(charmap.get(s, f"<{s:04X}>") for s in slots)
            except Exception:
                text, raw = "?", b""
            pointed.append({"payload": hex(off), "text": text, "refs": refs})

    # Stitch 回避 from ROM sheet with live pal bank 11 (OBJ/BG pal 0xB)
    canvas = [[0] * 32 for _ in range(16)]
    for i, tile in enumerate(EVADE):
        tx, ty = i % 4, i // 4
        raw = japan[GFX + tile * 32 : GFX + tile * 32 + 32]
        pix = decode_tile(raw)
        for y in range(8):
            for x in range(8):
                canvas[ty * 8 + y][tx * 8 + x] = pix[y][x]
    colors = [rgb555(u16(pal, (11 * 16 + i) * 2)) for i in range(16)]
    img = Image.new("RGB", (32, 16))
    px = img.load()
    counts = [0] * 16
    for y in range(16):
        for x in range(32):
            idx = canvas[y][x]
            counts[idx] += 1
            px[x, y] = colors[idx]
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    img.resize((256, 128), Image.NEAREST).save(PREVIEW)

    uniqueness = []
    for tile in EVADE:
        raw = japan[GFX + tile * 32 : GFX + tile * 32 + 32]
        uniqueness.append({"tile": tile, "jp_hits": len(find_all(japan, raw, 20)), "main_hits": len(find_all(rom, raw, 20)), "off": hex(GFX + tile * 32)})

    report = {
        "pointed_sea_payloads": pointed,
        "palette_index_counts": counts,
        "uniqueness": uniqueness,
        "preview": str(PREVIEW),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
