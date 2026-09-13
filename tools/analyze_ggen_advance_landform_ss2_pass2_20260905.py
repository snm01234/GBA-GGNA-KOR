#!/usr/bin/env python3
"""Second-pass LANDFORM ss2: BG0 map, 回避 tiles, and 海 translation records."""
from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path

from PIL import Image

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_ko_poc as fontops
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, slot_raw
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_landform"
JSON_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass2_20260905.json"
ROM_BASE = 0x08000000


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def rgb555(value):
    return tuple(((value >> s) & 31) * 255 // 31 for s in (0, 5, 10))


def find_all(hay, needle, limit=48):
    hits = []
    start = 0
    while len(hits) < limit:
        pos = hay.find(needle, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
    return hits


def decode_tile(raw):
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + x // 2]
            out[y][x] = (packed >> (4 * (x & 1))) & 15
    return out


def main():
    state, _ = statefmt.parse_png_state(STATE)
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    info = bg.bg_info(state, 0)
    # BG0 LANDFORM overlay: dump tile grid covering the window.
    grid = []
    for ty in range(4, 16):
        row = []
        for tx in range(4, 26):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tile_id = cell & 0x3FF
            raw = bytes(vram[info["char_base"] + tile_id * 32 : info["char_base"] + tile_id * 32 + 32])
            row.append({"tx": tx, "ty": ty, "cell": f"0x{cell:04X}", "tile": tile_id, "bank": (cell >> 12) & 0xF, "raw": raw.hex()})
        grid.append(row)

    # Crop 回避 region from the window PNG coordinates.
    # Window starts at (32,32). 回避 is below 海 (~x=96-136, y=88-104 native).
    evade_tx0, evade_ty0, evade_tx1, evade_ty1 = 12, 11, 17, 13
    evade_tiles = []
    canvas = [[0] * ((evade_tx1 - evade_tx0) * 8) for _ in range((evade_ty1 - evade_ty0) * 8)]
    colors = [rgb555(u16(pal, i * 2)) for i in range(256)]
    for ty in range(evade_ty0, evade_ty1):
        for tx in range(evade_tx0, evade_tx1):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tile_id = cell & 0x3FF
            bank = (cell >> 12) & 0xF
            raw = bytes(vram[info["char_base"] + tile_id * 32 : info["char_base"] + tile_id * 32 + 32])
            pix = decode_tile(raw)
            for y in range(8):
                for x in range(8):
                    canvas[(ty - evade_ty0) * 8 + y][(tx - evade_tx0) * 8 + x] = bank * 16 + pix[y][x]
            jp_hits = find_all(japan, raw, 12)
            main_hits = find_all(rom, raw, 12)
            evade_tiles.append(
                {
                    "tx": tx,
                    "ty": ty,
                    "tile": tile_id,
                    "cell": f"0x{cell:04X}",
                    "bank": bank,
                    "jp_hits": [f"0x{h:08X}" for h in jp_hits],
                    "main_hits": [f"0x{h:08X}" for h in main_hits],
                }
            )
    img = Image.new("RGB", (len(canvas[0]), len(canvas)))
    px = img.load()
    for y, row in enumerate(canvas):
        for x, idx in enumerate(row):
            px[x, y] = colors[idx]
    img.resize((img.width * 8, img.height * 8), Image.NEAREST).save(OUT / "ss2_bg0_evade_crop.png")

    # Sea glyph neighbourhood crop.
    sea_tx0, sea_ty0, sea_tx1, sea_ty1 = 12, 8, 16, 11
    sea_canvas = [[(0, 0, 0) for _ in range((sea_tx1 - sea_tx0) * 8)] for _ in range((sea_ty1 - sea_ty0) * 8)]
    sea_tiles = []
    for ty in range(sea_ty0, sea_ty1):
        for tx in range(sea_tx0, sea_tx1):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tile_id = cell & 0x3FF
            bank = (cell >> 12) & 0xF
            raw = bytes(vram[info["char_base"] + tile_id * 32 : info["char_base"] + tile_id * 32 + 32])
            pix = decode_tile(raw)
            for y in range(8):
                for x in range(8):
                    idx = pix[y][x]
                    if idx:
                        sea_canvas[(ty - sea_ty0) * 8 + y][(tx - sea_tx0) * 8 + x] = colors[bank * 16 + idx]
            sea_tiles.append({"tx": tx, "ty": ty, "tile": tile_id, "cell": f"0x{cell:04X}", "bank": bank})
    img = Image.new("RGB", (len(sea_canvas[0]), len(sea_canvas)))
    px = img.load()
    for y, row in enumerate(sea_canvas):
        for x, color in enumerate(row):
            px[x, y] = color
    img.resize((img.width * 8, img.height * 8), Image.NEAREST).save(OUT / "ss2_bg0_sea_crop.png")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    sea_rows = []
    pending_short = []
    kinds = Counter()
    for row in merged["records"]:
        source = str(row.get("source_text") or "")
        ko = str(row.get("translation_ko") or "")
        kinds[str(row.get("semantic_kind") or row.get("kind") or "")] += 1
        if "海" in source or ko in {"바다", "해"} or source in {"海", "海上", "水中", "宇宙", "地上", "空中", "砂漠", "森林", "市街", "山岳"}:
            sea_rows.append(
                {
                    "record_id": row.get("record_id"),
                    "semantic_kind": row.get("semantic_kind"),
                    "kind": row.get("kind"),
                    "source_text": source,
                    "translation_ko": ko,
                    "translation_status": row.get("translation_status"),
                    "uses_12x12": row.get("uses_12x12"),
                    "owner_ids": row.get("owner_ids"),
                    "raw_hex": row.get("raw_hex"),
                    "source_unresolved_slots": row.get("source_unresolved_slots"),
                }
            )
        if row.get("translation_status") == "pending" and 1 <= len(source) <= 6:
            pending_short.append(
                {
                    "record_id": row.get("record_id"),
                    "semantic_kind": row.get("semantic_kind"),
                    "source_text": source,
                    "raw_hex": row.get("raw_hex"),
                    "uses_12x12": row.get("uses_12x12"),
                    "owner_count": row.get("owner_count"),
                }
            )

    # Search IWRAM/VRAM for live 12x12 海 token 0xE1E1? slot 0x01C1 -> 0xDF20+0x01C1=0xE0E1
    token = 0xDF20 + 0x01C1
    needle = bytes((token >> 8, token & 0xFF))
    iwram = state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    report = {
        "bg0": {k: (hex(v) if isinstance(v, int) else v) for k, v in info.items()},
        "grid_tile_ids": [[cell["tile"] for cell in row] for row in grid],
        "grid_cells": [[cell["cell"] for cell in row] for row in grid],
        "sea_tiles": sea_tiles,
        "evade_tiles": evade_tiles,
        "vram_token_hits": [f"0x{h:08X}" for h in find_all(vram, needle, 16)],
        "iwram_token_hits": [f"0x{h:08X}" for h in find_all(iwram, needle, 16)],
        "sea_records": sea_rows,
        "pending_short_sample": pending_short[:60],
        "pending_short_count": len(pending_short),
        "semantic_kind_top": kinds.most_common(30),
    }
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "grid_tile_ids": report["grid_tile_ids"],
        "sea_tiles": sea_tiles,
        "evade_tiles": evade_tiles,
        "sea_record_count": len(sea_rows),
        "sea_sources": [r["source_text"] for r in sea_rows[:40]],
        "pending_short_count": len(pending_short),
        "vram_token_hits": report["vram_token_hits"],
        "iwram_token_hits": report["iwram_token_hits"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
