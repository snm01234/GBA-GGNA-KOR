#!/usr/bin/env python3
"""Inspect atlas tile 7 (menu well), DMA3 setup, and 0x0801550C item blit."""
from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from PIL import Image

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_action_menu_ko_poc as action

ROOT = Path(__file__).resolve().parents[1]
ROM_BASE = 0x08000000
KO = (ROOT / "SD Gundam GGeneration Advance (Korean).gba").read_bytes()
JP = (ROOT / "SD Gundam GGeneration Advance (Japan).gba").read_bytes()
ST, _ = statefmt.parse_png_state(ROOT / "SD Gundam GGeneration Advance (Korean).ss9")
OUT = ROOT / "outputs" / "20260912_ggen_advance_ss9_action_menu_flash"
REPORT = ROOT / "analysis" / "ggen_advance_ss9_action_menu_well_dma_20260912.json"


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def bl_target(rom, addr):
    off = addr - ROM_BASE
    h1, h2 = struct.unpack_from("<HH", rom, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    disp = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (addr + 4 + disp) & 0xFFFFFFFF


def disasm(rom, start, size):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    rows = []
    for ins in md.disasm(rom[start - ROM_BASE : start - ROM_BASE + size], start):
        row = {"a": f"0x{ins.address:08X}", "s": f"{ins.mnemonic} {ins.op_str}"}
        if ins.mnemonic == "bl":
            t = bl_target(rom, ins.address)
            if t:
                row["bl"] = f"0x{t:08X}"
        if ins.mnemonic == "ldr" and "pc" in ins.op_str and "#" in ins.op_str:
            try:
                imm = int(ins.op_str.split("#", 1)[1].split("]", 1)[0], 0)
                lit = ((ins.address + 4) & ~3) + imm
                row["val"] = f"0x{u32(rom, lit - ROM_BASE):08X}"
            except Exception:
                pass
        rows.append(row)
    return rows


def load_atlas(rom):
    table = u32(rom, action.TABLE_CONSUMER_LITERALS[0]) - ROM_BASE
    off = u32(rom, table) - ROM_BASE
    return scan.lzss_decompress(rom[off + 4 : off + 4 + (u32(rom, off) & 0xFFFF)]), table


def tile_hist(atlas, tid):
    raw = atlas[tid * 32 : tid * 32 + 32]
    pix = []
    for y in range(8):
        for x in range(8):
            pix.append((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 15)
    return {"hist": dict(Counter(pix)), "zero": pix.count(0), "raw_sha": raw.hex()}


def decode_dma_cnt(word):
    count = word & 0xFFFF
    h = word >> 16
    dest = (h >> 5) & 3
    src = (h >> 7) & 3
    return {
        "raw": f"0x{word:08X}",
        "count": count,
        "bits32": bool(h & 0x400),
        "repeat": bool(h & 0x200),
        "dest": ["inc", "dec", "fixed", "reload"][dest],
        "src": ["inc", "dec", "fixed", "prohibited"][src],
        "enable": bool(h & 0x8000),
        "bytes": count * (4 if h & 0x400 else 2),
    }


def main():
    ko_atlas, ko_table = load_atlas(KO)
    jp_atlas, jp_table = load_atlas(JP)
    vram = ST[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    tiles = {n: tile_hist(ko_atlas, n) for n in range(0, 20)}
    tiles_jp = {n: tile_hist(jp_atlas, n) for n in range(0, 20)}
    live = {}
    for tid in list(range(0, 16)) + list(range(736, 752)) + [743, 744, 757]:
        raw = bytes(vram[tid * 32 : tid * 32 + 32])
        pix = []
        for y in range(8):
            for x in range(8):
                pix.append((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 15)
        live[tid] = {"hist": dict(Counter(pix)), "zero": pix.count(0), "match_atlas": next((i for i in range(len(ko_atlas)//32) if ko_atlas[i*32:i*32+32]==raw), None)}

    # Render tile 7 ko vs jp
    OUT.mkdir(parents=True, exist_ok=True)
    pal = ST[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    def tile_img(atlas, tid, bank=11):
        im = Image.new("RGB", (8, 8))
        raw = atlas[tid * 32 : tid * 32 + 32]
        for y in range(8):
            for x in range(8):
                v = (raw[y * 4 + x // 2] >> (4 * (x & 1))) & 15
                rgb = bgutil.rgb555(u16(pal, (bank * 16 + v) * 2))
                im.putpixel((x, y), rgb)
        return im.resize((64, 64), Image.Resampling.NEAREST)
    sheet = Image.new("RGB", (64 * 6, 64))
    for i, (name, atlas, tid) in enumerate((("ko7", ko_atlas, 7), ("jp7", jp_atlas, 7), ("ko0", ko_atlas, 0), ("jp0", jp_atlas, 0), ("ko8", ko_atlas, 8), ("jp8", jp_atlas, 8))):
        sheet.paste(tile_img(atlas, tid), (i * 64, 0))
    sheet.save(OUT / "tile7_compare.png")

    report = {
        "ko_tile7": tiles[7],
        "jp_tile7": tiles_jp[7],
        "ko_tiles_0_19": tiles,
        "jp_tiles_0_19": tiles_jp,
        "live_tiles": live,
        "tile7_changed": ko_atlas[7 * 32:8 * 32] != jp_atlas[7 * 32:8 * 32],
        "dma_85000200": decode_dma_cnt(0x85000200),
        "fn_1550C": disasm(KO, 0x0801550C, 0x90),
        "fn_153B0": disasm(KO, 0x080153B0, 0x50),
        "fn_15488": disasm(KO, 0x08015488, 0x40),
        "fn_14ED0": disasm(KO, 0x08014ED0, 0x40),
        "atlas_base_live": 736,
        "well_live_tile": 736 + 7,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ko_tile7": tiles[7],
        "jp_tile7": tiles_jp[7],
        "tile7_changed": report["tile7_changed"],
        "live_743": live.get(743),
        "live_744": live.get(744),
        "live_7": live.get(7),
        "dma": report["dma_85000200"],
        "fn_1550C": report["fn_1550C"],
        "fn_153B0": report["fn_153B0"],
        "fn_15488": report["fn_15488"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
