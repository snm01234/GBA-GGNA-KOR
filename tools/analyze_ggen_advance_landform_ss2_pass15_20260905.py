#!/usr/bin/env python3
"""Bind LANDFORM text draw to the 回避 sheet function, decode nearby strings."""
from __future__ import annotations

import json
import struct
import sys

import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)
from analyze_direct_pc_literal import thumb_bl_target

CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass15_20260905.json"
ROM_BASE = 0x08000000
GFX = 0x000E3154
DRAW_WRAPPER = 0x08000CA0
DRAW_D10 = 0x08000D10


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def decode_stream(rom, charmap, dict12, off, limit=48):
    if not (0 <= off < len(rom) - 1):
        return None
    try:
        tokens, raw = read_tokens(rom, off, limit=limit)
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
    calls = draw.draw_calls(japan)

    decoded_xy = []
    for call in calls:
        val = call.get("r3_literal_value")
        decoded = None
        if val and ROM_BASE <= val < ROM_BASE + 0x01000000:
            decoded = decode_stream(japan, charmap, dict12, val - ROM_BASE)
        cx, cy = call.get("x_r1"), call.get("y_r2")
        keep = False
        if cx in {45, 40, 48, 96, 100, 101, 104, 72, 88} or cy in {18, 16, 20, 72, 74, 80}:
            keep = True
        if decoded and ("海" in decoded["text"] or len(decoded["text"]) <= 4):
            keep = keep or (decoded["n"] <= 4)
        if keep and cx is not None:
            decoded_xy.append({
                "call": hex(call["call"]),
                "renderer": call["renderer"],
                "x": cx,
                "y": cy,
                "r3": hex(val) if val else None,
                "decoded": decoded,
            })

    # Pointers to gfx sheet, then BL CA0/D10 within +/- 0x400
    needle = struct.pack("<I", ROM_BASE + GFX)
    gfx_refs = []
    start = 0
    while True:
        hit = japan.find(needle, start)
        if hit < 0:
            break
        gfx_refs.append(hit)
        start = hit + 1
        if len(gfx_refs) >= 20:
            break

    nearby_draws = []
    for ref in gfx_refs:
        lo, hi = max(0, ref - 0x400), min(len(japan) - 4, ref + 0x400)
        for off in range(lo & ~1, hi, 2):
            target = thumb_bl_target(japan, off)
            if target in {DRAW_WRAPPER, DRAW_D10}:
                nearby_draws.append({"gfx_ref": hex(ref), "bl": hex(ROM_BASE + off), "target": hex(target)})

    # Also search any pointer to 0x080E3xxx (sheet neighborhood)
    neighborhood_refs = []
    for addr in range(0x080E3000, 0x080E3C00, 4):
        n = struct.pack("<I", addr)
        pos = japan.find(n)
        if pos >= 0:
            neighborhood_refs.append({"addr": hex(addr), "ref": hex(pos)})

    # Decode 地上 neighborhoods as C-string pools
    ground_pools = []
    for off in (0x1805B8, 0x18D65F):
        strings = []
        cursor = off - 64
        for _ in range(24):
            row = decode_stream(japan, charmap, dict12, cursor, limit=32)
            if row and 1 <= row["n"] <= 6:
                strings.append(row)
                cursor = int(row["offset"], 16) + len(bytes.fromhex(row["raw"]))
            else:
                cursor += 1
            if cursor > off + 96:
                break
        ground_pools.append({"seed": hex(off), "strings": strings[:20]})

    # Decode the two xy-close literals
    specials = {
        "0x081be7c7": decode_stream(japan, charmap, dict12, 0x01BE7C7, limit=64),
        "0x08d56380": decode_stream(japan, charmap, dict12, 0x00D56380, limit=64),
        "0x01be7c4": decode_stream(japan, charmap, dict12, 0x01BE7C4, limit=64),
        "0x01be7c0": decode_stream(japan, charmap, dict12, 0x01BE7C0, limit=64),
    }

    # Relative xy 45,18 among all calls
    rel = [
        {
            "call": hex(c["call"]),
            "renderer": c["renderer"],
            "x": c.get("x_r1"),
            "y": c.get("y_r2"),
            "r3": hex(c["r3_literal_value"]) if c.get("r3_literal_value") else None,
        }
        for c in calls
        if c.get("x_r1") in {45, 44, 46, 40, 48, 32, 36} or c.get("y_r2") in {18, 17, 19, 16, 20, 24}
    ]

    report = {
        "gfx_refs": [hex(r) for r in gfx_refs],
        "nearby_draws": nearby_draws,
        "neighborhood_refs": neighborhood_refs[:40],
        "specials": specials,
        "rel_xy": rel,
        "decoded_xy_sample": decoded_xy[:40],
        "ground_pools": ground_pools,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("gfx_refs", report["gfx_refs"])
    print("nearby_draws", nearby_draws)
    print("specials", json.dumps(specials, ensure_ascii=False, indent=2)[:2000])
    print("rel_xy", json.dumps(rel, ensure_ascii=False, indent=2)[:2500])
    print("neighborhood", neighborhood_refs[:20])
    print("ground", json.dumps(ground_pools, ensure_ascii=False)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
