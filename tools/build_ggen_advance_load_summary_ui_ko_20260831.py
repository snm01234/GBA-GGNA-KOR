#!/usr/bin/env python3
"""Build a Korean fixed-graphic candidate for the post-stage/load summary screen.

The supplied mGBA state proves that BG1 is loaded from the 30x20 resource
0x08C7994C through the unique table pointer at file offset 0x00D590B4.  The
follow-up state/screenshot closes six visible Japanese labels as private tile
rectangles in that resource:

* データロード -> 데이터로드 (top title)
* クリア -> 클리어 (Galmuri11-Condensed 8x16)
* 次は -> 다음
* プレイ時間 -> 플레이시간
* ゲームモード -> 게임모드 (right side of the play-time row)
* ロードします -> 로드합니다 (the native ``A:`` prefix is untouched)

The source rectangles contain only transparent pixels plus the Japanese face
and contour indices.  We erase both Japanese layers completely and rebuild a
one-pixel contour from the Korean Galmuri11 mask, so no Japanese-shaped shadow
can survive.  The original shared resource is left byte-exact: a private clone
is written into zero-filled expansion space and only its unique owner pointer
is redirected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as bg  # noqa: E402
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt  # noqa: E402
import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    advance_relative,
)

ROM_BASE = 0x08000000
SOURCE_RESOURCE = 0x08C7994C
SOURCE_OFFSET = SOURCE_RESOURCE - ROM_BASE
OWNER_POINTER_OFFSET = 0x00D590B4
CLONE_OFFSET = 0x01281000
CLONE_ADDRESS = ROM_BASE + CLONE_OFFSET

# The stage subtitle visible in the same state is not part of C7994C: it is a
# normal 8x16 text stream.  The canonical unified ROM already relocated the
# original record GGA-TEXT-0018D15B to 0x09052476 and its sole owner is the
# u32 pointer at 0x00FCE2FC.  Keep this separate ownership contract explicit.
STAGE_OWNER_POINTER_OFFSET = 0x00FCE2FC
STAGE_ACTIVE_OFFSET = 0x01052476
STAGE_ACTIVE_ADDRESS = ROM_BASE + STAGE_ACTIVE_OFFSET
STAGE_JP_RAW = bytes.fromhex("E1 FD E6 1D 3B E0 B5 33 00")
STAGE_JP_TEXT = "砂塵の果て"
STAGE_KO_TEXT = "모래먼지의 끝"
STAGE_TEXT_OFFSET = 0x01283000
STAGE_TEXT_ADDRESS = ROM_BASE + STAGE_TEXT_OFFSET
STAGE_KO_SLOTS = {
    "모": 0x0767,
    "래": 0x0712,
    "먼": 0x043E,
    "지": 0x018B,
    "의": 0x07A9,
    " ": 0x0001,
    "끝": 0x06A6,
}
FONT8_LITERAL_FILE = 0x00001350

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
SOURCE_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui"
DEFAULT_OUT = OUT_DIR / "ggen_advance_load_summary_ui_ko_followup_candidate_20260831.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_load_summary_ui_ko_followup_candidate_20260831.sav"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_load_summary_ui_ko_followup_20260831.json"

CONTOUR = 2
TRANSPARENT = 0
EXPECTED_DECODED_TILES = 111

# (map x, map y, width tiles, height tiles), Korean text, original face index,
# font mode.  The first candidate misidentified the top データロード as
# ゲームモード and started ロードします one tile too far right.  The fresh
# screenshot plus source raster proves the corrected rectangles below.
TARGETS: dict[str, tuple[tuple[int, int, int, int], str, int, str]] = {
    "data_load": ((10, 2, 9, 2), "데이터로드", 11, "12x12"),
    "clear": ((25, 5, 4, 2), "클리어", 11, "condensed_8x16"),
    "next": ((1, 8, 4, 2), "다음", 10, "12x12"),
    "play_time": ((1, 11, 8, 2), "플레이시간", 11, "12x12"),
    "game_mode": ((15, 11, 9, 2), "게임모드", 11, "12x12"),
    "load": ((20, 14, 9, 3), "로드합니다", 10, "12x12"),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def slot_to_token_bytes(slot: int) -> bytes:
    gate(1 <= slot <= 0x0813, f"8x16 slot outside literal text range: 0x{slot:04X}")
    if slot <= 0xDF:
        return bytes((slot,))
    token = 0xDF20 + slot
    gate(0xE000 <= token <= 0xEFFF, f"8x16 slot cannot form literal token: 0x{slot:04X}")
    return bytes((token >> 8, token & 0xFF))


def encode_stage_translation() -> bytes:
    return b"".join(slot_to_token_bytes(STAGE_KO_SLOTS[char]) for char in STAGE_KO_TEXT) + b"\x00"


def pointer_hits(data: bytes, value: int) -> list[int]:
    needle = struct.pack("<I", value)
    result: list[int] = []
    cursor = 0
    while True:
        found = data.find(needle, cursor)
        if found < 0:
            return result
        result.append(found)
        cursor = found + 1


def target_map_indices(resource: dict[str, Any], rect: tuple[int, int, int, int]) -> list[int]:
    x, y, width, height = rect
    map_width = int(resource["width"])
    return [(y + yy) * map_width + x + xx for yy in range(height) for xx in range(width)]


def make_condensed_8x16_mask(text: str, font: fontpair.BdfFont, width: int, height: int) -> tuple[list[list[bool]], int]:
    text_width = len(text) * 8
    gate(text_width <= width - 2, f"condensed text does not fit {width}px region: {text!r}")
    gate(height >= 16, f"condensed text region too short: {height}")
    ox = (width - text_width) // 2
    oy = (height - 16) // 2
    mask = [[False] * width for _ in range(height)]
    for index, char in enumerate(text):
        glyph = fontpair.render_condensed_8x16_basic(char, font)
        gate(glyph.size == (8, 16), f"condensed glyph size drift: {char} {glyph.size}")
        for y in range(16):
            for x in range(8):
                if glyph.getpixel((x, y)):
                    mask[oy + y][ox + index * 8 + x] = True
    coords = [(x, y) for y in range(height) for x in range(width) if mask[y][x]]
    gate(coords, f"condensed mask is empty: {text!r}")
    gate(min(x for x, _ in coords) > 0 and max(x for x, _ in coords) < width - 1, f"condensed mask lacks horizontal contour margin: {text!r}")
    gate(min(y for _, y in coords) > 0 and max(y for _, y in coords) < height - 1, f"condensed mask lacks vertical contour margin: {text!r}")
    return mask, text_width


def patch_rect(
    atlas: bytearray,
    resource: dict[str, Any],
    rect: tuple[int, int, int, int],
    text: str,
    face: int,
    font: fontpair.BdfFont,
    font_mode: str,
) -> dict[str, Any]:
    x, y, width_tiles, height_tiles = rect
    tile_rows = bg.map_rect(resource, x, y, width_tiles, height_tiles)
    pixels = paintops.stitch_variable(bytes(atlas), tile_rows)
    pixel_width = width_tiles * 8
    pixel_height = height_tiles * 8
    gate(len(pixels) == pixel_height and all(len(row) == pixel_width for row in pixels), f"{text}: raster dimensions drift")

    before_counts: dict[int, int] = {}
    for row in pixels:
        for value in row:
            before_counts[value] = before_counts.get(value, 0) + 1
    allowed = {TRANSPARENT, CONTOUR, face}
    gate(set(before_counts) <= allowed, f"{text}: rectangle contains non-glyph/background indices {sorted(set(before_counts) - allowed)}")
    gate(before_counts.get(face, 0) > 0 and before_counts.get(CONTOUR, 0) > 0, f"{text}: source face/contour pixels missing")

    source_glyph_pixels = before_counts.get(face, 0) + before_counts.get(CONTOUR, 0)
    for yy in range(pixel_height):
        for xx in range(pixel_width):
            if pixels[yy][xx] in (face, CONTOUR):
                pixels[yy][xx] = TRANSPARENT
    gate(all(value == TRANSPARENT for row in pixels for value in row), f"{text}: Japanese source layer did not clear completely")

    if font_mode == "12x12":
        mask, text_width = paintops.make_text_mask(text, font, pixel_width, pixel_height)
    elif font_mode == "condensed_8x16":
        mask, text_width = make_condensed_8x16_mask(text, font, pixel_width, pixel_height)
    else:
        raise SystemExit(f"gate failed: unsupported font mode {font_mode!r} for {text!r}")
    ink_pixels, contour_pixels = paintops.paint_mask(pixels, mask, ink=face, contour=CONTOUR)
    gate(ink_pixels > 0 and contour_pixels > 0, f"{text}: Korean glyph/contour rendering failed")

    # Reconstruct an independent expected Korean-only raster and demand exact
    # equality.  This is the residue gate: every non-transparent pixel in the
    # output must have been generated by the Korean mask or its contour.
    expected = [[TRANSPARENT] * pixel_width for _ in range(pixel_height)]
    expected_ink, expected_contour = paintops.paint_mask(expected, mask, ink=face, contour=CONTOUR)
    gate(expected_ink == ink_pixels and expected_contour == contour_pixels, f"{text}: contour accounting drift")
    gate(expected == pixels, f"{text}: Japanese-shaped residue survived Korean repaint")

    paintops.write_variable(atlas, tile_rows, pixels)
    return {
        "translation": text,
        "font_mode": font_mode,
        "map_rect": [x, y, width_tiles, height_tiles],
        "source_tile_ids": [[f"0x{tile:03X}" for tile in row] for row in tile_rows],
        "face_index": face,
        "contour_index": CONTOUR,
        "transparent_index": TRANSPARENT,
        "source_face_pixels": before_counts.get(face, 0),
        "source_contour_pixels": before_counts.get(CONTOUR, 0),
        "source_glyph_pixels_cleared": source_glyph_pixels,
        "korean_text_width_px": text_width,
        "korean_ink_pixels": ink_pixels,
        "korean_contour_pixels": contour_pixels,
        "japanese_face_and_shadow_fully_cleared_before_repaint": True,
        "post_raster_exactly_korean_mask_plus_contour": True,
    }


def build_clone(source: bytes, font12: fontpair.BdfFont, font8: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], bytes, bytes]:
    resource = bg.parse_bg_resource(source, SOURCE_RESOURCE)
    gate(int(resource["decoded_tiles"]) == EXPECTED_DECODED_TILES, f"source decoded tile count drift: {resource['decoded_tiles']}")
    source_offset = int(resource["file_offset"])
    tiles_rel = int(resource["tiles_relative_offset"])
    comp_len = int(resource["compressed_tile_length"])
    palette_rel = int(resource["palette_relative_offset"])
    palette_len = int(resource["palette_length"])
    map_rel = int(resource["map_relative_offset"])
    map_len = int(resource["map_length"])

    original_map = source[source_offset + map_rel : source_offset + map_rel + map_len]
    original_comp = source[source_offset + tiles_rel : source_offset + tiles_rel + comp_len]
    original_palette = source[source_offset + palette_rel : source_offset + palette_rel + palette_len]
    original_atlas = bg.custom_lzss_decompress(original_comp)
    gate(len(original_atlas) == EXPECTED_DECODED_TILES * 32, "source atlas size drift")

    # Prove every target tile is private to the selected five rectangles.  We
    # can therefore rewrite tile payloads without touching the map or any
    # neighboring word/decoration.
    target_indices: set[int] = set()
    for rect, _text, _face, _font_mode in TARGETS.values():
        target_indices.update(target_map_indices(resource, rect))
    target_tiles = {int(resource["cells"][index]) & 0x03FF for index in target_indices}
    outside_tiles = {
        int(resource["cells"][index]) & 0x03FF
        for index in range(len(resource["cells"]))
        if index not in target_indices
    }
    shared = target_tiles & outside_tiles
    gate(not shared, f"target source tiles are shared with non-target cells: {sorted(shared)}")
    gate(len(target_indices) == 95 and len(target_tiles) == 95, f"target ownership drift: cells={len(target_indices)} tiles={len(target_tiles)}")

    atlas = bytearray(original_atlas)
    reports: dict[str, Any] = {}
    for key, (rect, text, face, font_mode) in TARGETS.items():
        face_font = font8 if font_mode == "condensed_8x16" else font12
        reports[key] = patch_rect(atlas, resource, rect, text, face, face_font, font_mode)
    gate(len(atlas) == len(original_atlas), "decoded atlas unexpectedly expanded")

    # Only target source tiles may differ in decoded graphics.
    changed_tiles = [
        tile
        for tile in range(EXPECTED_DECODED_TILES)
        if original_atlas[tile * 32 : (tile + 1) * 32] != atlas[tile * 32 : (tile + 1) * 32]
    ]
    gate(set(changed_tiles) <= target_tiles, "decoded atlas changed outside target tiles")
    gate(changed_tiles, "no decoded tile changes produced")

    compressed = paintops.literal_only_lzss_body(bytes(atlas))
    gate(bg.custom_lzss_decompress(compressed) == bytes(atlas), "clone custom-LZSS round-trip failed")

    header = bytearray(source[source_offset : source_offset + 16])
    new_map_rel = 0x10
    new_tiles_rel = new_map_rel + len(original_map)
    gate(new_tiles_rel == 0x4C0, "30x20 map layout drift")
    new_palette_rel = (new_tiles_rel + len(compressed) + 3) & ~3
    clone = bytearray(new_palette_rel + len(original_palette))
    clone[:16] = header
    struct.pack_into(
        "<HHHHHH",
        clone,
        4,
        new_map_rel,
        len(original_map),
        new_tiles_rel,
        len(compressed),
        new_palette_rel,
        len(original_palette),
    )
    clone[new_map_rel : new_map_rel + len(original_map)] = original_map
    clone[new_tiles_rel : new_tiles_rel + len(compressed)] = compressed
    clone[new_palette_rel : new_palette_rel + len(original_palette)] = original_palette

    clone_resource = bg.parse_bg_resource(bytes(bytearray(CLONE_OFFSET) + clone), CLONE_ADDRESS)
    gate(int(clone_resource["decoded_tiles"]) == EXPECTED_DECODED_TILES, "clone decoded tile count drift")
    gate(bytes(clone[new_map_rel : new_map_rel + len(original_map)]) == original_map, "clone map changed")
    gate(bytes(clone[new_palette_rel : new_palette_rel + len(original_palette)]) == original_palette, "clone palette changed")

    return bytes(clone), {
        "targets": reports,
        "target_map_cells": len(target_indices),
        "private_target_source_tiles": len(target_tiles),
        "target_source_tiles": [f"0x{tile:03X}" for tile in sorted(target_tiles)],
        "changed_decoded_tiles": [f"0x{tile:03X}" for tile in changed_tiles],
        "decoded_tile_count_preserved": EXPECTED_DECODED_TILES,
        "map_byte_exact": True,
        "palette_byte_exact": True,
        "non_target_tiles_byte_exact": True,
    }, original_atlas, bytes(atlas)


def verify_stage_text_binding(source: bytes, state: bytes, font8: fontpair.BdfFont) -> dict[str, Any]:
    gate(source[STAGE_ACTIVE_OFFSET : STAGE_ACTIVE_OFFSET + len(STAGE_JP_RAW)] == STAGE_JP_RAW, "active stage-title Japanese payload drift")
    gate(u32(source, STAGE_OWNER_POINTER_OFFSET) == STAGE_ACTIVE_ADDRESS, "stage-title owner pointer drift")
    active_hits = pointer_hits(source, STAGE_ACTIVE_ADDRESS)
    gate(active_hits == [STAGE_OWNER_POINTER_OFFSET], f"stage-title active pointer is not unique: {[hex(x) for x in active_hits]}")

    # The screenshot/state title tiles 208..212 (top) + 213..217 (bottom)
    # exactly reproduce five 8x16 Japanese font masks.  This ties the visible
    # 砂塵の果て to GGA-TEXT-0018D15B rather than merely relying on a text search.
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    active_font_address = u32(source, FONT8_LITERAL_FILE)
    gate(ROM_BASE <= active_font_address < ROM_BASE + len(source), f"active 8x16 font pointer invalid: 0x{active_font_address:08X}")
    active_font_offset = active_font_address - ROM_BASE
    jp_slots = [0x02DD, 0x06FD, 0x003B, 0x0195, 0x0033]

    def vram_mask(index: int) -> tuple[tuple[bool, ...], ...]:
        rows: list[tuple[bool, ...]] = []
        for tile in (208 + index, 213 + index):
            raw = bytes(vram[tile * 32 : (tile + 1) * 32])
            for y in range(8):
                row: list[bool] = []
                for x in range(8):
                    value = raw[y * 4 + x // 2]
                    row.append(((value >> (4 * (x & 1))) & 0x0F) != 0)
                rows.append(tuple(row))
        return tuple(rows)

    def font_mask(slot: int) -> tuple[tuple[bool, ...], ...]:
        raw = source[active_font_offset + slot * 32 : active_font_offset + (slot + 1) * 32]
        gate(len(raw) == 32, f"active font slot 0x{slot:04X} truncated")
        image = fontops.unpack_8x16(raw)
        return tuple(tuple(bool(image.getpixel((x, y))) for x in range(8)) for y in range(16))

    jp_matches = [vram_mask(index) == font_mask(slot) for index, slot in enumerate(jp_slots)]
    gate(all(jp_matches), f"live stage-title glyph masks do not match 砂塵の果て slots: {jp_matches}")

    # Verify every Korean slot currently loaded by the main TIP is exactly the
    # canonical Galmuri11-Condensed glyph we intend the normal renderer to use.
    ko_slot_report: list[dict[str, Any]] = []
    for char in STAGE_KO_TEXT:
        slot = STAGE_KO_SLOTS[char]
        if char == " ":
            ko_slot_report.append({"char": char, "slot": f"0x{slot:04X}", "space": True})
            continue
        expected = fontops.pack_8x16(fontpair.render_condensed_8x16_basic(char, font8))
        raw = source[active_font_offset + slot * 32 : active_font_offset + (slot + 1) * 32]
        gate(raw == expected, f"active Korean 8x16 glyph drift: {char} slot 0x{slot:04X}")
        ko_slot_report.append({"char": char, "slot": f"0x{slot:04X}", "canonical_galmuri11_condensed": True})

    encoded = encode_stage_translation()
    gate(encoded.endswith(b"\x00") and len(encoded) == 14, f"stage Korean payload length drift: {len(encoded)}")
    return {
        "record_id": "GGA-TEXT-0018D15B",
        "owner_pointer_file_offset": f"0x{STAGE_OWNER_POINTER_OFFSET:08X}",
        "active_payload_file_offset": f"0x{STAGE_ACTIVE_OFFSET:08X}",
        "active_payload_address": f"0x{STAGE_ACTIVE_ADDRESS:08X}",
        "active_pointer_hits": [f"0x{value:08X}" for value in active_hits],
        "source_text": STAGE_JP_TEXT,
        "source_raw_hex": STAGE_JP_RAW.hex(" ").upper(),
        "live_japanese_font_slots": [f"0x{slot:04X}" for slot in jp_slots],
        "live_state_glyphs_exactly_match_source_font_slots": True,
        "translation": STAGE_KO_TEXT,
        "translation_raw_hex": encoded.hex(" ").upper(),
        "active_font_address": f"0x{active_font_address:08X}",
        "korean_slots": ko_slot_report,
    }


def verify_state_binding(source: bytes, decoded_atlas: bytes, font8: fontpair.BdfFont) -> dict[str, Any]:
    gate(STATE.is_file(), f"state missing: {STATE}")
    state, chunks = statefmt.parse_png_state(STATE)
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    dispcnt = struct.unpack_from("<H", io, 0)[0]
    bg1cnt = struct.unpack_from("<H", io, 10)[0]
    charblock = (bg1cnt >> 2) & 3
    screenblock = (bg1cnt >> 8) & 31
    gate(dispcnt == 0x1F40, f"state DISPCNT drift: 0x{dispcnt:04X}")
    gate(charblock == 0 and screenblock == 14, f"state BG1 binding drift: char={charblock} screen={screenblock}")
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]

    exact = 0
    for tile in range(1, 110):
        live = bytes(vram[tile * 32 : (tile + 1) * 32])
        expected = decoded_atlas[tile * 32 : (tile + 1) * 32]
        if live == expected:
            exact += 1
    gate(exact == 109, f"state BG1/source atlas ownership mismatch: {exact}/109")

    # Map cells in live BG1 must equal the source resource map.  This connects
    # the screenshot/state geometry to the ROM owner, independently of tile
    # bitmap matching.
    resource = bg.parse_bg_resource(source, SOURCE_RESOURCE)
    live_cells = [
        struct.unpack_from("<H", vram, screenblock * 0x800 + (y * 32 + x) * 2)[0]
        for y in range(20)
        for x in range(30)
    ]
    source_cells = [int(value) for value in resource["cells"]]
    # The loader applies palette-bank 3 to this resource at runtime, so compare
    # the 10-bit tile IDs rather than the palette attribute nibble.
    map_exact = sum((a & 0x03FF) == (b & 0x03FF) for a, b in zip(live_cells, source_cells))
    gate(map_exact == 30 * 20, f"state BG1/source tilemap mismatch: {map_exact}/600")
    palette_banks = sorted({(value >> 12) & 0x0F for value in live_cells})

    stage_text = verify_stage_text_binding(source, state, font8)
    return {
        "state": advance_relative(STATE),
        "state_sha256": sha256(STATE.read_bytes()),
        "png_chunks": [entry["kind"] for entry in chunks],
        "dispcnt": f"0x{dispcnt:04X}",
        "bg1_charblock": charblock,
        "bg1_screenblock": screenblock,
        "live_atlas_tiles_1_109_exact": exact,
        "live_tilemap_ids_exact": map_exact,
        "runtime_palette_banks": palette_banks,
        "stage_text": stage_text,
        "owner_proven": True,
    }


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    result: list[list[str]] = []
    start = previous = offsets[0]
    for value in offsets[1:]:
        if value != previous + 1:
            result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
            start = value
        previous = value
    result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    source = args.input.read_bytes()
    gate(len(source) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(main_manifest.get("status") == "approved_main_tip", "main TIP manifest is not approved")
    gate(sha256(source) == main_manifest.get("sha256"), f"main TIP/manifest hash drift: {sha256(source)}")
    gate(u32(source, OWNER_POINTER_OFFSET) == SOURCE_RESOURCE, f"owner pointer drift at 0x{OWNER_POINTER_OFFSET:08X}")
    hits = pointer_hits(source, SOURCE_RESOURCE)
    gate(hits == [OWNER_POINTER_OFFSET], f"source resource pointer ownership is no longer unique: {[hex(x) for x in hits]}")

    source_resource = bg.parse_bg_resource(source, SOURCE_RESOURCE)
    source_off = int(source_resource["file_offset"])
    source_span_end = source_off + max(
        int(source_resource["map_relative_offset"]) + int(source_resource["map_length"]),
        int(source_resource["tiles_relative_offset"]) + int(source_resource["compressed_tile_length"]),
        int(source_resource["palette_relative_offset"]) + int(source_resource["palette_length"]),
    )
    source_resource_before = source[source_off:source_span_end]
    source_comp = source[
        source_off + int(source_resource["tiles_relative_offset"]) :
        source_off + int(source_resource["tiles_relative_offset"]) + int(source_resource["compressed_tile_length"])
    ]
    source_atlas = bg.custom_lzss_decompress(source_comp)

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
        font8 = fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf")
    state_binding = verify_state_binding(source, source_atlas, font8)
    clone, patch_report, original_atlas, patched_atlas = build_clone(source, font, font8)

    gate(CLONE_OFFSET + len(clone) <= len(source), "clone allocation exceeds ROM")
    allocation_before = source[CLONE_OFFSET : CLONE_OFFSET + len(clone)]
    gate(all(value == 0 for value in allocation_before), "clone allocation is not zero-filled")

    stage_payload = encode_stage_translation()
    gate(STAGE_TEXT_OFFSET + len(stage_payload) <= len(source), "stage-title allocation exceeds ROM")
    gate(all(value == 0 for value in source[STAGE_TEXT_OFFSET : STAGE_TEXT_OFFSET + len(stage_payload)]), "stage-title allocation is not zero-filled")

    candidate = bytearray(source)
    candidate[CLONE_OFFSET : CLONE_OFFSET + len(clone)] = clone
    struct.pack_into("<I", candidate, OWNER_POINTER_OFFSET, CLONE_ADDRESS)
    candidate[STAGE_TEXT_OFFSET : STAGE_TEXT_OFFSET + len(stage_payload)] = stage_payload
    struct.pack_into("<I", candidate, STAGE_OWNER_POINTER_OFFSET, STAGE_TEXT_ADDRESS)
    gate(candidate[source_off:source_span_end] == source_resource_before, "original 0x08C7994C resource changed")
    gate(u32(candidate, OWNER_POINTER_OFFSET) == CLONE_ADDRESS, "fixed-graphic owner pointer redirect failed")
    gate(candidate[STAGE_ACTIVE_OFFSET : STAGE_ACTIVE_OFFSET + len(STAGE_JP_RAW)] == STAGE_JP_RAW, "original active Japanese stage-title payload changed")
    gate(u32(candidate, STAGE_OWNER_POINTER_OFFSET) == STAGE_TEXT_ADDRESS, "stage-title owner pointer redirect failed")
    gate(candidate[STAGE_TEXT_OFFSET : STAGE_TEXT_OFFSET + len(stage_payload)] == stage_payload, "stage-title Korean payload write failed")

    # Parse clone from its final ROM position and validate payloads again.
    final_clone = bg.parse_bg_resource(bytes(candidate), CLONE_ADDRESS)
    final_tiles_rel = int(final_clone["tiles_relative_offset"])
    final_comp_len = int(final_clone["compressed_tile_length"])
    final_atlas = bg.custom_lzss_decompress(
        candidate[CLONE_OFFSET + final_tiles_rel : CLONE_OFFSET + final_tiles_rel + final_comp_len]
    )
    gate(final_atlas == patched_atlas, "final clone atlas differs from rendered Korean atlas")
    gate(len(final_atlas) == len(original_atlas), "final clone decoded size drift")

    changed = [index for index, (old, new) in enumerate(zip(source, candidate)) if old != new]
    pointer_range = set(range(OWNER_POINTER_OFFSET, OWNER_POINTER_OFFSET + 4))
    stage_pointer_range = set(range(STAGE_OWNER_POINTER_OFFSET, STAGE_OWNER_POINTER_OFFSET + 4))
    escaped = [
        index for index in changed
        if index not in pointer_range
        and index not in stage_pointer_range
        and not (CLONE_OFFSET <= index < CLONE_OFFSET + len(clone))
        and not (STAGE_TEXT_OFFSET <= index < STAGE_TEXT_OFFSET + len(stage_payload))
    ]
    gate(not escaped, f"candidate changed bytes outside fixed/stage owner pointers and private allocations: {escaped[:8]}")
    gate(len(candidate) == len(source), "candidate ROM size changed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    copied_sav = False
    sav_sha = None
    if SOURCE_SAV.is_file():
        args.out_sav.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_SAV, args.out_sav)
        gate(args.out_sav.read_bytes() == SOURCE_SAV.read_bytes(), "candidate SAV copy is not byte-exact")
        copied_sav = True
        sav_sha = sha256(args.out_sav.read_bytes())

    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_load_summary_ui_ko_followup_candidate_20260831",
        "result": "PASS",
        "source": {
            "main_tip": advance_relative(args.input),
            "main_tip_sha256": sha256(source),
            "main_tip_promotion_reason": main_manifest.get("promotion_reason"),
            "state_binding": state_binding,
        },
        "ownership": {
            "source_resource": f"0x{SOURCE_RESOURCE:08X}",
            "source_file_offset": f"0x{SOURCE_OFFSET:08X}",
            "owner_pointer_file_offset": f"0x{OWNER_POINTER_OFFSET:08X}",
            "source_pointer_hits": [f"0x{value:08X}" for value in hits],
            "runtime_bg": "BG1",
            "runtime_charblock": 0,
            "runtime_screenblock": 14,
            "decoded_tiles": EXPECTED_DECODED_TILES,
            "stage_text_record_id": "GGA-TEXT-0018D15B",
            "stage_text_owner_pointer_file_offset": f"0x{STAGE_OWNER_POINTER_OFFSET:08X}",
            "stage_text_active_address": f"0x{STAGE_ACTIVE_ADDRESS:08X}",
        },
        "patch": {
            "clone_file_offset": f"0x{CLONE_OFFSET:08X}",
            "clone_address": f"0x{CLONE_ADDRESS:08X}",
            "clone_size": len(clone),
            "font": "Galmuri11.bdf 12x12 + Galmuri11-Condensed.bdf native 8x16 for 클리어",
            "translations": {
                **{key: text for key, (_rect, text, _face, _font_mode) in TARGETS.items()},
                "stage_title": STAGE_KO_TEXT,
            },
            "stage_title": {
                "source_text": STAGE_JP_TEXT,
                "translation": STAGE_KO_TEXT,
                "source_active_payload_preserved": True,
                "new_payload_file_offset": f"0x{STAGE_TEXT_OFFSET:08X}",
                "new_payload_address": f"0x{STAGE_TEXT_ADDRESS:08X}",
                "new_payload_length": len(stage_payload),
                "new_payload_hex": stage_payload.hex(" ").upper(),
                "owner_pointer_redirected": True,
                "font": "Galmuri11-Condensed.bdf / existing canonical 8x16 slots",
            },
            **patch_report,
        },
        "output": {
            "rom": advance_relative(args.out),
            "rom_size": len(output),
            "rom_sha256": sha256(output),
            "sav": advance_relative(args.out_sav) if copied_sav else None,
            "sav_sha256": sav_sha,
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_hash_verified": True,
            "state_and_source_resource_owner_proven": True,
            "source_resource_pointer_unique": True,
            "source_resource_byte_exact_preserved": True,
            "clone_allocation_zero_filled_before_write": True,
            "clone_map_byte_exact": True,
            "clone_palette_byte_exact": True,
            "decoded_tile_count_preserved": True,
            "all_target_source_tiles_private": True,
            "japanese_face_and_shadow_removed_before_each_korean_repaint": True,
            "all_post_rasters_exactly_korean_mask_plus_contour": True,
            "data_load_and_game_mode_consumers_separated": True,
            "load_clear_zone_extended_left_to_tile_x20": True,
            "clear_uses_galmuri11_condensed_8x16": True,
            "stage_title_visible_state_masks_match_source_japanese_font_slots": True,
            "stage_title_korean_slots_verified_against_canonical_galmuri11_condensed": True,
            "stage_title_unique_owner_redirected_to_private_payload": True,
            "changes_restricted_to_two_unique_owner_pointers_and_private_allocations": True,
            "canonical_main_tip_modified": False,
            "stale_state_warning": "The supplied ss1 embeds the old Japanese BG1/title VRAM. Test by booting the candidate/SAV or re-entering this screen so fixed graphics and the stage title are redrawn from ROM.",
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "rom": str(args.out),
        "rom_sha256": sha256(output),
        "sav": str(args.out_sav) if copied_sav else None,
        "manifest": str(args.manifest),
        "changed_bytes": len(changed),
        "clone_size": len(clone),
        "translations": {
            **{key: text for key, (_rect, text, _face, _font_mode) in TARGETS.items()},
            "stage_title": STAGE_KO_TEXT,
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
