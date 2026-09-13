#!/usr/bin/env python3
"""Build the exhaustive `持 -> 지` status-family follow-up candidate.

This candidate carries forward the already measured-good `盾 -> 방패` and
`万 -> 만` edits, but replaces the first `持` implementation with a full
consumer closure:

* resource[12] private right-rounded copy
* resource[14]/[62]/[63] shared prefix copy (0x09F/0x0A0)
* resource[40] embedded lower-status copy, including the Japanese spill at the
  right edge that the previous x=3..10 patch left behind

All edits remain inside the active 16,608-byte status atlas already allocated in
the 32 MiB main TIP.  No palette, tilemap, resource pointer, or original 16 MiB
ROM data is changed.
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

import analyze_ggen_advance_hold_badge_consumers_20260830 as audit  # noqa: E402
import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402
import build_ggen_advance_status_badge_followup_20260830 as prior  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import FONT_ZIP  # noqa: E402

MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_MANIFEST = ROOT / "integrated" / "main_tip" / "ggen_advance_main_tip_manifest.json"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_badges_hold_full_followup_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_badges_hold_full_followup_preview_20260830.png"

HOLD_TEXT = "지"
HOLD_FACE_INDEX = 10
HOLD_CONTOUR_INDEX = 4

# Standalone 1x2 right-rounded copy (resource[12]).
HOLD_STANDALONE_TILES = [[0x09B], [0x09C]]
# Shared prefix used by resources[14], [62], [63].
HOLD_SHARED_PREFIX_TILES = [[0x09F], [0x0A0]]
# Embedded copy in resource[40].  The visible narrow plaque itself starts at
# x=3 (previous patch placement), while the original Japanese glyph spills into
# x=11..12.  We retain the measured `지` placement and clear the spill tail.
HOLD_EMBEDDED_TILES = [[0x176, 0x177], [0x17D, 0x17E]]
HOLD_EMBEDDED_BADGE_X = 3
HOLD_EMBEDDED_BADGE_W = 8
HOLD_EMBEDDED_TAIL_X = (11, 12)

# Blank connected prefix: flat left/right continuation, native green center.
CONNECTED_PREFIX_BACKGROUND = [
    "66666666",
    "77777777",
    *(["88888888"] * 12),
    "77777777",
    "66666666",
]

EXPECTED_TARGET_TILES = {
    0x09B, 0x09C, 0x09F, 0x0A0,
    0x176, 0x177, 0x17D, 0x17E,
    0x1D8, 0x1D9, 0x1DC, 0x1DD,
    0x1E3, 0x1E4, 0x1E5, 0x1E6,
}

PRESERVE_SUFFIX_TILES = {
    # resource[14]
    0x09D, 0x09E,
    # resource[62]
    0x1EF, 0x1F0,
    # resource[63]
    0x1F1, 0x1F2,
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def render_badge_mask(font7: fontpair.BdfFont) -> list[list[bool]]:
    glyph = status.render_galmuri7_badge(HOLD_TEXT, font7)
    gate(glyph.size == (8, 16), f"unexpected Galmuri7 badge canvas: {glyph.size}")
    return [[bool(glyph.getpixel((x, y))) for x in range(8)] for y in range(16)]


def paint_hold_background(background_rows: list[str], font7: fontpair.BdfFont) -> tuple[list[list[int]], int, int]:
    gate(len(background_rows) == 16 and all(len(row) == 8 for row in background_rows), "hold background must be 8x16")
    pixels = [[int(ch, 16) for ch in row] for row in background_rows]
    mask = render_badge_mask(font7)
    ink, contour = prior.paint_mask(pixels, mask, HOLD_FACE_INDEX, HOLD_CONTOUR_INDEX)
    return pixels, ink, contour


def patch_hold_standalone(atlas: bytearray, font7: fontpair.BdfFont) -> dict:
    source = prior.stitch(atlas, HOLD_STANDALONE_TILES)
    # resource[12] is the horizontal reverse of the approved left-rounded
    # one-cell background.  Rebuild the entire private 8x16 cell to guarantee
    # no Japanese shadow survives.
    right_single = [row[::-1] for row in status.WEAPON_BADGE_BACKGROUNDS["left_single"]]
    pixels, ink, contour = paint_hold_background(right_single, font7)
    changed = prior.write_block(atlas, HOLD_STANDALONE_TILES, pixels)
    gate(all(item["changed_bytes"] > 0 for item in changed), "resource[12] 持 patch did not change both tiles")
    return {
        "source": "持",
        "text": HOLD_TEXT,
        "resource_indices": [12],
        "resource_file_offset": "0x000DEAD8",
        "tiles": changed,
        "source_sha256": prior.pixel_sha(source),
        "background": "right-rounded native 8x16 plaque (reverse of approved left_single template)",
        "font": "Galmuri7.bdf native 6x7 centered in 8x16",
        "face_palette_index": HOLD_FACE_INDEX,
        "contour_palette_index": HOLD_CONTOUR_INDEX,
        "ink_pixels": ink,
        "contour_pixels": contour,
    }


def patch_hold_shared_prefix(atlas: bytearray, font7: fontpair.BdfFont) -> dict:
    source = prior.stitch(atlas, HOLD_SHARED_PREFIX_TILES)
    pixels, ink, contour = paint_hold_background(CONNECTED_PREFIX_BACKGROUND, font7)
    changed = prior.write_block(atlas, HOLD_SHARED_PREFIX_TILES, pixels)
    gate(all(item["changed_bytes"] > 0 for item in changed), "shared 持 prefix patch did not change both tiles")
    return {
        "source": "持",
        "text": HOLD_TEXT,
        "resource_indices": [14, 62, 63],
        "shared_tiles": changed,
        "source_sha256": prior.pixel_sha(source),
        "background": "connected native green 8x16 prefix; flat continuation edges preserved by resource suffix cells",
        "font": "Galmuri7.bdf native 6x7 centered in 8x16",
        "face_palette_index": HOLD_FACE_INDEX,
        "contour_palette_index": HOLD_CONTOUR_INDEX,
        "ink_pixels": ink,
        "contour_pixels": contour,
        "suffix_policy": {
            "resource14": ["0x09D", "0x09E"],
            "resource62": ["0x1EF", "0x1F0"],
            "resource63": ["0x1F1", "0x1F2"],
            "all_suffix_tiles_byte_exact_preserved": True,
        },
    }


def patch_hold_embedded(atlas: bytearray, font7: fontpair.BdfFont) -> dict:
    original = prior.stitch(atlas, HOLD_EMBEDDED_TILES)
    pixels = [row[:] for row in original]

    # Keep the previous candidate's visually accepted narrow-plaque placement:
    # native left_single background at x=3..10, with Galmuri7 `지` centered in
    # that 8px plaque.
    background = [[int(ch, 16) for ch in row] for row in status.WEAPON_BADGE_BACKGROUNDS["left_single"]]
    for y in range(16):
        pixels[y][HOLD_EMBEDDED_BADGE_X : HOLD_EMBEDDED_BADGE_X + HOLD_EMBEDDED_BADGE_W] = background[y][:]
    mask = render_badge_mask(font7)
    badge = [row[HOLD_EMBEDDED_BADGE_X : HOLD_EMBEDDED_BADGE_X + HOLD_EMBEDDED_BADGE_W] for row in pixels]
    ink, contour = prior.paint_mask(badge, mask, HOLD_FACE_INDEX, HOLD_CONTOUR_INDEX)
    for y in range(16):
        pixels[y][HOLD_EMBEDDED_BADGE_X : HOLD_EMBEDDED_BADGE_X + HOLD_EMBEDDED_BADGE_W] = badge[y]

    # Root-cause fix: the Japanese source face is centered two pixels farther
    # right than the 8px replacement plaque.  The old patch ended at x=10 and
    # left source pixels in x=11/12.  For those two columns the adjacent x=13
    # pixel is the measured continuous native panel fill on every scanline.
    # Clear every source deviation in x=11/12 back to that row-native value.
    cleared_tail: list[list[int]] = []
    for y in range(16):
        row_background = original[y][13]
        for x in HOLD_EMBEDDED_TAIL_X:
            if original[y][x] == row_background:
                continue
            pixels[y][x] = row_background
            cleared_tail.append([x, y])
    gate(len(cleared_tail) == 22, f"embedded 持 tail footprint drift: {len(cleared_tail)}")
    gate(max(x for x, _ in cleared_tail) == 12, "embedded 持 tail no longer reaches x=12")

    # Outside the rebuilt plaque x=3..10 and measured spill x=11..12, preserve
    # the surrounding panel exactly.
    mutable_x = set(range(HOLD_EMBEDDED_BADGE_X, HOLD_EMBEDDED_BADGE_X + HOLD_EMBEDDED_BADGE_W)) | set(HOLD_EMBEDDED_TAIL_X)
    for y in range(16):
        for x in range(16):
            if x not in mutable_x:
                gate(pixels[y][x] == original[y][x], f"embedded 持 neighbour changed at {x},{y}")

    changed = prior.write_block(atlas, HOLD_EMBEDDED_TILES, pixels)
    gate(all(item["changed_bytes"] > 0 for item in changed), "embedded 持 patch did not change all four expected tiles")
    return {
        "source": "持",
        "text": HOLD_TEXT,
        "resource_indices": [40],
        "resource_file_offset": "0x000DFF9C",
        "block_tiles": changed,
        "replacement_plaque_window": [HOLD_EMBEDDED_BADGE_X, HOLD_EMBEDDED_BADGE_X + HOLD_EMBEDDED_BADGE_W - 1],
        "japanese_source_face_cell": [5, 12],
        "right_tail_columns_cleared": list(HOLD_EMBEDDED_TAIL_X),
        "right_tail_pixels_cleared": len(cleared_tail),
        "right_tail_coordinates": cleared_tail,
        "tail_background_reference_column": 13,
        "font": "Galmuri7.bdf native 6x7 centered in the measured 8x16 plaque",
        "background": "approved left_single plaque + row-native adjacent panel fill for Japanese spill tail",
        "face_palette_index": HOLD_FACE_INDEX,
        "contour_palette_index": HOLD_CONTOUR_INDEX,
        "ink_pixels": ink,
        "contour_pixels": contour,
        "neighbour_pixels_outside_plaque_and_tail_preserved": True,
    }


def resource_tiles(data: bytes, index: int) -> list[int]:
    ptr = struct.unpack_from("<I", data, status.RESOURCE_TABLE + index * 4)[0]
    gate(0x08000000 <= ptr < 0x09000000, f"resource[{index}] pointer invalid")
    off = ptr - 0x08000000
    w, h = data[off], data[off + 1]
    cells = struct.unpack_from(f"<{w*h}H", data, off + 4)
    return [cell & 0x03FF for cell in cells]


def build_preview(atlas: bytes, out: Path) -> None:
    # Show each distinct `지` composition plus the carried-forward approved
    # `방패`/`만` items in one static QA sheet.
    specs = [
        ("지 standalone r12", HOLD_STANDALONE_TILES),
        ("지 shared r14 prefix", [[0x09F, 0x09D], [0x0A0, 0x09E]]),
        ("지 embedded r40", HOLD_EMBEDDED_TILES),
        ("방패 r47", prior.SHIELD_TILES),
        ("만 r52", prior.MAN_TILES),
    ]
    scale = 4
    pad = 8
    gap = 20
    max_w = max(len(tiles[0]) * 8 for _, tiles in specs)
    width = max_w * scale + pad * 2
    height = sum(len(tiles) * 8 * scale + gap for _, tiles in specs) + pad
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    palette = {
        3: (70, 45, 10, 255), 4: (20, 45, 35, 255), 5: (116, 57, 1, 255),
        6: (239, 41, 15, 255), 7: (80, 180, 120, 255), 8: (30, 150, 105, 255),
        9: (255, 181, 40, 255), 10: (251, 229, 59, 255), 11: (255, 255, 141, 255),
        13: (80, 115, 80, 255), 14: (210, 235, 210, 255), 15: (255, 255, 255, 255),
    }
    y_cursor = pad
    for _label, tiles in specs:
        pixels = prior.stitch(atlas, tiles)
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                rgba = palette.get(value, (100, 100, 100, 255))
                for sy in range(scale):
                    for sx in range(scale):
                        image.putpixel((pad + x * scale + sx, y_cursor + y * scale + sy), rgba)
        y_cursor += len(pixels) * scale + gap
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main", type=Path, default=MAIN_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    ap.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    args = ap.parse_args()

    main_rom = args.main.read_bytes()
    jp_rom = JP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    gate(len(main_rom) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    gate(main_manifest["sha256"] == sha256(main_rom), "main TIP manifest/hash mismatch")
    gate(sha256(jp_rom) == status.EXPECTED_JP_SHA256, "clean Japanese ROM hash mismatch")

    atlas, active_offset, compressed_len = prior.read_active_atlas(main_rom)
    before_atlas = bytes(atlas)

    # Clean Japanese atlas supplies the immutable source reference for all new
    # target tiles.  This avoids inheriting a failed/partial older candidate.
    jp_header = struct.unpack_from("<I", jp_rom, status.ATLAS_RESOURCE)[0]
    jp_comp_len = jp_header & 0xFFFF
    jp_atlas = status.lzss_decompress(jp_rom[status.ATLAS_RESOURCE + 4 : status.ATLAS_RESOURCE + 4 + jp_comp_len])
    gate(len(jp_atlas) == status.ATLAS_EXPECTED_DECODED, "Japanese decoded atlas size drift")

    for tile_id in EXPECTED_TARGET_TILES:
        gate(
            before_atlas[tile_id * 32 : tile_id * 32 + 32] == jp_atlas[tile_id * 32 : tile_id * 32 + 32],
            f"target tile 0x{tile_id:03X} already differs from clean Japanese source",
        )

    # Preserve non-target neighbors and already-approved status work.
    suffix_before = {tile_id: bytes(atlas[tile_id * 32 : tile_id * 32 + 32]) for tile_id in PRESERVE_SUFFIX_TILES}
    shield_shared_before = bytes(atlas[0x172 * 32 : 0x173 * 32])
    interval_before = bytes(atlas[0x1E7 * 32 : 0x1EB * 32])
    resource64_before = bytes(atlas[0x1F3 * 32 : 0x1FB * 32])
    resource65_before = bytes(atlas[0x1FB * 32 : 0x203 * 32])

    with ZipFile(args.font_zip) as archive:
        font8 = fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf")
        font7 = fontpair.load_bdf(archive, "Galmuri7.bdf")

    hold_standalone = patch_hold_standalone(atlas, font7)
    hold_shared = patch_hold_shared_prefix(atlas, font7)
    hold_embedded = patch_hold_embedded(atlas, font7)
    shield_report = prior.patch_shield_badge(atlas, font8)
    man_report = prior.patch_man_badge(atlas, font7)

    for tile_id, expected in suffix_before.items():
        gate(bytes(atlas[tile_id * 32 : tile_id * 32 + 32]) == expected, f"suffix tile 0x{tile_id:03X} changed")
    gate(bytes(atlas[0x172 * 32 : 0x173 * 32]) == shield_shared_before, "shield shared tile 0x172 changed")
    gate(bytes(atlas[0x1E7 * 32 : 0x1EB * 32]) == interval_before, "approved 간 resource[53] changed")
    gate(bytes(atlas[0x1F3 * 32 : 0x1FB * 32]) == resource64_before, "resource[64] changed")
    gate(bytes(atlas[0x1FB * 32 : 0x203 * 32]) == resource65_before, "resource[65] changed")
    gate(len(atlas) == status.ATLAS_EXPECTED_DECODED, "decoded atlas size changed")

    changed_tile_ids = {
        tile_id
        for tile_id in range(len(atlas) // 32)
        if atlas[tile_id * 32 : tile_id * 32 + 32] != before_atlas[tile_id * 32 : tile_id * 32 + 32]
    }
    gate(changed_tile_ids == EXPECTED_TARGET_TILES, f"unexpected changed tile set: {[hex(x) for x in sorted(changed_tile_ids)]}")

    rebuilt = status.literal_only_compress(bytes(atlas))
    gate(len(rebuilt) == compressed_len + 4, "active compressed status-atlas footprint changed")
    gate(status.lzss_decompress(rebuilt[4:]) == bytes(atlas), "compression round-trip mismatch")

    candidate = bytearray(main_rom)
    candidate[active_offset : active_offset + len(rebuilt)] = rebuilt
    gate(candidate[:0x01000000] == main_rom[:0x01000000], "original 16 MiB changed")
    gate(struct.unpack_from("<I", candidate, status.RESOURCE_TABLE)[0] == status.GRAPHICS_ADDRESS, "status atlas pointer changed")
    diff_offsets = [i for i, (new, old) in enumerate(zip(candidate, main_rom)) if new != old]
    gate(diff_offsets, "candidate contains no changes")
    gate(min(diff_offsets) >= active_offset and max(diff_offsets) < active_offset + len(rebuilt), "ROM changes escaped active status-atlas allocation")

    # Resource tables/tilemaps remain byte exact; only atlas tile payloads move.
    for index in (12, 14, 40, 47, 52, 53, 62, 63, 64, 65):
        ptr = struct.unpack_from("<I", main_rom, status.RESOURCE_TABLE + index * 4)[0]
        off = ptr - 0x08000000
        w, h = main_rom[off], main_rom[off + 1]
        size = 4 + w * h * 2
        gate(candidate[off : off + size] == main_rom[off : off + size], f"resource[{index}] tilemap changed")

    # Confirm the complete source-family consumer census still closes at exactly
    # resources 12/14/40/62/63 on the clean atlas.
    resources = [row for idx in range(audit.RESOURCE_COUNT) if (row := audit.read_resource(jp_rom, idx)) is not None]
    hits, all_hits = audit.scan_face_pattern(resources, jp_atlas)
    gate({row["resource_index"] for row in hits} == audit.EXPECTED_HIT_RESOURCES, "hold consumer census drift")
    gate(all(row["palette_index"] == 10 for row in all_hits), "alternate-palette exact hold copy appeared")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    build_preview(bytes(atlas), args.preview)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_badges_hold_full_followup_20260830",
        "result": "PASS",
        "source_main": {
            "path": str(args.main.relative_to(ROOT)),
            "sha256": sha256(main_rom),
            "size": len(main_rom),
            "promotion_reason": main_manifest.get("promotion_reason"),
        },
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
        "hold_consumer_closure": {
            "all_69_resources_scanned": True,
            "exact_source_resources": [12, 14, 40, 62, 63],
            "renderer_0x0806C548_resources": [12, 14, 62, 63],
            "renderer_0x0806C10C_resources": [12, 14, 62, 63],
            "renderer_0x0806C934_resources": [40],
            "resources_64_65_scanned_and_preserved": True,
            "audit": "legacy/analysis/ggen_advance_hold_badge_consumers_20260830.json",
        },
        "targets": {
            "持_to_지": [hold_standalone, hold_shared, hold_embedded],
            "盾_to_방패_carried_forward": shield_report,
            "万_to_만_carried_forward": man_report,
        },
        "previous_residue_fix": {
            "old_replacement_plaque_window": [3, 10],
            "japanese_source_face_cell": [5, 12],
            "cleared_right_tail_columns": [11, 12],
            "cleared_right_tail_pixels": hold_embedded["right_tail_pixels_cleared"],
            "reason": "previous patch rebuilt the 8px plaque but did not clear the wider Japanese source glyph/shadow spill into x=11..12",
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_hash_verified": True,
            "clean_japanese_source_verified_for_all_target_tiles": True,
            "changed_tile_ids": [f"0x{x:03X}" for x in sorted(changed_tile_ids)],
            "changed_tile_count": len(changed_tile_ids),
            "resource14_62_63_suffix_tiles_preserved": True,
            "shield_shared_tile_0x172_preserved": True,
            "approved_interval_resource53_preserved": True,
            "resources64_65_preserved": True,
            "palette_modified": False,
            "tilemap_modified": False,
            "resource_pointer_modified": False,
            "original_16MiB_unchanged": True,
            "decoded_atlas_size_unchanged": True,
            "compressed_footprint_unchanged": True,
            "status_hold_consumer_census_closed": True,
        },
        "preview": str(args.preview.relative_to(ROOT)),
        "measurement_checkpoints": [
            "lower unit-status panel: `지` right side must have no three-dot/Japanese residue; adjacent pale panel geometry must remain intact",
            "full unit information/status screen: every prior `持` variant selected through resources 12/14/62/63 must show `지`",
            "split/list/detail unit screen: the same resource 12/14/62/63 variants must show `지` across row/state changes",
            "switch unit states that alter the suffix after the shared `지` prefix and verify the suffix graphics remain unchanged",
            "verify already-approved `방패` and `만` remain visually identical to the previous candidate; `간`, resource64/65 and other status badges must not regress",
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
        "hold_resources": [12, 14, 40, 62, 63],
        "right_tail_pixels_cleared": hold_embedded["right_tail_pixels_cleared"],
        "changed_tiles": [f"0x{x:03X}" for x in sorted(changed_tile_ids)],
        "changed_rom_bytes": len(diff_offsets),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
