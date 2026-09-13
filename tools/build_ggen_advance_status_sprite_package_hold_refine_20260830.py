#!/usr/bin/env python3
"""Rebuild the C5A5DC unit-list hold badge without JP residue or clipping.

The previous package patch copied only the six-column overlap from the wider
E0518 badge and then cleared its left-most column.  That removed the visible
Japanese residue, but it also removed a real column of the Korean ``지``.

This narrow follow-up starts from the current approved Main TIP, restores the
entire seven-pixel interior of the private C5A5DC badge to its measured native
background, and paints a five-pixel-wide Galmuri7-derived ``지`` with a one
pixel contour on both sides.  The package-specific right edge and every byte
outside the two live 4bpp tiles remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
MAIN_TIP = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_MANIFEST = ROOT / "integrated" / "main_tip" / "ggen_advance_main_tip_manifest.json"

OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_sprite_package_hold_refined_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_sprite_package_hold_refined_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_sprite_package_hold_refined_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "b244f4103e2ae870cfe888dee569feca17c96f0bf55b71f74675ed76983f0a10"

HOLD_TOP = 0x00C5CEB0
HOLD_BOTTOM = 0x00C5CF10
TILE_BYTES = 32

FACE_INDEX = 10
CONTOUR_INDEX = 4
BACKGROUND_INDEX = 8

# Exact live canvas in the current approved b244... Main TIP.  Hex digits are
# palette indices; A is the Korean face color and 4 is its contour color.
EXPECTED_BEFORE_ROWS = (
    "66666666",
    "77777777",
    "88876888",
    "84444489",
    "8AAAA489",
    "8A44A489",
    "8A44A489",
    "84A4A489",
    "84A4A489",
    "844AA489",
    "8844A489",
    "88844489",
    "88887889",
    "88876888",
    "77766777",
    "66666666",
)

# Galmuri7's native six-column 지 is narrowed by merging the expendable fourth
# source column.  This retains the top bar, central strokes, and right stem in
# five columns so an outline fits inside the package's seven-pixel interior.
GLYPH_5X7 = (
    "#####",
    "..#.#",
    "..#.#",
    ".#.##",
    ".#.##",
    "#...#",
    "....#",
)
GLYPH_X = 1
GLYPH_Y = 4

EXPECTED_AFTER_ROWS = (
    "66666666",
    "77777777",
    "88876888",
    "44444449",
    "4AAAAA49",
    "444A4A49",
    "844A4A49",
    "84A4AA49",
    "44A4AA49",
    "4A444A49",
    "44484A49",
    "88884449",
    "88887889",
    "88876888",
    "77766777",
    "66666666",
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes | bytearray) -> list[int]:
    gate(len(raw) == TILE_BYTES, f"4bpp tile must be {TILE_BYTES} bytes")
    pixels: list[int] = []
    for value in raw:
        pixels.extend((value & 0x0F, (value >> 4) & 0x0F))
    return pixels


def encode_tile(pixels: list[int]) -> bytes:
    gate(len(pixels) == 64, "4bpp tile must contain 64 pixels")
    raw = bytearray(TILE_BYTES)
    for i in range(TILE_BYTES):
        raw[i] = (pixels[i * 2] & 0x0F) | ((pixels[i * 2 + 1] & 0x0F) << 4)
    return bytes(raw)


def get_canvas(data: bytes | bytearray) -> list[list[int]]:
    top = decode_tile(data[HOLD_TOP : HOLD_TOP + TILE_BYTES])
    bottom = decode_tile(data[HOLD_BOTTOM : HOLD_BOTTOM + TILE_BYTES])
    return [top[y * 8 : (y + 1) * 8] for y in range(8)] + [
        bottom[y * 8 : (y + 1) * 8] for y in range(8)
    ]


def put_canvas(data: bytearray, canvas: list[list[int]]) -> None:
    gate(len(canvas) == 16 and all(len(row) == 8 for row in canvas), "hold canvas must be 8x16")
    top = [value for row in canvas[:8] for value in row]
    bottom = [value for row in canvas[8:] for value in row]
    data[HOLD_TOP : HOLD_TOP + TILE_BYTES] = encode_tile(top)
    data[HOLD_BOTTOM : HOLD_BOTTOM + TILE_BYTES] = encode_tile(bottom)


def canvas_rows(canvas: list[list[int]]) -> tuple[str, ...]:
    return tuple("".join(f"{value:X}" for value in row) for row in canvas)


def contour(mask: list[list[bool]]) -> list[list[bool]]:
    height = len(mask)
    width = len(mask[0])
    result = [[False] * width for _ in range(height)]
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
                        result[oy][ox] = True
    return result


def build_refined_canvas(before: list[list[int]]) -> tuple[list[list[int]], dict[str, int]]:
    canvas = [row[:] for row in before]

    # The live badge has a seven-pixel interior (x=0..6) and a private right
    # edge at x=7.  Clear the full old glyph/contour footprint before repainting.
    for y in range(3, 12):
        canvas[y][0:7] = [BACKGROUND_INDEX] * 7

    mask = [[False] * 8 for _ in range(16)]
    for gy, row in enumerate(GLYPH_5X7):
        for gx, value in enumerate(row):
            if value == "#":
                mask[GLYPH_Y + gy][GLYPH_X + gx] = True

    outline = contour(mask)
    for y in range(16):
        for x in range(8):
            if outline[y][x]:
                canvas[y][x] = CONTOUR_INDEX
    for y in range(16):
        for x in range(8):
            if mask[y][x]:
                canvas[y][x] = FACE_INDEX

    ink_pixels = sum(value for row in mask for value in row)
    contour_pixels = sum(value for row in outline for value in row)
    return canvas, {"ink_pixels": ink_pixels, "contour_pixels": contour_pixels}


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


def make_preview(before: list[list[int]], after: list[list[int]], out: Path) -> None:
    palette = {
        4: (70, 45, 25),
        6: (238, 41, 16),
        7: (255, 82, 16),
        8: (255, 115, 24),
        9: (255, 180, 41),
        10: (255, 230, 65),
    }
    scale = 12
    pad = 16
    label_h = 20
    gap = 24
    cell_w = 8 * scale
    cell_h = 16 * scale
    image = Image.new("RGB", (pad * 2 + cell_w * 2 + gap, pad * 2 + label_h + cell_h), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for index, (label, canvas) in enumerate((("BEFORE", before), ("AFTER", after))):
        ox = pad + index * (cell_w + gap)
        oy = pad + label_h
        draw.text((ox, pad), label, fill=(20, 20, 20))
        for y, row in enumerate(canvas):
            for x, value in enumerate(row):
                color = palette.get(value, (140, 140, 140))
                draw.rectangle(
                    (ox + x * scale, oy + y * scale, ox + (x + 1) * scale - 1, oy + (y + 1) * scale - 1),
                    fill=color,
                )
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_TIP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = parser.parse_args()

    source = args.input.read_bytes()
    gate(len(source) == 32 * 1024 * 1024, "input Main TIP must be 32 MiB")
    gate(sha256(source) == EXPECTED_MAIN_SHA256, f"input Main TIP hash drift: {sha256(source)}")

    main_manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    gate(main_manifest.get("status") == "approved_main_tip", "current Main TIP manifest is not approved")
    gate(main_manifest.get("sha256") == EXPECTED_MAIN_SHA256, "current Main TIP manifest hash drift")

    before = get_canvas(source)
    gate(canvas_rows(before) == EXPECTED_BEFORE_ROWS, f"live hold canvas drift: {canvas_rows(before)}")
    after, paint_report = build_refined_canvas(before)
    gate(canvas_rows(after) == EXPECTED_AFTER_ROWS, f"refined hold canvas drift: {canvas_rows(after)}")
    gate(paint_report == {"ink_pixels": 18, "contour_pixels": 38}, f"paint count drift: {paint_report}")

    # The package-specific right edge and all rows outside the rebuilt glyph
    # band are byte/pixel exact.
    gate([row[7] for row in after] == [row[7] for row in before], "package right edge changed")
    gate(after[:3] == before[:3] and after[12:] == before[12:], "native top/bottom geometry changed")

    candidate = bytearray(source)
    put_canvas(candidate, after)
    changed = [i for i, (old, new) in enumerate(zip(source, candidate)) if old != new]
    gate(changed, "refined badge made no changes")
    gate(
        all(
            HOLD_TOP <= offset < HOLD_TOP + TILE_BYTES
            or HOLD_BOTTOM <= offset < HOLD_BOTTOM + TILE_BYTES
            for offset in changed
        ),
        "refined badge escaped the two live package tiles",
    )
    gate(get_canvas(candidate) == after, "encoded refined canvas did not round-trip")

    output = bytes(candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    make_preview(before, after, args.preview)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ggen_advance_status_sprite_package_hold_refined_20260830",
        "result": "PASS",
        "source": {
            "path": str(args.input.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(source),
            "main_tip_manifest": str(MAIN_MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        },
        "output": {
            "path": str(args.out.relative_to(ROOT)).replace("\\", "/"),
            "size": len(output),
            "sha256": sha256(output),
            "preview": str(args.preview.relative_to(ROOT)).replace("\\", "/"),
        },
        "patch": {
            "target": "active C5A5DC package hold badge",
            "tile_offsets": [f"0x{HOLD_TOP:08X}", f"0x{HOLD_BOTTOM:08X}"],
            "method": "clear full x=0..6 old glyph footprint and repaint centered 5x7 지 with one-pixel contour",
            "glyph_bbox": [GLYPH_X, GLYPH_Y, GLYPH_X + 4, GLYPH_Y + 6],
            "ink_pixels": paint_report["ink_pixels"],
            "contour_pixels": paint_report["contour_pixels"],
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "parent_main_tip_hash_verified": True,
            "parent_manifest_hash_verified": True,
            "before_canvas_exactly_verified": True,
            "full_old_japanese_footprint_cleared_before_repaint": True,
            "complete_korean_glyph_fits_inside_seven_pixel_interior": True,
            "package_specific_right_edge_preserved": True,
            "native_top_bottom_geometry_preserved": True,
            "changes_restricted_to_two_live_hold_tiles": True,
            "palette_modified": False,
            "resource_pointer_modified": False,
            "changed_bytes_vs_parent": len(changed),
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "result": "PASS",
                "out": str(args.out),
                "sha256": sha256(output),
                "manifest": str(args.manifest),
                "preview": str(args.preview),
                "changed_bytes": len(changed),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
