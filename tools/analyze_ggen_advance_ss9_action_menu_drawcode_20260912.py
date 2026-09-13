#!/usr/bin/env python3
"""Disassemble the action-menu draw/cursor-move helpers and inspect frame maps."""
from __future__ import annotations

import json
import struct
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import build_ggen_advance_action_menu_ko_poc as action

ROOT = Path(__file__).resolve().parents[1]
ROM_BASE = 0x08000000
ROM = (ROOT / "SD Gundam GGeneration Advance (Korean).gba").read_bytes()
OUT = ROOT / "analysis" / "ggen_advance_ss9_action_menu_drawcode_20260912.json"


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def bl_target(addr):
    off = addr - ROM_BASE
    h1, h2 = struct.unpack_from("<HH", ROM, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    disp = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (addr + 4 + disp) & 0xFFFFFFFF


def disasm_range(start, end):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.skipdata = True
    rows = []
    for ins in md.disasm(ROM[start - ROM_BASE : end - ROM_BASE], start):
        row = {"a": f"0x{ins.address:08X}", "b": bytes(ins.bytes).hex(), "s": f"{ins.mnemonic} {ins.op_str}"}
        if ins.mnemonic == "bl":
            t = bl_target(ins.address)
            if t:
                row["bl"] = f"0x{t:08X}"
        if ins.mnemonic == "ldr" and "pc" in ins.op_str and "#" in ins.op_str:
            try:
                imm = int(ins.op_str.split("#", 1)[1].split("]", 1)[0], 0)
                lit = ((ins.address + 4) & ~3) + imm
                row["lit"] = f"0x{lit:08X}"
                row["val"] = f"0x{u32(ROM, lit - ROM_BASE):08X}"
            except Exception:
                pass
        rows.append(row)
    return rows


def main():
    table = u32(ROM, action.TABLE_CONSUMER_LITERALS[0]) - ROM_BASE
    atlas_off = u32(ROM, table) - ROM_BASE
    atlas = scan.lzss_decompress(ROM[atlas_off + 4 : atlas_off + 4 + (u32(ROM, atlas_off) & 0xFFFF)])
    maps = {i: action.parse_map(ROM, u32(ROM, table + i * 4)) for i in range(44) if u32(ROM, table + i * 4)}

    frames = {}
    for i in range(10, 18):
        mp = maps[i]
        w, h = mp["width"], mp["height"]
        grid = []
        for y in range(h):
            row = []
            for x in range(w):
                c = mp["cells"][y * w + x]
                row.append({"x": x, "y": y, "tid": c & 0x3FF, "pal": (c >> 12) & 15, "cell": f"0x{c:04X}"})
            grid.append(row)
        # Button column guess: x=1..4 inside 11-wide frame (x=0 chrome)
        button_cols = []
        for y in range(h):
            button_cols.append([grid[y][x]["tid"] for x in range(min(5, w))])
        frames[str(i)] = {"w": w, "h": h, "button_col_tids": button_cols, "tile0": sum(1 for c in mp["cells"] if (c & 0x3FF) == 0)}

    # Compare frame-17 button 4x2 strips vs label resources
    mp17 = maps[17]
    w, h = mp17["width"], mp17["height"]
    strips = []
    for y in range(0, h - 1, 2):
        ids = [mp17["cells"][(y + dy) * w + (1 + dx)] & 0x3FF for dy in range(2) for dx in range(4)]
        match = None
        for idx, mp in maps.items():
            if mp["width"] == 4 and mp["height"] == 2 and [c & 0x3FF for c in mp["cells"]] == ids:
                match = idx
                break
        strips.append({"y": y, "ids": ids, "match_resource": match, "all_zero": all(v == 0 for v in ids)})

    code = disasm_range(0x08014E80, 0x08015740)
    interesting = [r for r in code if r["s"].startswith("bl ") or "lit" in r or r["s"].startswith("swi") or "0x6000000" in r["s"]]
    OUT.write_text(json.dumps({
        "strips_res17": strips,
        "frames_tile0": {k: v["tile0"] for k, v in frames.items()},
        "frame17_button_cols": frames["17"]["button_col_tids"],
        "code_interesting": interesting,
        "code": code,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "strips_res17": strips,
        "interesting": interesting,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
