#!/usr/bin/env python3
"""Patch the actual battle-forecast BG2 row resources with Korean mini labels.

The supplied main-TIP savestate proves that the visible forecast top bar is
not sourced from the previously patched A8C004 cells.  0x0803860E draws
resource 0x08A85FB4 directly to BG2, and the live VRAM tiles for 実/攻/命 are
byte-identical to that resource.  This builder patches that real source and
the conditional 24x2 row variants.  It also repairs the older A8C004 raw-cell
patch using the correct interleaved tile matrix so the historical false pairing
does not remain in the main TIP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

import build_ggen_advance_battle_weapon_fixed_graphics_galmuri7_poc as fixed
from ggen_advance_project_paths import ADVANCE_ROOT

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
SOURCE_MAIN_ROM = (
    ADVANCE_ROOT
    / "integrated"
    / "main_tip"
    / "backups"
    / "20260830T001604Z_battle_forecast_bg2_runtime_rows_galmuri7_20260830"
    / "SD Gundam GGeneration Advance (Korean).gba"
)
OUT = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_battle_forecast_ui" / "ggen_advance_battle_forecast_runtime_rows_galmuri7_candidate_20260830.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_forecast_runtime_rows_galmuri7_20260830.json"
PREVIEW = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_battle_forecast_ui" / "ggen_advance_battle_forecast_runtime_rows_galmuri7_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "a3b1c5e4566762f5e486364ff4abace675548f29a34215bd81604925772d01e1"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

# Source cells proved by the current main-TIP state plus equivalent conditional
# row variants selected by the same forecast routine.  Each tuple is
# (top 8x8 file offset, bottom 8x8 file offset, patch mode).
ROW_CELLS = {
    "0x08A85FB4_base": {
        "실": (0x00A8616C, 0x00A8624C, "physical_edge_variant"),
        "공": (0x00A861CC, 0x00A8626C, "exact_canonical"),
        "명": (0x00A8620C, 0x00A8628C, "exact_canonical"),
    },
    "0x08A8642C_default": {
        "실": (0x00A8649C, 0x00A8657C, "physical_edge_variant"),
        "공": (0x00A864FC, 0x00A8659C, "exact_canonical"),
        "명": (0x00A8653C, 0x00A865BC, "exact_canonical"),
    },
    "0x08A8661C_branch_a": {
        "공": (0x00A866EC, 0x00A8678C, "exact_canonical"),
        "명": (0x00A8672C, 0x00A867AC, "exact_canonical"),
    },
    "0x08A8680C_branch_b": {
        "공": (0x00A868DC, 0x00A8697C, "exact_canonical"),
        "명": (0x00A8691C, 0x00A8699C, "exact_canonical"),
    },
}

# Correct tile pairing inside sprite resource 0x08A8C004.  The old 22.78
# analyzer incorrectly assumed eight consecutive 64-byte cells.  In reality
# the latter six labels are interleaved by tile row/column.
RAW_RESOURCE = 0x00A8C004
RAW_GRAPHICS = 0x00A8CFD4
RAW_PALETTE = 0x00A8D7F4
RAW_TILE_PAIRS = {
    "실": (15, 16),
    "공": (17, 18),
    "명": (19, 21),
    "탄": (20, 22),
    "사": (23, 25),
    "전": (24, 26),
    "근": (27, 29),
    "단": (28, 30),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_cell(data: bytes, translation: str) -> bytes:
    spec = fixed.LABELS[translation]
    start = int(spec["offset"]) + fixed.GRAPHIC_REL
    return data[start : start + fixed.GRAPHIC_BYTES]


def split_cell(cell: bytes) -> tuple[bytes, bytes]:
    gate(len(cell) == 64, "canonical cell must be 64 bytes")
    return cell[:32], cell[32:]


def join_pair(data: bytes | bytearray, top: int, bottom: int) -> bytes:
    return bytes(data[top : top + 32]) + bytes(data[bottom : bottom + 32])


def write_pair(data: bytearray, top: int, bottom: int, payload: bytes) -> None:
    upper, lower = split_cell(payload)
    data[top : top + 32] = upper
    data[bottom : bottom + 32] = lower


def patch_exact_row_cell(
    rom: bytearray,
    main_before: bytes,
    jp: bytes,
    translation: str,
    top: int,
    bottom: int,
    family: str,
) -> dict:
    source_pair = join_pair(jp, top, bottom)
    before_pair = join_pair(main_before, top, bottom)
    canonical_jp = canonical_cell(jp, translation)
    canonical_ko = canonical_cell(main_before, translation)
    gate(source_pair == canonical_jp, f"row source is not canonical {translation}: {family}")
    gate(before_pair == source_pair, f"row cell already differs from Japanese source: {family}/{translation}")
    gate(canonical_ko != canonical_jp, f"canonical Korean fixed label missing: {translation}")
    write_pair(rom, top, bottom, canonical_ko)
    return {
        "family": family,
        "translation": translation,
        "mode": "exact_canonical_copy",
        "top_file_offset": f"0x{top:08X}",
        "bottom_file_offset": f"0x{bottom:08X}",
        "before_sha256": sha256(before_pair),
        "after_sha256": sha256(canonical_ko),
        "canonical_fixed_resource": f"0x{int(fixed.LABELS[translation]['offset']):08X}",
    }


def patch_physical_edge_variant(
    rom: bytearray,
    main_before: bytes,
    jp: bytes,
    top: int,
    bottom: int,
    family: str,
) -> dict:
    translation = "실"
    variant_jp = join_pair(jp, top, bottom)
    variant_before = join_pair(main_before, top, bottom)
    canonical_jp_bytes = canonical_cell(jp, translation)
    canonical_ko_bytes = canonical_cell(main_before, translation)
    gate(variant_before == variant_jp, f"physical row variant already differs: {family}")
    gate(canonical_ko_bytes != canonical_jp_bytes, "canonical Korean physical label missing")

    variant = fixed.decode_8x16(variant_jp)
    canonical_jp = fixed.decode_8x16(canonical_jp_bytes)
    canonical_ko = fixed.decode_8x16(canonical_ko_bytes)
    variant_positions = {
        (x, y)
        for y in range(16)
        for x in range(8)
        if variant[y][x] != canonical_jp[y][x]
    }
    korean_positions = {
        (x, y)
        for y in range(16)
        for x in range(8)
        if canonical_ko[y][x] != canonical_jp[y][x]
    }
    # Both measured left-edge variants differ from the canonical 実 cell only
    # by six frame pixels at the far edge.  None overlap the glyph rewrite.
    gate(len(variant_positions) == 6, f"unexpected physical edge delta in {family}: {len(variant_positions)}")
    gate(not (variant_positions & korean_positions), f"physical edge delta overlaps Korean glyph in {family}")

    result = [row[:] for row in canonical_ko]
    for x, y in variant_positions:
        result[y][x] = variant[y][x]
    patched = fixed.encode_8x16(result)
    write_pair(rom, top, bottom, patched)
    return {
        "family": family,
        "translation": translation,
        "mode": "canonical_korean_plus_native_edge_delta",
        "top_file_offset": f"0x{top:08X}",
        "bottom_file_offset": f"0x{bottom:08X}",
        "native_edge_delta_pixels": len(variant_positions),
        "edge_delta_overlaps_korean_glyph": False,
        "before_sha256": sha256(variant_before),
        "after_sha256": sha256(patched),
        "canonical_fixed_resource": f"0x{int(fixed.LABELS[translation]['offset']):08X}",
    }


def repair_raw_matrix(rom: bytearray, main_before: bytes, jp: bytes) -> list[dict]:
    reports = []
    for translation, (top_tile, bottom_tile) in RAW_TILE_PAIRS.items():
        top = RAW_GRAPHICS + top_tile * 32
        bottom = RAW_GRAPHICS + bottom_tile * 32
        canonical_jp = canonical_cell(jp, translation)
        canonical_ko = canonical_cell(main_before, translation)
        jp_top, jp_bottom = split_cell(canonical_jp)
        ko_top, ko_bottom = split_cell(canonical_ko)
        gate(jp[top : top + 32] == jp_top, f"raw matrix top pairing drift: {translation}")
        gate(jp[bottom : bottom + 32] == jp_bottom, f"raw matrix bottom pairing drift: {translation}")
        before_pair = join_pair(main_before, top, bottom)
        rom[top : top + 32] = ko_top
        rom[bottom : bottom + 32] = ko_bottom
        after_pair = ko_top + ko_bottom
        reports.append(
            {
                "translation": translation,
                "top_tile_id": top_tile,
                "bottom_tile_id": bottom_tile,
                "top_file_offset": f"0x{top:08X}",
                "bottom_file_offset": f"0x{bottom:08X}",
                "before_sha256": sha256(before_pair),
                "after_sha256": sha256(after_pair),
                "japanese_pair_matches_fixed_descriptor": True,
                "repair": "overwrite the correctly interleaved pair with the already-approved Korean fixed-label halves",
            }
        )
    return reports


def decode_pair(data: bytes | bytearray, top: int, bottom: int) -> list[list[int]]:
    return fixed.decode_8x16(join_pair(data, top, bottom))


def render_cell(pixels: list[list[int]], scale: int = 5) -> Image.Image:
    palette = {
        0: (0, 0, 0), 1: (20, 20, 20), 2: (35, 35, 35), 3: (45, 45, 45),
        4: (55, 55, 55), 5: (80, 80, 80), 6: (110, 110, 110), 7: (140, 140, 140),
        8: (175, 175, 175), 9: (205, 205, 205), 10: (220, 220, 220), 11: (230, 230, 230),
        12: (190, 160, 70), 13: (205, 180, 80), 14: (230, 205, 105), 15: (255, 240, 145),
    }
    image = Image.new("RGB", (8, 16), (0, 0, 0))
    for y in range(16):
        for x in range(8):
            image.putpixel((x, y), palette[pixels[y][x]])
    return image.resize((8 * scale, 16 * scale), Image.Resampling.NEAREST)


def build_preview(jp: bytes, patched: bytes, out: Path) -> None:
    # First three columns are the exact live source cells from the savestate
    # trace.  Remaining five show the repaired raw-matrix labels not visible in
    # that single captured weapon.
    cells = [
        ("실", 0x00A8616C, 0x00A8624C),
        ("공", 0x00A861CC, 0x00A8626C),
        ("명", 0x00A8620C, 0x00A8628C),
    ]
    for translation in ("탄", "사", "전", "근", "단"):
        top_tile, bottom_tile = RAW_TILE_PAIRS[translation]
        cells.append((translation, RAW_GRAPHICS + top_tile * 32, RAW_GRAPHICS + bottom_tile * 32))
    scale = 5
    image = Image.new("RGB", (8 * scale * len(cells), 16 * scale * 2), (0, 0, 0))
    for column, (_translation, top, bottom) in enumerate(cells):
        image.paste(render_cell(decode_pair(jp, top, bottom), scale), (column * 8 * scale, 0))
        image.paste(render_cell(decode_pair(patched, top, bottom), scale), (column * 8 * scale, 16 * scale))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=SOURCE_MAIN_ROM)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--preview", type=Path, default=PREVIEW)
    args = parser.parse_args()

    main_before = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(sha256(main_before) == EXPECTED_MAIN_SHA256, f"unexpected main TIP hash: {sha256(main_before)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"unexpected Japanese ROM hash: {sha256(jp)}")
    gate(len(main_before) == 32 * 1024 * 1024, f"unexpected main TIP size: {len(main_before)}")

    # The fixed battle-label family is already approved in the current main
    # TIP.  It is the canonical Korean pixel source for this visually identical
    # forecast family and avoids rerendering with a second implementation.
    for translation in fixed.LABELS:
        gate(canonical_cell(main_before, translation) != canonical_cell(jp, translation), f"fixed Korean label missing: {translation}")

    patched = bytearray(main_before)
    row_reports = []
    for family, labels in ROW_CELLS.items():
        for translation, (top, bottom, mode) in labels.items():
            if mode == "physical_edge_variant":
                row_reports.append(patch_physical_edge_variant(patched, main_before, jp, top, bottom, family))
            else:
                row_reports.append(patch_exact_row_cell(patched, main_before, jp, translation, top, bottom, family))

    raw_reports = repair_raw_matrix(patched, main_before, jp)

    changed = [index for index, (before, after) in enumerate(zip(main_before, patched)) if before != after]
    allowed: set[int] = set()
    for labels in ROW_CELLS.values():
        for top, bottom, _mode in labels.values():
            allowed.update(range(top, top + 32))
            allowed.update(range(bottom, bottom + 32))
    for top_tile, bottom_tile in RAW_TILE_PAIRS.values():
        for tile in (top_tile, bottom_tile):
            start = RAW_GRAPHICS + tile * 32
            allowed.update(range(start, start + 32))
    gate(changed and all(index in allowed for index in changed), "changes escaped forecast label source tiles")

    # The raw matrix pairing covers exactly tiles 15..30 once each.
    covered_raw_tiles = sorted(tile for pair in RAW_TILE_PAIRS.values() for tile in pair)
    gate(covered_raw_tiles == list(range(15, 31)), f"raw tile matrix is not a complete 15..30 permutation: {covered_raw_tiles}")

    # Resource metadata/palettes and all code remain byte-identical because the
    # allowed ranges contain graphic tile payloads only.  Gate the important
    # A8C004 metadata explicitly as a regression guard.
    gate(bytes(patched[RAW_RESOURCE:RAW_GRAPHICS]) == main_before[RAW_RESOURCE:RAW_GRAPHICS], "A8C004 header/frame table changed")
    gate(bytes(patched[RAW_PALETTE:RAW_PALETTE + 0x60]) == main_before[RAW_PALETTE:RAW_PALETTE + 0x60], "A8C004 palette changed")
    gate(bytes(patched[0x00038000:0x00039700]) == main_before[0x00038000:0x00039700], "forecast Thumb code changed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(patched)
    build_preview(jp, patched, args.preview)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_runtime_rows_galmuri7",
        "result": "PASS",
        "source": {
            "main_path": str(args.main.relative_to(ADVANCE_ROOT)),
            "main_sha256": sha256(main_before),
            "japanese_sha256": sha256(jp),
            "runtime_state_analysis": "legacy/analysis/ggen_advance_battle_forecast_main_state_20260830.json",
        },
        "runtime_ownership": {
            "visible_owner": "BG2",
            "base_resource": "0x08A85FB4",
            "base_draw": "0x0803860E -> 0x08001C50",
            "destination": "0x0600E800",
            "live_state_badges": {"実": "실", "攻": "공", "命": "명"},
            "conditional_row_resources": ["0x08A8642C", "0x08A8661C", "0x08A8680C"],
        },
        "row_patches": row_reports,
        "raw_matrix_repair": {
            "resource": "0x08A8C004",
            "graphics": f"0x{RAW_GRAPHICS:08X}",
            "reason": "22.78 paired later labels as adjacent 64-byte cells, but the source tiles are interleaved",
            "correct_pairs": {translation: list(pair) for translation, pair in RAW_TILE_PAIRS.items()},
            "patches": raw_reports,
        },
        "output": {
            "path": str(args.out.relative_to(ADVANCE_ROOT)),
            "size": len(patched),
            "sha256": sha256(bytes(patched)),
            "preview": str(args.preview.relative_to(ADVANCE_ROOT)),
        },
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "changed_bytes_confined_to_proven_graphic_tiles": True,
            "base_live_row_three_labels_patched": True,
            "conditional_attack_hit_variants_patched": True,
            "two_physical_edge_variants_preserve_native_frame_pixels": True,
            "raw_matrix_tiles_15_through_30_rebuilt_once_each": True,
            "raw_source_pairs_match_japanese_fixed_descriptors": True,
            "korean_pixels_reused_from_approved_fixed_battle_labels": True,
            "resource_headers_frame_tables_palettes_unchanged": True,
            "forecast_thumb_code_unchanged": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": report["output"]["sha256"],
        "changed_bytes": len(changed),
        "row_patches": len(row_reports),
        "raw_matrix_patches": len(raw_reports),
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
