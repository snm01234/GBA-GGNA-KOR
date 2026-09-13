#!/usr/bin/env python3
"""Restore rounded red frame only for the six C43 direct type badges.

Parent is the approved main TIP.  Scope is deliberately limited to the six
4x2 direct descriptors used by the unit-type badge family:
범용/지상/수륙/우주/만능/비행.

The Korean interior/text pixels from main TIP are preserved.  Only perimeter
pixels that are unanimous across all six clean Japanese C43 badges are used as
frame geometry donors.  Japanese glyph/shadow palette indices 4/5 are never
written.  The single measured unanimous dark perimeter site at local (3,4)
is not structural red chrome: it is replaced with the adjacent bright-yellow
interior colour (palette 11), preventing the red-dot artifact seen in-game.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_status_sprite_package_duplicates_20260830 as audit
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_c43_type_badges_round_restore"
RESULT = OUT_DIR / "ggen_advance_c43_type_badges_round_restore_candidate_20260905.gba"
PREVIEW = OUT_DIR / "ggen_advance_c43_type_badges_round_restore_preview_20260905.png"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_c43_type_badges_round_restore_candidate_20260905.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"

SAFE_FRAME = {6, 7, 8, 9, 10}
FORBIDDEN_JP_INK = {4, 5}
DARK_YELLOW_SITE = (3, 4)
DARK_YELLOW_FILL = 11
EXPECTED_LABELS = ["범용", "지상", "수륙", "우주", "만능", "비행"]


def gate(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {msg}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "tile size")
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def encode_tile(tile: list[list[int]]) -> bytes:
    gate(len(tile) == 8 and all(len(row) == 8 for row in tile), "tile shape")
    raw = bytearray(32)
    for y in range(8):
        for x in range(8):
            raw[y * 4 + x // 2] |= (tile[y][x] & 0xF) << (4 * (x & 1))
    return bytes(raw)


def stitch_direct(rom: bytes, desc: int) -> list[list[int]]:
    graphics = desc + 0x20
    raw = rom[graphics:graphics + 256]
    gate(len(raw) == 256, f"direct graphics short read at 0x{graphics:08X}")
    canvas = [[0] * 32 for _ in range(16)]
    for i in range(8):
        tile = decode_tile(raw[i * 32:(i + 1) * 32])
        tx, ty = i % 4, i // 4
        for y in range(8):
            canvas[ty * 8 + y][tx * 8:(tx + 1) * 8] = tile[y]
    return canvas


def encode_direct(canvas: list[list[int]]) -> bytes:
    gate(len(canvas) == 16 and all(len(row) == 32 for row in canvas), "direct canvas shape")
    parts = []
    for ty in range(2):
        for tx in range(4):
            tile = [canvas[ty * 8 + y][tx * 8:(tx + 1) * 8] for y in range(8)]
            parts.append(encode_tile(tile))
    return b"".join(parts)


def in_frame_ring(x: int, y: int) -> bool:
    # Same frame-only policy as the preceding E0518 experiment.
    return y in {0, 15} or x < 4 or x >= 28


def nearest_safe_consensus(consensus: list[list[int | None]], x: int, y: int) -> int | None:
    for distance in range(1, 8):
        for nx, ny in ((x - distance, y), (x + distance, y), (x, y - distance), (x, y + distance)):
            if not (0 <= nx < 32 and 0 <= ny < 16 and in_frame_ring(nx, ny)):
                continue
            value = consensus[ny][nx]
            if value in SAFE_FRAME:
                return int(value)
    return None


def render_badge(canvas: list[list[int]], scale: int = 5) -> Image.Image:
    palette = {
        4: (20, 45, 35),
        5: (116, 57, 1),
        6: (239, 41, 15),
        7: (245, 96, 14),
        8: (250, 135, 22),
        9: (255, 181, 40),
        10: (251, 229, 59),
        11: (255, 255, 141),
    }
    image = Image.new("RGB", (32 * scale, 16 * scale), (80, 80, 80))
    for y in range(16):
        for x in range(32):
            colour = palette.get(canvas[y][x], (80, 80, 80))
            for sy in range(scale):
                for sx in range(scale):
                    image.putpixel((x * scale + sx, y * scale + sy), colour)
    return image


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == meta["sha256"], "approved main TIP hash mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")

    labels = list(audit.DIRECT_TYPES.items())
    gate([name for name, _ in labels] == EXPECTED_LABELS, "C43 direct type order drift")

    # Verify the descriptor header family before touching graphics.
    for name, (desc, _tile_ids) in labels:
        gate(parent[desc:desc + len(audit.DIRECT_HEADER_PREFIX)] == audit.DIRECT_HEADER_PREFIX,
             f"{name}: main direct descriptor header drift")
        gate(jp[desc:desc + len(audit.DIRECT_HEADER_PREFIX)] == audit.DIRECT_HEADER_PREFIX,
             f"{name}: JP direct descriptor header drift")

    jp_canvases = {name: stitch_direct(jp, desc) for name, (desc, _ids) in labels}
    main_canvases = {name: stitch_direct(parent, desc) for name, (desc, _ids) in labels}

    # Common frame geometry across all six JP C43 badges.  Letter shapes differ,
    # so only unanimous perimeter pixels are accepted as structural donors.
    consensus: list[list[int | None]] = [[None] * 32 for _ in range(16)]
    unanimous_count = 0
    for y in range(16):
        for x in range(32):
            values = [jp_canvases[name][y][x] for name, _ in labels]
            if len(set(values)) == 1:
                consensus[y][x] = values[0]
                unanimous_count += 1

    candidate = bytearray(parent)
    reports = []
    allowed_ranges: list[tuple[int, int]] = []
    all_changed: list[tuple[str, int, int, int, int, str]] = []

    for name, (desc, _tile_ids) in labels:
        before = main_canvases[name]
        after = [row[:] for row in before]
        copied = 0
        substituted = 0
        skipped_nonunanimous = 0

        for y in range(16):
            for x in range(32):
                if not in_frame_ring(x, y):
                    continue
                donor = consensus[y][x]
                if donor is None:
                    skipped_nonunanimous += 1
                    continue
                value = int(donor)
                source_kind = "unanimous_jp_c43_frame"
                if value in FORBIDDEN_JP_INK:
                    gate((x, y) == DARK_YELLOW_SITE,
                         f"{name}: unexpected unanimous dark frame site at {x},{y}")
                    value = DARK_YELLOW_FILL
                    source_kind = "adjacent_yellow_substitution"
                    substituted += 1
                elif value not in SAFE_FRAME:
                    continue
                gate(value not in FORBIDDEN_JP_INK, f"{name}: forbidden JP ink/shadow write")
                if after[y][x] != value:
                    old = after[y][x]
                    after[y][x] = value
                    copied += 1
                    all_changed.append((name, x, y, old, value, source_kind))

        # Guarantee that the Korean interior is untouched.
        for y in range(16):
            for x in range(32):
                if not in_frame_ring(x, y):
                    gate(after[y][x] == before[y][x], f"{name}: interior changed at {x},{y}")
        gate(copied > 0, f"{name}: no C43 frame pixels restored")

        gfx = desc + 0x20
        payload = encode_direct(after)
        gate(len(payload) == 256, f"{name}: payload size")
        candidate[gfx:gfx + 256] = payload
        allowed_ranges.append((gfx, gfx + 256))

        changed_tiles = []
        for i in range(8):
            old = parent[gfx + i * 32:gfx + (i + 1) * 32]
            new = payload[i * 32:(i + 1) * 32]
            if old != new:
                changed_tiles.append(i)

        reports.append({
            "label": name,
            "descriptor": f"0x{desc:08X}",
            "graphics": f"0x{gfx:08X}",
            "changed_frame_pixels": copied,
            "dark_donor_pixels_substituted": substituted,
            "nonunanimous_ring_pixels_skipped": skipped_nonunanimous,
            "changed_local_tiles": changed_tiles,
        })

    candidate = bytes(candidate)
    gate(all(new not in FORBIDDEN_JP_INK for _n, _x, _y, _old, new, _kind in all_changed),
         "C43 patch writes JP glyph/shadow index")

    # No bytes outside the six direct graphics payloads may differ from main TIP.
    escaped = [
        i for i, (a, b) in enumerate(zip(parent, candidate))
        if a != b and not any(start <= i < end for start, end in allowed_ranges)
    ]
    gate(not escaped, f"ROM changes escaped C43 graphics: {[hex(x) for x in escaped[:8]]}")

    # Re-decode output and verify the main-TIP interior remained exact.
    for name, (desc, _ids) in labels:
        before = main_canvases[name]
        after = stitch_direct(candidate, desc)
        for y in range(16):
            for x in range(32):
                if not in_frame_ring(x, y):
                    gate(after[y][x] == before[y][x], f"{name}: output interior drift at {x},{y}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(candidate)
    if MAIN_SAV.is_file():
        shutil.copy2(MAIN_SAV, RESULT.with_suffix(".sav"))

    # Preview: MAIN / JP / AFTER for all six C43 badges.
    scale = 4
    badge_w, badge_h = 32 * scale, 16 * scale
    margin_x, margin_y = 14, 22
    preview = Image.new("RGB", (badge_w * 3 + margin_x * 4, (badge_h + margin_y) * 6 + 26), (30, 30, 30))
    draw = ImageDraw.Draw(preview)
    draw.text((margin_x, 5), "MAIN TIP C43", fill="white")
    draw.text((badge_w + margin_x * 2, 5), "JP C43 geometry", fill="white")
    draw.text((badge_w * 2 + margin_x * 3, 5), "AFTER", fill="white")
    for row_index, (name, (desc, _ids)) in enumerate(labels):
        y = 26 + row_index * (badge_h + margin_y)
        draw.text((2, y + badge_h + 2), f"{name} @ 0x{desc:08X}", fill="white")
        imgs = [
            render_badge(main_canvases[name], scale),
            render_badge(jp_canvases[name], scale),
            render_badge(stitch_direct(candidate, desc), scale),
        ]
        for col, img in enumerate(imgs):
            x = margin_x + col * (badge_w + margin_x)
            preview.paste(img, (x, y))
    preview.save(PREVIEW)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_c43_type_badges_round_restore_candidate_20260905",
        "result": "PASS",
        "parent": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
        },
        "output": {
            "path": advance_relative(RESULT),
            "sha256": sha256(candidate),
            "size": len(candidate),
            "sav": advance_relative(RESULT.with_suffix('.sav')) if RESULT.with_suffix('.sav').is_file() else None,
            "preview": advance_relative(PREVIEW),
        },
        "scope": {
            "family": "C43 direct 4x2 type badges only",
            "labels": EXPECTED_LABELS,
            "descriptors": {name: f"0x{desc:08X}" for name, (desc, _ids) in labels},
        },
        "method": {
            "baseline": "approved main TIP only; E0518 and all remodel test candidates are excluded as parents",
            "geometry_donor": "pixel must be identical across all six clean JP C43 badges and lie in outer frame ring",
            "frame_ring": "y=0/15 or x<4 or x>=28",
            "safe_written_indices": sorted(SAFE_FRAME | {DARK_YELLOW_FILL}),
            "forbidden_jp_text_shadow_indices": sorted(FORBIDDEN_JP_INK),
            "dark_unanimous_border_handling": "single measured site (3,4) is never copied; replace with adjacent bright-yellow palette index 11",
            "korean_interior": "byte/pixel-identical to approved main TIP",
        },
        "reports": reports,
        "verification": {
            "result": "PASS",
            "main_tip_unmodified": True,
            "e0518_unmodified": True,
            "only_c43_direct_graphics_changed": True,
            "no_patch_write_uses_index_4_or_5": True,
            "unanimous_jp_pixels": unanimous_count,
            "total_changed_frame_pixels": len(all_changed),
            "runtime_emulator": "not verified",
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "output": str(RESULT),
        "sha256": sha256(candidate),
        "preview": str(PREVIEW),
        "total_changed_frame_pixels": len(all_changed),
        "reports": reports,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
