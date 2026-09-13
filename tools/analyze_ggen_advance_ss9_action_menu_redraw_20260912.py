#!/usr/bin/env python3
"""Second-pass: BG0 menu map + action-menu redraw path for the ss9 1-frame hole."""
from __future__ import annotations

import json
import struct
from collections import defaultdict
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from PIL import Image, ImageDraw

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_action_menu_ko_poc as action
import render_ggen_ss_tiles_20260905 as renderer

ROOT = Path(__file__).resolve().parents[1]
ROM_BASE = 0x08000000
STATE = ROOT / "SD Gundam GGeneration Advance (Korean).ss9"
ROM_PATH = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
OUT = ROOT / "outputs" / "20260912_ggen_advance_ss9_action_menu_flash"
REPORT = ROOT / "analysis" / "ggen_advance_ss9_action_menu_redraw_20260912.json"
LABELS = {18: "이동N", 19: "대열N", 20: "공격N", 21: "간접N", 22: "IDN", 23: "포획N", 24: "변형N",
          30: "이동F", 31: "대열F", 32: "공격F", 33: "간접F", 34: "IDF", 35: "포획F", 36: "변형F",
          42: "이동D", 43: "IDD"}


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def bl_target(data, addr):
    off = addr - ROM_BASE
    h1, h2 = struct.unpack_from("<HH", data, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    disp = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (addr + 4 + disp) & 0xFFFFFFFF


def find_func_start(rom, addr, limit=0x80):
    """Walk back to a common Thumb prologue (push {..lr})."""
    off = addr - ROM_BASE
    for delta in range(0, limit, 2):
        p = off - delta
        if p < 0:
            break
        hw = u16(rom, p)
        if hw & 0xFF00 == 0xB500 or hw in (0xB570, 0xB5F0, 0xB5F8, 0xB5E0, 0xB5C0, 0xB580):
            return ROM_BASE + p
        if hw == 0xB5FE or hw == 0xB5FF:
            return ROM_BASE + p
    return addr


def disasm(rom, start, size):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    rows = []
    for ins in md.disasm(rom[start - ROM_BASE : start - ROM_BASE + size], start):
        row = {"a": f"0x{ins.address:08X}", "s": f"{ins.mnemonic} {ins.op_str}"}
        t = bl_target(rom, ins.address) if ins.mnemonic in ("bl", "blx") or len(ins.bytes) == 4 else None
        if ins.mnemonic == "bl":
            t = bl_target(rom, ins.address)
            if t:
                row["bl"] = f"0x{t:08X}"
        if ins.mnemonic == "swi":
            row["swi"] = ins.op_str
        rows.append(row)
    return rows


def find_calls(rom, target, lo=0x08000000, hi=0x08120000):
    hits = []
    data = rom[lo - ROM_BASE : hi - ROM_BASE]
    for i in range(0, len(data) - 3, 2):
        dest = bl_target(rom, lo + i)
        if dest == target:
            hits.append(f"0x{lo + i:08X}")
            if len(hits) >= 32:
                break
    return hits


def load_maps(rom):
    table = u32(rom, action.TABLE_CONSUMER_LITERALS[0]) - ROM_BASE
    atlas_off = u32(rom, table) - ROM_BASE
    body = u32(rom, atlas_off) & 0xFFFF
    atlas = scan.lzss_decompress(rom[atlas_off + 4 : atlas_off + 4 + body])
    maps = {}
    for i in range(action.RESOURCE_COUNT):
        mp = u32(rom, table + i * 4)
        if mp:
            maps[i] = action.parse_map(rom, mp)
    return table, atlas, maps


def main():
    rom = ROM_PATH.read_bytes()
    st, _ = statefmt.parse_png_state(STATE)
    table, atlas, maps = load_maps(rom)
    vram = st[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    info = bgutil.bg_info(st, 0)
    # Menu column: ss9 buttons start at screen x=32,y=24. Include chrome.
    grid = []
    for ty in range(1, 18):
        row = []
        for tx in range(3, 10):
            cell = bgutil.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tid = cell & 0x3FF
            raw = bytes(vram[info["char_base"] + tid * 32 : info["char_base"] + tid * 32 + 32])
            zero = sum(1 for y in range(8) for x in range(8) if ((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 15) == 0)
            row.append({"tx": tx, "ty": ty, "sx": tx * 8, "sy": ty * 8, "cell": f"0x{cell:04X}",
                        "tile": tid, "pal": (cell >> 12) & 15, "flip": (cell >> 10) & 3, "zero64": zero})
        grid.append(row)

    # Match each 4x2 at x=4 (tile), y=3,5,7... to resources
    buttons = []
    for by in range(3, 16, 2):
        cells = [bgutil.map_entry(vram, info["screen_base"], info["size"], 4 + x, by + y) for y in range(2) for x in range(4)]
        live = [c & 0x3FF for c in cells]
        hit = None
        for idx, mp in maps.items():
            if mp["width"] == 4 and mp["height"] == 2 and [c & 0x3FF for c in mp["cells"]]:
                src = action.stitch_map(atlas, mp)
                pix = []
                # compare live stitched vs resource via tile id sets and exact pixel
                from analyze_ggen_advance_ss9_action_menu_flash_20260912 import stitch_live, flatten
                live_pix = stitch_live(vram, info["char_base"], cells, 4)
                if flatten(live_pix) == flatten(src):
                    hit = {"resource": idx, "name": LABELS.get(idx, str(idx))}
                    break
        buttons.append({"y": by * 8, "tiles": live, "cells": [f"0x{c:04X}" for c in cells], "match": hit,
                        "any_tile0": 0 in live})

    # Frame resources 10-17: look for tile-0 wells
    frames = []
    for i in range(10, 18):
        mp = maps[i]
        ids = [c & 0x3FF for c in mp["cells"]]
        frames.append({"resource": i, "w": mp["width"], "h": mp["height"], "tile0_cells": ids.count(0),
                       "unique": len(set(ids)), "ids": ids})

    # Label resources: tile0 in maps?
    labels = []
    for i, name in LABELS.items():
        if i not in maps:
            continue
        mp = maps[i]
        ids = [c & 0x3FF for c in mp["cells"]]
        pix = [v for row in action.stitch_map(atlas, mp) for v in row]
        labels.append({"resource": i, "name": name, "ids": ids, "map_tile0": ids.count(0), "pixel0": pix.count(0),
                       "pixels": len(pix)})

    # Disassemble consumers and their function starts
    literal_info = []
    for lit in action.TABLE_CONSUMER_LITERALS:
        addr = ROM_BASE + lit
        start = find_func_start(rom, addr)
        literal_info.append({"literal": f"0x{addr:08X}", "value": f"0x{u32(rom, lit):08X}",
                             "func_guess": f"0x{start:08X}", "calls": find_calls(rom, start | 1) or find_calls(rom, start),
                             "disasm": disasm(rom, start, 0x140)})

    # Known blitters
    helpers = {}
    for a, n, sz in ((0x0800269C, "blit269C", 0x180), (0x0800261C, "upload261C", 0x80),
                     (0x08001928, "xfer1928", 0x80), (0x08000CA0, "textCA0", 0x40)):
        helpers[n] = {"start": f"0x{a:08X}", "calls_from": find_calls(rom, a), "disasm": disasm(rom, a, sz)}

    # Search action-menu range for swi / stores to 0x0600
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    swis = []
    for ins in md.disasm(rom[0x14E00:0x15800], 0x08014E00):
        if ins.mnemonic in ("swi", "stm", "stmia") or "0x6000000" in ins.op_str or "0600" in ins.op_str:
            swis.append({"a": f"0x{ins.address:08X}", "s": f"{ins.mnemonic} {ins.op_str}"})

    OUT.mkdir(parents=True, exist_ok=True)
    renderer.OUT = OUT
    # Force render module global
    import render_ggen_ss_tiles_20260905 as r2
    r2.OUT = OUT
    frame = renderer.render(st)
    crop = frame.crop((24, 0, 80, 160)).resize((224, 640), Image.Resampling.NEAREST)
    crop.save(OUT / "ss9_menu_left.png")
    marked = frame.copy()
    d = ImageDraw.Draw(marked)
    for b in buttons:
        color = (0, 255, 0) if b["match"] and not b["any_tile0"] else (255, 0, 0)
        d.rectangle((32, b["y"], 63, b["y"] + 15), outline=color)
    marked.crop((0, 0, 120, 160)).resize((480, 640), Image.Resampling.NEAREST).save(OUT / "ss9_menu_marked.png")
    frame.resize((960, 640), Image.Resampling.NEAREST).save(OUT / "ss9_full.png")

    report = {
        "bg0": info,
        "grid": grid,
        "buttons": buttons,
        "frames": frames,
        "labels": labels,
        "literals": [{"literal": x["literal"], "value": x["value"], "func_guess": x["func_guess"],
                      "calls": x["calls"], "disasm": x["disasm"]} for x in literal_info],
        "helpers": {k: {"start": v["start"], "calls_from_count": len(v["calls_from"]),
                        "calls_from": v["calls_from"][:12], "disasm": v["disasm"][:40]} for k, v in helpers.items()},
        "swis_in_menu_range": swis,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "buttons": buttons,
        "frames": [{"resource": f["resource"], "w": f["w"], "h": f["h"], "tile0_cells": f["tile0_cells"]} for f in frames],
        "labels": labels,
        "func_guesses": [{"literal": x["literal"], "func": x["func_guess"], "ncalls": len(x["calls"])} for x in literal_info],
        "swis": swis,
        "blit_calls": {k: v["calls_from"][:8] for k, v in helpers.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
