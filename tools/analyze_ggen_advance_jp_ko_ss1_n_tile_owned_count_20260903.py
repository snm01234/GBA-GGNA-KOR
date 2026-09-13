#!/usr/bin/env python3
"""Fresh JP/KO ss1 contrast for the unit-list N tile and 所有数 plaque.

Previous work treated the unit-list 8x16 badge as 持 and redirected C490/C491
duplicates onto Korean C439 지.  This analyzer does not reuse those ownership
conclusions.  It renders both savestates, compares live BG1 badge tiles against
Japanese C439/C490 and Korean C439, and re-derives the BG2 所有数 plaque from
the current pair of states.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as lz
import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_hold_fixed_graphics_20260830 as holdfmt
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
KO_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903.json"
PREVIEW_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_jp_ko_ss1_n_owned"

ROM_BASE = 0x08000000
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
HOLD_REDIRECTS = {
    "normal_B": {
        "duplicate": 0x08C490B8,
        "c439": 0x08C43954,
        "literals": (0x080752E8, 0x08075450),
        "graphic": 0x00C43968,
    },
    "focus_A": {
        "duplicate": 0x08C4910C,
        "c439": 0x08C439A8,
        "literals": (0x080758EC, 0x08075A54),
        "graphic": 0x00C439BC,
    },
}
SUFFIX = {
    "suffix_B": 0x00C43ACC,
    "suffix_A": 0x00C43B00,
}
FONT12_BASE = 0x0008AC40
FONT12_STRIDE = 18
KANJI_SLOTS = {"所": 0x03C1, "有": 0x0685, "数": 0x0427}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def ascii_glyph(pixels: list[list[int]], nonzero: bool = True) -> list[str]:
    rows = []
    for row in pixels:
        line = []
        for value in row:
            if nonzero and value == 0:
                line.append(".")
            else:
                line.append("." if value == 0 else format(value, "X"))
        rows.append("".join(line))
    return rows


def decode_8x16(raw: bytes) -> list[list[int]]:
    return holdfmt.decode_8x16(raw)


def decode_tile4(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile size drift")
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + (x >> 1)]
            out[y][x] = (packed >> (4 * (x & 1))) & 0xF
    return out


def descriptor_decoded(rom: bytes, off: int) -> dict[str, Any]:
    header = rom[off : off + 0x14]
    flags = header[0]
    width, height = header[2], header[3]
    map_rel = u16(rom, off + 4)
    gfx_rel = u16(rom, off + 8)
    gfx_len = u16(rom, off + 10)
    body = rom[off + gfx_rel : off + gfx_rel + gfx_len]
    decoded = lz.lzss_decompress(body) if flags & 0x10 else bytes(body)
    return {
        "offset": f"0x{off:08X}",
        "flags": flags,
        "width": width,
        "height": height,
        "gfx_len": gfx_len,
        "decoded_len": len(decoded),
        "decoded_sha256": sha256(decoded),
        "decoded": decoded,
        "map_cell": u16(rom, off + map_rel) if map_rel + 2 <= 0x14 + 8 else None,
    }


def bg_tile_bytes(state: bytes, layer: int, tile: int) -> bytes:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    size = 64 if info["color_8bpp"] else 32
    off = info["char_base"] + tile * size
    return bytes(vram[off : off + size])


def map_cell(state: bytes, layer: int, x: int, y: int) -> dict[str, Any]:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    cell = bgutil.map_entry(vram, info["screen_base"], info["size"], x, y)
    return {
        "x": x,
        "y": y,
        "cell": f"0x{cell:04X}",
        "tile": cell & 0x3FF,
        "palette": (cell >> 12) & 0xF,
        "hflip": bool(cell & 0x400),
        "vflip": bool(cell & 0x800),
    }


def render_bg_native(state: bytes, layer: int) -> Image.Image:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    pixels = image.load()
    for sy in range(160):
        wy = sy + info["scroll_y"]
        for sx in range(240):
            wx = sx + info["scroll_x"]
            entry = bgutil.map_entry(vram, info["screen_base"], info["size"], wx // 8, wy // 8)
            tile = entry & 0x3FF
            px, py = wx & 7, wy & 7
            if entry & 0x400:
                px = 7 - px
            if entry & 0x800:
                py = 7 - py
            if info["color_8bpp"]:
                off = info["char_base"] + tile * 64 + py * 8 + px
                colour = vram[off]
                if colour == 0:
                    continue
                value = u16(pal, colour * 2)
            else:
                off = info["char_base"] + tile * 32 + py * 4 + px // 2
                packed = vram[off]
                colour = (packed >> (4 * (px & 1))) & 15
                if colour == 0:
                    continue
                bank = (entry >> 12) & 15
                value = u16(pal, (bank * 16 + colour) * 2)
            pixels[sx, sy] = (*bgutil.rgb555(value), 255)
    return image


def composite_state(state: bytes) -> Image.Image:
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    dispcnt = u16(io, 0)
    layers = []
    for index in range(4):
        if dispcnt & (1 << (8 + index)):
            layers.append((bgutil.bg_info(state, index)["priority"], index, render_bg_native(state, index)))
    layers.sort()
    out = Image.new("RGBA", (240, 160), (0, 0, 32, 255))
    for _prio, _idx, img in reversed(layers):
        out = Image.alpha_composite(out, img)
    return out


def scale(image: Image.Image, factor: int = 4) -> Image.Image:
    return image.resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST)


def save_pixels(pixels: list[list[int]], path: Path, palette: list[tuple[int, int, int]] | None = None) -> None:
    h = len(pixels)
    w = len(pixels[0]) if h else 0
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    default = [
        (0, 0, 0),
        (32, 32, 32),
        (64, 64, 64),
        (96, 96, 96),
        (160, 160, 160),
        (192, 120, 64),
        (80, 160, 80),
        (80, 80, 192),
        (220, 220, 80),
        (220, 80, 80),
        (240, 240, 240),
        (40, 120, 160),
        (180, 80, 180),
        (80, 200, 200),
        (200, 160, 80),
        (255, 255, 255),
    ]
    pal = palette or default
    for y, row in enumerate(pixels):
        for x, value in enumerate(row):
            if value == 0:
                continue
            colour = pal[value % len(pal)]
            px[x, y] = (*colour, 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    scale(img, 8).save(path)


def stitch_2x2(tiles: list[list[list[int]]]) -> list[list[int]]:
    # tiles order: TL, TR, BL, BR
    out = [[0] * 16 for _ in range(16)]
    for index, tile in enumerate(tiles):
        ox = (index % 2) * 8
        oy = (index // 2) * 8
        for y in range(8):
            for x in range(8):
                out[oy + y][ox + x] = tile[y][x]
    return out


def find_all(data: bytes, pattern: bytes) -> list[int]:
    hits = []
    start = 0
    if not pattern:
        return hits
    while True:
        pos = data.find(pattern, start)
        if pos < 0:
            return hits
        hits.append(pos)
        start = pos + 1


def glyph12_mask(rom: bytes, slot: int) -> set[tuple[int, int]]:
    raw = rom[FONT12_BASE + slot * FONT12_STRIDE : FONT12_BASE + (slot + 1) * FONT12_STRIDE]
    pts = set()
    for y in range(12):
        for x in range(12):
            bit = y * 12 + x
            if raw[bit // 8] & (1 << (bit & 7)):
                pts.add((x, y))
    return pts


def dice(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return (2 * len(a & b)) / (len(a) + len(b))


def plaque_scan(state: bytes) -> dict[str, Any]:
    """Locate the orange 所有数 plaque by BG2 chrome, not by stale tile IDs."""
    info = bgutil.bg_info(state, 2)
    rows = []
    for y in range(20):
        line = [map_cell(state, 2, x, y) for x in range(30)]
        rows.append(line)
    # The plaque is a short orange framed run on the right half, typically y=8..11.
    candidates = []
    for y in range(1, 18):
        for x in range(16, 28):
            cell = rows[y][x]
            if cell["palette"] != 0xB:
                continue
            run = 1
            while x + run < 30 and rows[y][x + run]["palette"] == 0xB:
                run += 1
            if run >= 6:
                candidates.append((y, x, run))
    # Prefer the unique longest framed block near the right pane.
    if not candidates:
        return {"found": False, "bg2": info}
    y0, x0, run = max(candidates, key=lambda item: (item[2], -item[0]))
    # Expand vertically while palette B remains dense.
    y1 = y0
    while y1 + 1 < 20:
        dens = sum(1 for x in range(x0, x0 + run) if rows[y1 + 1][x]["palette"] == 0xB)
        if dens < run - 1:
            break
        y1 += 1
    y_start = y0
    while y_start > 0:
        dens = sum(1 for x in range(x0, x0 + run) if rows[y_start - 1][x]["palette"] == 0xB)
        if dens < run - 1:
            break
        y_start -= 1
    block = []
    tiles = []
    for y in range(y_start, y1 + 1):
        line = []
        for x in range(x0, x0 + run):
            cell = rows[y][x]
            payload = bg_tile_bytes(state, 2, cell["tile"])
            line.append({**cell, "sha256": sha256(payload)})
            tiles.append(cell["tile"])
        block.append(line)
    return {
        "found": True,
        "bg2cnt": f"0x{info['cnt']:04X}",
        "char_base": f"0x{info['char_base']:04X}",
        "screen_base": f"0x{info['screen_base']:04X}",
        "screen_vram": f"0x{0x06000000 + info['screen_base']:08X}",
        "charblock": info["char_base"] // 0x4000,
        "screenblock": info["screen_base"] // 0x800,
        "x0": x0,
        "y0": y_start,
        "width": run,
        "height": y1 - y_start + 1,
        "unique_tiles": sorted(set(tiles)),
        "map": [[{k: v for k, v in cell.items() if k != "hflip"} for cell in line] for line in block],
    }


def live_8x16(state: bytes, layer: int, x: int, y: int) -> tuple[bytes, list[dict[str, Any]]]:
    cells = [map_cell(state, layer, x, y), map_cell(state, layer, x, y + 1)]
    payload = bg_tile_bytes(state, layer, cells[0]["tile"]) + bg_tile_bytes(state, layer, cells[1]["tile"])
    return payload, cells


def badge_column(state: bytes) -> list[dict[str, Any]]:
    """Collect 16x16 badge windows at x=14 for each unit-list row pair."""
    rows = []
    for y in range(1, 16, 2):
        cells = [
            map_cell(state, 1, 14, y),
            map_cell(state, 1, 15, y),
            map_cell(state, 1, 14, y + 1),
            map_cell(state, 1, 15, y + 1),
        ]
        tiles = [decode_tile4(bg_tile_bytes(state, 1, cell["tile"])) for cell in cells]
        left = bg_tile_bytes(state, 1, cells[0]["tile"]) + bg_tile_bytes(state, 1, cells[2]["tile"])
        right = bg_tile_bytes(state, 1, cells[1]["tile"]) + bg_tile_bytes(state, 1, cells[3]["tile"])
        rows.append({
            "y": y,
            "cells": cells,
            "left_sha256": sha256(left),
            "right_sha256": sha256(right),
            "left_ascii": ascii_glyph(decode_8x16(left)),
            "right_ascii": ascii_glyph(decode_8x16(right)),
            "left_payload": left,
            "right_payload": right,
            "window_pixels": stitch_2x2(tiles),
        })
    return rows


def pointer_report(rom: bytes) -> dict[str, Any]:
    rows = {}
    for name, spec in HOLD_REDIRECTS.items():
        values = {hex(addr): f"0x{u32(rom, addr - ROM_BASE):08X}" for addr in spec["literals"]}
        rows[name] = {
            "duplicate": f"0x{spec['duplicate']:08X}",
            "c439": f"0x{spec['c439']:08X}",
            "literals": values,
            "points_to_c439": all(u32(rom, addr - ROM_BASE) == spec["c439"] for addr in spec["literals"]),
            "points_to_duplicate": all(u32(rom, addr - ROM_BASE) == spec["duplicate"] for addr in spec["literals"]),
        }
    return rows


def mask_from_indices(pixels: list[list[int]], keep: set[int] | None = None) -> set[tuple[int, int]]:
    pts = set()
    for y, row in enumerate(pixels):
        for x, value in enumerate(row):
            if value == 0:
                continue
            if keep is None or value in keep:
                pts.add((x, y))
    return pts


def classify_badge(payload: bytes, catalog: dict[str, bytes]) -> list[str]:
    hits = [name for name, raw in catalog.items() if raw == payload]
    return hits or ["unmatched"]


def main() -> int:
    jp_rom = ORIGINAL_ROM.read_bytes()
    ko_rom = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(jp_rom) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(sha256(ko_rom) == manifest["sha256"], "Korean main TIP hash/manifest drift")
    gate(JP_STATE.exists() and KO_STATE.exists(), "JP/KO ss1 missing")

    jp_state, _ = statefmt.parse_png_state(JP_STATE)
    ko_state, _ = statefmt.parse_png_state(KO_STATE)
    jp_crc = u32(jp_state, 8)
    ko_crc = u32(ko_state, 8)
    jp_rom_crc = binascii.crc32(jp_rom) & 0xFFFFFFFF
    ko_rom_crc = binascii.crc32(ko_rom) & 0xFFFFFFFF

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    jp_full = composite_state(jp_state)
    ko_full = composite_state(ko_state)
    scale(jp_full).save(PREVIEW_DIR / "jp_composite.png")
    scale(ko_full).save(PREVIEW_DIR / "ko_composite.png")
    for layer in range(4):
        scale(render_bg_native(jp_state, layer)).save(PREVIEW_DIR / f"jp_bg{layer}.png")
        scale(render_bg_native(ko_state, layer)).save(PREVIEW_DIR / f"ko_bg{layer}.png")

    jp_badges = badge_column(jp_state)
    ko_badges = badge_column(ko_state)

    catalog: dict[str, bytes] = {}
    rom_ascii = {}
    for rom_name, rom in (("jp", jp_rom), ("ko", ko_rom)):
        for variant, spec in HOLD_REDIRECTS.items():
            raw = rom[spec["graphic"] : spec["graphic"] + 0x40]
            key = f"{rom_name}_c439_{variant}"
            catalog[key] = raw
            rom_ascii[key] = ascii_glyph(decode_8x16(raw))
            save_pixels(decode_8x16(raw), PREVIEW_DIR / f"{key}.png")
            dup = descriptor_decoded(rom, spec["duplicate"] - ROM_BASE)
            dkey = f"{rom_name}_c490_{variant}"
            catalog[dkey] = dup["decoded"]
            rom_ascii[dkey] = ascii_glyph(decode_8x16(dup["decoded"]))
            save_pixels(decode_8x16(dup["decoded"]), PREVIEW_DIR / f"{dkey}.png")
        for sname, soff in SUFFIX.items():
            desc = descriptor_decoded(rom, soff)
            skey = f"{rom_name}_{sname}"
            catalog[skey] = desc["decoded"]
            raw = desc["decoded"]
            if len(raw) == 64:
                pix = decode_8x16(raw)
            elif len(raw) == 32:
                pix = decode_tile4(raw)
            else:
                pix = [[int(b)] for b in raw[:16]]
            rom_ascii[skey] = ascii_glyph(pix)
            save_pixels(pix, PREVIEW_DIR / f"{skey}.png")

    badge_report = []
    for jp_row, ko_row in zip(jp_badges, ko_badges):
        jp_left_hit = classify_badge(jp_row["left_payload"], catalog)
        ko_left_hit = classify_badge(ko_row["left_payload"], catalog)
        jp_right_hit = classify_badge(jp_row["right_payload"], catalog)
        ko_right_hit = classify_badge(ko_row["right_payload"], catalog)
        save_pixels(jp_row["window_pixels"], PREVIEW_DIR / f"jp_badge_y{jp_row['y']:02d}.png")
        save_pixels(ko_row["window_pixels"], PREVIEW_DIR / f"ko_badge_y{ko_row['y']:02d}.png")
        badge_report.append({
            "y": jp_row["y"],
            "jp": {
                "cells": jp_row["cells"],
                "left_sha256": jp_row["left_sha256"],
                "right_sha256": jp_row["right_sha256"],
                "left_match": jp_left_hit,
                "right_match": jp_right_hit,
                "left_ascii": jp_row["left_ascii"],
                "right_ascii": jp_row["right_ascii"],
            },
            "ko": {
                "cells": ko_row["cells"],
                "left_sha256": ko_row["left_sha256"],
                "right_sha256": ko_row["right_sha256"],
                "left_match": ko_left_hit,
                "right_match": ko_right_hit,
                "left_ascii": ko_row["left_ascii"],
                "right_ascii": ko_row["right_ascii"],
            },
            "left_jp_equals_ko": jp_row["left_payload"] == ko_row["left_payload"],
            "right_jp_equals_ko": jp_row["right_payload"] == ko_row["right_payload"],
        })

    jp_plaque = plaque_scan(jp_state)
    ko_plaque = plaque_scan(ko_state)
    jp_owned_tiles = {}
    ko_owned_tiles = {}
    if jp_plaque["found"]:
        crop = jp_full.crop((jp_plaque["x0"] * 8, jp_plaque["y0"] * 8,
                             (jp_plaque["x0"] + jp_plaque["width"]) * 8,
                             (jp_plaque["y0"] + jp_plaque["height"]) * 8))
        scale(crop, 6).save(PREVIEW_DIR / "jp_owned_plaque.png")
        for tile in jp_plaque["unique_tiles"]:
            jp_owned_tiles[f"0x{tile:03X}"] = sha256(bg_tile_bytes(jp_state, 2, tile))
    if ko_plaque["found"]:
        crop = ko_full.crop((ko_plaque["x0"] * 8, ko_plaque["y0"] * 8,
                             (ko_plaque["x0"] + ko_plaque["width"]) * 8,
                             (ko_plaque["y0"] + ko_plaque["height"]) * 8))
        scale(crop, 6).save(PREVIEW_DIR / "ko_owned_plaque.png")
        for tile in ko_plaque["unique_tiles"]:
            ko_owned_tiles[f"0x{tile:03X}"] = sha256(bg_tile_bytes(ko_state, 2, tile))

    # Compare interior letter tiles between states by relative plaque cell.
    plaque_compare = []
    if jp_plaque["found"] and ko_plaque["found"]:
        h = min(jp_plaque["height"], ko_plaque["height"])
        w = min(jp_plaque["width"], ko_plaque["width"])
        for y in range(h):
            for x in range(w):
                jp_cell = jp_plaque["map"][y][x]
                ko_cell = ko_plaque["map"][y][x]
                jp_raw = bg_tile_bytes(jp_state, 2, jp_cell["tile"])
                ko_raw = bg_tile_bytes(ko_state, 2, ko_cell["tile"])
                jp_hits = find_all(jp_rom, jp_raw)[:8]
                ko_hits_jp = find_all(jp_rom, ko_raw)[:8]
                ko_hits_main = find_all(ko_rom, ko_raw)[:8]
                plaque_compare.append({
                    "rel": [x, y],
                    "jp_tile": f"0x{jp_cell['tile']:03X}",
                    "ko_tile": f"0x{ko_cell['tile']:03X}",
                    "same_payload": jp_raw == ko_raw,
                    "jp_raw_in_jp_rom": [f"0x{h:08X}" for h in jp_hits],
                    "ko_raw_in_jp_rom": [f"0x{h:08X}" for h in ko_hits_jp],
                    "ko_raw_in_main": [f"0x{h:08X}" for h in ko_hits_main],
                })

    # Dice the plaque interior against native 所/有/数, using KO/JP live tiles
    # that are not generic frame edges. Interior is typically rows 1-2, cols 1-4.
    font_compare = {}
    if jp_plaque["found"]:
        interior = []
        for y in range(1, min(3, jp_plaque["height"])):
            for x in range(1, min(5, jp_plaque["width"])):
                cell = jp_plaque["map"][y][x]
                pix = decode_tile4(bg_tile_bytes(jp_state, 2, cell["tile"]))
                interior.extend(pix)
        # Too crude as concatenated 8x8; instead score each 12x12 window later.
        font_compare["note"] = "see glyph_windows"
    glyph_windows = []
    if jp_plaque["found"]:
        plaque_img = jp_full.crop((
            jp_plaque["x0"] * 8 + 8,
            jp_plaque["y0"] * 8 + 8,
            jp_plaque["x0"] * 8 + 8 + 36,
            jp_plaque["y0"] * 8 + 8 + 12,
        )).convert("L")
        px = plaque_img.load()
        # Split roughly into three 12px glyphs.
        for index, name in enumerate(("所", "有", "数")):
            mask = set()
            for y in range(12):
                for x in range(12):
                    sx = index * 12 + x
                    if sx < plaque_img.width and plaque_img.getpixel((sx, y)) > 80:
                        mask.add((x, y))
            native = glyph12_mask(jp_rom, KANJI_SLOTS[name])
            glyph_windows.append({
                "glyph": name,
                "dice_native12": round(dice(mask, native), 6),
                "live_points": len(mask),
                "native_points": len(native),
            })

    result = {
        "schema_version": 1,
        "kind": "ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903",
        "result": "PASS",
        "source": {
            "jp_state": advance_relative(JP_STATE),
            "jp_state_sha256": sha256(JP_STATE.read_bytes()),
            "jp_state_crc32": f"0x{jp_crc:08X}",
            "jp_rom_crc32": f"0x{jp_rom_crc:08X}",
            "jp_state_matches_jp_rom": jp_crc == jp_rom_crc,
            "ko_state": advance_relative(KO_STATE),
            "ko_state_sha256": sha256(KO_STATE.read_bytes()),
            "ko_state_crc32": f"0x{ko_crc:08X}",
            "ko_rom_crc32": f"0x{ko_rom_crc:08X}",
            "ko_state_matches_current_main": ko_crc == ko_rom_crc,
            "main_sha256": sha256(ko_rom),
        },
        "bg_info": {
            "jp": [bgutil.bg_info(jp_state, i) for i in range(4)],
            "ko": [bgutil.bg_info(ko_state, i) for i in range(4)],
        },
        "hold_pointers_current_main": pointer_report(ko_rom),
        "hold_pointers_jp": pointer_report(jp_rom),
        "rom_glyph_ascii": rom_ascii,
        "badge_rows": [
            {k: v for k, v in row.items() if k in ("y", "jp", "ko", "left_jp_equals_ko", "right_jp_equals_ko")}
            for row in badge_report
        ],
        "owned_plaque": {
            "jp": {k: v for k, v in jp_plaque.items() if k != "map"} | {
                "map_cells": [[cell["cell"] for cell in line] for line in jp_plaque.get("map", [])]
            },
            "ko": {k: v for k, v in ko_plaque.items() if k != "map"} | {
                "map_cells": [[cell["cell"] for cell in line] for line in ko_plaque.get("map", [])]
            },
            "same_unique_tile_ids": jp_plaque.get("unique_tiles") == ko_plaque.get("unique_tiles"),
            "cell_compare": plaque_compare,
            "glyph_windows_jp_composite": glyph_windows,
        },
        "previews": advance_relative(PREVIEW_DIR),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "result": "PASS",
        "report": advance_relative(OUT),
        "jp_crc_match": jp_crc == jp_rom_crc,
        "ko_crc_match": ko_crc == ko_rom_crc,
        "main_points_to_c439": {
            name: row["points_to_c439"] for name, row in pointer_report(ko_rom).items()
        },
        "badge_left_changed_rows": [row["y"] for row in badge_report if not row["left_jp_equals_ko"]],
        "owned_found": {"jp": jp_plaque["found"], "ko": ko_plaque["found"]},
        "owned_same_tile_ids": jp_plaque.get("unique_tiles") == ko_plaque.get("unique_tiles"),
        "glyph_dice": glyph_windows,
        "previews": advance_relative(PREVIEW_DIR),
    }
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
