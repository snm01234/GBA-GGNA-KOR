#!/usr/bin/env python3
"""Restore only the E0518 type-badge rounded red frame on top of main TIP.

Scope is deliberately narrow: E0518 resources 41..46 only
(범용/우주/지상/만능/수륙/비행).  The current Korean glyphs/background remain
from the approved main TIP.  Only border pixels that are unanimously identical
across all six clean Japanese badges are used as geometric donors.

Japanese glyph/shadow indices 4/5 are never copied.  The one unanimous dark
border-site is replaced by the nearest safe red/orange frame colour instead.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_e0518_type_badges_round_restore"
RESULT = OUT_DIR / "ggen_advance_e0518_type_badges_round_restore_candidate_20260905.gba"
PREVIEW = OUT_DIR / "ggen_advance_e0518_type_badges_round_restore_preview_20260905.png"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_e0518_type_badges_round_restore_candidate_20260905.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
ROM_BASE = 0x08000000
EXPECTED_MAIN_PTR = 0x09240000
EXPECTED_JP_PTR = 0x080DC848
SAFE_FRAME = {6, 7, 8, 9, 10}
FORBIDDEN_JP_INK = {4, 5}


def gate(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {msg}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def load_atlas(rom: bytes) -> tuple[int, int, int, bytes]:
    ptr = struct.unpack_from("<I", rom, status.RESOURCE_TABLE)[0]
    off = ptr - ROM_BASE
    gate(0 <= off + 4 <= len(rom), f"E0518 pointer outside ROM: 0x{ptr:08X}")
    hdr = struct.unpack_from("<I", rom, off)[0]
    gate(hdr & 0x80000000, f"E0518 atlas not custom-LZSS: 0x{hdr:08X}")
    clen = hdr & 0xFFFF
    decoded = status.lzss_decompress(rom[off + 4: off + 4 + clen])
    gate(len(decoded) == status.ATLAS_EXPECTED_DECODED, f"atlas decoded size drift: {len(decoded)}")
    return ptr, off, clen, decoded


def stitch(atlas: bytes | bytearray, spec: dict) -> list[list[int]]:
    rows: list[list[int]] = []
    for tile_row in spec["tiles"]:
        tiles = [status.decode_tile(atlas, tile_id) for tile_id in tile_row]
        for y in range(8):
            rows.append([value for tile in tiles for value in tile[y]])
    gate(len(rows) == 16 and all(len(row) == 32 for row in rows), "type badge stitch shape")
    return rows


def write_canvas(atlas: bytearray, spec: dict, canvas: list[list[int]]) -> None:
    gate(len(canvas) == 16 and all(len(row) == 32 for row in canvas), "type badge write shape")
    for ty, tile_row in enumerate(spec["tiles"]):
        for tx, tile_id in enumerate(tile_row):
            tile = [row[tx * 8:(tx + 1) * 8] for row in canvas[ty * 8:(ty + 1) * 8]]
            status.encode_tile(atlas, tile_id, tile)


def in_frame_ring(x: int, y: int) -> bool:
    # Exact scope requested: rounded red frame only.  Korean text starts farther
    # inward, so this ring does not rewrite translated glyph/outline pixels.
    return y in {0, 15} or x < 4 or x >= 28


def nearest_safe_consensus(consensus: list[list[int | None]], x: int, y: int) -> int | None:
    # Used only when a unanimous donor point itself is dark 4/5.  Search nearby
    # unanimous frame pixels and reuse a safe red/orange colour instead of ever
    # importing Japanese text/shadow colour.
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
    jp_rom = ORIGINAL_ROM.read_bytes()
    meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == meta["sha256"], "approved main TIP hash mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")

    main_ptr, main_off, main_clen, main_decoded = load_atlas(parent)
    jp_ptr, _jp_off, _jp_clen, jp_decoded = load_atlas(jp_rom)
    gate(main_ptr == EXPECTED_MAIN_PTR, f"main E0518 pointer drift: 0x{main_ptr:08X}")
    gate(jp_ptr == EXPECTED_JP_PTR, f"JP E0518 pointer drift: 0x{jp_ptr:08X}")

    labels = list(status.TYPE_LABELS.items())
    gate([spec["resource_index"] for _name, spec in labels] == [41, 42, 43, 44, 45, 46], "type label order drift")

    jp_canvases = {name: stitch(jp_decoded, spec) for name, spec in labels}
    main_canvases = {name: stitch(main_decoded, spec) for name, spec in labels}

    # Per-pixel unanimous Japanese geometry.  Text differs among all six labels,
    # while the rounded frame is common; unanimous + ring is therefore a strict
    # structural donor test.
    consensus: list[list[int | None]] = [[None] * 32 for _ in range(16)]
    unanimous_count = 0
    for y in range(16):
        for x in range(32):
            values = [jp_canvases[name][y][x] for name, _spec in labels]
            if len(set(values)) == 1:
                consensus[y][x] = values[0]
                unanimous_count += 1

    atlas = bytearray(main_decoded)
    reports = []
    all_changed_coords: list[tuple[str, int, int, int, int, str]] = []
    target_tile_ids = {tile for _name, spec in labels for row in spec["tiles"] for tile in row}

    for name, spec in labels:
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
                source_kind = "unanimous_jp_frame"
                value = int(donor)
                if value in FORBIDDEN_JP_INK:
                    replacement = nearest_safe_consensus(consensus, x, y)
                    if replacement is None:
                        continue
                    value = replacement
                    source_kind = "safe_neighbor_substitution"
                    substituted += 1
                elif value not in SAFE_FRAME:
                    continue
                gate(value not in FORBIDDEN_JP_INK, f"{name}: JP glyph/shadow donor escaped filter")
                if after[y][x] != value:
                    old = after[y][x]
                    after[y][x] = value
                    copied += 1
                    all_changed_coords.append((name, x, y, old, value, source_kind))

        # The interior is byte/pixel-identical to main TIP; only the perimeter
        # may change.  This guarantees Korean glyphs are not regenerated/replaced.
        for y in range(16):
            for x in range(32):
                if not in_frame_ring(x, y):
                    gate(after[y][x] == before[y][x], f"{name}: interior pixel changed at {x},{y}")
        gate(copied > 0, f"{name}: no rounded-frame pixels restored")
        write_canvas(atlas, spec, after)
        reports.append({
            "label": name,
            "resource_index": spec["resource_index"],
            "tiles": [tile for row in spec["tiles"] for tile in row],
            "changed_frame_pixels": copied,
            "dark_donor_pixels_substituted": substituted,
            "nonunanimous_ring_pixels_skipped": skipped_nonunanimous,
        })

    # Decoded-atlas diff must be confined to the six type-label blocks.
    changed_tiles = []
    for tile_id in range(len(main_decoded) // 32):
        a = main_decoded[tile_id * 32:(tile_id + 1) * 32]
        b = atlas[tile_id * 32:(tile_id + 1) * 32]
        if a != b:
            changed_tiles.append(tile_id)
    gate(bool(changed_tiles), "no E0518 tiles changed")
    gate(set(changed_tiles) <= target_tile_ids, f"E0518 changes escaped type badges: {[hex(x) for x in changed_tiles if x not in target_tile_ids]}")
    gate(all(new not in FORBIDDEN_JP_INK for _name, _x, _y, _old, new, _kind in all_changed_coords), "patch writes JP glyph/shadow index")

    packed = status.literal_only_compress(bytes(atlas))
    gate(len(packed) == 4 + main_clen, f"E0518 stream size drift: {len(packed)} vs {4 + main_clen}")
    candidate = bytearray(parent)
    candidate[main_off:main_off + len(packed)] = packed
    candidate = bytes(candidate)

    # ROM scope: only the already-relocated E0518 stream may differ.
    escaped = [
        i for i, (a, b) in enumerate(zip(parent, candidate))
        if a != b and not (main_off <= i < main_off + len(packed))
    ]
    gate(not escaped, f"ROM changes escaped E0518 stream: {[hex(i) for i in escaped[:8]]}")
    check_ptr, _check_off, _check_clen, check_decoded = load_atlas(candidate)
    gate(check_ptr == main_ptr, "E0518 pointer changed")
    gate(check_decoded == bytes(atlas), "E0518 compression roundtrip mismatch")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(candidate)
    if MAIN_SAV.is_file():
        shutil.copy2(MAIN_SAV, RESULT.with_suffix(".sav"))

    # MAIN / JP / AFTER comparison.  The JP column is diagnostic only; the
    # actual patch does not copy text/shadow because donor pixels are filtered.
    scale = 4
    badge_w, badge_h = 32 * scale, 16 * scale
    margin_x, margin_y = 14, 22
    canvas = Image.new("RGB", (badge_w * 3 + margin_x * 4, (badge_h + margin_y) * 6 + 26), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin_x, 5), "MAIN TIP", fill="white")
    draw.text((badge_w + margin_x * 2, 5), "JP geometry", fill="white")
    draw.text((badge_w * 2 + margin_x * 3, 5), "AFTER", fill="white")
    after_decoded = bytes(atlas)
    for row_index, (name, spec) in enumerate(labels):
        y = 26 + row_index * (badge_h + margin_y)
        draw.text((2, y + badge_h + 2), f"E0518[{spec['resource_index']}]", fill="white")
        imgs = [render_badge(stitch(main_decoded, spec), scale), render_badge(stitch(jp_decoded, spec), scale), render_badge(stitch(after_decoded, spec), scale)]
        for col, img in enumerate(imgs):
            x = margin_x + col * (badge_w + margin_x)
            canvas.paste(img, (x, y))
    canvas.save(PREVIEW)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_e0518_type_badges_round_restore_candidate_20260905",
        "result": "PASS",
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {"path": advance_relative(RESULT), "sha256": sha256(candidate), "size": len(candidate), "preview": advance_relative(PREVIEW)},
        "scope": {
            "resource_table": "0x080E0518",
            "active_atlas": hex(main_ptr),
            "resources": [41, 42, 43, 44, 45, 46],
            "labels": [name for name, _spec in labels],
            "changed_tiles": [hex(x) for x in changed_tiles],
        },
        "method": {
            "baseline": "approved main TIP only; all prior remodel/scanline test candidates are excluded as parents",
            "geometry_donor": "pixel must be identical across all six clean JP type badges and lie in outer rounded-frame ring",
            "frame_ring": "y=0/15 or x<4 or x>=28",
            "safe_written_indices": sorted(SAFE_FRAME),
            "forbidden_jp_text_shadow_indices": sorted(FORBIDDEN_JP_INK),
            "dark_unanimous_border_handling": "never copied; substitute nearest unanimous safe frame colour",
            "korean_interior": "byte/pixel-identical to approved main TIP before frame restoration",
        },
        "reports": reports,
        "verification": {
            "main_tip_unmodified": True,
            "only_e0518_stream_changed": True,
            "only_type_label_tiles_changed_in_decoded_atlas": True,
            "no_patch_write_uses_index_4_or_5": True,
            "compression_roundtrip": True,
            "unanimous_jp_pixels": unanimous_count,
            "total_changed_frame_pixels": len(all_changed_coords),
            "runtime_emulator": "not verified",
        },
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "output": str(RESULT),
        "sha256": sha256(candidate),
        "preview": str(PREVIEW),
        "changed_tiles": len(changed_tiles),
        "changed_frame_pixels": len(all_changed_coords),
        "reports": reports,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
