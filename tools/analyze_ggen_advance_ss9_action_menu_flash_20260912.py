#!/usr/bin/env python3
"""Read-only diagnosis of the ss9 battle action-menu 1-frame hole.

The user-captured ss9 and screenshot show the right-side command list with a
see-through slot where 이동 should be.  This tool reconstructs live BG/OBJ,
matches the 32x16 action resources, and inspects WIN/blend/OAM for a 1-frame
cover during D-pad selection changes.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_action_menu_ko_poc as action
import render_ggen_ss_tiles_20260905 as renderer

STATE = ROOT / "SD Gundam GGeneration Advance (Korean).ss9"
ROM_PATH = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JP_PATH = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ROOT / "outputs" / "20260912_ggen_advance_ss9_action_menu_flash"
REPORT = ROOT / "analysis" / "ggen_advance_ss9_action_menu_flash_20260912.json"
ROM_BASE = 0x08000000
LABELS = {
    0: "이동",
    1: "대열",
    2: "공격",
    3: "간접",
    4: "ID",
    5: "포획",
    6: "변형",
    7: "교신",
    8: "발진",
    9: "확정",
    10: "전체",
    11: "개별",
}


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile_bytes(raw: bytes) -> list[list[int]]:
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + x // 2]
            out[y][x] = (packed >> (4 * (x & 1))) & 15
    return out


def tile_zero_ratio(raw: bytes) -> float:
    pix = [v for row in decode_tile_bytes(raw) for v in row]
    return pix.count(0) / 64


def io_dump(io: bytes) -> dict[str, Any]:
    disp = u16(io, 0)
    win0h, win1h = u16(io, 0x40), u16(io, 0x42)
    win0v, win1v = u16(io, 0x44), u16(io, 0x46)
    return {
        "dispcnt": f"0x{disp:04X}",
        "mode": disp & 7,
        "obj_1d": bool(disp & 0x40),
        "force_blank": bool(disp & 0x80),
        "bg_enable": [bool(disp & (0x100 << i)) for i in range(4)],
        "obj_enable": bool(disp & 0x1000),
        "win0": bool(disp & 0x2000),
        "win1": bool(disp & 0x4000),
        "objwin": bool(disp & 0x8000),
        "dispstat": f"0x{u16(io, 4):04X}",
        "vcount": u16(io, 6),
        "win0h": {"left": win0h >> 8, "right": win0h & 0xFF, "raw": f"0x{win0h:04X}"},
        "win1h": {"left": win1h >> 8, "right": win1h & 0xFF, "raw": f"0x{win1h:04X}"},
        "win0v": {"top": win0v >> 8, "bottom": win0v & 0xFF, "raw": f"0x{win0v:04X}"},
        "win1v": {"top": win1v >> 8, "bottom": win1v & 0xFF, "raw": f"0x{win1v:04X}"},
        "winin": f"0x{u16(io, 0x48):04X}",
        "winout": f"0x{u16(io, 0x4A):04X}",
        "mosaic": f"0x{u16(io, 0x4C):04X}",
        "bldcnt": f"0x{u16(io, 0x50):04X}",
        "bldalpha": f"0x{u16(io, 0x52):04X}",
        "bldy": f"0x{u16(io, 0x54):04X}",
    }


def load_action_table(rom: bytes) -> tuple[int, bytes, dict[int, dict]]:
    table = None
    for literal in action.TABLE_CONSUMER_LITERALS:
        ptr = u32(rom, literal)
        if table is None:
            table = ptr
        elif ptr != table:
            raise SystemExit(f"action table literal drift at 0x{literal:08X}")
    if table is None:
        raise SystemExit("action table missing")
    table_off = table - ROM_BASE
    atlas_ptr = u32(rom, table_off)
    atlas_off = atlas_ptr - ROM_BASE
    header = u32(rom, atlas_off)
    body = header & 0xFFFF
    atlas = scan.lzss_decompress(rom[atlas_off + 4 : atlas_off + 4 + body])
    maps = {}
    for i in range(action.RESOURCE_COUNT):
        mp = u32(rom, table_off + i * 4)
        if not mp:
            continue
        maps[i] = action.parse_map(rom, mp)
    return table_off, atlas, maps


def stitch_live(vram: bytes, char_base: int, cells: list[int], width: int) -> list[list[int]]:
    h = len(cells) // width
    pixels = [[0] * (width * 8) for _ in range(h * 8)]
    for ty in range(h):
        for tx in range(width):
            cell = cells[ty * width + tx]
            raw = bytes(vram[char_base + (cell & 0x3FF) * 32 : char_base + (cell & 0x3FF) * 32 + 32])
            tile = decode_tile_bytes(raw)
            hflip, vflip = bool(cell & 0x400), bool(cell & 0x800)
            for yy in range(8):
                sy = 7 - yy if vflip else yy
                for xx in range(8):
                    sx = 7 - xx if hflip else xx
                    pixels[ty * 8 + yy][tx * 8 + xx] = tile[sy][sx]
    return pixels


def nmi_indices(a: list[int], b: list[int]) -> float:
    return scan.nmi(a, b)


def flatten(pixels: list[list[int]]) -> list[int]:
    return [v for row in pixels for v in row]


def match_resource(live_pixels: list[list[int]], maps: dict[int, dict], atlas: bytes) -> list[dict[str, Any]]:
    live = flatten(live_pixels)
    hits = []
    for idx, mp in maps.items():
        if mp["width"] * 8 != len(live_pixels[0]) or mp["height"] * 8 != len(live_pixels):
            continue
        src = flatten(action.stitch_map(atlas, mp))
        score = nmi_indices(live, src)
        exact = live == src
        if exact or score >= 0.55:
            hits.append({"resource": idx, "nmi": round(score, 4), "exact": exact, "label": LABELS.get(idx - 18, LABELS.get(idx - 30, ""))})
    hits.sort(key=lambda r: (r["exact"], r["nmi"]), reverse=True)
    return hits[:6]


def scan_menu_slots(state: bytes, atlas: bytes, maps: dict[int, dict]) -> list[dict[str, Any]]:
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    disp = u16(io, 0)
    slots = []
    for layer in range(4):
        if not (disp & (0x100 << layer)):
            continue
        info = bgutil.bg_info(state, layer)
        if info["color_8bpp"]:
            continue
        # Right command column plus a little slack; also scan full screen 4x2.
        for sy in range(0, 160, 8):
            for sx in range(0, 240, 8):
                cells = []
                palettes = []
                zero_ratios = []
                for ty in range(2):
                    for tx in range(4):
                        px, py = sx + tx * 8, sy + ty * 8
                        if px >= 240 or py >= 160:
                            cells = []
                            break
                        wx, wy = px + info["scroll_x"], py + info["scroll_y"]
                        cell = bgutil.map_entry(vram, info["screen_base"], info["size"], wx // 8, wy // 8)
                        tid = cell & 0x3FF
                        raw = bytes(vram[info["char_base"] + tid * 32 : info["char_base"] + tid * 32 + 32])
                        cells.append(cell)
                        palettes.append((cell >> 12) & 15)
                        zero_ratios.append(tile_zero_ratio(raw))
                    if not cells and ty == 0:
                        break
                if len(cells) != 8:
                    continue
                live = stitch_live(vram, info["char_base"], cells, 4)
                flat = flatten(live)
                zero = flat.count(0) / len(flat)
                unique = sorted(set(flat))
                if unique == [0]:
                    kind = "all_transparent"
                elif zero >= 0.45:
                    kind = "mostly_transparent"
                else:
                    kind = "opaque"
                # Skip empty map filler unless it sits in the right-side menu column.
                if kind == "all_transparent" and sx < 184:
                    continue
                hits = match_resource(live, maps, atlas)
                interesting = kind != "opaque" or hits or sx >= 184
                if not interesting:
                    continue
                if kind == "opaque" and sx >= 184 and not hits:
                    # keep right-column 4x2 even without atlas match
                    pass
                elif kind == "opaque" and not hits:
                    continue
                slots.append(
                    {
                        "layer": layer,
                        "x": sx,
                        "y": sy,
                        "priority": info["priority"],
                        "palette": palettes,
                        "tiles": [c & 0x3FF for c in cells],
                        "cells_hex": [f"0x{c:04X}" for c in cells],
                        "zero_ratio": round(zero, 4),
                        "per_tile_zero": [round(v, 3) for v in zero_ratios],
                        "index_hist": dict(Counter(flat)),
                        "kind": kind,
                        "matches": hits,
                    }
                )
    slots.sort(key=lambda r: (r["layer"], r["y"], r["x"]))
    return slots


def overlapping_oam(state: bytes, box: tuple[int, int, int, int]) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM : statefmt.STATE_VRAM]
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    obj = vram[statefmt.OBJ_VRAM :]
    x0, y0, x1, y1 = box
    rows = []
    for i in range(128):
        try:
            e = statefmt.parse_oam_entry(oam, i)
        except SystemExit:
            continue
        a0 = int(e["attr0"], 16)
        if ((a0 >> 8) & 3) == 2:
            continue
        if e["x"] + e["width"] <= x0 or e["x"] >= x1 or e["y"] + e["height"] <= y0 or e["y"] >= y1:
            continue
        tiles = []
        mapping_1d = bool(u16(state[statefmt.STATE_IO : statefmt.STATE_PALETTE], 0) & 0x40)
        ids = bgutil.object_tile_ids(e, mapping_1d)
        for tid in ids:
            raw = bytes(obj[tid * 32 : tid * 32 + 32]) if tid * 32 + 32 <= len(obj) else b""
            tiles.append({"id": tid, "zero": round(tile_zero_ratio(raw), 3) if raw else None, "empty": raw == b"\0" * 32 if raw else True})
        rows.append({**e, "mode": (a0 >> 8) & 3, "affine": bool(a0 & 0x100), "tiles": tiles})
    return rows


def disasm_around(rom: bytes, addr: int, size: int = 0x80) -> list[dict[str, str]]:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = False
    rows = []
    for ins in md.disasm(rom[addr - ROM_BASE : addr - ROM_BASE + size], addr):
        rows.append({"addr": f"0x{ins.address:08X}", "op": f"{ins.mnemonic} {ins.op_str}"})
    return rows


def find_bl_to(rom: bytes, target: int, start: int = 0x08000000, end: int = 0x08100000) -> list[str]:
    hits = []
    off0, off1 = start - ROM_BASE, end - ROM_BASE
    data = rom[off0:off1]
    for i in range(0, len(data) - 3, 2):
        h1, h2 = struct.unpack_from("<HH", data, i)
        if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
            continue
        disp = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
        if disp & (1 << 22):
            disp -= 1 << 23
        dest = (start + i + 4 + disp) & 0xFFFFFFFF
        if dest == target:
            hits.append(f"0x{start + i:08X}")
            if len(hits) >= 24:
                break
    return hits


def render_menu_crop(frame: Image.Image, slots: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame.resize((960, 640), Image.Resampling.NEAREST).save(OUT_DIR / "ss9_full.png")
    crop = frame.crop((184, 0, 240, 160)).resize((224, 640), Image.Resampling.NEAREST)
    crop.save(OUT_DIR / "ss9_menu_column.png")
    marked = frame.copy()
    draw = ImageDraw.Draw(marked)
    for slot in slots:
        if slot["x"] < 184:
            continue
        color = {"all_transparent": (255, 0, 0), "mostly_transparent": (255, 128, 0), "opaque": (0, 255, 0)}[slot["kind"]]
        draw.rectangle((slot["x"], slot["y"], slot["x"] + 31, slot["y"] + 15), outline=color)
    marked.resize((960, 640), Image.Resampling.NEAREST).save(OUT_DIR / "ss9_marked.png")


def compare_move_tiles(rom: bytes, jp: bytes, atlas: bytes, maps: dict[int, dict], vram: bytes, char_bases: list[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for res_idx, name in ((18, "normal_이동"), (30, "focus_이동"), (42, "disabled_이동")):
        if res_idx not in maps:
            continue
        mp = maps[res_idx]
        src_ids = [c & 0x3FF for c in mp["cells"]]
        src_pixels = action.stitch_map(atlas, mp)
        hist = dict(Counter(flatten(src_pixels)))
        live_hits = []
        for char_base in char_bases:
            for sid in src_ids:
                raw = atlas[sid * 32 : sid * 32 + 32]
                for tid in range(0x400):
                    live = bytes(vram[char_base + tid * 32 : char_base + tid * 32 + 32])
                    if live == raw:
                        live_hits.append({"resource_tile": sid, "vram_tile": tid, "char_base": char_base})
                        break
        out[name] = {
            "resource": res_idx,
            "source_tiles": src_ids,
            "index_hist": hist,
            "zero_ratio": round(flatten(src_pixels).count(0) / 512, 4),
            "live_exact_uploads": live_hits,
        }
    return out


def main() -> int:
    if not STATE.exists():
        raise SystemExit(f"missing {STATE}")
    rom = ROM_PATH.read_bytes()
    jp = JP_PATH.read_bytes() if JP_PATH.exists() else b""
    st, _ = statefmt.parse_png_state(STATE)
    table_off, atlas, maps = load_action_table(rom)
    io = st[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    vram = st[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    regs = io_dump(io)
    bgs = [bgutil.bg_info(st, i) for i in range(4)]
    regs["bg"] = bgs
    renderer.OUT = OUT_DIR
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame = renderer.render(st)
    slots = scan_menu_slots(st, atlas, maps)
    right_slots = [s for s in slots if s["x"] >= 184]
    hole_slots = [s for s in right_slots if s["kind"] != "opaque"]
    render_menu_crop(frame, right_slots)
    char_bases = sorted({bg["char_base"] for bg in bgs})
    move_cmp = compare_move_tiles(rom, jp, atlas, maps, vram, char_bases)
    consumers = {}
    for lit in action.TABLE_CONSUMER_LITERALS:
        addr = ROM_BASE + lit
        consumers[f"0x{addr:08X}"] = {
            "literal": f"0x{u32(rom, lit):08X}",
            "disasm": disasm_around(rom, addr - 0x20 if addr >= ROM_BASE + 0x20 else addr, 0xC0),
        }
    # The three literals sit inside draw helpers; also dump likely function entries.
    fn_guesses = [0x08014E88, 0x08014F20, 0x08015500, 0x08015590, 0x08015628]
    functions = {f"0x{a:08X}": disasm_around(rom, a, 0x100) for a in fn_guesses}

    menu_box = (184, 0, 240, 160)
    oam_hits = overlapping_oam(st, menu_box)

    # Palette used by right-column buttons
    pal = st[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    palettes = {}
    for slot in right_slots:
        for bank in slot["palette"]:
            if bank in palettes:
                continue
            palettes[bank] = [f"#{bgutil.rgb555(u16(pal, (bank * 16 + i) * 2))[0]:02X}{bgutil.rgb555(u16(pal, (bank * 16 + i) * 2))[1]:02X}{bgutil.rgb555(u16(pal, (bank * 16 + i) * 2))[2]:02X}" for i in range(16)]

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_ss9_action_menu_flash_20260912",
        "state": {"path": str(STATE.relative_to(ROOT)), "sha256": sha256(STATE.read_bytes())},
        "rom_sha256": sha256(rom),
        "jp_sha256": sha256(jp) if jp else None,
        "action_table": hex(table_off + ROM_BASE),
        "atlas_tiles": len(atlas) // 32,
        "io": regs,
        "right_slots": right_slots,
        "transparent_right_slots": hole_slots,
        "all_interesting_slots": slots,
        "move_resource_compare": move_cmp,
        "oam_over_menu": oam_hits,
        "palettes": palettes,
        "consumers": consumers,
        "function_windows": functions,
        "notes": {
            "screenshot_selected": "포획",
            "expected_top_command": "이동",
            "question": "1-frame transparent cover over 이동-class badges while moving the cursor",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "result": "ANALYZED",
        "report": str(REPORT.relative_to(ROOT)),
        "dispcnt": regs["dispcnt"],
        "windows": {"win0": regs["win0"], "win1": regs["win1"], "win0h": regs["win0h"], "win0v": regs["win0v"], "winin": regs["winin"], "winout": regs["winout"]},
        "blend": {"bldcnt": regs["bldcnt"], "bldalpha": regs["bldalpha"], "bldy": regs["bldy"]},
        "bg_enable": regs["bg_enable"],
        "right_slot_count": len(right_slots),
        "transparent_right": [{"x": s["x"], "y": s["y"], "layer": s["layer"], "kind": s["kind"], "zero": s["zero_ratio"], "tiles": s["tiles"], "matches": s["matches"][:2]} for s in hole_slots],
        "opaque_right_labels": [{"x": s["x"], "y": s["y"], "layer": s["layer"], "zero": s["zero_ratio"], "tiles": s["tiles"], "top_match": (s["matches"][0] if s["matches"] else None)} for s in right_slots if s["kind"] == "opaque"],
        "move_zero": {k: v["zero_ratio"] for k, v in move_cmp.items()},
        "oam_count": len(oam_hits),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
