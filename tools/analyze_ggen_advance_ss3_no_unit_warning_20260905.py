#!/usr/bin/env python3
"""Bind Korean.ss3 'no selectable units' warning popup to its sprite package."""
from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_states_20260902 as ui
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss3"
OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_no_unit_warning"
JSON_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_ss3_no_unit_warning_20260905.json"
ROM_BASE = 0x08000000
CLONE = 0x092D8000
ORIGINAL = 0x08C64140


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def rgb555(value: int) -> tuple[int, int, int]:
    return tuple(((value >> s) & 31) * 255 // 31 for s in (0, 5, 10))


def decode_tile(raw: bytes) -> list[list[int]]:
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + x // 2]
            out[y][x] = (packed >> (4 * (x & 1))) & 15
    return out


def obj_tile(vram: bytes, tid: int) -> bytes:
    off = 0x10000 + tid * 32
    return bytes(vram[off : off + 32])


def canvas_image(canvas: list[list[int]], colors: list[tuple[int, int, int]], scale: int = 4) -> Image.Image:
    height, width = len(canvas), len(canvas[0])
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = colors[canvas[y][x]]
    return img.resize((width * scale, height * scale), Image.NEAREST)


def render_obj_region(state: bytes, oam_rows: list[dict[str, Any]], path: Path) -> None:
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    px = image.load()
    for row in reversed(oam_rows):
        attr0 = int(row["attr0"], 16)
        if ((attr0 >> 8) & 3) == 2 or bool(attr0 & 0x2000):
            continue
        tw, th = row["width"] // 8, row["height"] // 8
        bank = row["palette_bank"]
        for ty in range(th):
            for tx in range(tw):
                tid = row["tile"] + ty * tw + tx
                tile = decode_tile(obj_tile(vram, tid))
                for y in range(8):
                    for x in range(8):
                        c = tile[y][x]
                        if not c:
                            continue
                        sx, sy = row["x"] + tx * 8 + x, row["y"] + ty * 8 + y
                        if 0 <= sx < 240 and 0 <= sy < 160:
                            val = u16(pal, (16 * 16 + bank * 16 + c) * 2)
                            px[sx, sy] = (*rgb555(val), 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((960, 640), Image.NEAREST).save(path)


def header_info(rom: bytes, address: int) -> dict[str, Any]:
    off = address - ROM_BASE
    kind = u32(rom, off)
    palette_count = u32(rom, off + 4)
    graphics_rel = u32(rom, off + 8)
    palette_rel = u32(rom, off + 0x0C)
    anim_count = u32(rom, off + 0x10)
    graphics_bytes = palette_rel - graphics_rel
    return {
        "address": f"0x{address:08X}",
        "kind": kind,
        "palette_count": palette_count,
        "graphics_rel": hex(graphics_rel),
        "palette_rel": hex(palette_rel),
        "animation_count": anim_count,
        "source_tiles": graphics_bytes // 32 if graphics_bytes > 0 else 0,
        "resource_bytes": palette_rel + palette_count * 32,
        "offset": off,
    }


def parse_anim_safe(rom: bytes, address: int, anim: int) -> dict[str, Any] | None:
    try:
        _gfx, records = sprite.animation_records(rom, address)
    except Exception as exc:
        return {"error": str(exc)}
    if anim >= len(records):
        return None
    start, record = records[anim]
    marker = analysis.find_marker(record)
    if marker is None:
        return {"error": "no marker", "record_len": len(record)}
    sliced = record[marker:]
    try:
        parsed = sprite.parse_animation_oam(sliced)
    except Exception as exc:
        return {"error": f"oam: {exc}"}
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    blob = b"".join(item[1] for item in records[anim:])[marker:]
    if parsed["entries_end"] + total * 2 > len(blob):
        # still try within this record only
        if parsed["entries_end"] + total * 2 > len(sliced):
            return {
                "error": "lookup overrun",
                "objects": parsed["object_count"],
                "total_tiles": total,
                "record_len": len(record),
                "sliced_len": len(sliced),
                "geom": [
                    {
                        "i": o["index"],
                        "x": o["x"],
                        "y": o["y"],
                        "size": o["size_px"],
                        "tile_start": o["tile_start"],
                        "count": o["tile_count"],
                        "bank": o["palette_bank"],
                    }
                    for o in parsed["objects"]
                ],
            }
        ids = list(struct.unpack_from(f"<{total}H", sliced, parsed["entries_end"]))
    else:
        ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
    return {
        "file_start": start,
        "marker": marker,
        "objects": parsed["object_count"],
        "total_tiles": total,
        "source_ids": ids,
        "geom": [
            {
                "i": o["index"],
                "x": o["x"],
                "y": o["y"],
                "size": o["size_px"],
                "tile_start": o["tile_start"],
                "count": o["tile_count"],
                "bank": o["palette_bank"],
            }
            for o in parsed["objects"]
        ],
        "parsed": parsed,
        "ids": ids,
    }


def stitch_live(oam_rows: list[dict[str, Any]], vram: bytes) -> tuple[list[list[int]], int, int]:
    x0 = min(r["x"] for r in oam_rows)
    y0 = min(r["y"] for r in oam_rows)
    x1 = max(r["x"] + r["width"] for r in oam_rows)
    y1 = max(r["y"] + r["height"] for r in oam_rows)
    canvas = [[0] * (x1 - x0) for _ in range(y1 - y0)]
    for row in oam_rows:
        tw, th = row["width"] // 8, row["height"] // 8
        for ty in range(th):
            for tx in range(tw):
                tile = decode_tile(obj_tile(vram, row["tile"] + ty * tw + tx))
                ox = row["x"] - x0 + tx * 8
                oy = row["y"] - y0 + ty * 8
                for yy in range(8):
                    canvas[oy + yy][ox : ox + 8] = tile[yy]
    return canvas, x0, y0


def match_graphics(live_tiles: list[bytes], graphics: bytes) -> dict[str, Any]:
    n = len(graphics) // 32
    hits = 0
    mapping: list[int | None] = []
    unique_src: set[int] = set()
    for tile in live_tiles:
        found = None
        for sid in range(n):
            if graphics[sid * 32 : (sid + 1) * 32] == tile:
                found = sid
                unique_src.add(sid)
                hits += 1
                break
        mapping.append(found)
    return {"hits": hits, "total": len(live_tiles), "unique_source_ids": sorted(unique_src), "mapping": mapping}


def pointer_hits(data: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    hits: list[int] = []
    cursor = 0
    while True:
        found = data.find(needle, cursor)
        if found < 0:
            return hits
        hits.append(found)
        cursor = found + 1


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    st, _ = statefmt.parse_png_state(STATE)
    vram = st[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    pal = st[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    slots = ui.sprite_slots(st)
    oam = ui.visible_oam(st)
    popup = [row for row in oam if row["palette_bank"] == 12]
    OUT.mkdir(parents=True, exist_ok=True)
    render_obj_region(st, oam, OUT / "ss3_obj.png")
    render_obj_region(st, popup, OUT / "ss3_popup_obj.png")
    for i in range(4):
        bg.render_bg(st, bg.bg_info(st, i), OUT / f"ss3_bg{i}.png")

    live_ids: list[int] = []
    live_tiles: list[bytes] = []
    for row in popup:
        tw, th = row["width"] // 8, row["height"] // 8
        for ty in range(th):
            for tx in range(tw):
                tid = row["tile"] + ty * tw + tx
                live_ids.append(tid)
                live_tiles.append(obj_tile(vram, tid))

    canvas, ox, oy = stitch_live(popup, vram)
    colors = [rgb555(u16(pal, (16 * 16 + 12 * 16 + i) * 2)) for i in range(16)]
    canvas_image(canvas, colors, 4).save(OUT / "ss3_popup_canvas.png")
    # text plane: the two 64x32 objects
    text_oam = [row for row in popup if row["width"] == 64 and row["height"] == 32]
    text_canvas, tx0, ty0 = stitch_live(text_oam, vram)
    canvas_image(text_canvas, colors, 5).save(OUT / "ss3_text_plane.png")

    counts = Counter(c for row in text_canvas for c in row)
    face_shadow = Counter()
    # glyph-like: not the modal fill. sample unique indices
    clone_h = header_info(rom, CLONE)
    orig_h = header_info(jp, ORIGINAL)
    clone_gfx = rom[CLONE - ROM_BASE + u32(rom, CLONE - ROM_BASE + 8) : CLONE - ROM_BASE + u32(rom, CLONE - ROM_BASE + 0xC)]
    orig_gfx = jp[ORIGINAL - ROM_BASE + u32(jp, ORIGINAL - ROM_BASE + 8) : ORIGINAL - ROM_BASE + u32(jp, ORIGINAL - ROM_BASE + 0xC)]
    clone_match = match_graphics(live_tiles, clone_gfx)
    orig_match = match_graphics(live_tiles, orig_gfx)

    anims = []
    for anim in range(clone_h["animation_count"]):
        info = parse_anim_safe(rom, CLONE, anim)
        row = {k: v for k, v in (info or {}).items() if k not in {"parsed", "ids", "source_ids"}}
        if info and "ids" in info:
            hits = 0
            for sid, tile in zip(info["ids"], live_tiles) if len(info["ids"]) == len(live_tiles) else []:
                src = clone_gfx[sid * 32 : (sid + 1) * 32]
                if src == tile:
                    hits += 1
            # geometry compare with popup OAM dest sizes
            geom_match = False
            if info.get("objects") == len(popup):
                geom_match = all(
                    info["geom"][i]["size"] == [popup[i]["width"], popup[i]["height"]]
                    for i in range(len(popup))
                )
            row["live_lookup_hits_if_same_len"] = hits
            row["geom_size_match_popup"] = geom_match
            if geom_match and "ids" in info:
                exact = sum(
                    clone_gfx[sid * 32 : (sid + 1) * 32] == live_tiles[i]
                    for i, sid in enumerate(info["ids"])
                )
                row["source_lookup_exact"] = exact
                row["source_lookup_total"] = len(info["ids"])
                row["source_id_set"] = sorted(set(info["ids"]))
        anims.append(row)

    # also dump original anims
    orig_anims = []
    for anim in range(orig_h["animation_count"]):
        info = parse_anim_safe(jp, ORIGINAL, anim)
        orig_anims.append({k: v for k, v in (info or {}).items() if k not in {"parsed", "ids", "source_ids"}})

    # palette dump
    pal_rgb = [{"index": i, "rgb": colors[i]} for i in range(16)]

    report = {
        "slots": slots,
        "popup_oam": popup,
        "popup_origin": [ox, oy],
        "text_origin": [tx0, ty0],
        "text_size": [len(text_canvas[0]), len(text_canvas)],
        "text_index_counts": counts.most_common(),
        "obj_palette_bank12": pal_rgb,
        "clone_header": clone_h,
        "original_header": orig_h,
        "clone_match_tiles": {k: (v if k != "mapping" else None) for k, v in clone_match.items()},
        "original_match_tiles": {k: (v if k != "mapping" else None) for k, v in orig_match.items()},
        "clone_unmatched_live": [i for i, sid in enumerate(clone_match["mapping"]) if sid is None],
        "clone_anims": anims,
        "original_anims": orig_anims,
        "clone_consumers": [f"0x{x:08X}" for x in pointer_hits(rom[:0x01000000], CLONE)],
        "original_consumers_low": [f"0x{x:08X}" for x in pointer_hits(rom[:0x01000000], ORIGINAL)],
        "live_tile_count": len(live_tiles),
    }
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "clone": clone_h,
        "original": orig_h,
        "clone_hits": clone_match["hits"],
        "orig_hits": orig_match["hits"],
        "unmatched": report["clone_unmatched_live"],
        "anims": anims,
        "orig_anims": orig_anims,
        "text_counts": counts.most_common(8),
        "palette": pal_rgb,
        "consumers_clone": report["clone_consumers"],
        "consumers_orig": report["original_consumers_low"],
        "out": advance_relative(JSON_OUT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
