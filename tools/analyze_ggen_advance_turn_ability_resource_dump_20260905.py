#!/usr/bin/env python3
"""Render every animation in the turn-banner and ability-name sprite resources."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
PARENT = (
    ADVANCE_ROOT
    / "outputs"
    / "20260905_ggen_advance_stage_titles"
    / "ggen_advance_stage_entry_titles_ko_candidate_20260905.gba"
)
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_overlays_20260905"
TURN = 0x08165044
ABILITY = 0x083424A0


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_tile(raw: bytes) -> list[list[int]]:
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def palette_rgb(raw: bytes) -> list[tuple[int, int, int]]:
    return [
        tuple(((u16(raw, i * 2) >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))
        for i in range(len(raw) // 2)
    ]


def render_tile(raw: bytes, colors: list[tuple[int, int, int]]) -> Image.Image:
    im = Image.new("RGB", (8, 8), colors[0])
    pix = decode_tile(raw)
    for y in range(8):
        for x in range(8):
            im.putpixel((x, y), colors[pix[y][x]])
    return im


def header(rom: bytes, address: int) -> dict[str, int]:
    off = address - ROM_BASE
    kind, pal_count, gfx_rel, pal_rel, anim_count = struct.unpack_from("<5I", rom, off)
    return {
        "off": off,
        "pal_count": pal_count,
        "gfx_rel": gfx_rel,
        "pal_rel": pal_rel,
        "anim_count": anim_count,
        "source_tiles": (pal_rel - gfx_rel) // 32,
    }


def records(rom: bytes, address: int) -> list[tuple[int, bytes]]:
    h = header(rom, address)
    rels = [u32(rom, h["off"] + 0x14 + i * 4) for i in range(h["anim_count"])]
    starts = [h["off"] + 0x14 + rel for rel in rels]
    ends = starts[1:] + [h["off"] + h["gfx_rel"]]
    return [(start, rom[start:end]) for start, end in zip(starts, ends)]


def try_parse(blob: bytes) -> dict | str:
    try:
        parsed = sprite.parse_animation_oam(blob)
        src = sprite.parse_animation_source_tiles(blob, parsed)
        return {
            "objects": parsed["objects"],
            "marker": parsed["marker_offset"],
            "source_ids": src["source_ids"],
            "by_object": src["by_object"],
        }
    except SystemExit as exc:
        return str(exc)


def stitch(graphics: bytes, parsed: dict, pal: bytes) -> Image.Image:
    objs = parsed["objects"]
    x0 = min(int(o["x"]) for o in objs)
    y0 = min(int(o["y"]) for o in objs)
    x1 = max(int(o["x"]) + int(o["size_px"][0]) for o in objs)
    y1 = max(int(o["y"]) + int(o["size_px"][1]) for o in objs)
    colors = palette_rgb(pal)
    im = Image.new("RGB", (x1 - x0, y1 - y0), colors[0])
    for obj, ids in zip(objs, parsed["by_object"]):
        wt, ht = obj["size_px"][0] // 8, obj["size_px"][1] // 8
        for ty in range(ht):
            for tx in range(wt):
                src = ids[ty * wt + tx]
                tile = render_tile(graphics[src * 32:(src + 1) * 32], colors)
                im.paste(tile, (obj["x"] - x0 + tx * 8, obj["y"] - y0 + ty * 8))
    return im


def tile_sheet(graphics: bytes, pal: bytes, columns: int = 16) -> Image.Image:
    count = len(graphics) // 32
    rows = (count + columns - 1) // columns
    colors = palette_rgb(pal)
    im = Image.new("RGB", (columns * 9 + 8, rows * 9 + 8), (16, 16, 16))
    for i in range(count):
        tile = render_tile(graphics[i * 32:(i + 1) * 32], colors)
        im.paste(tile, (4 + (i % columns) * 9, 4 + (i // columns) * 9))
    return im


def dump_resource(rom: bytes, address: int, name: str, pal_index: int) -> dict:
    h = header(rom, address)
    recs = records(rom, address)
    graphics = rom[h["off"] + h["gfx_rel"]:h["off"] + h["pal_rel"]]
    palettes = rom[h["off"] + h["pal_rel"]:h["off"] + h["pal_rel"] + h["pal_count"] * 32]
    pal = palettes[pal_index * 32:(pal_index + 1) * 32]
    sheet = tile_sheet(graphics, pal)
    sheet.resize((sheet.width * 3, sheet.height * 3), Image.Resampling.NEAREST).save(OUT / f"{name}_tiles_x3.png")
    anims = []
    parsed_images = []
    for index, (start, blob) in enumerate(recs):
        parsed = try_parse(blob)
        row = {
            "index": index,
            "record_offset": f"0x{start:08X}",
            "record_bytes": len(blob),
            "head_hex": blob[:48].hex(),
            "marker_hits": [],
        }
        pos = 0
        while True:
            found = blob.find(b"\x40\x00\x40\x00", pos)
            if found < 0:
                break
            row["marker_hits"].append(found)
            pos = found + 2
        if isinstance(parsed, dict):
            row["objects"] = [
                {
                    "i": o["index"],
                    "x": o["x"],
                    "y": o["y"],
                    "size": o["size_px"],
                    "pal": o["palette_bank"],
                    "tile_start": o["tile_start"],
                    "tiles": o["tile_count"],
                }
                for o in parsed["objects"]
            ]
            row["source_ids"] = parsed["source_ids"]
            row["source_min_max"] = [min(parsed["source_ids"]), max(parsed["source_ids"])]
            im = stitch(graphics, parsed, pal)
            scaled = im.resize((im.width * 3, im.height * 3), Image.Resampling.NEAREST)
            scaled.save(OUT / f"{name}_anim{index:02d}.png")
            parsed_images.append((index, scaled))
        else:
            row["parse"] = parsed
            # Fallback: treat trailing u16s after any 8-aligned point as source ids.
            guesses = []
            for off in range(0, min(len(blob) - 4, 80), 2):
                count = (len(blob) - off) // 2
                ids = list(struct.unpack_from(f"<{count}H", blob, off))
                if ids and max(ids) < h["source_tiles"] and min(ids) >= 0 and len(set(ids)) > 3:
                    guesses.append({"off": off, "count": count, "min": min(ids), "max": max(ids), "ids": ids[:32]})
            row["source_id_guesses"] = guesses[:6]
        anims.append(row)
    if parsed_images:
        width = max(im.width for _i, im in parsed_images)
        height = sum(im.height + 18 for _i, im in parsed_images)
        sheet = Image.new("RGB", (width + 16, height + 8), (12, 12, 16))
        draw = ImageDraw.Draw(sheet)
        y = 4
        for index, im in parsed_images:
            draw.text((8, y), f"anim {index}", fill=(255, 255, 255))
            sheet.paste(im, (8, y + 14))
            y += im.height + 18
        sheet.save(OUT / f"{name}_all_anims.png")
    pal_sheet = Image.new("RGB", (h["pal_count"] * 18 + 8, 24), (12, 12, 16))
    for i in range(h["pal_count"]):
        colors = palette_rgb(palettes[i * 32:(i + 1) * 32])
        for c, color in enumerate(colors):
            pal_sheet.putpixel((4 + i * 18 + c, 4), color)
            pal_sheet.putpixel((4 + i * 18 + c, 5), color)
        ImageDraw.Draw(pal_sheet).text((4 + i * 18, 10), str(i), fill=(255, 255, 255))
    pal_sheet.resize((pal_sheet.width * 8, pal_sheet.height * 8), Image.Resampling.NEAREST).save(OUT / f"{name}_palettes.png")
    return {
        "address": f"0x{address:08X}",
        "header": {k: h[k] for k in h},
        "pointer_hits": [],
        "animations": anims,
        "palette_rgb": [palette_rgb(palettes[i * 32:(i + 1) * 32]) for i in range(h["pal_count"])],
    }


def pointer_hits(rom: bytes, address: int) -> list[str]:
    needle = struct.pack("<I", address)
    hits = []
    start = 0
    while True:
        found = rom.find(needle, start)
        if found < 0:
            break
        hits.append(f"0x{found:08X}")
        start = found + 1
    return hits


def live_turn_canvas(rom: bytes) -> None:
    """Rebuild the live ss2 banner from OAM + source mapping."""
    state, _ = statefmt.parse_png_state(PARENT.with_suffix(".ss2"))
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE + 0x200:statefmt.STATE_OAM]
    h = header(rom, TURN)
    graphics = rom[h["off"] + h["gfx_rel"]:h["off"] + h["pal_rel"]]
    lookup = {graphics[i * 32:(i + 1) * 32]: i for i in range(h["source_tiles"])}
    colors = palette_rgb(pal[5 * 32:6 * 32])
    im = Image.new("RGB", (240, 160), (0, 0, 0))
    mapping = []
    for index in range(15):
        row = statefmt.parse_oam_entry(oam, index)
        x, y, w, ht = int(row["x"]), int(row["y"]), int(row["width"]), int(row["height"])
        tile0 = int(row["tile"])
        srcs = []
        for ty in range(ht // 8):
            for tx in range(w // 8):
                raw = bytes(obj[(tile0 + ty * (w // 8) + tx) * 32:(tile0 + ty * (w // 8) + tx + 1) * 32])
                srcs.append(lookup.get(raw, -1))
                tile = render_tile(raw, colors)
                im.paste(tile, (x + tx * 8, y + ty * 8))
        mapping.append({"oam": index, "x": x, "y": y, "w": w, "h": ht, "dest": tile0, "sources": srcs})
    im.resize((720, 480), Image.Resampling.NEAREST).save(OUT / "ss2_live_banner_x3.png")
    (OUT / "ss2_live_banner_mapping.json").write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")


def live_ability_canvas(rom: bytes) -> None:
    state, _ = statefmt.parse_png_state(PARENT.with_suffix(".ss3"))
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE + 0x200:statefmt.STATE_OAM]
    h = header(rom, ABILITY)
    graphics = rom[h["off"] + h["gfx_rel"]:h["off"] + h["pal_rel"]]
    lookup = {graphics[i * 32:(i + 1) * 32]: i for i in range(h["source_tiles"])}
    colors = palette_rgb(pal[11 * 32:12 * 32])
    im = Image.new("RGB", (80, 24), colors[0])
    mapping = []
    for index in (0, 1):
        row = statefmt.parse_oam_entry(oam, index)
        x, y, w, ht = int(row["x"]), int(row["y"]), int(row["width"]), int(row["height"])
        tile0 = int(row["tile"])
        srcs = []
        for ty in range(ht // 8):
            for tx in range(w // 8):
                raw = bytes(obj[(tile0 + ty * (w // 8) + tx) * 32:(tile0 + ty * (w // 8) + tx + 1) * 32])
                srcs.append(lookup.get(raw, -1))
                tile = render_tile(raw, colors)
                im.paste(tile, (x - 84 + tx * 8, ty * 8))
        mapping.append({"oam": index, "x": x, "y": y, "w": w, "h": ht, "dest": tile0, "sources": srcs, "pal": int(row["palette_bank"])})
    im.resize((im.width * 6, im.height * 6), Image.Resampling.NEAREST).save(OUT / "ss3_live_ability_x6.png")
    (OUT / "ss3_live_ability_mapping.json").write_text(json.dumps({"palette11": palette_rgb(pal[11 * 32:12 * 32]), "objects": mapping}, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    rom = PARENT.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    turn = dump_resource(rom, TURN, "turn", pal_index=0)
    ability = dump_resource(rom, ABILITY, "ability", pal_index=0)
    turn["pointer_hits"] = pointer_hits(rom, TURN)
    ability["pointer_hits"] = pointer_hits(rom, ABILITY)
    live_turn_canvas(rom)
    live_ability_canvas(rom)
    report = {"turn": turn, "ability": ability}
    (ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_resource_dump_20260905.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "turn_anims": [
            {k: a[k] for k in a if k in {"index", "record_bytes", "parse", "marker_hits", "source_min_max", "objects", "source_id_guesses"}}
            for a in turn["animations"]
        ],
        "ability_anims": [
            {k: a[k] for k in a if k in {"index", "record_bytes", "parse", "marker_hits", "source_min_max", "objects"}}
            for a in ability["animations"]
        ],
        "turn_pointers": turn["pointer_hits"],
        "ability_pointers": ability["pointer_hits"],
        "turn_palettes": turn["palette_rgb"],
        "ability_palettes": ability["palette_rgb"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
