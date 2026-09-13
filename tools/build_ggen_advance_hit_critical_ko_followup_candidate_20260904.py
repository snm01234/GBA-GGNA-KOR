#!/usr/bin/env python3
"""Build the follow-up Korean HIT!/CRITICAL!! graphics candidate.

Runtime ownership established from the user-supplied candidate states:
* combo family: 20 battle-unit resources, HIT source tiles 0..7 and CRITICAL
  source tiles 8..23, pointer table 0x00D56DEC..0x00D56E38.
* hit-only family: 20 resources, the same native HIT eight-tile blob at source
  tile 17 (first ten) or 21 (last ten), pointer table
  0x00D56E3C..0x00D56E88.

Follow-up changes:
* Galmuri9 for both labels.
* HIT uses a single light-green body (palette index 5) plus dark outline 1.
* CRITICAL is encoded as two native 32x16 OBJ blocks (tiles 8..15, 16..23),
  not as one 64x16 linear 8x2 sheet.
* all 20 hit-only consumers are patched as well.

Resource headers, palettes, pointer tables, and unrelated graphics remain
byte-exact.
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
OUT_ROM = OUT_DIR / "ggen_advance_hit_critical_ko_followup_candidate_20260904.gba"
OUT_PREVIEW = OUT_DIR / "ggen_advance_hit_critical_ko_followup_preview_20260904.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_hit_critical_ko_followup_candidate_20260904.json"
FONT_MEMBER = "Galmuri9.bdf"

COMBO_POINTER_START = 0x00D56DEC
COMBO_POINTER_END = 0x00D56E38
HIT_ONLY_POINTER_START = 0x00D56E3C
HIT_ONLY_POINTER_END = 0x00D56E88


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


def decode_canvas(blob: bytes, width: int, height: int) -> list[list[int]]:
    gate(width % 8 == 0 and height % 8 == 0, "decode canvas is not tile-aligned")
    gate(len(blob) == (width // 8) * (height // 8) * 32, "decode canvas byte size drift")
    canvas = [[0] * width for _ in range(height)]
    tiles_w = width // 8
    for index in range(len(blob) // 32):
        tile = decode_tile(blob[index * 32:(index + 1) * 32])
        ox = (index % tiles_w) * 8
        oy = (index // tiles_w) * 8
        for y in range(8):
            canvas[oy + y][ox:ox + 8] = tile[y]
    return canvas


def encode_critical_obj_pair(canvas: list[list[int]]) -> bytes:
    """Encode 64x16 into the two 32x16 OBJ blocks used at runtime.

    OAM tile 392 consumes source tiles 8..15 as 4x2; OAM tile 400 consumes
    source tiles 16..23 as 4x2.  A plain 64x16 8x2 encoding places the intended
    upper-right quadrant into the lower-left position of the first object.
    """
    gate(len(canvas) == 16 and all(len(row) == 64 for row in canvas), "critical canvas shape drift")
    left = [row[:32] for row in canvas]
    right = [row[32:] for row in canvas]
    blob = encode_canvas(left) + encode_canvas(right)
    gate(len(blob) == 16 * 32, "critical OBJ-pair byte size drift")

    reconstructed_left = decode_canvas(blob[:8 * 32], 32, 16)
    reconstructed_right = decode_canvas(blob[8 * 32:], 32, 16)
    reconstructed = [reconstructed_left[y] + reconstructed_right[y] for y in range(16)]
    gate(reconstructed == canvas, "critical 32x16 OBJ-pair ordering drift")
    return blob


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


def glyph_mask(
    text: str,
    font: fontpair.BdfFont,
    hangul_cell: int = 12,
    punctuation_cell: int = 6,
) -> tuple[set[tuple[int, int]], int]:
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
    for x, y in ink:
        canvas[y][x] = 5

    used = sorted({value for row in canvas for value in row if value})
    gate(used == [1, 5], f"hit palette index drift: {used}")
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
        "style": "palette 1 one-pixel dark outline; single light-green body index 5",
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
        "style": "red 9/10 body, orange 11 top highlight, dark 1 ring, white 2 outer ring",
        "source_tile_layout": {
            "left_32x16": [[8, 9, 10, 11], [12, 13, 14, 15]],
            "right_32x16": [[16, 17, 18, 19], [20, 21, 22, 23]],
        },
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
    gate(len(resources) == 20, "expected exactly 20 combo battle-unit resources")
    gate(report["ownership"]["pointer_table_span"] == ["0x00D56DEC", "0x00D56E38"], "combo pointer table span drift")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, FONT_MEMBER)
    hit_canvas, hit_meta = build_hit(font)
    critical_canvas, critical_meta = build_critical(font)
    hit_blob = encode_canvas(hit_canvas)
    critical_blob = encode_critical_obj_pair(critical_canvas)
    replacement = hit_blob + critical_blob
    gate(len(hit_blob) == 8 * 32, "hit tile count drift")
    gate(len(critical_blob) == 16 * 32, "critical tile count drift")
    gate(len(replacement) == 24 * 32, "combined tile count drift")

    rom = bytearray(source)
    combo_pointer_before = source[COMBO_POINTER_START:COMBO_POINTER_END + 4]
    hit_only_pointer_before = source[HIT_ONLY_POINTER_START:HIT_ONLY_POINTER_END + 4]

    combo_patches: list[dict[str, object]] = []
    original_blob: bytes | None = None
    for item in resources:
        graphics_off = int(item["graphics_offset"], 16)
        resource_off = int(item["file_offset"], 16)
        palette_rel = int(item["palette_rel"], 16)
        graphics_rel = int(item["graphics_rel"], 16)
        gate(resource_off + graphics_rel == graphics_off, f"graphics owner mismatch at 0x{graphics_off:08X}")
        before_blob = source[graphics_off:graphics_off + len(replacement)]
        if original_blob is None:
            original_blob = before_blob
        gate(before_blob == original_blob, f"24-tile combo duplicate drift at 0x{graphics_off:08X}")

        tail_before = source[graphics_off + len(replacement):resource_off + palette_rel]
        rom[graphics_off:graphics_off + len(replacement)] = replacement
        tail_after = bytes(rom[graphics_off + len(replacement):resource_off + palette_rel])
        gate(tail_after == tail_before, f"unit graphics after tile 23 changed at 0x{graphics_off:08X}")
        combo_patches.append({
            "resource": item["address"],
            "graphics_offset": item["graphics_offset"],
            "patched_span": [f"0x{graphics_off:08X}", f"0x{graphics_off + len(replacement):08X}"],
            "tiles": [0, 23],
        })

    gate(original_blob is not None, "missing combo source blob")
    original_hit_blob = original_blob[:8 * 32]

    hit_only_patches: list[dict[str, object]] = []
    hit_only_indices: list[int] = []
    for pointer_off in range(HIT_ONLY_POINTER_START, HIT_ONLY_POINTER_END + 1, 4):
        resource_address = struct.unpack_from("<I", source, pointer_off)[0]
        gate(ROM_BASE <= resource_address < ROM_BASE + len(source), f"invalid hit-only resource pointer at 0x{pointer_off:08X}")
        resource_off = resource_address - ROM_BASE
        kind, tag, graphics_rel, palette_rel, animation_count = struct.unpack_from("<5I", source, resource_off)
        gate(kind == 0 and tag == 6 and animation_count == 2, f"hit-only resource header drift at 0x{resource_address:08X}")
        gate(0x20 <= graphics_rel < palette_rel, f"hit-only graphics bounds drift at 0x{resource_address:08X}")

        graphics_off = resource_off + graphics_rel
        graphics = source[graphics_off:resource_off + palette_rel]
        matches = [
            offset
            for offset in range(0, len(graphics) - len(original_hit_blob) + 1, 32)
            if graphics[offset:offset + len(original_hit_blob)] == original_hit_blob
        ]
        gate(len(matches) == 1, f"expected one native HIT copy in hit-only resource 0x{resource_address:08X}, got {len(matches)}")
        local_off = matches[0]
        tile_index = local_off // 32
        hit_only_indices.append(tile_index)
        target = graphics_off + local_off
        gate(bytes(rom[target:target + len(hit_blob)]) == original_hit_blob, f"hit-only source drift at 0x{target:08X}")
        rom[target:target + len(hit_blob)] = hit_blob
        hit_only_patches.append({
            "pointer_literal": f"0x{pointer_off:08X}",
            "resource": f"0x{resource_address:08X}",
            "graphics_offset": f"0x{graphics_off:08X}",
            "source_tile": tile_index,
            "patched_span": [f"0x{target:08X}", f"0x{target + len(hit_blob):08X}"],
            "tiles": [tile_index, tile_index + 7],
        })

    gate(hit_only_indices == [17] * 10 + [21] * 10, f"hit-only source tile family drift: {hit_only_indices}")
    gate(bytes(rom[COMBO_POINTER_START:COMBO_POINTER_END + 4]) == combo_pointer_before, "combo pointer table changed")
    gate(bytes(rom[HIT_ONLY_POINTER_START:HIT_ONLY_POINTER_END + 4]) == hit_only_pointer_before, "hit-only pointer table changed")

    out = bytes(rom)
    ranges = changed_ranges(source, out)
    target_spans = [
        (int(item["graphics_offset"], 16), int(item["graphics_offset"], 16) + 24 * 32)
        for item in resources
    ] + [
        (int(item["patched_span"][0], 16), int(item["patched_span"][1], 16))
        for item in hit_only_patches
    ]
    gate(
        all(any(start < target_end and end > target_start for start, end in ranges) for target_start, target_end in target_spans),
        "not every intended graphics block changed",
    )
    gate(
        all(any(target_start <= start and end <= target_end for target_start, target_end in target_spans) for start, end in ranges),
        "change outside intended graphics spans",
    )

    # Active combo resource 0x08382934 uses local palette 0 -> live OBJ palette 11.
    active = resources[7]
    colors = palette_rgb(
        source[
            int(active["file_offset"], 16) + int(active["palette_rel"], 16):
            int(active["file_offset"], 16) + int(active["palette_rel"], 16) + 32
        ]
    )
    hit_img = render_canvas(hit_canvas, colors)
    critical_img = render_canvas(critical_canvas, colors)
    scale = 8
    preview = Image.new("RGB", (max(64 * scale, 560), 16 * scale * 2 + 92), (18, 18, 18))
    draw = ImageDraw.Draw(preview)
    draw.text((8, 8), "Galmuri9 / corrected CRITICAL OBJ order / HIT-only coverage", fill=(255, 255, 255))
    preview.paste(hit_img.resize((32 * scale, 16 * scale), Image.Resampling.NEAREST), (8, 34))
    draw.text((32 * scale + 20, 84), "히트! / solid palette 5 + outline 1", fill=(230, 230, 230))
    y2 = 34 + 16 * scale + 18
    preview.paste(critical_img.resize((64 * scale, 16 * scale), Image.Resampling.NEAREST), (8, y2))
    draw.text((8, y2 + 16 * scale + 4), "크리티컬!! / source 8..15 left OBJ, 16..23 right OBJ", fill=(230, 230, 230))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    preview.save(OUT_PREVIEW)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_hit_critical_ko_followup_candidate_20260904",
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
        "ownership_followup": {
            "candidate_ss1_observation": {
                "active_hit_only_resource": "0x083AC518",
                "resource_graphics_rel": "0x0D6C",
                "native_hit_source_tile": 17,
                "live_obj_tiles": [384, 391],
                "live_palette_bank": 11,
            },
            "hit_exact_blob_copies_in_main": 40,
            "combo_resource_count": 20,
            "hit_only_resource_count": 20,
        },
        "replacement": {
            "combo_resources_patched": len(combo_patches),
            "combo_tiles_per_resource": 24,
            "combo_bytes_per_resource": len(replacement),
            "combo_pointer_table": [f"0x{COMBO_POINTER_START:08X}", f"0x{COMBO_POINTER_END:08X}"],
            "combo_pointer_table_unchanged": True,
            "unit_graphics_after_tile_23_unchanged": True,
            "combo_patches": combo_patches,
            "hit_only_resources_patched": len(hit_only_patches),
            "hit_only_tiles_per_resource": 8,
            "hit_only_bytes_per_resource": len(hit_blob),
            "hit_only_pointer_table": [f"0x{HIT_ONLY_POINTER_START:08X}", f"0x{HIT_ONLY_POINTER_END:08X}"],
            "hit_only_pointer_table_unchanged": True,
            "hit_only_source_tile_distribution": {"17": 10, "21": 10},
            "hit_only_patches": hit_only_patches,
            "total_target_bytes": len(combo_patches) * len(replacement) + len(hit_only_patches) * len(hit_blob),
        },
        "diff": {
            "changed_byte_count": sum(1 for a, b in zip(source, out) if a != b),
            "contiguous_changed_ranges": len(ranges),
            "all_changes_within_target_spans": True,
            "ranges": [[f"0x{a:08X}", f"0x{b:08X}"] for a, b in ranges],
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
        "combo_resources_patched": len(combo_patches),
        "hit_only_resources_patched": len(hit_only_patches),
        "hit_only_source_tiles": {"17": hit_only_indices.count(17), "21": hit_only_indices.count(21)},
        "changed_byte_count": manifest["diff"]["changed_byte_count"],
        "changed_ranges": len(ranges),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
