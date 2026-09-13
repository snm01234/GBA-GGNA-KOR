#!/usr/bin/env python3
"""Bind Korean.ss2 LANDFORM window 海 text and 回避 badge to ROM owners."""
from __future__ import annotations

import json
import struct
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_ko_poc as fontops
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_painted_glyph_identity import FONT8_RELOCATED, FONT12_RELOCATED, slot_raw

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_landform"
JSON_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_20260905.json"
ROM_BASE = 0x08000000
CHARMAP8 = ADVANCE_ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
WINDOW = (32, 32, 208, 128)


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def rgb555(value: int) -> tuple[int, int, int]:
    return tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))


def decode_tile4(raw: bytes) -> list[list[int]]:
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + x // 2]
            out[y][x] = (packed >> (4 * (x & 1))) & 15
    return out


def obj_tile(vram: bytes, tid: int) -> bytes:
    off = 0x10000 + tid * 32
    return bytes(vram[off : off + 32])


def bg_tile(vram: bytes, char_base: int, tile_id: int, eight: bool) -> bytes:
    stride = 64 if eight else 32
    off = char_base + tile_id * stride
    return bytes(vram[off : off + stride])


def save_rgb(pixels: list[list[tuple[int, int, int]]], path: Path, scale: int = 4) -> None:
    height, width = len(pixels), len(pixels[0])
    image = Image.new("RGB", (width, height))
    px = image.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = pixels[y][x]
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((width * scale, height * scale), Image.NEAREST).save(path)


def render_bg_rgb(state: bytes, layer: int) -> list[list[tuple[int, int, int]]]:
    info = bg.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    pixels = [[(0, 0, 0) for _ in range(240)] for _ in range(160)]
    for y in range(160):
        for x in range(240):
            mx = (info["scroll_x"] + x) & 0x1FF
            my = (info["scroll_y"] + y) & 0x1FF
            cell = bg.map_entry(vram, info["screen_base"], info["size"], mx // 8, my // 8)
            tile_id = cell & 0x3FF
            hflip = bool(cell & 0x400)
            vflip = bool(cell & 0x800)
            bank = (cell >> 12) & 0xF
            stride = 64 if info["color_8bpp"] else 32
            raw = vram[info["char_base"] + tile_id * stride : info["char_base"] + tile_id * stride + stride]
            if len(raw) < stride:
                continue
            lx, ly = mx & 7, my & 7
            if hflip:
                lx = 7 - lx
            if vflip:
                ly = 7 - ly
            if info["color_8bpp"]:
                index = raw[ly * 8 + lx]
                color = u16(pal, index * 2)
            else:
                packed = raw[ly * 4 + lx // 2]
                index = (packed >> (4 * (lx & 1))) & 15
                if index == 0:
                    continue
                color = u16(pal, (bank * 16 + index) * 2)
            pixels[y][x] = rgb555(color)
    return pixels


def visible_oam(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM : statefmt.STATE_VRAM]
    rows = []
    for index in range(128):
        attr0 = u16(oam, index * 8)
        if ((attr0 >> 8) & 3) == 2:
            continue
        row = statefmt.parse_oam_entry(oam, index)
        if row["x"] >= 240 or row["y"] >= 160 or row["x"] + row["width"] <= 0 or row["y"] + row["height"] <= 0:
            continue
        rows.append(row)
    return rows


def oam_in_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    x0, y0, x1, y1 = WINDOW
    hits = []
    for row in rows:
        if row["x"] >= x1 or row["y"] >= y1 or row["x"] + row["width"] <= x0 or row["y"] + row["height"] <= y0:
            continue
        hits.append(row)
    return hits


def render_obj_rgb(state: bytes, rows: list[dict[str, Any]]) -> list[list[tuple[int, int, int]]]:
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    pixels = [[(0, 0, 0) for _ in range(240)] for _ in range(160)]
    for row in reversed(rows):
        tw, th = row["width"] // 8, row["height"] // 8
        bank = row["palette_bank"]
        for ty in range(th):
            for tx in range(tw):
                tid = row["tile"] + ty * tw + tx
                tile = decode_tile4(obj_tile(vram, tid))
                for y in range(8):
                    for x in range(8):
                        index = tile[y][x]
                        if not index:
                            continue
                        sx, sy = row["x"] + tx * 8 + x, row["y"] + ty * 8 + y
                        if 0 <= sx < 240 and 0 <= sy < 160:
                            color = u16(pal, (16 * 16 + bank * 16 + index) * 2)
                            pixels[sy][sx] = rgb555(color)
    return pixels


def find_all(haystack: bytes, needle: bytes, limit: int = 32) -> list[int]:
    hits: list[int] = []
    start = 0
    while len(hits) < limit:
        pos = haystack.find(needle, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
    return hits


def slot_for_char(charmap: dict[str, str], char: str) -> int | None:
    hits = [int(slot, 16) for slot, value in charmap.items() if value == char]
    return min(hits) if hits else None


def glyph_mask12(rom: bytes, slot: int) -> set[tuple[int, int]]:
    raw = slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
    image = fontops.unpack_12x12(raw)
    return {(x, y) for y in range(12) for x in range(12) if image.getpixel((x, y))}


def glyph_mask8(rom: bytes, slot: int) -> set[tuple[int, int]]:
    raw = slot_raw(rom, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
    image = fontops.unpack_8x16(raw)
    return {(x, y) for y in range(16) for x in range(8) if image.getpixel((x, y))}


def dice(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def locate_mask(screen: list[list[int]], mask: set[tuple[int, int]], width: int, height: int) -> list[dict[str, Any]]:
    x0, y0, x1, y1 = WINDOW
    best: list[tuple[float, int, int, int]] = []
    for y in range(max(0, y0), min(160 - height, y1) + 1):
        for x in range(max(0, x0), min(240 - width, x1) + 1):
            counts = [0] * 16
            for yy in range(height):
                row = screen[y + yy]
                for xx in range(width):
                    counts[row[x + xx]] += 1
            for value in range(1, 16):
                if counts[value] < 4:
                    continue
                observed = {
                    (xx, yy)
                    for yy in range(height)
                    for xx in range(width)
                    if screen[y + yy][x + xx] == value
                }
                score = dice(observed, mask)
                if score >= 0.55:
                    best.append((score, x, y, value))
    best.sort(reverse=True)
    out = []
    seen: set[tuple[int, int]] = set()
    for score, x, y, value in best[:12]:
        if (x, y) in seen:
            continue
        seen.add((x, y))
        out.append({"score": round(score, 4), "x": x, "y": y, "palette_index": value})
    return out


def bg_cells_in_window(state: bytes, layer: int) -> list[dict[str, Any]]:
    info = bg.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    x0, y0, x1, y1 = WINDOW
    rows = []
    seen: dict[int, int] = {}
    for py in range(y0, y1, 8):
        for px in range(x0, x1, 8):
            mx = (info["scroll_x"] + px) // 8
            my = (info["scroll_y"] + py) // 8
            cell = bg.map_entry(vram, info["screen_base"], info["size"], mx, my)
            tile_id = cell & 0x3FF
            raw = bg_tile(vram, info["char_base"], tile_id, info["color_8bpp"])
            key = tile_id
            if key not in seen:
                seen[key] = len(rows)
                rows.append(
                    {
                        "tile_id": tile_id,
                        "cell": f"0x{cell:04X}",
                        "bank": (cell >> 12) & 0xF,
                        "raw": raw.hex(),
                        "screens": [],
                    }
                )
            rows[seen[key]]["screens"].append({"x": px, "y": py})
    return rows


def match_tiles_to_rom(rom: bytes, tiles: list[bytes], limit: int = 8) -> list[dict[str, Any]]:
    hits = []
    for index, raw in enumerate(tiles):
        if raw.count(0) == len(raw):
            continue
        found = find_all(rom, raw, limit)
        hits.append({"index": index, "rom_hits": [f"0x{off:08X}" for off in found], "hit_count": len(found)})
    return hits


def terrain_like_records(merged: dict[str, Any]) -> list[dict[str, Any]]:
    names = (
        "海", "空", "宇宙", "地上", "砂漠", "砂地", "森林", "密林", "市街", "都市",
        "基地", "山岳", "山地", "荒地", "月面", "水面", "浅瀬", "深海", "草原", "湿地",
        "宇宙空間", "コロニー", "廃墟", "工場", "基地内", "艦橋", "艦内", "海底",
        "氷原", "雪原", "火山", "溶岩", "道路", "橋梁", "島", "湖", "川", "池",
        "宇宙空間", "地上", "空中", "海上", "水中", "宇宙",
    )
    out = []
    for row in merged["records"]:
        source = str(row.get("source_text") or "")
        ko = str(row.get("translation_ko") or "")
        if source not in names and not (len(source) <= 4 and any(ch in source for ch in "海空宇宙砂漠林市街山月")):
            continue
        out.append(
            {
                "record_id": row.get("record_id"),
                "kind": row.get("kind") or row.get("record_kind") or row.get("semantic_kind"),
                "source_text": source,
                "translation_ko": ko,
                "translation_status": row.get("translation_status"),
                "uses_12x12": bool(row.get("uses_12x12")),
                "owner_ids": (row.get("owner_ids") or [])[:8],
                "owner_count": row.get("owner_count"),
                "raw_hex": row.get("raw_hex"),
            }
        )
    return out


def search_iwram_tokens(state: bytes, token: int) -> list[str]:
    iwram = state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    needle = bytes((token >> 8, token & 0xFF)) if token > 0xDF else bytes((token,))
    return [f"0x{off:08X}" for off in find_all(iwram, needle, 24)]


def main() -> int:
    state, _ = statefmt.parse_png_state(STATE)
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    charmap8 = json.loads(CHARMAP8.read_text(encoding="utf-8")).get("verified_charmap") or {}
    charmap12 = json.loads(CHARMAP12.read_text(encoding="utf-8")).get("verified_charmap") or {}
    slot8 = slot_for_char(charmap8, "海")
    slot12 = slot_for_char(charmap12, "海")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = {}
    for layer in range(4):
        info = bg.bg_info(state, layer)
        rgb = render_bg_rgb(state, layer)
        save_rgb(rgb, OUT_DIR / f"ss2_bg{layer}.png")
        crop = [row[WINDOW[0] : WINDOW[2]] for row in rgb[WINDOW[1] : WINDOW[3]]]
        save_rgb(crop, OUT_DIR / f"ss2_bg{layer}_window.png")
        cells = bg_cells_in_window(state, layer)
        layers[str(layer)] = {"info": {k: (hex(v) if isinstance(v, int) else v) for k, v in info.items()}, "unique_tiles": len(cells)}

    oam_rows = visible_oam(state)
    window_oam = oam_in_window(oam_rows)
    obj_rgb = render_obj_rgb(state, oam_rows)
    save_rgb(obj_rgb, OUT_DIR / "ss2_obj.png")
    save_rgb([row[WINDOW[0] : WINDOW[2]] for row in obj_rgb[WINDOW[1] : WINDOW[3]]], OUT_DIR / "ss2_obj_window.png")

    glyph_hits: dict[str, Any] = {}
    if slot12 is not None:
        mask12 = glyph_mask12(rom, slot12)
        for layer in range(4):
            pixels, _ = draw.layer_pixels(state, layer)
            glyph_hits[f"bg{layer}_12x12"] = locate_mask(pixels, mask12, 12, 12)
    if slot8 is not None:
        mask8 = glyph_mask8(rom, slot8)
        for layer in range(4):
            pixels, _ = draw.layer_pixels(state, layer)
            glyph_hits[f"bg{layer}_8x16"] = locate_mask(pixels, mask8, 8, 16)

    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    obj_tiles = []
    for row in window_oam:
        tw, th = row["width"] // 8, row["height"] // 8
        tiles = []
        for ty in range(th):
            for tx in range(tw):
                tid = row["tile"] + ty * tw + tx
                raw = obj_tile(vram, tid)
                tiles.append(raw)
        obj_tiles.append(
            {
                "oam": {k: row[k] for k in ("index", "x", "y", "width", "height", "tile", "palette_bank")},
                "rom_match_main": match_tiles_to_rom(rom, tiles),
                "rom_match_jp": match_tiles_to_rom(japan, tiles),
            }
        )

    token8 = None if slot8 is None else (slot8 if slot8 <= 0xDF else 0xDF20 + slot8)
    token12 = None if slot12 is None else (slot12 if slot12 <= 0xDF else 0xDF20 + slot12)
    report = {
        "state": advance_relative(STATE),
        "window": WINDOW,
        "bg": layers,
        "visible_oam_count": len(oam_rows),
        "window_oam": [
            {k: row[k] for k in ("index", "x", "y", "width", "height", "tile", "palette_bank", "priority")}
            for row in window_oam
        ],
        "sea_slots": {"8x16": None if slot8 is None else f"0x{slot8:04X}", "12x12": None if slot12 is None else f"0x{slot12:04X}"},
        "sea_tokens": {"8x16": None if token8 is None else f"0x{token8:04X}", "12x12": None if token12 is None else f"0x{token12:04X}"},
        "glyph_hits": glyph_hits,
        "iwram_token8": search_iwram_tokens(state, token8) if token8 else [],
        "iwram_token12": search_iwram_tokens(state, token12) if token12 else [],
        "window_obj_rom": obj_tiles,
        "terrain_like_records": terrain_like_records(merged)[:80],
        "terrain_like_count": len(terrain_like_records(merged)),
    }
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "window_oam": report["window_oam"],
        "sea_slots": report["sea_slots"],
        "glyph_hits": {k: v[:3] for k, v in glyph_hits.items() if v},
        "terrain_like_count": report["terrain_like_count"],
        "out": advance_relative(JSON_OUT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
