#!/usr/bin/env python3
"""Analyze the HIT!/CRITICAL!! graphics visible in the promoted-main SS1."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_remaining_ui_states_20260902 as remaining
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_event_exp_weapon_badges_preemptive_candidate_20260904 as gfxutil
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, advance_relative

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_hit_critical_ss1_20260904.json"
PREVIEW = ADVANCE_ROOT / "analysis" / "ggen_advance_hit_critical_ss1_active_obj_20260904.png"
ROM_PREVIEW = ADVANCE_ROOT / "analysis" / "ggen_advance_hit_critical_ss1_rom_tiles_20260904.png"
ROM_BASE = 0x08000000
ACTIVE_RESOURCE = 0x08382934


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def pointer_hits(data: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    hits: list[int] = []
    start = 0
    while True:
        found = data.find(needle, start)
        if found < 0:
            return hits
        hits.append(found)
        start = found + 1


def linear_canvas(graphics: bytes, first_tile: int, width_tiles: int, height_tiles: int) -> list[list[int]]:
    canvas = [[0] * (width_tiles * 8) for _ in range(height_tiles * 8)]
    for index in range(width_tiles * height_tiles):
        tile_id = first_tile + index
        tile = gfxutil.decode_tile(graphics[tile_id * 32:(tile_id + 1) * 32])
        ox, oy = (index % width_tiles) * 8, (index // width_tiles) * 8
        for y in range(8):
            canvas[oy + y][ox:ox + 8] = tile[y]
    return canvas


def resource_for_graphics(main_rom: bytes, graphics_offset: int) -> dict[str, object]:
    matches = []
    for offset in range(max(0, graphics_offset - 0x4000), graphics_offset, 4):
        kind, tag, graphics_rel, palette_rel, animation_count = struct.unpack_from("<5I", main_rom, offset)
        if kind == 0 and tag == 6 and 0x20 <= graphics_rel < palette_rel and offset + graphics_rel == graphics_offset and 1 <= animation_count <= 64:
            matches.append((offset, graphics_rel, palette_rel, animation_count))
    if len(matches) != 1:
        raise SystemExit(f"gate failed: graphics 0x{graphics_offset:08X} has {len(matches)} resource owners")
    offset, graphics_rel, palette_rel, animation_count = matches[0]
    address = ROM_BASE + offset
    return {
        "address": f"0x{address:08X}",
        "file_offset": f"0x{offset:08X}",
        "graphics_offset": f"0x{graphics_offset:08X}",
        "graphics_rel": f"0x{graphics_rel:X}",
        "palette_rel": f"0x{palette_rel:X}",
        "animation_count": animation_count,
        "source_tiles": (palette_rel - graphics_rel) // 32,
        "pointer_literals": [f"0x{x:08X}" for x in pointer_hits(main_rom, address)],
    }


def object_image(obj_vram: bytes, obj_palette: bytes, row: dict[str, object]) -> tuple[Image.Image, list[int]]:
    width, height = int(row["width"]), int(row["height"])
    tiles_w, tiles_h = width // 8, height // 8
    pixels = [[0] * width for _ in range(height)]
    tile_ids: list[int] = []
    for ty in range(tiles_h):
        for tx in range(tiles_w):
            tile_id = int(row["tile"]) + ty * tiles_w + tx
            tile_ids.append(tile_id)
            tile = gfxutil.decode_tile(obj_vram[tile_id * 32:(tile_id + 1) * 32])
            for y in range(8):
                pixels[ty * 8 + y][tx * 8:tx * 8 + 8] = tile[y]
    image = gfxutil.render_canvas(pixels, gfxutil.palette_rgb(obj_palette, int(row["palette_bank"]))).convert("RGBA")
    alpha = Image.new("L", (width, height), 0)
    alpha.putdata([255 if value else 0 for line in pixels for value in line])
    image.putalpha(alpha)
    return image, tile_ids


def main() -> int:
    raw = STATE.read_bytes()
    state, _chunks = statefmt.parse_png_state(STATE)
    main_rom = MAIN_TIP_ROM.read_bytes()
    state_crc = struct.unpack_from("<I", state, 8)[0]
    main_crc = binascii.crc32(main_rom) & 0xFFFFFFFF
    if state_crc != main_crc:
        raise SystemExit(f"gate failed: state/main CRC mismatch 0x{state_crc:08X} != 0x{main_crc:08X}")

    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    obj_vram = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    obj_palette = state[statefmt.STATE_PALETTE + 0x200:statefmt.STATE_OAM]
    visible = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if not (0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160):
            continue
        image, tile_ids = object_image(obj_vram, obj_palette, row)
        row = {**row, "tile_ids": tile_ids, "nontransparent_pixels": sum(1 for value in list(image.getchannel("A").getdata()) if value)}
        visible.append((row, image))

    canvas = Image.new("RGBA", (240, 160), (16, 16, 16, 255))
    for row, image in reversed(visible):
        canvas.alpha_composite(image, (int(row["x"]), int(row["y"])))
    crop = canvas.crop((72, 0, 208, 96)).resize((816, 576), Image.Resampling.NEAREST)
    sheet = Image.new("RGBA", (816, 640), (16, 16, 16, 255))
    sheet.paste(crop, (0, 32))
    ImageDraw.Draw(sheet).text((8, 8), "SS1 active OBJ crop (6x)", fill=(255, 255, 255, 255))
    sheet.save(PREVIEW)

    active_offset = ACTIVE_RESOURCE - ROM_BASE
    kind, tag, graphics_rel, palette_rel, animation_count = struct.unpack_from("<5I", main_rom, active_offset)
    if (kind, tag, animation_count) != (0, 6, 1):
        raise SystemExit("gate failed: active battle resource header drift")
    graphics = main_rom[active_offset + graphics_rel:active_offset + palette_rel]
    text_blob = graphics[:24 * 32]
    live_text = obj_vram[384 * 32:408 * 32]
    if live_text != text_blob:
        raise SystemExit("gate failed: live HIT/CRITICAL tiles do not match active resource tiles 0..23")

    hit_canvas = linear_canvas(graphics, 0, 4, 2)
    critical_canvas = linear_canvas(graphics, 8, 8, 2)
    local_palette0 = main_rom[active_offset + palette_rel:active_offset + palette_rel + 32]
    live_palette11 = obj_palette[11 * 32:12 * 32]
    if local_palette0 != live_palette11:
        raise SystemExit("gate failed: live OBJ palette 11 does not match resource palette 0")
    colors = gfxutil.palette_rgb(local_palette0)
    source_sheet = Image.new("RGB", (512, 320), (16, 16, 16))
    source_sheet.paste(gfxutil.render_canvas(hit_canvas, colors).resize((256, 128), Image.Resampling.NEAREST), (128, 32))
    source_sheet.paste(gfxutil.render_canvas(critical_canvas, colors).resize((512, 128), Image.Resampling.NEAREST), (0, 192))
    ImageDraw.Draw(source_sheet).text((8, 8), "HIT source tiles 0-7 / CRITICAL source tiles 8-23", fill=(255, 255, 255))
    source_sheet.save(ROM_PREVIEW)

    graphics_hits: list[int] = []
    start = 0
    while True:
        found = main_rom.find(text_blob, start)
        if found < 0:
            break
        graphics_hits.append(found)
        start = found + 1
    owners = [resource_for_graphics(main_rom, found) for found in graphics_hits]
    if len(owners) != 20:
        raise SystemExit(f"gate failed: expected 20 exact HIT/CRITICAL copies, got {len(owners)}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_hit_critical_ss1_20260904",
        "result": "PASS",
        "state": {"path": advance_relative(STATE), "sha256": sha256(raw), "rom_crc32": f"0x{state_crc:08X}"},
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(main_rom), "crc32": f"0x{main_crc:08X}"},
        "preview": advance_relative(PREVIEW),
        "rom_tiles_preview": advance_relative(ROM_PREVIEW),
        "visible_oam": [row for row, _image in visible],
        "sprite_slots": remaining.sprite_slots(state),
        "live_graphics": {
            "active_resource": f"0x{ACTIVE_RESOURCE:08X}",
            "resource_graphics_start": f"0x{ACTIVE_RESOURCE + graphics_rel:08X}",
            "hit": {"text": "ヒット!", "oam_indices": [0], "live_obj_tiles": [384, 391], "source_tiles": [0, 7], "canvas": [32, 16]},
            "critical": {"text": "クリティカル!!", "oam_indices": [1, 2], "live_obj_tiles": [392, 407], "source_tiles": [8, 23], "canvas": [64, 16]},
            "palette": {
                "resource_bank": 0,
                "live_obj_bank": 11,
                "exact_match": True,
                "colors_rgb": {str(index): list(color) for index, color in enumerate(colors)},
            },
        },
        "ownership": {
            "architecture": "24 text tiles are duplicated byte-exact at the start of 20 battle-unit sprite resources",
            "exact_duplicate_count": len(owners),
            "resources": owners,
            "pointer_table_span": [owners[0]["pointer_literals"][0], owners[-1]["pointer_literals"][0]],
        },
        "localization_plan": {
            "hit": "Render 히트! centered in the existing 32x16/8-tile field, using two 12-pixel Hangul cells plus compact punctuation; retain palette indices 1/3/4/5 for dark-to-bright green shading.",
            "critical": "Render 크리티컬!! centered in the existing 64x16/16-tile field, using four 12-pixel Hangul cells plus two 6-pixel punctuation cells; retain white index 2, dark/red indices 1/9/10, and orange highlight index 11.",
            "coverage": "Patch source tiles 0..23 in all 20 exact duplicate resources; do not redirect the unit-resource pointer table or alter unit graphics after tile 23.",
            "recommended_font": "Galmuri11 regular at native size for both labels, with compact punctuation advances and a one-pixel native-style outline.",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(OUT), "preview": str(PREVIEW), "visible_oam": len(visible)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
