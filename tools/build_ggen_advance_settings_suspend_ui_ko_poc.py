#!/usr/bin/env python3
"""Build a Korean POC for the map Settings screen and Suspend warning popup.

The approved main TIP already contains the situation-menu follow-up.  This
builder adds only two UI families proven by
``analyze_ggen_advance_settings_suspend_ui.py``:

* Settings: clone the 30x20 fixed-label BG resource 0x08C70DF0, repaint only
  the Japanese fixed-label strips with Galmuri11 12x12 glyphs, and redirect the
  Settings-only literal at 0x08021050.  Dynamic ON/OFF, speed buttons, and the
  already-translated footer are untouched.
* Suspend: clone the shared sprite resource 0x08C7504C, rebuild animation 11's
  144x32 warning-message plane, and redirect only the Suspend consumer literal
  at 0x08020B98.  Other four consumers of the shared original resource remain
  byte-exact and continue to use 0x08C7504C.

Both clones live in zero-filled expansion space.  The original ROM resources,
Thumb code, palettes, and unrelated UI are not rewritten in place.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as analysis  # noqa: E402
import build_ggen_advance_map_menu_ui_ko_poc as tileops  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM  # noqa: E402

ROM_BASE = 0x08000000
EXPECTED_JP_SHA256 = analysis.EXPECTED_JP_SHA256
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_settings_suspend_ui"
OUT = OUT_DIR / "ggen_advance_settings_suspend_ui_ko_followup_candidate_20260830.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_settings_suspend_ui_ko_followup_20260830.json"
SETTINGS_PREVIEW = OUT_DIR / "ggen_advance_settings_ui_ko_followup_preview_20260830.png"
SUSPEND_PREVIEW = OUT_DIR / "ggen_advance_suspend_warning_ko_followup_preview_20260830.png"

# The approved main TIP currently has one continuous zero run from 0x01261C6C
# through the end of the graphics region and beyond.  Keep the POC allocations
# explicit so any future main-TIP growth fails closed instead of overlapping.
SETTINGS_CLONE_OFFSET = 0x01270000
SUSPEND_CLONE_OFFSET = 0x01274000

SETTINGS_FACE = 10
SETTINGS_CONTOUR = 5
SETTINGS_BACKGROUND = 11
SETTINGS_SOURCE_GLYPH_INDICES = {SETTINGS_FACE, SETTINGS_CONTOUR}
# 0x08020F6A supplies tile base 0xC9 for the fixed foreground.  The dynamic
# option compositor starts at tile base 0x191.  Therefore the fixed resource
# may occupy at most 0x191-0xC9 == 200 decoded tiles.  The first candidate
# expanded to 269 tiles and overwrote the ON/OFF / 1..4 graphics in VRAM.
SETTINGS_RUNTIME_TILE_BASE = 0x00C9
SETTINGS_OPTION_TILE_BASE = 0x0191
SETTINGS_MAX_DECODED_TILES = SETTINGS_OPTION_TILE_BASE - SETTINGS_RUNTIME_TILE_BASE

# Runtime screenshot/palette correlation for the suspend popup: the warning
# message uses the warm system-message palette family.  We rebuild only the
# inner text plane while keeping the outer two rows and edge pixels native.
# Correct source-map reconstruction shows the warning uses palette index 11
# for the light glyph face, index 2 for the dark-brown contour, and 9/10 for
# the yellow panel fill.  The first candidate sampled the wrong source tiles
# and therefore inferred the wrong palette roles.
SUSPEND_INK = 11
SUSPEND_CONTOUR = 2
SUSPEND_BACKGROUND_CANDIDATES = {9, 10}

SETTINGS_TRANSLATIONS = {
    "各種設定を行います": "각종 설정을 합니다",
    "攻撃方法の確認": "공격방법 확인",
    "メッセージの自動送り": "메시지 자동 진행",
    "メッセージ表示速度": "메시지 표시속도",
    "早い": "빠름",
    "遅い": "느림",
}
SUSPEND_LINES = ("중단 처리 중입니다", "전원을 끄지 마세요")


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def pack_u32(value: int) -> bytes:
    return struct.pack("<I", value)


def literal_only_lzss_body(decoded: bytes) -> bytes:
    body = bytearray()
    for start in range(0, len(decoded), 8):
        chunk = decoded[start : start + 8]
        body.append((1 << len(chunk)) - 1)
        body.extend(chunk)
    gate(len(body) <= 0xFFFF, "settings cloned tile stream exceeds 16-bit length")
    return bytes(body)


def stitch_variable(atlas: bytes | bytearray, tile_rows: list[list[int]]) -> list[list[int]]:
    rows = len(tile_rows)
    cols = len(tile_rows[0])
    gate(rows > 0 and cols > 0 and all(len(row) == cols for row in tile_rows), "invalid tile rectangle")
    pixels = [[0] * (cols * 8) for _ in range(rows * 8)]
    for ty, row in enumerate(tile_rows):
        for tx, tile_id in enumerate(row):
            tile = tileops.decode_tile(atlas, tile_id)
            for yy in range(8):
                pixels[ty * 8 + yy][tx * 8 : tx * 8 + 8] = tile[yy]
    return pixels


def write_variable(atlas: bytearray, tile_rows: list[list[int]], pixels: list[list[int]]) -> None:
    rows = len(tile_rows)
    cols = len(tile_rows[0])
    gate(len(pixels) == rows * 8 and all(len(row) == cols * 8 for row in pixels), "pixel/tile rectangle mismatch")
    for ty, row in enumerate(tile_rows):
        for tx, tile_id in enumerate(row):
            tile = [pixels[ty * 8 + yy][tx * 8 : tx * 8 + 8] for yy in range(8)]
            start = tile_id * 32
            gate(start + 32 <= len(atlas), f"settings tile 0x{tile_id:03X} outside atlas")
            atlas[start : start + 32] = tileops.encode_tile(tile)


def detach_map_rect(atlas: bytearray, resource: dict[str, Any], rect: tuple[int, int, int, int]) -> dict[str, Any]:
    """Give one fixed-label rectangle private atlas tiles inside the clone.

    The original settings foreground intentionally shares prefix tiles between
    ``メッセージの自動送り`` and ``メッセージ表示速度``.  Repainting those
    source IDs in place would make one translated row overwrite the other.
    Every target rectangle therefore gets fresh clone-local tiles and only its
    map cells are remapped; all non-target cells keep their original IDs.
    """
    x, y, w, h = rect
    map_width = int(resource["width"])
    cells = resource["cells"]
    source_ids = analysis.map_rect(resource, x, y, w, h)
    new_ids: list[list[int]] = []
    for yy in range(h):
        row: list[int] = []
        for xx in range(w):
            source_id = source_ids[yy][xx]
            source_start = source_id * 32
            gate(source_start + 32 <= len(atlas), f"settings source tile 0x{source_id:03X} outside atlas")
            new_id = len(atlas) // 32
            gate(new_id < 0x400, "settings detached tile exceeds 10-bit tilemap ID")
            atlas.extend(atlas[source_start : source_start + 32])
            index = (y + yy) * map_width + x + xx
            original_cell = int(cells[index])
            cells[index] = (original_cell & ~0x03FF) | new_id
            row.append(new_id)
        new_ids.append(row)
    return {
        "source_tile_ids": [[f"0x{value:03X}" for value in row] for row in source_ids],
        "new_tile_ids": [[f"0x{value:03X}" for value in row] for row in new_ids],
        "new_tile_first": f"0x{new_ids[0][0]:03X}",
        "new_tile_count": w * h,
    }


def make_text_mask(text: str, font: fontpair.BdfFont, width: int, height: int, *, cell_width: int = 12, space_width: int = 4, y_origin: int | None = None) -> tuple[list[list[bool]], int]:
    parts: list[tuple[Image.Image | None, int]] = []
    for char in text:
        if char == " ":
            parts.append((None, space_width))
        else:
            parts.append((fontpair.render_12x12_basic(char, font), cell_width))
    text_width = sum(part_width for _glyph, part_width in parts)
    gate(text_width <= width - 2, f"text does not fit {width}px region: {text!r} ({text_width}px)")
    x_cursor = (width - text_width) // 2
    if y_origin is None:
        y_origin = (height - 12) // 2
    gate(0 <= y_origin and y_origin + 12 <= height, f"invalid text Y origin for {text!r}")
    mask = [[False] * width for _ in range(height)]
    for glyph, part_width in parts:
        if glyph is not None:
            for y in range(12):
                for x in range(12):
                    if glyph.getpixel((x, y)):
                        mask[y_origin + y][x_cursor + x] = True
        x_cursor += part_width
    return mask, text_width


def paint_mask(pixels: list[list[int]], mask: list[list[bool]], *, ink: int, contour: int, clip: tuple[int, int, int, int] | None = None) -> tuple[int, int]:
    height = len(pixels)
    width = len(pixels[0])
    gate(len(mask) == height and all(len(row) == width for row in mask), "mask dimensions drift")
    if clip is None:
        x0, y0, x1, y1 = 0, 0, width, height
    else:
        x0, y0, x1, y1 = clip
    outline = [[False] * width for _ in range(height)]
    for y in range(y0, y1):
        for x in range(x0, x1):
            if not mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ox, oy = x + dx, y + dy
                    if not (dx or dy):
                        continue
                    if x0 <= ox < x1 and y0 <= oy < y1 and not mask[oy][ox]:
                        outline[oy][ox] = True
    contour_pixels = 0
    ink_pixels = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if outline[y][x]:
                pixels[y][x] = contour
                contour_pixels += 1
            if mask[y][x]:
                pixels[y][x] = ink
                ink_pixels += 1
    return ink_pixels, contour_pixels


def rectangle_map_indices(resource: dict[str, Any], rect: tuple[int, int, int, int]) -> list[int]:
    x, y, w, h = rect
    map_width = int(resource["width"])
    return [(y + yy) * map_width + x + xx for yy in range(h) for xx in range(w)]


def tile_payloads_from_pixels(pixels: list[list[int]], width_tiles: int, height_tiles: int) -> list[bytes]:
    gate(len(pixels) == height_tiles * 8 and all(len(row) == width_tiles * 8 for row in pixels), "settings rendered strip dimensions drift")
    payloads: list[bytes] = []
    for ty in range(height_tiles):
        for tx in range(width_tiles):
            tile = [pixels[ty * 8 + yy][tx * 8 : tx * 8 + 8] for yy in range(8)]
            payloads.append(tileops.encode_tile(tile))
    return payloads


def patch_settings_strip(
    atlas: bytes,
    resource: dict[str, Any],
    rect: tuple[int, int, int, int],
    text: str,
    font: fontpair.BdfFont,
) -> tuple[dict[str, Any], dict[int, bytes]]:
    """Render one strip without mutating the shared source atlas.

    The final map/tile allocation is deferred until all four strips have been
    rendered.  This lets shared source tiles diverge safely while reusing the
    original 131-slot budget wherever possible.
    """
    x, y, w, h = rect
    tile_rows = analysis.map_rect(resource, x, y, w, h)
    pixels = stitch_variable(atlas, tile_rows)
    gate(len(pixels) == 16, "settings fixed strip must be 16px high")
    cleared = 0
    for yy in range(16):
        for xx in range(w * 8):
            if pixels[yy][xx] in SETTINGS_SOURCE_GLYPH_INDICES:
                pixels[yy][xx] = SETTINGS_BACKGROUND
                cleared += 1
    gate(cleared > 0, f"settings source glyph pixels not found for {text!r}")
    mask, text_width = make_text_mask(text, font, w * 8, 16)
    ink_pixels, contour_pixels = paint_mask(pixels, mask, ink=SETTINGS_FACE, contour=SETTINGS_CONTOUR)
    payloads = tile_payloads_from_pixels(pixels, w, h)
    indices = rectangle_map_indices(resource, rect)
    desired = dict(zip(indices, payloads))
    return ({
        "translation": text,
        "map_xy": [x, y],
        "size_tiles": [w, h],
        "source_glyph_pixels_cleared": cleared,
        "text_width_px": text_width,
        "korean_ink_pixels": ink_pixels,
        "korean_contour_pixels": contour_pixels,
    }, desired)


def patch_settings_speed_strip(atlas: bytes, resource: dict[str, Any], font: fontpair.BdfFont) -> tuple[dict[str, Any], dict[int, bytes]]:
    rect = (1, 13, 29, 2)
    x, y, w, h = rect
    tile_rows = analysis.map_rect(resource, x, y, w, h)
    pixels = stitch_variable(atlas, tile_rows)
    gate(len(pixels) == 16 and len(pixels[0]) == 232, "settings speed strip dimensions drift")

    # Measured from the original strip's source-glyph X projection.  Leave the
    # center speed-button zone 139..197 completely native; those buttons are
    # separately managed by the six-record option compositor.
    regions = [
        (0, 106, SETTINGS_TRANSLATIONS["メッセージ表示速度"]),
        (108, 139, SETTINGS_TRANSLATIONS["早い"]),
        (198, 230, SETTINGS_TRANSLATIONS["遅い"]),
    ]
    reports: list[dict[str, Any]] = []
    for x0, x1, text in regions:
        cleared = 0
        for yy in range(16):
            for xx in range(x0, x1):
                if pixels[yy][xx] in SETTINGS_SOURCE_GLYPH_INDICES:
                    pixels[yy][xx] = SETTINGS_BACKGROUND
                    cleared += 1
        gate(cleared > 0, f"speed-row source glyph pixels not found for {text!r}")
        local_width = x1 - x0
        local_mask, text_width = make_text_mask(text, font, local_width, 16)
        full_mask = [[False] * 232 for _ in range(16)]
        for yy in range(16):
            for xx in range(local_width):
                if local_mask[yy][xx]:
                    full_mask[yy][x0 + xx] = True
        ink_pixels, contour_pixels = paint_mask(
            pixels,
            full_mask,
            ink=SETTINGS_FACE,
            contour=SETTINGS_CONTOUR,
            clip=(x0, 0, x1, 16),
        )
        reports.append({
            "translation": text,
            "pixel_x_range": [x0, x1],
            "source_glyph_pixels_cleared": cleared,
            "text_width_px": text_width,
            "korean_ink_pixels": ink_pixels,
            "korean_contour_pixels": contour_pixels,
        })

    payloads = tile_payloads_from_pixels(pixels, w, h)
    indices = rectangle_map_indices(resource, rect)
    desired = dict(zip(indices, payloads))
    return ({
        "map_xy": [x, y],
        "size_tiles": [w, h],
        "button_preserve_x_range": [139, 198],
        "regions": reports,
    }, desired)


def materialize_settings_tiles(
    original_atlas: bytes,
    resource: dict[str, Any],
    desired_by_map_index: dict[int, bytes],
) -> tuple[bytes, dict[str, Any]]:
    """Assign rendered variants without crossing the dynamic-option VRAM base.

    A tile slot referenced outside the four translated rectangles is immutable.
    Slots referenced only by translated cells (plus unused original slots) are
    safe scratch slots because every translated map cell is remapped below.
    Only if those 131 original slots are insufficient do we append deduplicated
    private variants, with a hard runtime cap of 200 decoded tiles.
    """
    gate(len(original_atlas) % 32 == 0, "settings atlas is not tile aligned")
    original_tile_count = len(original_atlas) // 32
    gate(original_tile_count == 131, "settings original atlas tile count drift")
    cells = resource["cells"]
    target_indices = set(desired_by_map_index)
    gate(len(target_indices) == 138, f"settings translated map-cell count drift: {len(target_indices)}")

    uses: dict[int, set[int]] = {tile_id: set() for tile_id in range(original_tile_count)}
    for map_index, cell in enumerate(cells):
        tile_id = int(cell) & 0x03FF
        if tile_id < original_tile_count:
            uses[tile_id].add(map_index)
    writable = [tile_id for tile_id in range(original_tile_count) if not uses[tile_id] or uses[tile_id] <= target_indices]
    immutable = [tile_id for tile_id in range(original_tile_count) if tile_id not in set(writable)]

    atlas = bytearray(original_atlas)
    payload_to_tile: dict[bytes, int] = {}
    # Immutable slots may always be reused by translated cells when their exact
    # pixel payload already matches; they are never rewritten.
    for tile_id in immutable:
        payload = original_atlas[tile_id * 32 : tile_id * 32 + 32]
        payload_to_tile.setdefault(payload, tile_id)

    writable_iter = iter(writable)
    rewritten_original_slots: list[int] = []
    appended_slots: list[int] = []
    assigned: dict[int, int] = {}
    for map_index in sorted(target_indices):
        payload = desired_by_map_index[map_index]
        tile_id = payload_to_tile.get(payload)
        if tile_id is None:
            try:
                tile_id = next(writable_iter)
                atlas[tile_id * 32 : tile_id * 32 + 32] = payload
                rewritten_original_slots.append(tile_id)
            except StopIteration:
                tile_id = len(atlas) // 32
                gate(tile_id < SETTINGS_MAX_DECODED_TILES, "settings rendered variants collide with dynamic option VRAM tile base")
                atlas.extend(payload)
                appended_slots.append(tile_id)
            payload_to_tile[payload] = tile_id
        assigned[map_index] = tile_id

    for map_index, tile_id in assigned.items():
        cells[map_index] = (int(cells[map_index]) & ~0x03FF) | tile_id

    decoded_tiles = len(atlas) // 32
    gate(decoded_tiles <= SETTINGS_MAX_DECODED_TILES, "settings atlas crosses dynamic option tile base")
    gate(SETTINGS_RUNTIME_TILE_BASE + decoded_tiles <= SETTINGS_OPTION_TILE_BASE, "settings runtime VRAM range overlaps ON/OFF compositor")
    # Non-target map cells must remain byte-exact, and none may reference a
    # rewritten scratch slot.
    rewritten_set = set(rewritten_original_slots)
    gate(all((int(cells[i]) & 0x03FF) not in rewritten_set for i in range(len(cells)) if i not in target_indices), "settings scratch slot leaked into non-target map cells")
    return bytes(atlas), {
        "original_tiles": original_tile_count,
        "decoded_tiles": decoded_tiles,
        "runtime_tile_base": SETTINGS_RUNTIME_TILE_BASE,
        "runtime_tile_end_exclusive": SETTINGS_RUNTIME_TILE_BASE + decoded_tiles,
        "dynamic_option_tile_base": SETTINGS_OPTION_TILE_BASE,
        "max_decoded_tiles_before_collision": SETTINGS_MAX_DECODED_TILES,
        "target_map_cells": len(target_indices),
        "writable_original_slots": len(writable),
        "rewritten_original_slots": rewritten_original_slots,
        "appended_slots": appended_slots,
        "unique_rendered_payloads": len({desired_by_map_index[i] for i in target_indices}),
    }


def build_settings_clone(jp: bytes, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], bytes, bytes]:
    resource = analysis.parse_bg_resource(jp, analysis.SETTINGS_FOREGROUND)
    offset = int(resource["file_offset"])
    tiles_rel = int(resource["tiles_relative_offset"])
    comp_len = int(resource["compressed_tile_length"])
    palette_rel = int(resource["palette_relative_offset"])
    palette_len = int(resource["palette_length"])
    map_rel = int(resource["map_relative_offset"])
    map_len = int(resource["map_length"])

    original_comp = jp[offset + tiles_rel : offset + tiles_rel + comp_len]
    original_atlas = analysis.custom_lzss_decompress(original_comp)

    reports: dict[str, Any] = {}
    desired: dict[int, bytes] = {}
    reports["title"], part = patch_settings_strip(
        original_atlas,
        resource,
        (8, 1, 14, 2),
        SETTINGS_TRANSLATIONS["各種設定を行います"],
        font,
    )
    desired.update(part)
    reports["attack_method"], part = patch_settings_strip(
        original_atlas,
        resource,
        (6, 5, 12, 2),
        SETTINGS_TRANSLATIONS["攻撃方法の確認"],
        font,
    )
    desired.update(part)
    reports["auto_message"], part = patch_settings_strip(
        original_atlas,
        resource,
        (4, 9, 14, 2),
        SETTINGS_TRANSLATIONS["メッセージの自動送り"],
        font,
    )
    desired.update(part)
    reports["message_speed"], part = patch_settings_speed_strip(original_atlas, resource, font)
    desired.update(part)
    gate(len(desired) == 138, f"settings desired map-cell union drift: {len(desired)}")

    atlas, allocation = materialize_settings_tiles(original_atlas, resource, desired)
    reports["allocation"] = allocation
    # Record the final remapped IDs only after the global variant allocator has
    # resolved all cross-strip sharing.
    for key, rect in (
        ("title", (8, 1, 14, 2)),
        ("attack_method", (6, 5, 12, 2)),
        ("auto_message", (4, 9, 14, 2)),
        ("message_speed", (1, 13, 29, 2)),
    ):
        reports[key]["tile_ids"] = [[f"0x{value:03X}" for value in row] for row in analysis.map_rect(resource, *rect)]

    compressed = literal_only_lzss_body(atlas)
    gate(analysis.custom_lzss_decompress(compressed) == atlas, "settings clone LZSS round-trip failed")

    header = bytearray(jp[offset : offset + 16])
    map_payload = struct.pack(f"<{len(resource['cells'])}H", *resource["cells"])
    gate(len(map_payload) == map_len, "settings cloned map payload length drift")
    palette_payload = jp[offset + palette_rel : offset + palette_rel + palette_len]
    new_map_rel = 0x10
    new_tiles_rel = new_map_rel + len(map_payload)
    gate(new_tiles_rel == 0x4C0, "settings clone map layout drift")
    new_palette_rel = (new_tiles_rel + len(compressed) + 3) & ~3
    clone = bytearray(new_palette_rel + len(palette_payload))
    clone[:16] = header
    struct.pack_into(
        "<HHHHHH",
        clone,
        4,
        new_map_rel,
        len(map_payload),
        new_tiles_rel,
        len(compressed),
        new_palette_rel,
        len(palette_payload),
    )
    clone[new_map_rel : new_map_rel + len(map_payload)] = map_payload
    clone[new_tiles_rel : new_tiles_rel + len(compressed)] = compressed
    clone[new_palette_rel : new_palette_rel + len(palette_payload)] = palette_payload
    return bytes(clone), reports, original_atlas, atlas


def suspend_text_layout(jp: bytes) -> tuple[list[dict[str, Any]], int]:
    """Return every animation-11 OBJ that composes the 144x48 text panel.

    The first candidate assumed only destination OBJ tiles 66..137 (objects
    9..11) formed a 144x32 message plane.  Real-hardware evidence plus the OAM
    geometry shows the lower 16 pixels are separate objects 2..6 at y=8.  The
    complete text field is therefore 144x48: top objects 9..11 and bottom
    objects 2..6.  OAM attr2 remains a destination-VRAM index; source graphics
    come from the u16 lookup table after the OAM list.
    """
    resource_offset = analysis.SUSPEND_RESOURCE - ROM_BASE
    _graphics_rel, records = analysis.animation_records(jp, analysis.SUSPEND_RESOURCE)
    record_start, record = records[analysis.SUSPEND_ANIMATION]
    parsed = analysis.parse_animation_oam(record)
    source = analysis.parse_animation_source_tiles(record, parsed)
    target_indices = (2, 3, 4, 5, 6, 9, 10, 11)
    entry_offsets: list[int] = []
    cursor = 0
    for obj in parsed["objects"]:
        entry_offsets.append(cursor)
        cursor += int(obj["tile_count"])
    parts: list[dict[str, Any]] = []
    for index in target_indices:
        obj = parsed["objects"][index]
        source_ids = source["by_object"][index]
        parts.append({
            "object": obj,
            "source_ids": source_ids[:],
            "source_entry_offset": entry_offsets[index],
        })
    min_x = min(int(part["object"]["x"]) for part in parts)
    min_y = min(int(part["object"]["y"]) for part in parts)
    max_x = max(int(part["object"]["x"]) + int(part["object"]["size_px"][0]) for part in parts)
    max_y = max(int(part["object"]["y"]) + int(part["object"]["size_px"][1]) for part in parts)
    gate((min_x, min_y, max_x, max_y) == (-60, -24, 84, 24), "suspend 144x48 text-panel geometry drift")
    # Unique Japanese text source runs that prove the source lookup is parsed
    # rather than confusing destination OAM tile numbers for ROM graphics.
    gate(source["by_object"][3][:4] == list(range(0xD5, 0xD9)), "suspend lower-left source run drift")
    gate(source["by_object"][4][:4] == list(range(0xD9, 0xDD)), "suspend lower-middle source run drift")
    gate(source["by_object"][5][:4] == list(range(0xDD, 0xE1)), "suspend lower-right source run drift")
    gate(source["by_object"][6][:4] == list(range(0xE1, 0xE5)), "suspend lower-tail source run drift")
    gate(source["by_object"][9][8:24] == list(range(0xE5, 0xF5)), "suspend upper source run E5-F4 drift")
    gate(source["by_object"][10][8:24] == list(range(0xF5, 0x105)), "suspend upper source run F5-104 drift")
    gate(0x105 in source["by_object"][11], "suspend source graphic 0x105 missing")
    record_rel = record_start - resource_offset
    source_table_rel = record_rel + int(source["source_table_offset"])
    return parts, source_table_rel


def stitch_suspend_text_plane(atlas: bytes | bytearray, parts: list[dict[str, Any]]) -> list[list[int]]:
    objects = [part["object"] for part in parts]
    min_x = min(int(obj["x"]) for obj in objects)
    min_y = min(int(obj["y"]) for obj in objects)
    max_x = max(int(obj["x"]) + int(obj["size_px"][0]) for obj in objects)
    max_y = max(int(obj["y"]) + int(obj["size_px"][1]) for obj in objects)
    gate((max_x - min_x, max_y - min_y) == (144, 48), "suspend text plane geometry drift")
    canvas = [[0] * 144 for _ in range(48)]
    for part in parts:
        obj = part["object"]
        source_ids = part["source_ids"]
        width_tiles = int(obj["size_px"][0]) // 8
        height_tiles = int(obj["size_px"][1]) // 8
        gate(len(source_ids) == width_tiles * height_tiles, "suspend source-map tile count mismatch")
        for ty in range(height_tiles):
            for tx in range(width_tiles):
                tile_id = int(source_ids[ty * width_tiles + tx])
                tile = tileops.decode_tile(atlas, tile_id)
                ox = int(obj["x"]) - min_x + tx * 8
                oy = int(obj["y"]) - min_y + ty * 8
                for yy in range(8):
                    canvas[oy + yy][ox : ox + 8] = tile[yy]
    return canvas


def materialize_suspend_private_source_tiles(
    original_graphics: bytes,
    parts: list[dict[str, Any]],
    patched_plane: list[list[int]],
) -> tuple[bytes, list[dict[str, Any]], dict[str, Any]]:
    """Append private source tiles and remap only animation-11 lookup entries.

    No original source graphic tile is rewritten.  This is stronger than the
    first candidate: post-operation animation 5 and every other animation in
    the cloned bank remain byte-exact even if they share original source IDs.
    """
    gate(len(original_graphics) % 32 == 0, "suspend source graphics not tile aligned")
    original_tile_count = len(original_graphics) // 32
    gate(original_tile_count == 262, "suspend original source graphic count drift")
    gate(len(patched_plane) == 48 and all(len(row) == 144 for row in patched_plane), "invalid suspend patched plane")
    objects = [part["object"] for part in parts]
    min_x = min(int(obj["x"]) for obj in objects)
    min_y = min(int(obj["y"]) for obj in objects)

    existing_payload_to_id: dict[bytes, int] = {}
    for tile_id in range(original_tile_count):
        payload = original_graphics[tile_id * 32 : tile_id * 32 + 32]
        existing_payload_to_id.setdefault(payload, tile_id)
    private_payload_to_id: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    remapped_parts: list[dict[str, Any]] = []
    changed_entries = 0

    for part in parts:
        obj = part["object"]
        source_ids = list(part["source_ids"])
        remapped_ids = source_ids[:]
        width_tiles = int(obj["size_px"][0]) // 8
        height_tiles = int(obj["size_px"][1]) // 8
        for ty in range(height_tiles):
            for tx in range(width_tiles):
                position = ty * width_tiles + tx
                ox = int(obj["x"]) - min_x + tx * 8
                oy = int(obj["y"]) - min_y + ty * 8
                tile = [patched_plane[oy + yy][ox : ox + 8] for yy in range(8)]
                payload = tileops.encode_tile(tile)
                source_id = int(source_ids[position])
                source_payload = original_graphics[source_id * 32 : source_id * 32 + 32]
                if payload == source_payload:
                    new_id = source_id
                elif payload in existing_payload_to_id:
                    new_id = existing_payload_to_id[payload]
                else:
                    new_id = private_payload_to_id.get(payload, -1)
                    if new_id < 0:
                        new_id = original_tile_count + len(private_payloads)
                        gate(new_id <= 0xFFFF, "suspend private source tile ID overflow")
                        private_payload_to_id[payload] = new_id
                        private_payloads.append(payload)
                if new_id != source_id:
                    changed_entries += 1
                remapped_ids[position] = new_id
        remapped_parts.append({
            "object": obj,
            "source_ids": source_ids,
            "remapped_source_ids": remapped_ids,
            "source_entry_offset": int(part["source_entry_offset"]),
        })

    graphics = original_graphics + b"".join(private_payloads)
    return graphics, remapped_parts, {
        "original_source_tiles": original_tile_count,
        "private_source_tiles_appended": len(private_payloads),
        "source_tiles_after_append": len(graphics) // 32,
        "animation_11_text_source_entries": sum(len(part["source_ids"]) for part in parts),
        "source_lookup_entries_changed": changed_entries,
        "private_source_id_first": original_tile_count if private_payloads else None,
        "private_source_id_last": original_tile_count + len(private_payloads) - 1 if private_payloads else None,
    }


def rebuild_suspend_plane(source: list[list[int]], font: fontpair.BdfFont) -> tuple[list[list[int]], dict[str, Any]]:
    gate(len(source) == 48 and all(len(row) == 144 for row in source), "suspend source plane must be 144x48")
    pixels = [row[:] for row in source]
    # Correct source reconstruction reveals a native 9px top border, two 14px
    # text bands at y=9..22 and y=25..38, and a bottom border below them.  Clear
    # only those bands, keep the right 4px edge native, and recover each row's
    # yellow fill from palette indices 9/10.  This preserves the warning frame
    # and avoids the first candidate's full-plane flattening.
    bands = ((9, 23), (25, 39))
    row_backgrounds: list[dict[str, int]] = []
    cleared = 0
    for y0, y1 in bands:
        for y in range(y0, y1):
            candidates = [pixels[y][x] for x in range(2, 140) if pixels[y][x] in SUSPEND_BACKGROUND_CANDIDATES]
            gate(candidates, f"no suspend panel background sample on scanline {y}")
            background = Counter(candidates).most_common(1)[0][0]
            row_backgrounds.append({"y": y, "index": background})
            for x in range(2, 140):
                if pixels[y][x] != background:
                    cleared += 1
                pixels[y][x] = background
    gate(cleared > 0, "suspend message-band clear did not change pixels")

    line_reports: list[dict[str, Any]] = []
    for text, y_origin in zip(SUSPEND_LINES, (10, 26)):
        mask, text_width = make_text_mask(text, font, 144, 48, y_origin=y_origin)
        ink_pixels, contour_pixels = paint_mask(
            pixels,
            mask,
            ink=SUSPEND_INK,
            contour=SUSPEND_CONTOUR,
            clip=(2, 9, 140, 39),
        )
        line_reports.append({
            "translation": text,
            "y_origin": y_origin,
            "text_width_px": text_width,
            "korean_ink_pixels": ink_pixels,
            "korean_contour_pixels": contour_pixels,
        })

    return pixels, {
        "clear_mode": "two_native_text_bands_y9_22_y25_38_preserve_top_bottom_and_right_edge",
        "source_pixels_replaced": cleared,
        "row_background_indices": row_backgrounds,
        "ink_index": SUSPEND_INK,
        "contour_index": SUSPEND_CONTOUR,
        "lines": line_reports,
    }


def build_suspend_clone(jp: bytes, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], list[list[int]], list[list[int]]]:
    resource_offset = analysis.SUSPEND_RESOURCE - ROM_BASE
    palette_count = u32(jp, resource_offset + 0x04)
    graphics_rel = u32(jp, resource_offset + 0x08)
    palette_rel = u32(jp, resource_offset + 0x0C)
    gate(palette_count == 6 and graphics_rel == 0x0E04 and palette_rel == 0x2EC4, "suspend resource header drift")
    original_resource_size = palette_rel + palette_count * 32
    original = jp[resource_offset : resource_offset + original_resource_size]
    gate(len(original) == original_resource_size, "suspend clone source truncated")

    original_graphics = original[graphics_rel:palette_rel]
    palette = original[palette_rel : palette_rel + palette_count * 32]
    parts, source_table_rel = suspend_text_layout(jp)
    original_plane = stitch_suspend_text_plane(original_graphics, parts)
    patched_plane, report = rebuild_suspend_plane(original_plane, font)
    graphics, remapped_parts, source_report = materialize_suspend_private_source_tiles(
        original_graphics,
        parts,
        patched_plane,
    )

    # Rebuild the clone with a larger graphics span.  Animation/frame data are
    # copied byte-exact, except the source-lookup entries for the eight objects
    # that make the 144x48 text field.  The intervening right-edge objects 7/8
    # keep their native source lookups.
    new_palette_rel = graphics_rel + len(graphics)
    clone = bytearray(new_palette_rel + len(palette))
    clone[:graphics_rel] = original[:graphics_rel]
    for part in remapped_parts:
        cursor = source_table_rel + int(part["source_entry_offset"]) * 2
        for source_id in part["remapped_source_ids"]:
            struct.pack_into("<H", clone, cursor, int(source_id))
            cursor += 2
    clone[graphics_rel:new_palette_rel] = graphics
    clone[new_palette_rel : new_palette_rel + len(palette)] = palette
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)

    # Only the palette-rel header field and the selected animation-11 source
    # lookup entries may differ before graphics.  OAM geometry stays native.
    expected_pre = bytearray(original[:graphics_rel])
    struct.pack_into("<I", expected_pre, 0x0C, new_palette_rel)
    for part in remapped_parts:
        cursor = source_table_rel + int(part["source_entry_offset"]) * 2
        for source_id in part["remapped_source_ids"]:
            struct.pack_into("<H", expected_pre, cursor, int(source_id))
            cursor += 2
    gate(clone[:graphics_rel] == expected_pre, "suspend clone pre-graphics bytes changed outside source lookup/header")
    gate(graphics[: len(original_graphics)] == original_graphics, "suspend clone rewrote original source graphics")
    gate(clone[new_palette_rel:] == palette, "suspend clone palette bytes changed")

    source_report.update({
        "old_palette_relative_offset": f"0x{palette_rel:04X}",
        "new_palette_relative_offset": f"0x{new_palette_rel:04X}",
        "source_table_relative_offset": f"0x{source_table_rel:04X}",
        "target_object_indices": [int(part["object"]["index"]) for part in remapped_parts],
        "destination_obj_tile_ranges": [[part["object"]["tile_start"], part["object"]["tile_end"]] for part in remapped_parts],
        "original_source_maps": [[f"0x{x:03X}" for x in part["source_ids"]] for part in remapped_parts],
        "remapped_source_maps": [[f"0x{x:03X}" for x in part["remapped_source_ids"]] for part in remapped_parts],
    })
    report.update({
        "resource_size": len(clone),
        "source_tile_materialization": source_report,
        "text_objects": [
            {
                "index": part["object"]["index"],
                "xy": [part["object"]["x"], part["object"]["y"]],
                "size_px": part["object"]["size_px"],
                "destination_tile_range": [part["object"]["tile_start"], part["object"]["tile_end"]],
                "source_entry_offset": part["source_entry_offset"],
            }
            for part in remapped_parts
        ],
    })
    return bytes(clone), report, original_plane, patched_plane


def build_settings_preview(before_atlas: bytes, after_atlas: bytes, jp: bytes, reports: dict[str, Any], path: Path) -> None:
    resource = analysis.parse_bg_resource(jp, analysis.SETTINGS_FOREGROUND)
    rowspecs = [
        ("title", (8, 1, 14, 2)),
        ("attack_method", (6, 5, 12, 2)),
        ("auto_message", (4, 9, 14, 2)),
        ("message_speed", (1, 13, 29, 2)),
    ]
    rows: list[tuple[list[list[int]], list[list[int]]]] = []
    for key, (x, y, w, h) in rowspecs:
        source_ids = analysis.map_rect(resource, x, y, w, h)
        patched_ids = [[int(value, 16) for value in row] for row in reports[key]["tile_ids"]]
        rows.append((stitch_variable(before_atlas, source_ids), stitch_variable(after_atlas, patched_ids)))
    scale = 3
    gap = 8
    width = max(len(p[0]) for pair in rows for p in pair)
    height = sum(32 * scale + gap for _ in rows) - gap
    image = Image.new("RGB", (width * scale, height), (0, 0, 0))
    # Symbolic palette: make background/face/contour hierarchy obvious.
    colors = {i: (i * 16, i * 16, i * 16) for i in range(16)}
    colors.update({5: (70, 35, 20), 10: (235, 205, 75), 11: (255, 245, 150)})
    y_cursor = 0
    for before, after in rows:
        for pixels in (before, after):
            tile = Image.new("RGB", (len(pixels[0]), len(pixels)))
            for yy, row in enumerate(pixels):
                for xx, value in enumerate(row):
                    tile.putpixel((xx, yy), colors[value])
            image.paste(tile.resize((tile.width * scale, tile.height * scale), Image.Resampling.NEAREST), (0, y_cursor))
            y_cursor += 16 * scale
        y_cursor += gap
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def build_suspend_preview(jp: bytes, before: list[list[int]], after: list[list[int]], path: Path) -> None:
    resource_offset = analysis.SUSPEND_RESOURCE - ROM_BASE
    palette_rel = u32(jp, resource_offset + 0x0C)
    # Correct source reconstruction + screenshot colors identify palette bank 0:
    # index 2 is the dark-brown contour and index 11 the light yellow face.
    palette_bank = 0
    palette_offset = resource_offset + palette_rel + palette_bank * 32
    palette = []
    for index in range(16):
        value = struct.unpack_from("<H", jp, palette_offset + index * 2)[0]
        r = (value & 31) * 255 // 31
        g = ((value >> 5) & 31) * 255 // 31
        b = ((value >> 10) & 31) * 255 // 31
        palette.append((r, g, b))
    scale = 4
    image = Image.new("RGB", (144 * scale, 96 * scale), (0, 0, 0))
    for row_index, pixels in enumerate((before, after)):
        tile = Image.new("RGB", (144, 48))
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                tile.putpixel((x, y), palette[value])
        image.paste(tile.resize((144 * scale, 48 * scale), Image.Resampling.NEAREST), (0, row_index * 48 * scale))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--settings-preview", type=Path, default=SETTINGS_PREVIEW)
    parser.add_argument("--suspend-preview", type=Path, default=SUSPEND_PREVIEW)
    args = parser.parse_args()

    main_bytes = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(len(main_bytes) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    manifest_main_hash = str(main_manifest.get("sha256", ""))
    gate(manifest_main_hash and sha256(main_bytes) == manifest_main_hash, f"main TIP/manifest hash drift: rom={sha256(main_bytes)} manifest={manifest_main_hash}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM hash drift: {sha256(jp)}")
    gate(u32(main_bytes, analysis.SETTINGS_RESOURCES[2]["literal"]) == analysis.SETTINGS_FOREGROUND, "settings literal already redirected")
    gate(u32(main_bytes, analysis.SUSPEND_RESOURCE_LITERAL) == analysis.SUSPEND_RESOURCE, "suspend literal already redirected")

    with ZipFile(args.font_zip) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    settings_clone, settings_report, settings_before, settings_after = build_settings_clone(jp, font)
    suspend_clone, suspend_report, suspend_before, suspend_after = build_suspend_clone(jp, font)

    candidate = bytearray(main_bytes)
    for offset, payload, name in (
        (SETTINGS_CLONE_OFFSET, settings_clone, "settings clone"),
        (SUSPEND_CLONE_OFFSET, suspend_clone, "suspend clone"),
    ):
        gate(candidate[offset : offset + len(payload)] == b"\x00" * len(payload), f"{name} allocation not zero-filled")
        candidate[offset : offset + len(payload)] = payload

    candidate[analysis.SETTINGS_RESOURCES[2]["literal"] : analysis.SETTINGS_RESOURCES[2]["literal"] + 4] = pack_u32(ROM_BASE + SETTINGS_CLONE_OFFSET)
    candidate[analysis.SUSPEND_RESOURCE_LITERAL : analysis.SUSPEND_RESOURCE_LITERAL + 4] = pack_u32(ROM_BASE + SUSPEND_CLONE_OFFSET)

    # Re-parse cloned assets from the candidate as the runtime will see them.
    parsed_clone = analysis.parse_bg_resource(bytes(candidate), ROM_BASE + SETTINGS_CLONE_OFFSET)
    expected_settings_tiles = int(settings_report["allocation"]["decoded_tiles"])
    gate(parsed_clone["decoded_tiles"] == expected_settings_tiles, "settings cloned atlas tile count drift")
    gate(expected_settings_tiles <= SETTINGS_MAX_DECODED_TILES, "settings clone exceeds pre-option VRAM budget")
    gate(SETTINGS_RUNTIME_TILE_BASE + expected_settings_tiles <= SETTINGS_OPTION_TILE_BASE, "settings clone overlaps ON/OFF runtime tile base")
    original_settings = analysis.parse_bg_resource(jp, analysis.SETTINGS_FOREGROUND)
    target_indices = set()
    for rect in ((8, 1, 14, 2), (6, 5, 12, 2), (4, 9, 14, 2), (1, 13, 29, 2)):
        target_indices.update(rectangle_map_indices(original_settings, rect))
    gate(len(target_indices) == 138, "settings target-map union drift")
    remapped_settings_cells = [
        index
        for index, (before, after) in enumerate(zip(original_settings["cells"], parsed_clone["cells"]))
        if before != after
    ]
    gate(all(index in target_indices for index in remapped_settings_cells), "settings map remap escaped translated rectangles")
    gate(all(parsed_clone["cells"][index] == original_settings["cells"][index] for index in range(len(original_settings["cells"])) if index not in target_indices), "settings non-target map cell changed")
    clone_off = SETTINGS_CLONE_OFFSET
    clone_tiles_rel = int(parsed_clone["tiles_relative_offset"])
    clone_comp_len = int(parsed_clone["compressed_tile_length"])
    clone_atlas = analysis.custom_lzss_decompress(bytes(candidate[clone_off + clone_tiles_rel : clone_off + clone_tiles_rel + clone_comp_len]))
    gate(clone_atlas == settings_after, "settings clone decoded atlas differs from builder materialization")
    # Every tile still referenced by a non-target map cell must remain byte-exact
    # to the original atlas.  This proves scratch-slot reuse cannot corrupt the
    # rest of the foreground.
    non_target_ids = {int(original_settings["cells"][index]) & 0x03FF for index in range(len(original_settings["cells"])) if index not in target_indices}
    for tile_id in non_target_ids:
        gate(clone_atlas[tile_id * 32 : tile_id * 32 + 32] == settings_before[tile_id * 32 : tile_id * 32 + 32], f"settings non-target tile 0x{tile_id:03X} changed")

    clone_graphics_rel, clone_records = analysis.animation_records(bytes(candidate), ROM_BASE + SUSPEND_CLONE_OFFSET)
    gate(clone_graphics_rel == 0x0E04 and len(clone_records) == 12, "suspend cloned resource parse drift")
    clone_anim11 = clone_records[11][1]
    clone_oam11 = analysis.parse_animation_oam(clone_anim11)
    gate(clone_oam11["object_count"] == 12, "suspend cloned animation 11 OAM drift")
    clone_source11 = analysis.parse_animation_source_tiles(clone_anim11, clone_oam11)
    gate(max(clone_source11["source_ids"]) >= 262, "suspend clone did not redirect animation-11 text to private source tiles")
    _orig_graphics_rel, orig_records = analysis.animation_records(jp, analysis.SUSPEND_RESOURCE)
    orig_oam11 = analysis.parse_animation_oam(orig_records[11][1])
    orig_source11 = analysis.parse_animation_source_tiles(orig_records[11][1], orig_oam11)
    target_suspend_objects = {2, 3, 4, 5, 6, 9, 10, 11}
    gate(all(clone_source11["by_object"][i] == orig_source11["by_object"][i] for i in range(12) if i not in target_suspend_objects), "suspend clone changed non-text animation-11 source lookups")
    gate(any(clone_source11["by_object"][i] != orig_source11["by_object"][i] for i in target_suspend_objects), "suspend clone did not change target source lookups")
    clone_palette_rel = u32(candidate, SUSPEND_CLONE_OFFSET + 0x0C)
    clone_source_tile_count = (clone_palette_rel - clone_graphics_rel) // 32
    gate((clone_palette_rel - clone_graphics_rel) % 32 == 0, "suspend clone graphics span not tile aligned")
    gate(max(clone_source11["source_ids"]) < clone_source_tile_count, "suspend clone source lookup exceeds expanded graphics span")
    original_suspend_graphics = jp[
        (analysis.SUSPEND_RESOURCE - ROM_BASE) + 0x0E04 : (analysis.SUSPEND_RESOURCE - ROM_BASE) + 0x2EC4
    ]
    gate(candidate[SUSPEND_CLONE_OFFSET + clone_graphics_rel : SUSPEND_CLONE_OFFSET + clone_graphics_rel + len(original_suspend_graphics)] == original_suspend_graphics, "suspend clone rewrote original 262 source tiles")

    # Original resources and non-target consumers remain untouched.
    settings_original_start = analysis.SETTINGS_FOREGROUND - ROM_BASE
    settings_original_end = analysis.SETTINGS_RESOURCES[1]["address"] - ROM_BASE
    gate(candidate[settings_original_start:settings_original_end] == main_bytes[settings_original_start:settings_original_end], "original settings foreground changed in place")
    suspend_original_start = analysis.SUSPEND_RESOURCE - ROM_BASE
    suspend_original_end = suspend_original_start + 0x2EC4 + 6 * 32
    gate(candidate[suspend_original_start:suspend_original_end] == main_bytes[suspend_original_start:suspend_original_end], "original shared suspend resource changed in place")
    for hit in analysis.RESOURCE_POINTER_HITS:
        expected = ROM_BASE + SUSPEND_CLONE_OFFSET if hit == analysis.SUSPEND_RESOURCE_LITERAL else analysis.SUSPEND_RESOURCE
        gate(u32(candidate, hit) == expected, f"shared suspend resource pointer consumer drift at 0x{hit:08X}")

    # Settings dynamic option table and footer draw/pointer stay byte-exact.
    gate(candidate[analysis.OPTION_TABLE : analysis.OPTION_TABLE + 6 * 0x10] == main_bytes[analysis.OPTION_TABLE : analysis.OPTION_TABLE + 6 * 0x10], "settings option table changed")
    gate(candidate[analysis.TITLE_LITERAL : analysis.TITLE_LITERAL + 4] == main_bytes[analysis.TITLE_LITERAL : analysis.TITLE_LITERAL + 4], "settings footer pointer changed")
    settings_code_start = analysis.SETTINGS_FUNCTION - ROM_BASE
    settings_code_end = 0x00021474
    settings_literal = int(analysis.SETTINGS_RESOURCES[2]["literal"])
    gate(
        candidate[settings_code_start:settings_literal] == main_bytes[settings_code_start:settings_literal]
        and candidate[settings_literal + 4 : settings_code_end] == main_bytes[settings_literal + 4 : settings_code_end],
        "settings Thumb code changed outside the one resource literal",
    )
    suspend_code_start = analysis.SUSPEND_FUNCTION - ROM_BASE
    suspend_code_end = 0x00020C2C
    gate(
        candidate[suspend_code_start:analysis.SUSPEND_RESOURCE_LITERAL] == main_bytes[suspend_code_start:analysis.SUSPEND_RESOURCE_LITERAL]
        and candidate[analysis.SUSPEND_RESOURCE_LITERAL + 4 : suspend_code_end] == main_bytes[analysis.SUSPEND_RESOURCE_LITERAL + 4 : suspend_code_end],
        "suspend Thumb code changed outside the one resource literal",
    )

    changed = [index for index, (before, after) in enumerate(zip(main_bytes, candidate)) if before != after]
    allowed_ranges = [
        (SETTINGS_CLONE_OFFSET, SETTINGS_CLONE_OFFSET + len(settings_clone)),
        (SUSPEND_CLONE_OFFSET, SUSPEND_CLONE_OFFSET + len(suspend_clone)),
        (analysis.SETTINGS_RESOURCES[2]["literal"], analysis.SETTINGS_RESOURCES[2]["literal"] + 4),
        (analysis.SUSPEND_RESOURCE_LITERAL, analysis.SUSPEND_RESOURCE_LITERAL + 4),
    ]
    gate(changed and all(any(start <= pos < end for start, end in allowed_ranges) for pos in changed), "changes escaped settings/suspend candidate scope")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    build_settings_preview(settings_before, settings_after, jp, settings_report, args.settings_preview)
    build_suspend_preview(jp, suspend_before, suspend_after, args.suspend_preview)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_settings_suspend_ui_ko_poc",
        "result": "PASS",
        "source": {
            "main_tip": str(args.main.relative_to(ADVANCE_ROOT)),
            "main_tip_sha256": sha256(main_bytes),
            "japanese_sha256": sha256(jp),
            "analysis": "legacy/analysis/ggen_advance_settings_suspend_ui_20260830.json",
        },
        "settings": {
            "source_resource": f"0x{analysis.SETTINGS_FOREGROUND:08X}",
            "clone_file_offset": f"0x{SETTINGS_CLONE_OFFSET:08X}",
            "clone_address": f"0x{ROM_BASE + SETTINGS_CLONE_OFFSET:08X}",
            "clone_size": len(settings_clone),
            "literal_file_offset": f"0x{analysis.SETTINGS_RESOURCES[2]['literal']:08X}",
            "font": "Galmuri11.bdf native 12x12",
            "palette_indices": {"face": SETTINGS_FACE, "contour": SETTINGS_CONTOUR, "background": SETTINGS_BACKGROUND},
            "translations": SETTINGS_TRANSLATIONS,
            "patches": settings_report,
            "dynamic_option_table_untouched": True,
            "footer_text_pointer_untouched": True,
            "preview": str(args.settings_preview.relative_to(ADVANCE_ROOT)),
        },
        "suspend": {
            "source_resource": f"0x{analysis.SUSPEND_RESOURCE:08X}",
            "clone_file_offset": f"0x{SUSPEND_CLONE_OFFSET:08X}",
            "clone_address": f"0x{ROM_BASE + SUSPEND_CLONE_OFFSET:08X}",
            "clone_size": len(suspend_clone),
            "literal_file_offset": f"0x{analysis.SUSPEND_RESOURCE_LITERAL:08X}",
            "animation_id": analysis.SUSPEND_ANIMATION,
            "font": "Galmuri11.bdf native 12x12",
            "translations": list(SUSPEND_LINES),
            "patch": suspend_report,
            "other_original_resource_consumers_untouched": [f"0x{value:08X}" for value in analysis.RESOURCE_POINTER_HITS if value != analysis.SUSPEND_RESOURCE_LITERAL],
            "preview": str(args.suspend_preview.relative_to(ADVANCE_ROOT)),
        },
        "output": {
            "path": str(args.out.relative_to(ADVANCE_ROOT)),
            "size": len(candidate),
            "sha256": sha256(candidate),
        },
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "changes_confined_to_two_clones_and_two_literals": True,
            "current_main_tip_manifest_hash_verified": sha256(main_bytes) == manifest_main_hash,
            "settings_clone_runtime_parse_verified": True,
            "settings_decoded_tile_count": expected_settings_tiles,
            "settings_original_131_tile_budget_preserved": expected_settings_tiles == 131,
            "settings_runtime_end_tile_exclusive": SETTINGS_RUNTIME_TILE_BASE + expected_settings_tiles,
            "settings_dynamic_option_tile_base": SETTINGS_OPTION_TILE_BASE,
            "settings_no_vram_overlap_with_dynamic_options": SETTINGS_RUNTIME_TILE_BASE + expected_settings_tiles <= SETTINGS_OPTION_TILE_BASE,
            "settings_map_remaps_confined_to_target_rectangles": all(index in target_indices for index in remapped_settings_cells),
            "settings_non_target_map_cells_unchanged": all(parsed_clone["cells"][index] == original_settings["cells"][index] for index in range(len(original_settings["cells"])) if index not in target_indices),
            "settings_non_target_referenced_tiles_unchanged": all(clone_atlas[tile_id * 32 : tile_id * 32 + 32] == settings_before[tile_id * 32 : tile_id * 32 + 32] for tile_id in non_target_ids),
            "settings_original_resource_unchanged": True,
            "settings_dynamic_options_unchanged": True,
            "settings_footer_unchanged": True,
            "suspend_clone_runtime_parse_verified": True,
            "suspend_animation_11_oam_unchanged": True,
            "suspend_text_plane_geometry_verified": [144, 48],
            "suspend_target_object_indices": sorted(target_suspend_objects),
            "suspend_non_target_animation11_source_lookups_unchanged": all(clone_source11["by_object"][i] == orig_source11["by_object"][i] for i in range(12) if i not in target_suspend_objects),
            "suspend_private_source_tiles_used": max(clone_source11["source_ids"]) >= 262,
            "suspend_private_source_lookup_within_expanded_graphics": max(clone_source11["source_ids"]) < clone_source_tile_count,
            "suspend_original_262_source_tiles_unchanged_inside_clone": True,
            "suspend_original_shared_resource_unchanged": True,
            "suspend_other_four_consumers_unchanged": True,
            "Thumb_code_unchanged": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": report["output"]["sha256"],
        "changed_bytes": len(changed),
        "settings_clone_bytes": len(settings_clone),
        "suspend_clone_bytes": len(suspend_clone),
        "settings_preview": str(args.settings_preview),
        "suspend_preview": str(args.suspend_preview),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
