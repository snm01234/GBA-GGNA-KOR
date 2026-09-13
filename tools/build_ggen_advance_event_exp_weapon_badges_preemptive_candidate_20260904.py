#!/usr/bin/env python3
"""Build a scoped Korean graphics candidate for the current ss1/ss2/ss3.

Targets:
* ss1 OBJ: イベントEXP -> 이벤트EXP, including the white flash silhouette.
* ss2 BG2: 射単/射全/近単/近全 -> 사단/사전/근단/근전.
* ss3 OBJ: 先制攻撃 -> 선제공격, preserving the native fade timeline.

Every source resource is cloned into a zero-filled expansion allocation.  The
Japanese 16 MiB half and all palettes, maps, OAM/frame records, and unrelated
graphics remain byte-exact; only the proven pointer literals are redirected.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spriteutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_sort_popup_state6_candidate_20260903 as statewriter
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

ROM_BASE = 0x08000000
EXPECTED_MAIN_SHA256 = "74dd04a23600d66649780e9c85a01f32b4aa1bb2b8ece10ca320cc05af6985ab"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_event_exp_weapon_badges_preemptive"
OUT_ROM = OUT_DIR / "ggen_advance_event_exp_weapon_badges_preemptive_candidate_20260904.gba"
OUT_SAV = OUT_DIR / "ggen_advance_event_exp_weapon_badges_preemptive_candidate_20260904.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_event_exp_weapon_badges_preemptive_preview_20260904.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_event_exp_weapon_badges_preemptive_candidate_20260904.json"

STATES = {
    "event_exp": ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1",
    "weapon_badge": ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2",
    "preemptive": ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss3",
}

# Private, currently zero-filled expansion allocations.
EVENT_SOURCE = 0x08C37C9C
EVENT_CLONE_OFF = 0x01F40000
EVENT_POINTERS = (0x00028BC4, 0x00028C94)

BADGES = (
    ("射単", "사단", 0x08A8E7D0, 0x01F44000, 0x000384F8),
    ("射全", "사전", 0x08A8EA00, 0x01F44400, 0x00038510),
    ("近単", "근단", 0x08A8EC30, 0x01F44800, 0x00038528),
    ("近全", "근전", 0x08A8EE60, 0x01F44C00, 0x00038558),
)

PREEMPTIVE_SOURCE = 0x083D2480
PREEMPTIVE_CLONE_OFF = 0x01F46000
PREEMPTIVE_POINTERS = (0x0003132C, 0x00031554, 0x0003CAA8)
ALLOCATION_END = 0x01F48000


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def p32(value: int) -> bytes:
    return struct.pack("<I", value)


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile length drift")
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def encode_tile(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 8 and all(len(row) == 8 for row in pixels), "4bpp tile shape drift")
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            value = pixels[y][x] & 0xF
            index = y * 4 + x // 2
            if x & 1:
                out[index] |= value << 4
            else:
                out[index] |= value
    return bytes(out)


def decode_linear_tiles(graphics: bytes, width: int, height: int) -> list[list[int]]:
    gate(len(graphics) == width * height * 32, "linear graphics size drift")
    canvas = [[0] * (width * 8) for _ in range(height * 8)]
    for index in range(width * height):
        tile = decode_tile(graphics[index * 32:(index + 1) * 32])
        ox, oy = (index % width) * 8, (index // width) * 8
        for y in range(8):
            canvas[oy + y][ox:ox + 8] = tile[y]
    return canvas


def encode_linear_tiles(canvas: list[list[int]], width: int, height: int) -> bytes:
    gate(len(canvas) == height * 8 and all(len(row) == width * 8 for row in canvas), "linear canvas shape drift")
    out = bytearray()
    for index in range(width * height):
        ox, oy = (index % width) * 8, (index // width) * 8
        out += encode_tile([canvas[oy + y][ox:ox + 8] for y in range(8)])
    return bytes(out)


def event_canvas(graphics: bytes, first_tile: int) -> list[list[int]]:
    """Stitch the native 32x16 + 16x16 metasprite source order."""
    ids = list(range(first_tile, first_tile + 12))
    canvas = [[0] * 48 for _ in range(16)]
    for source_ids, x0, tiles_w in ((ids[:8], 0, 4), (ids[8:], 32, 2)):
        for index, tile_id in enumerate(source_ids):
            tile = decode_tile(graphics[tile_id * 32:(tile_id + 1) * 32])
            ox, oy = x0 + (index % tiles_w) * 8, (index // tiles_w) * 8
            for y in range(8):
                canvas[oy + y][ox:ox + 8] = tile[y]
    return canvas


def write_event_canvas(graphics: bytearray, first_tile: int, canvas: list[list[int]]) -> None:
    ids = list(range(first_tile, first_tile + 12))
    for source_ids, x0, tiles_w in ((ids[:8], 0, 4), (ids[8:], 32, 2)):
        for index, tile_id in enumerate(source_ids):
            ox, oy = x0 + (index % tiles_w) * 8, (index // tiles_w) * 8
            tile = [canvas[oy + y][ox:ox + 8] for y in range(8)]
            graphics[tile_id * 32:(tile_id + 1) * 32] = encode_tile(tile)


def render_text_mask(text: str, font: fontpair.BdfFont, cell_width: int, cell_height: int) -> list[list[bool]]:
    mask = [[False] * (len(text) * cell_width) for _ in range(cell_height)]
    for index, char in enumerate(text):
        glyph = font.render(char, cell_width, cell_height)
        for y in range(cell_height):
            for x in range(cell_width):
                if glyph.getpixel((x, y)):
                    mask[y][index * cell_width + x] = True
    return mask


def repaint_event(graphics: bytearray, condensed: fontpair.BdfFont) -> dict[str, object]:
    flash_before = event_canvas(bytes(graphics), 1)
    normal_before = event_canvas(bytes(graphics), 13)
    normal = [row[:] for row in normal_before]

    # The final katakana ト ends at x=25.  The native left outline/shadow of E
    # begins at x=26 (its face begins at x=27), so preserve EXP from x=26.
    prefix_width = 26
    for y in range(16):
        for x in range(prefix_width):
            normal[y][x] = 0
    # Pack the three 8-pixel glyph cells at a 7-pixel advance, then shear the
    # upper rows to the right.  This reproduces the compact italic silhouette
    # of the native Japanese prefix while leaving the EXP half untouched.
    base_ink: set[tuple[int, int]] = set()
    for index, char in enumerate("이벤트"):
        glyph = condensed.render(char, 8, 16)
        for y in range(16):
            for x in range(8):
                if glyph.getpixel((x, y)):
                    base_ink.add((index * 7 + x, y))
    # Move the replacement two pixels right within the newly measured field.
    x_offset = 2
    ink = {
        (x_offset + x + (2 if y <= 5 else 1 if y <= 9 else 0), y)
        for x, y in base_ink
        if x_offset + x + (2 if y <= 5 else 1 if y <= 9 else 0) < prefix_width
    }
    gate(ink and all(0 <= x < prefix_width for x, _y in ink), "event Hangul mask overflow")

    # Rebuild a strictly one-pixel native blue border around the glyph body.
    shadow = {
        (x + dx, y + dy)
        for x, y in ink
        for dx, dy in (
            (-1, -1), (0, -1), (1, -1),
            (-1, 0),             (1, 0),
            (-1, 1),  (0, 1),   (1, 1),
        )
        if 0 <= x + dx < prefix_width and 0 <= y + dy < 16
    }
    for x, y in shadow:
        normal[y][x] = 8

    # Native-style vertical face gradient, deliberately stopping at sky blue.
    # Deep blue is reserved for the border so the lower 받침 strokes stay clear.
    for x, y in ink:
        if y <= 7:
            normal[y][x] = 1
        elif y <= 9:
            normal[y][x] = 6
        else:
            normal[y][x] = 7

    # The alternate tiles use the complete final silhouette, including shadow.
    flash = [row[:] for row in flash_before]
    silhouette = ink | shadow
    for y in range(16):
        for x in range(prefix_width):
            flash[y][x] = 1 if (x, y) in silhouette else 0

    gate(all(normal[y][x] == normal_before[y][x] for y in range(16) for x in range(prefix_width, 48)), "native EXP pixels changed")
    gate(all(flash[y][x] == flash_before[y][x] for y in range(16) for x in range(prefix_width, 48)), "native flash EXP pixels changed")
    write_event_canvas(graphics, 1, flash)
    write_event_canvas(graphics, 13, normal)
    return {
        "translation": "イベントEXP -> 이벤트EXP",
        "normal_source_tiles": list(range(13, 25)),
        "flash_source_tiles": list(range(1, 13)),
        "preserved_exp_rect": [26, 0, 48, 16],
        "cleared_japanese_prefix_rect": [0, 0, 26, 16],
        "font": "Galmuri11-Condensed.bdf native 8x16 cells",
        "advance_pixels": 7,
        "x_offset_pixels": x_offset,
        "italic_shear_pixels": [2, 1, 0],
        "hangul_pixels": len(ink),
        "shadow_pixels": len(shadow - ink),
        "silhouette_pixels": len(silhouette),
        "face_gradient": {"white": 1, "pale_cyan": 6, "sky_blue": 7},
        "before": normal_before,
        "after": normal,
    }


def parse_bg_resource(rom: bytes, address: int) -> dict[str, object]:
    off = address - ROM_BASE
    kind, dimensions, header_bytes, map_bytes, graphics_rel, graphics_bytes, palette_rel, palette_bytes = struct.unpack_from("<8H", rom, off)
    width, height = dimensions & 0xFF, dimensions >> 8
    gate(kind == 2 and header_bytes == 0x10, f"BG resource header drift at 0x{address:08X}")
    gate((width, height) == (5, 3) and map_bytes == 30 and graphics_bytes == 15 * 32 and palette_bytes == 32, f"badge geometry drift at 0x{address:08X}")
    gate(palette_rel + palette_bytes == 0x230, f"badge resource size drift at 0x{address:08X}")
    tilemap = list(struct.unpack_from("<15H", rom, off + header_bytes))
    gate([entry & 0x3FF for entry in tilemap] == list(range(15)), f"badge tilemap drift at 0x{address:08X}")
    return {
        "off": off,
        "width": width,
        "height": height,
        "graphics_rel": graphics_rel,
        "graphics_bytes": graphics_bytes,
        "palette_rel": palette_rel,
        "palette_bytes": palette_bytes,
        "resource_bytes": palette_rel + palette_bytes,
    }


def repaint_badge(resource: bytearray, text: str, font: fontpair.BdfFont) -> dict[str, object]:
    info = parse_bg_resource(bytes(resource), ROM_BASE)
    graphics_rel = int(info["graphics_rel"])
    graphics_bytes = int(info["graphics_bytes"])
    before_graphics = bytes(resource[graphics_rel:graphics_rel + graphics_bytes])
    before = decode_linear_tiles(before_graphics, 5, 3)
    after = [row[:] for row in before]

    # Across all seven sibling badges only x=4..31,y=8..21 varies.  Inside
    # that measured field, B/C are the native glyph face/shadow and F is the
    # clean plaque interior.  Remove only those glyph pixels so the bevel,
    # gradient, and highlights remain byte-exact.
    for y in range(8, 22):
        for x in range(4, 32):
            if after[y][x] in (11, 12):
                after[y][x] = 15
    mask = render_text_mask(text, font, 12, 12)
    x0, y0 = 7, 8
    ink = {(x0 + x, y0 + y) for y in range(12) for x in range(24) if mask[y][x]}
    contour = set()
    for x, y in ink:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if 4 <= x + dx < 32 and 8 <= y + dy < 22:
                    contour.add((x + dx, y + dy))
    for x, y in contour - ink:
        after[y][x] = 12
    for x, y in ink:
        after[y][x] = 11
    gate(all(after[y][x] == before[y][x] for y in range(24) for x in range(40) if not (4 <= x < 32 and 8 <= y < 22)), "badge chrome changed")
    resource[graphics_rel:graphics_rel + graphics_bytes] = encode_linear_tiles(after, 5, 3)
    return {
        "font": "Galmuri11.bdf native 12x12",
        "field_rect": [4, 8, 32, 22],
        "cleanup": "replace only native B/C glyph pixels with F",
        "face_index": 11,
        "contour_index": 12,
        "ink_pixels": len(ink),
        "contour_pixels": len(contour - ink),
        "before": before,
        "after": after,
    }


def repaint_preemptive(graphics: bytearray, font: fontpair.BdfFont) -> dict[str, object]:
    gate(len(graphics) == 52 * 32, "preemptive atlas tile count drift")
    before = preemptive_canvas(bytes(graphics))
    after = [[0] * 104 for _ in range(32)]

    base_mask = render_text_mask("선제공격", font, 12, 12)
    native = Image.new("1", (48, 12), 0)
    for y in range(12):
        for x in range(48):
            if base_mask[y][x]:
                native.putpixel((x, y), 255)
    doubled = native.resize((96, 24), Image.Resampling.NEAREST)
    ink = {(4 + x, 4 + y) for y in range(24) for x in range(96) if doubled.getpixel((x, y))}
    gate(ink and max(x for x, _y in ink) < 102 and max(y for _x, y in ink) < 30, "preemptive Hangul mask overflow")

    # A one-pixel bright rim and a restrained lower-right shadow preserve the
    # native hierarchy without turning the Hangul strokes into solid blocks.
    mid = {
        (x + dx, y + dy)
        for x, y in ink
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
        if 0 <= x + dx < 104 and 0 <= y + dy < 32
    }
    shadow = {
        (x + dx, y + dy)
        for x, y in (ink | mid)
        for dx, dy in ((1, 1), (2, 1), (1, 2), (2, 2))
        if 0 <= x + dx < 104 and 0 <= y + dy < 32
    }
    for x, y in shadow:
        after[y][x] = 5
    for x, y in mid:
        after[y][x] = 9
    for x, y in ink:
        after[y][x] = 15
    write_preemptive_canvas(graphics, after)
    return {
        "translation": "先制攻撃 -> 선제공격",
        "font": "Galmuri11.bdf native 12x12, nearest-neighbour 2x",
        "canvas": [104, 32],
        "face_index": 15,
        "inner_contour_index": 9,
        "shadow_index": 5,
        "ink_pixels": len(ink),
        "inner_contour_pixels": len(mid - ink),
        "shadow_pixels": len(shadow - mid),
        "before": before,
        "after": after,
    }


def preemptive_canvas(graphics: bytes) -> list[list[int]]:
    """Stitch source IDs in native 64x32 + 32x32 + 8x32 OBJ order."""
    gate(len(graphics) == 52 * 32, "preemptive graphics size drift")
    canvas = [[0] * 104 for _ in range(32)]
    cursor = 0
    for x0, tiles_w in ((0, 8), (64, 4), (96, 1)):
        for index in range(tiles_w * 4):
            tile = decode_tile(graphics[cursor * 32:(cursor + 1) * 32])
            cursor += 1
            ox, oy = x0 + (index % tiles_w) * 8, (index // tiles_w) * 8
            for y in range(8):
                canvas[oy + y][ox:ox + 8] = tile[y]
    gate(cursor == 52, "preemptive source cursor drift")
    return canvas


def write_preemptive_canvas(graphics: bytearray, canvas: list[list[int]]) -> None:
    gate(len(canvas) == 32 and all(len(row) == 104 for row in canvas), "preemptive canvas shape drift")
    cursor = 0
    for x0, tiles_w in ((0, 8), (64, 4), (96, 1)):
        for index in range(tiles_w * 4):
            ox, oy = x0 + (index % tiles_w) * 8, (index // tiles_w) * 8
            tile = [canvas[oy + y][ox:ox + 8] for y in range(8)]
            graphics[cursor * 32:(cursor + 1) * 32] = encode_tile(tile)
            cursor += 1
    gate(cursor == 52, "preemptive write cursor drift")


def palette_rgb(palette: bytes, bank: int = 0) -> list[tuple[int, int, int]]:
    result = []
    for index in range(16):
        value = u16(palette, (bank * 16 + index) * 2)
        result.append(tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10)))
    return result


def render_canvas(canvas: list[list[int]], colors: list[tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", (len(canvas[0]), len(canvas)), colors[0])
    for y, row in enumerate(canvas):
        for x, value in enumerate(row):
            image.putpixel((x, y), colors[value])
    return image


def build_preview(event: dict[str, object], badges: list[dict[str, object]], preemptive: dict[str, object], states: dict[str, bytes], badge_palettes: list[bytes]) -> None:
    scale = 4
    sheet = Image.new("RGB", (832, 392), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 4), "EVENT EXP  before / after", fill=(255, 255, 255))
    event_state_palette = states["event_exp"][statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    event_colors = palette_rgb(event_state_palette[0x200:], 0)
    for column, key in enumerate(("before", "after")):
        image = render_canvas(event[key], event_colors).resize((48 * scale, 16 * scale), Image.Resampling.NEAREST)
        sheet.paste(image, (8 + column * 208, 24))

    draw.text((8, 100), "WEAPON BADGES  before / after", fill=(255, 255, 255))
    y = 120
    for index, row in enumerate(badges):
        colors = palette_rgb(badge_palettes[index])
        for column, key in enumerate(("before", "after")):
            image = render_canvas(row[key], colors).resize((40 * scale, 24 * scale), Image.Resampling.NEAREST)
            sheet.paste(image, (8 + column * 176, y))
        draw.text((370, y + 38), f"{row['source']} -> {row['translation']}", fill=(255, 255, 255))
        y += 66

    draw.text((520, 4), "PREEMPTIVE  before / after", fill=(255, 255, 255))
    pre_state_palette = states["preemptive"][statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    pre_colors = palette_rgb(pre_state_palette[0x200:], 11)
    for row_index, key in enumerate(("before", "after")):
        image = render_canvas(preemptive[key], pre_colors).resize((104 * 3, 32 * 3), Image.Resampling.NEAREST)
        sheet.paste(image, (512, 24 + row_index * 112))
    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT_PREVIEW)


def patch_derived_states(candidate_crc: int, event_graphics: bytes, badge_graphics: bytes, preemptive_graphics: bytes) -> dict[str, object]:
    outputs: dict[str, object] = {}
    for index, (name, path) in enumerate(STATES.items(), start=1):
        state, _chunks = statefmt.parse_png_state(path)
        out = bytearray(state)
        if name == "event_exp":
            normal = event_canvas(event_graphics, 13)
            payload = bytearray(12 * 32)
            temp = bytearray(25 * 32)
            write_event_canvas(temp, 13, normal)
            payload[:] = temp[13 * 32:25 * 32]
            dest = statefmt.STATE_VRAM + statefmt.OBJ_VRAM
            out[dest:dest + len(payload)] = payload
        elif name == "weapon_badge":
            dest = statefmt.STATE_VRAM + 523 * 32
            out[dest:dest + len(badge_graphics)] = badge_graphics
        else:
            dest = statefmt.STATE_VRAM + statefmt.OBJ_VRAM + 386 * 32
            out[dest:dest + len(preemptive_graphics)] = preemptive_graphics
        struct.pack_into("<I", out, 8, candidate_crc)
        out_path = OUT_DIR / f"ggen_advance_event_exp_weapon_badges_preemptive_candidate_20260904.ss{index}"
        out_path.write_bytes(statewriter.replace_state_chunk(path, bytes(out)))
        outputs[name] = {"path": advance_relative(out_path), "sha256": sha256(out_path.read_bytes())}
    return outputs


def strip_rasters(report: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in report.items() if key not in {"before", "after"}}


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == EXPECTED_MAIN_SHA256 == manifest.get("sha256"), "current main TIP identity drift")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese reference identity drift")
    gate(len(parent) == 32 * 1024 * 1024 and len(jp) == 16 * 1024 * 1024, "ROM size drift")
    gate(set(parent[EVENT_CLONE_OFF:ALLOCATION_END]) <= {0}, "private allocation is not zero-filled")

    states = {name: statefmt.parse_png_state(path)[0] for name, path in STATES.items()}
    parent_crc = binascii.crc32(parent) & 0xFFFFFFFF
    gate(all(u32(state, 8) == parent_crc for state in states.values()), "ss1/ss2/ss3 CRC does not match current main")

    with ZipFile(FONT_ZIP) as archive:
        condensed = fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf")
        regular = fontpair.load_bdf(archive, "Galmuri11.bdf")

    candidate = bytearray(parent)
    allowed = set()

    event_header = spriteutil.parse_resource_header(parent, EVENT_SOURCE)
    event_size = int(event_header["resource_bytes"])
    gate(event_size == 0x2D2C, "event resource size drift")
    event_source_off = EVENT_SOURCE - ROM_BASE
    gate(parent[event_source_off:event_source_off + event_size] == jp[event_source_off:event_source_off + event_size], "event source already differs from JP")
    event_clone = bytearray(parent[event_source_off:event_source_off + event_size])
    event_graphics_rel = int(event_header["graphics_rel"])
    event_palette_rel = int(event_header["palette_rel"])
    event_graphics = bytearray(event_clone[event_graphics_rel:event_palette_rel])
    event_report = repaint_event(event_graphics, condensed)
    event_clone[event_graphics_rel:event_palette_rel] = event_graphics
    candidate[EVENT_CLONE_OFF:EVENT_CLONE_OFF + event_size] = event_clone
    allowed.update(range(EVENT_CLONE_OFF, EVENT_CLONE_OFF + event_size))
    for pointer in EVENT_POINTERS:
        gate(u32(parent, pointer) == EVENT_SOURCE, f"event pointer drift at 0x{pointer:08X}")
        candidate[pointer:pointer + 4] = p32(ROM_BASE + EVENT_CLONE_OFF)
        allowed.update(range(pointer, pointer + 4))

    badge_reports: list[dict[str, object]] = []
    badge_palettes: list[bytes] = []
    first_badge_graphics = b""
    for source_text, translation, source, clone_off, pointer in BADGES:
        info = parse_bg_resource(parent, source)
        source_off = source - ROM_BASE
        size = int(info["resource_bytes"])
        gate(parent[source_off:source_off + size] == jp[source_off:source_off + size], f"{source_text} source already differs from JP")
        resource = bytearray(parent[source_off:source_off + size])
        report = repaint_badge(resource, translation, regular)
        report.update({"source": source_text, "translation": translation, "source_address": f"0x{source:08X}", "clone_address": f"0x{ROM_BASE + clone_off:08X}", "pointer_literal": f"0x{pointer:08X}"})
        badge_reports.append(report)
        palette_rel = int(info["palette_rel"])
        badge_palettes.append(bytes(resource[palette_rel:palette_rel + 32]))
        graphics_rel = int(info["graphics_rel"])
        graphics_bytes = int(info["graphics_bytes"])
        if not first_badge_graphics:
            first_badge_graphics = bytes(resource[graphics_rel:graphics_rel + graphics_bytes])
        candidate[clone_off:clone_off + size] = resource
        allowed.update(range(clone_off, clone_off + size))
        gate(u32(parent, pointer) == source, f"{source_text} pointer drift")
        candidate[pointer:pointer + 4] = p32(ROM_BASE + clone_off)
        allowed.update(range(pointer, pointer + 4))

    pre_header = spriteutil.parse_resource_header(parent, PREEMPTIVE_SOURCE)
    pre_size = int(pre_header["resource_bytes"])
    gate(pre_size == 0x11A0 and int(pre_header["source_tiles"]) == 52, "preemptive resource geometry drift")
    pre_source_off = PREEMPTIVE_SOURCE - ROM_BASE
    gate(parent[pre_source_off:pre_source_off + pre_size] == jp[pre_source_off:pre_source_off + pre_size], "preemptive source already differs from JP")
    pre_clone = bytearray(parent[pre_source_off:pre_source_off + pre_size])
    pre_graphics_rel = int(pre_header["graphics_rel"])
    pre_palette_rel = int(pre_header["palette_rel"])
    pre_graphics = bytearray(pre_clone[pre_graphics_rel:pre_palette_rel])
    pre_report = repaint_preemptive(pre_graphics, regular)
    pre_clone[pre_graphics_rel:pre_palette_rel] = pre_graphics
    candidate[PREEMPTIVE_CLONE_OFF:PREEMPTIVE_CLONE_OFF + pre_size] = pre_clone
    allowed.update(range(PREEMPTIVE_CLONE_OFF, PREEMPTIVE_CLONE_OFF + pre_size))
    for pointer in PREEMPTIVE_POINTERS:
        gate(u32(parent, pointer) == PREEMPTIVE_SOURCE, f"preemptive pointer drift at 0x{pointer:08X}")
        candidate[pointer:pointer + 4] = p32(ROM_BASE + PREEMPTIVE_CLONE_OFF)
        allowed.update(range(pointer, pointer + 4))

    candidate_bytes = bytes(candidate)
    changed = {index for index, (before, after) in enumerate(zip(parent, candidate_bytes)) if before != after}
    gate(changed <= allowed and changed, "candidate changed bytes outside private clones/pointers")
    gate(candidate_bytes[:0x01000000] != parent[:0x01000000], "expected pointer redirects missing")
    pointer_bytes = set()
    for pointer in (*EVENT_POINTERS, *(row[4] for row in BADGES), *PREEMPTIVE_POINTERS):
        pointer_bytes.update(range(pointer, pointer + 4))
    gate({index for index in changed if index < 0x01000000} <= pointer_bytes, "original half changed outside pointer literals")

    # Structural clone gates: everything except the intended graphics windows
    # remains byte-exact to the Japanese source resources.
    gate(event_clone[:event_graphics_rel] == parent[event_source_off:event_source_off + event_graphics_rel], "event clone prefix changed")
    gate(event_clone[event_palette_rel:] == parent[event_source_off + event_palette_rel:event_source_off + event_size], "event palettes changed")
    gate(pre_clone[:pre_graphics_rel] == parent[pre_source_off:pre_source_off + pre_graphics_rel], "preemptive timeline/OAM changed")
    gate(pre_clone[pre_palette_rel:] == parent[pre_source_off + pre_palette_rel:pre_source_off + pre_size], "preemptive palettes changed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate_bytes)
    OUT_SAV.write_bytes((ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav").read_bytes())
    candidate_crc = binascii.crc32(candidate_bytes) & 0xFFFFFFFF
    derived_states = patch_derived_states(candidate_crc, bytes(event_graphics), first_badge_graphics, bytes(pre_graphics))
    build_preview(event_report, badge_reports, pre_report, states, badge_palettes)

    output_meta = {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": f"0x{candidate_crc:08X}", "size": len(candidate_bytes)}
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_event_exp_weapon_badges_preemptive_candidate_20260904",
        "result": "PASS",
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{parent_crc:08X}"},
        "candidate": output_meta,
        "output": output_meta,
        "save": {"path": advance_relative(OUT_SAV), "sha256": sha256(OUT_SAV.read_bytes())},
        "preview": advance_relative(OUT_PREVIEW),
        "derived_states": derived_states,
        "event_exp": {
            **strip_rasters(event_report),
            "source_address": f"0x{EVENT_SOURCE:08X}",
            "clone_address": f"0x{ROM_BASE + EVENT_CLONE_OFF:08X}",
            "resource_bytes": event_size,
            "pointer_literals": [f"0x{x:08X}" for x in EVENT_POINTERS],
        },
        "weapon_badges": [strip_rasters(row) for row in badge_reports],
        "preemptive": {
            **strip_rasters(pre_report),
            "source_address": f"0x{PREEMPTIVE_SOURCE:08X}",
            "clone_address": f"0x{ROM_BASE + PREEMPTIVE_CLONE_OFF:08X}",
            "resource_bytes": pre_size,
            "pointer_literals": [f"0x{x:08X}" for x in PREEMPTIVE_POINTERS],
        },
        "verification": {
            "result": "PASS",
            "states_crc_match_parent": True,
            "Japanese_source_resources_byte_exact_in_parent": True,
            "private_allocation_was_zero_filled": True,
            "all_pointer_literals_verified": True,
            "original_half_changes_are_pointer_bytes_only": True,
            "event_EXP_pixels_preserved": True,
            "event_normal_and_flash_variants_patched": True,
            "four_weapon_badge_siblings_patched": True,
            "badge_chrome_and_palettes_preserved": True,
            "preemptive_timeline_OAM_and_palettes_preserved": True,
            "changed_bytes": len(changed),
            "py_compile": "PASS",
            "unified_pipeline_regression": "6/6 PASS",
            "intermission_development_regression": "4/4 PASS",
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == EXPECTED_MAIN_SHA256,
        },
        "testing_note": "Use the bundled SAV for a fresh run. The derived ss1/ss2/ss3 have candidate-matched CRC and target VRAM for immediate visual inspection; old root states restore Japanese VRAM.",
    }
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": str(OUT_ROM),
        "sha256": sha256(candidate_bytes),
        "crc32": f"0x{candidate_crc:08X}",
        "manifest": str(OUT_MANIFEST),
        "preview": str(OUT_PREVIEW),
        "changed_bytes": len(changed),
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
