#!/usr/bin/env python3
"""Build a scoped Korean HIT!/CRITICAL!! graphics candidate.

The promoted 32 MiB Korean ROM contains the same 24 source tiles at the start
of 20 battle-unit sprite resources.  This builder replaces only those 24 tiles
in every resource.  Resource headers, palettes, animation data, unit graphics
from tile 24 onward, and the pointer table remain byte-exact.
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

import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
EXPECTED_MAIN_SHA256 = "219ab72224311a2e774e031da3344a4d56b0cf25c6e042af816e6a816ec0ae54"
ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_hit_critical_ss1_20260904.json"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_hit_critical_ko"
OUT_ROM = OUT_DIR / "ggen_advance_hit_critical_ko_candidate_20260904.gba"
OUT_PREVIEW = OUT_DIR / "ggen_advance_hit_critical_ko_preview_20260904.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_hit_critical_ko_candidate_20260904.json"
FONT_MEMBER = "Galmuri11.bdf"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


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


def encode_canvas(canvas: list[list[int]]) -> bytes:
    height = len(canvas)
    width = len(canvas[0]) if canvas else 0
    gate(height % 8 == 0 and width % 8 == 0, "canvas is not tile-aligned")
    gate(all(len(row) == width for row in canvas), "canvas row width drift")
    out = bytearray()
    tiles_w, tiles_h = width // 8, height // 8
    for ty in range(tiles_h):
        for tx in range(tiles_w):
            tile = [canvas[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
            out += encode_tile(tile)
    return bytes(out)


def palette_rgb(raw: bytes) -> list[tuple[int, int, int]]:
    gate(len(raw) >= 32, "palette too short")
    colors = []
    for index in range(16):
        value = struct.unpack_from("<H", raw, index * 2)[0]
        r = (value & 0x1F) * 255 // 31
        g = ((value >> 5) & 0x1F) * 255 // 31
        b = ((value >> 10) & 0x1F) * 255 // 31
        colors.append((r, g, b))
    return colors


def render_canvas(canvas: list[list[int]], colors: list[tuple[int, int, int]]) -> Image.Image:
    h = len(canvas)
    w = len(canvas[0]) if canvas else 0
    image = Image.new("RGB", (w, h))
    image.putdata([colors[value] for row in canvas for value in row])
    return image


def glyph_mask(text: str, font: fontpair.BdfFont, hangul_cell: int = 12, punctuation_cell: int = 6) -> tuple[set[tuple[int, int]], int]:
    widths = [punctuation_cell if ch == "!" else hangul_cell for ch in text]
    total_width = sum(widths)
    ink: set[tuple[int, int]] = set()
    cursor = 0
    for ch, width in zip(text, widths):
        cell = font.render(ch, width, 12)
        for y in range(12):
            for x in range(width):
                if cell.getpixel((x, y)):
                    ink.add((cursor + x, y))
        cursor += width
    return ink, total_width


def dilate(points: set[tuple[int, int]], radius: int, width: int, height: int) -> set[tuple[int, int]]:
    return {
        (x + dx, y + dy)
        for x, y in points
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
        if 0 <= x + dx < width and 0 <= y + dy < height
    }


def translate_mask(mask: set[tuple[int, int]], x0: int, y0: int) -> set[tuple[int, int]]:
    return {(x0 + x, y0 + y) for x, y in mask}


def build_hit(font: fontpair.BdfFont) -> tuple[list[list[int]], dict[str, object]]:
    width, height = 32, 16
    raw_ink, text_width = glyph_mask("히트!", font)
    x0 = (width - text_width) // 2
    y0 = 2
    ink = translate_mask(raw_ink, x0, y0)
    gate(ink and all(0 <= x < width and 0 <= y < height for x, y in ink), "hit ink overflow")
    outline = dilate(ink, 1, width, height) - ink

    canvas = [[0] * width for _ in range(height)]
    for x, y in outline:
        canvas[y][x] = 1
    # Green native-style vertical face gradient: bright upper face -> deep lower face.
    for x, y in ink:
        local_y = y - y0
        canvas[y][x] = 5 if local_y <= 3 else 4 if local_y <= 7 else 3

    used = sorted({value for row in canvas for value in row if value})
    gate(used == [1, 3, 4, 5], f"hit palette index drift: {used}")
    return canvas, {
        "text": "히트!",
        "canvas": [width, height],
        "font": FONT_MEMBER,
        "cells": {"hangul": [12, 12], "punctuation": [6, 12]},
        "text_width": text_width,
        "origin": [x0, y0],
        "ink_pixels": len(ink),
        "outline_pixels": len(outline),
        "palette_indices": used,
        "style": "palette 1 one-pixel dark outline; body gradient 5/4/3",
    }


def build_critical(font: fontpair.BdfFont) -> tuple[list[list[int]], dict[str, object]]:
    width, height = 64, 16
    raw_ink, text_width = glyph_mask("크리티컬!!", font)
    x0 = (width - text_width) // 2
    y0 = 2
    ink = translate_mask(raw_ink, x0, y0)
    gate(text_width == 60, f"critical text width drift: {text_width}")
    gate(ink and all(0 <= x < width and 0 <= y < height for x, y in ink), "critical ink overflow")

    dark_ring = dilate(ink, 1, width, height) - ink
    white_ring = dilate(ink | dark_ring, 1, width, height) - (ink | dark_ring)
    canvas = [[0] * width for _ in range(height)]
    for x, y in white_ring:
        canvas[y][x] = 2
    for x, y in dark_ring:
        canvas[y][x] = 1

    # Red body: orange top-edge highlight, bright red upper/middle, dark red lower.
    for x, y in ink:
        if (x, y - 1) not in ink:
            canvas[y][x] = 11
        else:
            local_y = y - y0
            canvas[y][x] = 10 if local_y <= 7 else 9

    used = sorted({value for row in canvas for value in row if value})
    gate(used == [1, 2, 9, 10, 11], f"critical palette index drift: {used}")
    return canvas, {
        "text": "크리티컬!!",
        "canvas": [width, height],
        "font": FONT_MEMBER,
        "cells": {"hangul": [12, 12], "punctuation": [6, 12]},
        "text_width": text_width,
        "origin": [x0, y0],
        "ink_pixels": len(ink),
        "dark_ring_pixels": len(dark_ring),
        "white_ring_pixels": len(white_ring),
        "palette_indices": used,
        "style": "red 9/10 body, orange 11 top highlight, dark 1 one-pixel ring, white 2 outer one-pixel ring",
    }


def changed_ranges(before: bytes, after: bytes) -> list[list[int]]:
    gate(len(before) == len(after), "ROM size changed")
    ranges: list[list[int]] = []
    start = None
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b and start is None:
            start = i
        elif a == b and start is not None:
            ranges.append([start, i])
            start = None
    if start is not None:
        ranges.append([start, len(before)])
    return ranges


def main() -> int:
    source = MAIN_TIP_ROM.read_bytes()
    gate(len(source) == 0x02000000, "expected 32 MiB promoted main ROM")
    gate(sha256(source) == EXPECTED_MAIN_SHA256, "promoted main ROM SHA-256 drift")

    report = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gate(report.get("result") == "PASS", "analysis report is not PASS")
    gate(report["main_tip"]["sha256"] == EXPECTED_MAIN_SHA256, "analysis/main SHA mismatch")
    resources = report["ownership"]["resources"]
    gate(len(resources) == 20, "expected exactly 20 duplicate battle-unit resources")
    gate(report["ownership"]["pointer_table_span"] == ["0x00D56DEC", "0x00D56E38"], "pointer table span drift")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, FONT_MEMBER)
    hit_canvas, hit_meta = build_hit(font)
    critical_canvas, critical_meta = build_critical(font)
    hit_blob = encode_canvas(hit_canvas)
    critical_blob = encode_canvas(critical_canvas)
    replacement = hit_blob + critical_blob
    gate(len(hit_blob) == 8 * 32, "hit tile count drift")
    gate(len(critical_blob) == 16 * 32, "critical tile count drift")
    gate(len(replacement) == 24 * 32, "combined tile count drift")

    rom = bytearray(source)
    pointer_before = source[0x00D56DEC:0x00D56E3C]
    patches: list[dict[str, object]] = []
    original_blob = None
    for item in resources:
        graphics_off = int(item["graphics_offset"], 16)
        resource_off = int(item["file_offset"], 16)
        palette_rel = int(item["palette_rel"], 16)
        graphics_rel = int(item["graphics_rel"], 16)
        gate(resource_off + graphics_rel == graphics_off, f"graphics owner mismatch at 0x{graphics_off:08X}")
        before_blob = source[graphics_off:graphics_off + len(replacement)]
        if original_blob is None:
            original_blob = before_blob
        gate(before_blob == original_blob, f"24-tile duplicate drift at 0x{graphics_off:08X}")
        tail_before = source[graphics_off + len(replacement):resource_off + palette_rel]
        rom[graphics_off:graphics_off + len(replacement)] = replacement
        tail_after = bytes(rom[graphics_off + len(replacement):resource_off + palette_rel])
        gate(tail_after == tail_before, f"unit graphics after tile 23 changed at 0x{graphics_off:08X}")
        patches.append({
            "resource": item["address"],
            "graphics_offset": item["graphics_offset"],
            "patched_span": [f"0x{graphics_off:08X}", f"0x{graphics_off + len(replacement):08X}"],
            "tiles": [0, 23],
        })

    gate(bytes(rom[0x00D56DEC:0x00D56E3C]) == pointer_before, "battle-unit resource pointer table changed")
    out = bytes(rom)
    ranges = changed_ranges(source, out)
    target_spans = [
        (int(item["graphics_offset"], 16), int(item["graphics_offset"], 16) + 24 * 32)
        for item in resources
    ]
    gate(
        all(any(start < target_end and end > target_start for start, end in ranges) for target_start, target_end in target_spans),
        "not every graphics block changed",
    )
    gate(
        all(any(target_start <= start and end <= target_end for target_start, target_end in target_spans) for start, end in ranges),
        "change outside target 24-tile spans",
    )

    colors = palette_rgb(source[int(resources[7]["file_offset"], 16) + int(resources[7]["palette_rel"], 16):][:32])
    hit_img = render_canvas(hit_canvas, colors)
    critical_img = render_canvas(critical_canvas, colors)
    scale = 8
    preview = Image.new("RGB", (max(64 * scale, 520), 16 * scale * 2 + 86), (18, 18, 18))
    draw = ImageDraw.Draw(preview)
    draw.text((8, 8), "Galmuri11 / source tiles 0-23 Korean candidate", fill=(255, 255, 255))
    preview.paste(hit_img.resize((32 * scale, 16 * scale), Image.Resampling.NEAREST), (8, 34))
    draw.text((32 * scale + 20, 84), "히트! 32x16 / tiles 0-7", fill=(230, 230, 230))
    y2 = 34 + 16 * scale + 18
    preview.paste(critical_img.resize((64 * scale, 16 * scale), Image.Resampling.NEAREST), (8, y2))
    draw.text((8, y2 + 16 * scale + 4), "크리티컬!! 64x16 / tiles 8-23", fill=(230, 230, 230))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    preview.save(OUT_PREVIEW)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_hit_critical_ko_candidate_20260904",
        "result": "PASS",
        "base": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(source),
            "crc32": f"0x{binascii.crc32(source) & 0xFFFFFFFF:08X}",
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "bytes": len(out),
        },
        "preview": advance_relative(OUT_PREVIEW),
        "font": FONT_MEMBER,
        "hit": hit_meta,
        "critical": critical_meta,
        "replacement": {
            "resources_patched": len(patches),
            "tiles_per_resource": 24,
            "bytes_per_resource": len(replacement),
            "total_target_bytes": len(patches) * len(replacement),
            "pointer_table": ["0x00D56DEC", "0x00D56E38"],
            "pointer_table_unchanged": True,
            "unit_graphics_after_tile_23_unchanged": True,
            "patches": patches,
        },
        "diff": {
            "changed_byte_count": sum(1 for a, b in zip(source, out) if a != b),
            "contiguous_changed_ranges": len(ranges),
            "ranges": [[f"0x{a:08X}", f"0x{b:08X}"] for a, b in ranges],
            "all_changes_within_target_spans": True,
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": str(OUT_ROM),
        "preview": str(OUT_PREVIEW),
        "manifest": str(OUT_MANIFEST),
        "sha256": manifest["output"]["sha256"],
        "crc32": manifest["output"]["crc32"],
        "resources_patched": len(patches),
        "changed_byte_count": manifest["diff"]["changed_byte_count"],
        "changed_ranges": len(ranges),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
