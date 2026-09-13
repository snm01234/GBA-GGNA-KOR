#!/usr/bin/env python3
"""Patch three measured status-UI graphic badges on top of the current main TIP.

Targets proven from the 2026-08-30 screenshots and static runtime audit:

- resource[40] embedded `持` badge -> `지` (Galmuri7-scale native 7px glyph)
- resource[47] unit-type `盾` badge -> `방패` (Galmuri11-Condensed 8x16 cells)
- resource[52] weapon-range `万` badge -> `만` (same Galmuri7/native-green style as resource[53] `間 -> 간`)

Unlike the historical status builder, this follow-up starts from the *active*
status atlas already embedded in the current 32 MiB main TIP at 0x09240000 and
changes only the measured target tile payloads.  No tilemap, palette, pointer,
or original 16 MiB data is rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import FONT_ZIP  # noqa: E402

MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_badges_ji_shield_man_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_badges_ji_shield_man_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_badges_ji_shield_man_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6"
EXPECTED_JP_SHA256 = status.EXPECTED_JP_SHA256
EXPECTED_ACTIVE_ATLAS_SHA256 = "79bfe0a29e0e4045e9fd4350c2a9697698ae7d9029b067fe255feefc954ff1dd"

# resource[40] is the 32x8 lower unit-status panel.  The screenshot's narrow
# `持` plaque begins at panel pixel x=139 and spans 8x16.  It straddles four
# otherwise-private tiles at tile columns 17/18, rows 0/1.
HOLD_TILES = [[0x176, 0x177], [0x17D, 0x17E]]
HOLD_WINDOW_X = 3  # relative to the 16x16 block formed by HOLD_TILES
HOLD_SOURCE_WINDOW_SHA256 = "26b878aaa76927d0819f5b00d471ee7683feddd3499bdd9c3fcfe4b61e99eefa"
HOLD_TEXT = "지"
HOLD_FACE_INDEX = 10
HOLD_CONTOUR_INDEX = 4

# resource[47], selected as resource_table[40 + unit_type] when unit_type=7.
# The first/last columns are rounded native frame geometry.  Tile 0x172 is also
# used by resource[40], so the patch deliberately changes only the central
# 16-pixel body (private tiles 0x1D8/0x1D9/0x1DC/0x1DD).
SHIELD_TILES = [[0x172, 0x1D8, 0x1D9, 0x1DA], [0x1DB, 0x1DC, 0x1DD, 0x1DE]]
SHIELD_PRIVATE_TILES = [[0x1D8, 0x1D9], [0x1DC, 0x1DD]]
SHIELD_SOURCE_SHA256 = "40181c985e33bf234567fc104c164010baef04c7606649d0f2746f240ddc8762"
SHIELD_TEXT = "방패"
SHIELD_FACE_INDEX = status.INK_INDEX
SHIELD_CONTOUR_INDEX = status.OUTLINE_INDEX

# resource[52] is selected in the weapon-row renderer as the alternate paired
# with resource[53] (`間`, already `간`).  Screenshot + source-glyph matching
# identify resource[52] as `万`; reproduce the approved `간` badge treatment.
MAN_TILES = [[0x1E3, 0x1E4], [0x1E5, 0x1E6]]
MAN_SOURCE_SHA256 = "d65a684379b7bb79b1a115f3aaea6011d90eaa7792a9e7edc73fc897bfbfd537"
MAN_TEXT = "만"
MAN_FACE_INDEX = status.INTERVAL_INK_INDEX
MAN_CONTOUR_INDEX = status.INTERVAL_SHADOW_INDEX


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def pixel_sha(pixels: list[list[int]]) -> str:
    return sha256(bytes(value for row in pixels for value in row))


def read_active_atlas(rom: bytes) -> tuple[bytearray, int, int]:
    pointer = struct.unpack_from("<I", rom, status.RESOURCE_TABLE)[0]
    gate(pointer == status.GRAPHICS_ADDRESS, f"active status atlas pointer drift: 0x{pointer:08X}")
    offset = pointer - 0x08000000
    header = struct.unpack_from("<I", rom, offset)[0]
    gate(header & 0x80000000, "active status atlas is not compressed")
    compressed_len = header & 0xFFFF
    decoded = status.lzss_decompress(rom[offset + 4 : offset + 4 + compressed_len])
    gate(len(decoded) == status.ATLAS_EXPECTED_DECODED, f"active atlas decoded-size drift: {len(decoded)}")
    return bytearray(decoded), offset, compressed_len


def stitch(atlas: bytes | bytearray, tiles: list[list[int]]) -> list[list[int]]:
    rows = len(tiles)
    cols = len(tiles[0])
    gate(rows > 0 and cols > 0 and all(len(row) == cols for row in tiles), "invalid tile grid")
    pixels = [[0] * (cols * 8) for _ in range(rows * 8)]
    for ty, tile_row in enumerate(tiles):
        for tx, tile_id in enumerate(tile_row):
            tile = status.decode_tile(atlas, tile_id)
            for py in range(8):
                pixels[ty * 8 + py][tx * 8 : tx * 8 + 8] = tile[py]
    return pixels


def write_block(atlas: bytearray, tiles: list[list[int]], pixels: list[list[int]]) -> list[dict]:
    rows = len(tiles)
    cols = len(tiles[0])
    gate(len(pixels) == rows * 8 and all(len(row) == cols * 8 for row in pixels), "pixel block shape mismatch")
    changed: list[dict] = []
    for ty, tile_row in enumerate(tiles):
        for tx, tile_id in enumerate(tile_row):
            before = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            tile = [row[tx * 8 : (tx + 1) * 8] for row in pixels[ty * 8 : (ty + 1) * 8]]
            status.encode_tile(atlas, tile_id, tile)
            after = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            changed.append({
                "tile_id": f"0x{tile_id:03X}",
                "changed_bytes": sum(a != b for a, b in zip(before, after)),
                "before_sha256": sha256(before),
                "after_sha256": sha256(after),
            })
    return changed


def contour(mask: list[list[bool]]) -> list[list[bool]]:
    height = len(mask)
    width = len(mask[0])
    out = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if not mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ox, oy = x + dx, y + dy
                    if 0 <= ox < width and 0 <= oy < height and not mask[oy][ox]:
                        out[oy][ox] = True
    return out


def paint_mask(
    pixels: list[list[int]],
    ink_mask: list[list[bool]],
    face_index: int,
    contour_index: int,
) -> tuple[int, int]:
    outline = contour(ink_mask)
    for y in range(len(pixels)):
        for x in range(len(pixels[0])):
            if outline[y][x]:
                pixels[y][x] = contour_index
    for y in range(len(pixels)):
        for x in range(len(pixels[0])):
            if ink_mask[y][x]:
                pixels[y][x] = face_index
    return (
        sum(sum(1 for value in row if value) for row in ink_mask),
        sum(sum(1 for value in row if value) for row in outline),
    )


def patch_hold_badge(atlas: bytearray, font7: fontpair.BdfFont) -> dict:
    before_pixels = stitch(atlas, HOLD_TILES)
    before_full = [row[:] for row in before_pixels]
    source_window = [row[HOLD_WINDOW_X : HOLD_WINDOW_X + 8] for row in before_pixels]
    gate(pixel_sha(source_window) == HOLD_SOURCE_WINDOW_SHA256, "持 source window drift")

    background_rows = status.WEAPON_BADGE_BACKGROUNDS["left_single"]
    background = [[int(ch, 16) for ch in row] for row in background_rows]
    for y in range(16):
        before_pixels[y][HOLD_WINDOW_X : HOLD_WINDOW_X + 8] = background[y][:]

    glyph = status.render_galmuri7_badge(HOLD_TEXT, font7)
    ink = [[bool(glyph.getpixel((x, y))) for x in range(8)] for y in range(16)]
    badge = [row[HOLD_WINDOW_X : HOLD_WINDOW_X + 8] for row in before_pixels]
    ink_pixels, contour_pixels = paint_mask(badge, ink, HOLD_FACE_INDEX, HOLD_CONTOUR_INDEX)
    for y in range(16):
        before_pixels[y][HOLD_WINDOW_X : HOLD_WINDOW_X + 8] = badge[y]

    # The badge lives inside a larger lower-panel tile pair; everything outside
    # the measured 8-pixel window must remain byte/pixel exact.
    for y in range(16):
        for x in range(16):
            if not (HOLD_WINDOW_X <= x < HOLD_WINDOW_X + 8):
                gate(before_pixels[y][x] == before_full[y][x], f"持 neighbour pixel changed at {x},{y}")

    changed = write_block(atlas, HOLD_TILES, before_pixels)
    gate(all(item["changed_bytes"] > 0 for item in changed), "持 tile patch did not touch all four expected tiles")
    return {
        "source": "持",
        "text": HOLD_TEXT,
        "source_resource": 40,
        "resource_file_offset": "0x000DFF9C",
        "resource_map_window_pixels": [139, 0, 8, 16],
        "tiles": changed,
        "font": "Galmuri7.bdf native 6x7 glyph centered in 8x16",
        "background": "measured left_single native green 8x16 plaque",
        "face_palette_index": HOLD_FACE_INDEX,
        "contour_palette_index": HOLD_CONTOUR_INDEX,
        "ink_pixels": ink_pixels,
        "contour_pixels": contour_pixels,
        "japanese_source_window_fully_rebuilt": True,
        "neighbour_pixels_preserved": True,
        "focus_variant": False,
    }


def patch_shield_badge(atlas: bytearray, font8: fontpair.BdfFont) -> dict:
    original = stitch(atlas, SHIELD_TILES)
    gate(pixel_sha(original) == SHIELD_SOURCE_SHA256, "盾 resource[47] source drift")
    pixels = [row[:] for row in original]

    # Clear only the central 16 px where the source glyph lives.  The leftmost
    # 8px tile 0x172 is shared with resource[40], so it is never encoded here.
    background_tile = status.decode_tile(atlas, status.BACKGROUND_TEMPLATE_TILE)
    background_strip = background_tile + list(reversed(background_tile))
    for y in range(16):
        for x in range(8, 24):
            pixels[y][x] = background_strip[y][x % 8]

    ink = [[False] * 16 for _ in range(16)]
    for index, char in enumerate(SHIELD_TEXT):
        glyph = fontpair.render_condensed_8x16_basic(char, font8)
        gate(glyph.size == (8, 16), f"unexpected condensed canvas for {char}: {glyph.size}")
        for y in range(16):
            for x in range(8):
                if glyph.getpixel((x, y)):
                    ink[y][index * 8 + x] = True

    central = [row[8:24] for row in pixels]
    ink_pixels, contour_pixels = paint_mask(central, ink, SHIELD_FACE_INDEX, SHIELD_CONTOUR_INDEX)
    for y in range(16):
        pixels[y][8:24] = central[y]

    # Do not write the shared/rounded outer columns at all.
    private_pixels = [row[8:24] for row in pixels]
    changed = write_block(atlas, SHIELD_PRIVATE_TILES, private_pixels)

    after = stitch(atlas, SHIELD_TILES)
    for y in range(16):
        gate(after[y][:8] == original[y][:8], f"盾 shared left frame changed at row {y}")
        gate(after[y][24:] == original[y][24:], f"盾 right frame changed at row {y}")

    return {
        "source": "盾",
        "text": SHIELD_TEXT,
        "source_resource": 47,
        "resource_file_offset": "0x000E0218",
        "resource_tiles": [[f"0x{x:03X}" for x in row] for row in SHIELD_TILES],
        "private_tiles_changed": changed,
        "shared_tile_0x172_preserved": True,
        "outer_rounded_frame_preserved": True,
        "font": "Galmuri11-Condensed.bdf via native 8x16 condensed cells",
        "face_palette_index": SHIELD_FACE_INDEX,
        "contour_palette_index": SHIELD_CONTOUR_INDEX,
        "ink_pixels": ink_pixels,
        "contour_pixels": contour_pixels,
        "focus_variant": False,
    }


def patch_man_badge(atlas: bytearray, font7: fontpair.BdfFont) -> dict:
    original = stitch(atlas, MAN_TILES)
    gate(pixel_sha(original) == MAN_SOURCE_SHA256, "万 resource[52] source drift")

    template = status.INTERVAL_NATIVE_GREEN_BACKGROUND
    gate(len(template) == 16 and all(len(row) == 16 for row in template), "16x16 green template drift")
    pixels = [[int(ch, 16) for ch in row] for row in template]

    glyph_info = font7.glyphs.get(ord(MAN_TEXT))
    gate(glyph_info is not None, "Galmuri7 glyph missing: 만")
    gate((glyph_info.width, glyph_info.height) == (7, 7), f"unexpected Galmuri7 BBX for 만: {glyph_info.width}x{glyph_info.height}")
    glyph = font7.render(MAN_TEXT, glyph_info.width, glyph_info.height)
    x0 = (16 - glyph.width) // 2
    y0 = (16 - glyph.height) // 2
    ink = [[False] * 16 for _ in range(16)]
    for y in range(glyph.height):
        for x in range(glyph.width):
            if glyph.getpixel((x, y)):
                ink[y0 + y][x0 + x] = True
    ink_pixels, contour_pixels = paint_mask(pixels, ink, MAN_FACE_INDEX, MAN_CONTOUR_INDEX)
    changed = write_block(atlas, MAN_TILES, pixels)

    return {
        "source": "万",
        "text": MAN_TEXT,
        "source_resource": 52,
        "resource_file_offset": "0x000E024C",
        "tiles": changed,
        "font": "Galmuri7.bdf native 7x7 centered in 16x16",
        "style_reference": "resource[53] 間 -> 간",
        "background": "same native green 16x16 template as 간",
        "face_palette_index": MAN_FACE_INDEX,
        "contour_palette_index": MAN_CONTOUR_INDEX,
        "ink_pixels": ink_pixels,
        "contour_pixels": contour_pixels,
        "focus_variant": False,
    }


def build_preview(atlas: bytes, out: Path) -> None:
    specs = [
        ("지", HOLD_TILES),
        ("방패", SHIELD_TILES),
        ("만", MAN_TILES),
    ]
    scale = 4
    pad = 8
    label_h = 18
    max_w = max(len(tiles[0]) * 8 for _, tiles in specs)
    width = max_w * scale + pad * 2
    height = sum(len(tiles) * 8 * scale + label_h for _, tiles in specs) + pad
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    palette = {
        4: (20, 45, 35, 255), 5: (116, 57, 1, 255), 6: (239, 41, 15, 255),
        7: (80, 180, 120, 255), 8: (30, 150, 105, 255), 9: (255, 181, 40, 255),
        10: (251, 229, 59, 255), 11: (255, 255, 141, 255), 13: (80, 115, 80, 255),
        14: (210, 235, 210, 255), 15: (255, 255, 255, 255),
    }
    y_cursor = pad
    for _, tiles in specs:
        pixels = stitch(atlas, tiles)
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                rgba = palette.get(value, (100, 100, 100, 255))
                for sy in range(scale):
                    for sx in range(scale):
                        image.putpixel((pad + x * scale + sx, y_cursor + y * scale + sy), rgba)
        y_cursor += len(pixels) * scale + label_h
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", type=Path, default=MAIN_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    args = parser.parse_args()

    main_rom = args.main.read_bytes()
    jp_rom = JP_ROM.read_bytes()
    gate(len(main_rom) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    gate(sha256(main_rom) == EXPECTED_MAIN_SHA256, f"main TIP hash drift: {sha256(main_rom)}")
    gate(sha256(jp_rom) == EXPECTED_JP_SHA256, "clean Japanese ROM hash mismatch")

    atlas, active_offset, compressed_len = read_active_atlas(main_rom)
    before_atlas = bytes(atlas)
    gate(sha256(before_atlas) == EXPECTED_ACTIVE_ATLAS_SHA256, f"active atlas hash drift: {sha256(before_atlas)}")

    # Prove all three requested source graphics are still byte-identical to the
    # clean Japanese atlas inside the current main TIP before touching them.
    jp_header = struct.unpack_from("<I", jp_rom, status.ATLAS_RESOURCE)[0]
    jp_comp_len = jp_header & 0xFFFF
    jp_atlas = status.lzss_decompress(jp_rom[status.ATLAS_RESOURCE + 4 : status.ATLAS_RESOURCE + 4 + jp_comp_len])
    gate(stitch(atlas, HOLD_TILES) == stitch(jp_atlas, HOLD_TILES), "持 source tiles already differ from Japanese base")
    gate(stitch(atlas, SHIELD_TILES) == stitch(jp_atlas, SHIELD_TILES), "盾 source tiles already differ from Japanese base")
    gate(stitch(atlas, MAN_TILES) == stitch(jp_atlas, MAN_TILES), "万 source tiles already differ from Japanese base")

    shared_172_before = bytes(atlas[0x172 * 32 : 0x172 * 32 + 32])
    interval_before = bytes(atlas[0x1E7 * 32 : 0x1EB * 32])

    with ZipFile(args.font_zip) as archive:
        font8 = fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf")
        font7 = fontpair.load_bdf(archive, "Galmuri7.bdf")

    hold_report = patch_hold_badge(atlas, font7)
    shield_report = patch_shield_badge(atlas, font8)
    man_report = patch_man_badge(atlas, font7)

    gate(bytes(atlas[0x172 * 32 : 0x172 * 32 + 32]) == shared_172_before, "shared tile 0x172 changed")
    gate(bytes(atlas[0x1E7 * 32 : 0x1EB * 32]) == interval_before, "existing 간 resource[53] changed")
    gate(len(atlas) == status.ATLAS_EXPECTED_DECODED, "decoded atlas size changed")

    changed_tile_ids = sorted(
        tile_id
        for tile_id in range(len(atlas) // 32)
        if atlas[tile_id * 32 : tile_id * 32 + 32] != before_atlas[tile_id * 32 : tile_id * 32 + 32]
    )
    expected_changed = sorted({0x176, 0x177, 0x17D, 0x17E, 0x1D8, 0x1D9, 0x1DC, 0x1DD, 0x1E3, 0x1E4, 0x1E5, 0x1E6})
    gate(changed_tile_ids == expected_changed, f"unexpected changed tile set: {[hex(x) for x in changed_tile_ids]}")

    rebuilt = status.literal_only_compress(bytes(atlas))
    gate(len(rebuilt) == compressed_len + 4, "active compressed resource footprint changed")
    gate(status.lzss_decompress(rebuilt[4:]) == bytes(atlas), "compression round-trip mismatch")

    candidate = bytearray(main_rom)
    candidate[active_offset : active_offset + len(rebuilt)] = rebuilt
    gate(candidate[:0x01000000] == main_rom[:0x01000000], "original 16 MiB changed")
    diff_offsets = [i for i, (a, b) in enumerate(zip(candidate, main_rom)) if a != b]
    gate(diff_offsets, "candidate contains no changes")
    gate(min(diff_offsets) >= active_offset and max(diff_offsets) < active_offset + len(rebuilt), "changes escaped active status atlas allocation")
    gate(struct.unpack_from("<I", candidate, status.RESOURCE_TABLE)[0] == status.GRAPHICS_ADDRESS, "status pointer changed unexpectedly")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    build_preview(bytes(atlas), args.preview)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_badge_followup_20260830",
        "result": "PASS",
        "source_main": {"path": str(args.main.relative_to(ROOT)), "sha256": sha256(main_rom), "size": len(main_rom)},
        "output": {"path": str(args.out.relative_to(ROOT)), "sha256": sha256(candidate), "size": len(candidate)},
        "active_status_atlas": {
            "pointer": f"0x{status.GRAPHICS_ADDRESS:08X}",
            "file_offset": f"0x{active_offset:08X}",
            "decoded_size": len(atlas),
            "decoded_sha256_before": sha256(before_atlas),
            "decoded_sha256_after": sha256(atlas),
            "compressed_body_length": compressed_len,
            "compression_round_trip": True,
        },
        "runtime_contract": {
            "resource_table": "0x080E0518",
            "tile_blitter": "0x0800277C",
            "持": {
                "path": "0x0806C934 lower-status renderer -> resource_table[40] (+0xA0) -> 0x0800277C",
                "resource": 40,
                "embedded_window": "panel x=139..146, y=0..15; displayed with lower panel at tile-row y=12",
            },
            "盾": {
                "path": "0x0806C620 -> 0x08005518 unit-type accessor -> resource_table[40 + unit_type]; unit_type=7 -> resource[47] -> 0x0800277C",
                "resource": 47,
            },
            "万": {
                "path": "0x0806CA68 weapon-row renderer; 0x0806CCA8..0x0806CCE4 selects resource[52] versus resource[53] and blits via 0x0800277C",
                "resource": 52,
                "paired_reference": "resource[53] 間 -> 간",
            },
        },
        "targets": [hold_report, shield_report, man_report],
        "verification": {
            "result": "PASS",
            "main_tip_hash_verified": True,
            "requested_source_tiles_equal_clean_japanese_before_patch": True,
            "changed_tile_ids": [f"0x{x:03X}" for x in changed_tile_ids],
            "changed_tile_count": len(changed_tile_ids),
            "shared_tile_0x172_preserved": True,
            "existing_interval_resource53_preserved": True,
            "palette_modified": False,
            "tilemap_modified": False,
            "resource_pointer_modified": False,
            "original_16MiB_unchanged": True,
            "decoded_atlas_size_unchanged": True,
            "compressed_footprint_unchanged": True,
            "focus_or_normal_alternate_resource_detected_for_targets": False,
            "source_shadow_or_contour_removed_by_full_target_window_rebuild": True,
        },
        "preview": str(args.preview.relative_to(ROOT)),
        "measurement_checkpoints": [
            "unit status lower panel: `持` position should read `지`; verify no old Japanese shadow remains and the following pale panel edge is intact",
            "unit type badge: shield-equipped sample should read `방패`; verify left rounded edge (shared tile 0x172) and right rounded edge remain unchanged",
            "weapon rows that previously showed `万` should read `만`; compare directly with approved `간` rows for size/background/contour tone",
            "switch several unit/weapon rows to ensure resource[53] `간`, existing `사/근/단/전`, and lower-status `남은횟수` are unchanged",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": sha256(candidate),
        "manifest": str(args.manifest),
        "preview": str(args.preview),
        "changed_tiles": [f"0x{x:03X}" for x in changed_tile_ids],
        "changed_rom_bytes": len(diff_offsets),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
