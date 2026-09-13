#!/usr/bin/env python3
"""Patch the eight untranslated raw mini-label cells in forecast sprite data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

import analyze_ggen_advance_battle_forecast_raw_cells as analysis
import build_ggen_advance_battle_weapon_fixed_graphics_galmuri7_poc as fixed
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_ROM

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_battle_forecast_ui" / "ggen_advance_battle_forecast_raw_cells_galmuri7_candidate_20260830.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_forecast_raw_cells_galmuri7_20260830.json"
PREVIEW = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_battle_forecast_ui" / "ggen_advance_battle_forecast_raw_cells_galmuri7_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "b689bd85075d494a6e99850e646453961adc47cab937b313a39475d5252eaee1"
EXPECTED_JP_SHA256 = analysis.EXPECTED_JP_SHA256
BACKGROUND_FOR_ROLE = {
    "physical_type": "left",
    "attack": "middle",
    "hit": "middle",
    "ammo": "middle",
    "ranged": "middle",
    "all": "right",
    "melee": "middle",
    "single": "right",
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_cell(rom: bytearray, jp: bytes, translation: str, top_tile_id: int, bottom_tile_id: int, role: str, font: fixed.fontpair.BdfFont) -> dict:
    top_offset = analysis.GRAPHICS_OFFSET + top_tile_id * analysis.TILE_BYTES
    bottom_offset = analysis.GRAPHICS_OFFSET + bottom_tile_id * analysis.TILE_BYTES
    before = bytes(rom[top_offset : top_offset + analysis.TILE_BYTES]) + bytes(rom[bottom_offset : bottom_offset + analysis.TILE_BYTES])
    source = jp[top_offset : top_offset + analysis.TILE_BYTES] + jp[bottom_offset : bottom_offset + analysis.TILE_BYTES]
    gate(before == source, f"raw source cell already differs: {translation}")
    pixels = fixed.decode_8x16(before)

    background_name = BACKGROUND_FOR_ROLE[role]
    background_resource = fixed.BACKGROUND_RESOURCES[background_name]
    background = fixed.decode_8x16(jp[background_resource + fixed.GRAPHIC_REL : background_resource + fixed.GRAPHIC_REL + fixed.GRAPHIC_BYTES])

    restored_shadow = 0
    restored_bright = 0
    for y in range(16):
        for x in range(8):
            value = pixels[y][x]
            if value in fixed.SOURCE_GLYPH_INDICES and value != background[y][x]:
                pixels[y][x] = background[y][x]
                if value == fixed.SHADOW_INDEX:
                    restored_shadow += 1
                else:
                    restored_bright += 1
    gate(restored_shadow > 0 and restored_bright > 0, f"Japanese glyph footprint missing: {translation}")

    glyph = fixed.render_galmuri7(translation, font)
    ink = [[bool(glyph.getpixel((x, y))) for x in range(8)] for y in range(16)]
    contour = [[False] * 8 for _ in range(16)]
    for y in range(16):
        for x in range(8):
            if not ink[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ox, oy = x + dx, y + dy
                    if (dx or dy) and 0 <= ox < 8 and 0 <= oy < 16 and not ink[oy][ox]:
                        contour[oy][ox] = True
    for y in range(16):
        for x in range(8):
            if contour[y][x]:
                pixels[y][x] = fixed.SHADOW_INDEX
            if ink[y][x]:
                pixels[y][x] = fixed.INK_INDEX

    after = fixed.encode_8x16(pixels)
    gate(after != before, f"no patch generated: {translation}")
    rom[top_offset : top_offset + analysis.TILE_BYTES] = after[:analysis.TILE_BYTES]
    rom[bottom_offset : bottom_offset + analysis.TILE_BYTES] = after[analysis.TILE_BYTES:]
    return {
        "translation": translation,
        "role": role,
        "top_tile_id": top_tile_id,
        "bottom_tile_id": bottom_tile_id,
        "top_graphic_file_offset": f"0x{top_offset:08X}",
        "bottom_graphic_file_offset": f"0x{bottom_offset:08X}",
        "background_template": background_name,
        "source_shadow_pixels_restored": restored_shadow,
        "source_bright_pixels_restored": restored_bright,
        "korean_ink_pixels": sum(sum(row) for row in ink),
        "korean_contour_pixels": sum(sum(row) for row in contour),
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
    }


def build_preview(jp: bytes, patched: bytes, out: Path) -> None:
    palette = {i: (i * 17, i * 17, i * 17) for i in range(16)}
    palette.update({4: (50, 50, 50), 6: (100, 100, 100), 7: (130, 130, 130), 8: (160, 160, 160), 9: (190, 190, 190), 10: (210, 210, 210), 13: (200, 180, 80), 14: (230, 205, 105), 15: (255, 240, 145)})
    scale = 5
    image = Image.new("RGB", (8 * scale * len(analysis.LABELS), 16 * scale * 2), (0, 0, 0))
    for column, (_source, _translation, top_tile_id, bottom_tile_id, _role) in enumerate(analysis.LABELS):
        top_offset = analysis.GRAPHICS_OFFSET + top_tile_id * analysis.TILE_BYTES
        bottom_offset = analysis.GRAPHICS_OFFSET + bottom_tile_id * analysis.TILE_BYTES
        for row, data in enumerate((jp, patched)):
            raw = data[top_offset : top_offset + analysis.TILE_BYTES] + data[bottom_offset : bottom_offset + analysis.TILE_BYTES]
            pixels = fixed.decode_8x16(raw)
            tile = Image.new("RGB", (8, 16))
            for y in range(16):
                for x in range(8):
                    tile.putpixel((x, y), palette[pixels[y][x]])
            image.paste(tile.resize((8 * scale, 16 * scale), Image.Resampling.NEAREST), (column * 8 * scale, row * 16 * scale))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--preview", type=Path, default=PREVIEW)
    args = parser.parse_args()

    main_bytes = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(sha256(main_bytes) == EXPECTED_MAIN_SHA256, f"unexpected main TIP hash: {sha256(main_bytes)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"unexpected Japanese ROM hash: {sha256(jp)}")
    gate(main_bytes[analysis.RESOURCE_OFFSET : analysis.GRAPHICS_OFFSET] == jp[analysis.RESOURCE_OFFSET : analysis.GRAPHICS_OFFSET], "forecast resource header/frame tables drift")
    gate(main_bytes[analysis.PALETTE_OFFSET : analysis.PALETTE_OFFSET + 0x60] == jp[analysis.PALETTE_OFFSET : analysis.PALETTE_OFFSET + 0x60], "forecast resource palette drift")

    with ZipFile(args.font_zip) as archive:
        font = fixed.fontpair.load_bdf(archive, "Galmuri7.bdf")

    patched = bytearray(main_bytes)
    reports = []
    for source, translation, top_tile_id, bottom_tile_id, role in analysis.LABELS:
        row = patch_cell(patched, jp, translation, top_tile_id, bottom_tile_id, role, font)
        row["source"] = source
        reports.append(row)

    changed = [index for index, (before, after) in enumerate(zip(main_bytes, patched)) if before != after]
    allowed: set[int] = set()
    for _source, _translation, top_tile_id, bottom_tile_id, _role in analysis.LABELS:
        for tile_id in (top_tile_id, bottom_tile_id):
            start = analysis.GRAPHICS_OFFSET + tile_id * analysis.TILE_BYTES
            allowed.update(range(start, start + analysis.TILE_BYTES))
    gate(changed and all(index in allowed for index in changed), "changes escaped eight raw forecast cells")
    gate(bytes(patched[analysis.RESOURCE_OFFSET : analysis.GRAPHICS_OFFSET]) == main_bytes[analysis.RESOURCE_OFFSET : analysis.GRAPHICS_OFFSET], "resource header/frame tables changed")
    gate(bytes(patched[analysis.PALETTE_OFFSET : analysis.PALETTE_OFFSET + 0x60]) == main_bytes[analysis.PALETTE_OFFSET : analysis.PALETTE_OFFSET + 0x60], "resource palette changed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(patched)
    build_preview(jp, bytes(patched), args.preview)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_raw_cells_galmuri7",
        "result": "PASS",
        "source": {"main_path": str(args.main.relative_to(ADVANCE_ROOT)), "main_sha256": sha256(main_bytes), "japanese_sha256": sha256(jp)},
        "static_ownership": {
            "analysis": "legacy/analysis/ggen_advance_battle_forecast_raw_cells_20260830.json",
            "screen_setup": "0x080394D8",
            "resource_literal": "0x08039638 -> 0x08A8C004",
            "resource_loads": ["0x08039556", "0x0803958A"],
            "sprite_create_calls": ["0x0803955C -> 0x08012B04", "0x08039592 -> 0x08012B04"],
        },
        "sprite_resource": {"file_offset": f"0x{analysis.RESOURCE_OFFSET:08X}", "graphics_file_offset": f"0x{analysis.GRAPHICS_OFFSET:08X}", "palette_file_offset": f"0x{analysis.PALETTE_OFFSET:08X}"},
        "patches": reports,
        "output": {"path": str(args.out.relative_to(ADVANCE_ROOT)), "size": len(patched), "sha256": sha256(bytes(patched)), "preview": str(args.preview.relative_to(ADVANCE_ROOT))},
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "changed_bytes_confined_to_eight_raw_cells": True,
            "resource_header_and_frame_tables_unchanged": True,
            "resource_palette_unchanged": True,
            "all_other_graphic_tiles_unchanged": True,
            "Thumb_code_and_resource_literal_unchanged": True,
            "galmuri7_native_no_scale": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(args.out), "sha256": report["output"]["sha256"], "changed_bytes": len(changed), "patches": len(reports)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
