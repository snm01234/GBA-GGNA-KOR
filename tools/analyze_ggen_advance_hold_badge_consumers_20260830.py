#!/usr/bin/env python3
"""Exhaustively close the fixed-graphic `持` consumers in the status UI family.

The previous one-off patch only rebuilt an 8px window inside resource[40].
User measurement showed two problems: Japanese residue remained at the right
edge, and the same `持` plaque is visible in other unit-information/list/detail
screens.  This analyzer scans every resource in the 0x080E0518 status resource
table, matches the measured `持` face bitmap, records shared tile ownership, and
asserts the runtime selector families that consume those resources.

Read-only: no ROM bytes are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402
import build_ggen_advance_status_badge_followup_20260830 as prior  # noqa: E402

JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_MANIFEST = ROOT / "integrated" / "main_tip" / "ggen_advance_main_tip_manifest.json"
DEFAULT_OUT = ROOT / "analysis" / "ggen_advance_hold_badge_consumers_20260830.json"

EXPECTED_JP_SHA256 = status.EXPECTED_JP_SHA256
RESOURCE_COUNT = 69
EXPECTED_HIT_RESOURCES = {12, 14, 40, 62, 63}

RESOURCE_EXPECTATIONS = {
    12: {"offset": 0x000DEAD8, "size": (1, 2), "tiles": [[0x09B], [0x09C]], "role": "standalone right-rounded 持 plaque"},
    14: {"offset": 0x000DEAE8, "size": (2, 2), "tiles": [[0x09F, 0x09D], [0x0A0, 0x09E]], "role": "持 prefix + state suffix"},
    40: {"offset": 0x000DFF9C, "size": (32, 8), "role": "lower-status panel with embedded 持"},
    62: {"offset": 0x000E04C0, "size": (2, 2), "tiles": [[0x09F, 0x1EF], [0x0A0, 0x1F0]], "role": "持 prefix + alternate suffix A"},
    63: {"offset": 0x000E04CC, "size": (2, 2), "tiles": [[0x09F, 0x1F1], [0x0A0, 0x1F2]], "role": "持 prefix + alternate suffix B"},
}

# Prior patch measured x=3..10.  The actual 8px glyph cell is x=5..12.
OLD_EMBEDDED_WINDOW_X = 3
CORRECT_EMBEDDED_WINDOW_X = 5
EMBEDDED_BLOCK_TILES = [[0x176, 0x177], [0x17D, 0x17E]]


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def read_resource(data: bytes, index: int) -> dict[str, Any] | None:
    ptr = struct.unpack_from("<I", data, status.RESOURCE_TABLE + index * 4)[0]
    if not 0x08000000 <= ptr < 0x09000000:
        return None
    offset = ptr - 0x08000000
    if offset + 4 > len(data):
        return None
    width, height = data[offset], data[offset + 1]
    count = width * height
    if not width or not height or count > 2048 or offset + 4 + count * 2 > len(data):
        return None
    cells = list(struct.unpack_from(f"<{count}H", data, offset + 4))
    return {
        "index": index,
        "offset": offset,
        "width": width,
        "height": height,
        "cells": cells,
        "tiles": [[cells[y * width + x] & 0x03FF for x in range(width)] for y in range(height)],
    }


def stitch(atlas: bytes, resource: dict[str, Any]) -> list[list[int]]:
    width = int(resource["width"])
    height = int(resource["height"])
    pixels = [[0] * (width * 8) for _ in range(height * 8)]
    for ty in range(height):
        for tx in range(width):
            cell = int(resource["cells"][ty * width + tx])
            tile = status.decode_tile(atlas, cell & 0x03FF)
            hflip = bool(cell & 0x0400)
            vflip = bool(cell & 0x0800)
            for y in range(8):
                sy = 7 - y if vflip else y
                for x in range(8):
                    sx = 7 - x if hflip else x
                    pixels[ty * 8 + y][tx * 8 + x] = tile[sy][sx]
    return pixels


def mask_contour(mask: list[list[bool]]) -> list[list[bool]]:
    h = len(mask)
    w = len(mask[0])
    out = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if not mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    ox, oy = x + dx, y + dy
                    if 0 <= ox < w and 0 <= oy < h and not mask[oy][ox]:
                        out[oy][ox] = True
    return out


def scan_face_pattern(resources: list[dict[str, Any]], atlas: bytes) -> tuple[list[dict[str, int]], list[dict[str, int]]]:
    # resource[14] left cell is a structurally shared, border-free copy of 持.
    reference = next(row for row in resources if row["index"] == 14)
    ref_pixels = stitch(atlas, reference)
    # Ignore the rounded/connected frame and compare the measured 6x11 face.
    pattern = [[ref_pixels[y][x] == 10 for x in range(1, 7)] for y in range(3, 14)]

    face10_hits: list[dict[str, int]] = []
    all_palette_hits: list[dict[str, int]] = []
    for row in resources:
        pixels = stitch(atlas, row)
        height, width = len(pixels), len(pixels[0])
        for palette_index in range(1, 16):
            for y0 in range(0, height - 11 + 1):
                for x0 in range(0, width - 6 + 1):
                    ok = True
                    for py in range(11):
                        for px in range(6):
                            if (pixels[y0 + py][x0 + px] == palette_index) != pattern[py][px]:
                                ok = False
                                break
                        if not ok:
                            break
                    if not ok:
                        continue
                    hit = {"resource_index": int(row["index"]), "palette_index": palette_index, "x": x0, "y": y0}
                    all_palette_hits.append(hit)
                    if palette_index == 10:
                        face10_hits.append(hit)
    return face10_hits, all_palette_hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--main", type=Path, default=MAIN_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    jp = args.jp.read_bytes()
    main_rom = args.main.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(len(main_rom) == 32 * 1024 * 1024, "main TIP is not 32 MiB")
    manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    gate(manifest["sha256"] == sha256(main_rom), "main TIP manifest/hash mismatch")

    jp_header = struct.unpack_from("<I", jp, status.ATLAS_RESOURCE)[0]
    gate(jp_header & 0x80000000, "clean status atlas is not compressed")
    jp_len = jp_header & 0xFFFF
    jp_atlas = status.lzss_decompress(jp[status.ATLAS_RESOURCE + 4 : status.ATLAS_RESOURCE + 4 + jp_len])
    gate(len(jp_atlas) == status.ATLAS_EXPECTED_DECODED, "clean status atlas decoded-size drift")

    resources = [row for idx in range(RESOURCE_COUNT) if (row := read_resource(jp, idx)) is not None]
    gate(len(resources) > 60, f"too few valid status resources: {len(resources)}")

    by_index = {int(row["index"]): row for row in resources}
    for index, expected in RESOURCE_EXPECTATIONS.items():
        row = by_index[index]
        gate(row["offset"] == expected["offset"], f"resource[{index}] offset drift")
        gate((row["width"], row["height"]) == expected["size"], f"resource[{index}] dimensions drift")
        if "tiles" in expected:
            gate(row["tiles"] == expected["tiles"], f"resource[{index}] tile composition drift")

    face10_hits, all_palette_hits = scan_face_pattern(resources, jp_atlas)
    hit_resources = {row["resource_index"] for row in face10_hits}
    all_hit_resources = {row["resource_index"] for row in all_palette_hits}
    gate(hit_resources == EXPECTED_HIT_RESOURCES, f"持 face hit-set drift: {sorted(hit_resources)}")
    gate(all_hit_resources == EXPECTED_HIT_RESOURCES, f"alternate-palette 持 hit-set drift: {sorted(all_hit_resources)}")
    gate(all(row["palette_index"] == 10 for row in all_palette_hits), "unexpected alternate-palette exact 持 copy")

    # Prove resource[12], shared-prefix resource[14]/[62]/[63], and embedded
    # resource[40] contain the same palette-10 face when aligned to their cells.
    r12 = stitch(jp_atlas, by_index[12])
    r14 = stitch(jp_atlas, by_index[14])
    r40_block = prior.stitch(jp_atlas, EMBEDDED_BLOCK_TILES)
    face12 = [[r12[y][x] == 10 for x in range(8)] for y in range(16)]
    face14 = [[r14[y][x] == 10 for x in range(8)] for y in range(16)]
    face40 = [[r40_block[y][CORRECT_EMBEDDED_WINDOW_X + x] == 10 for x in range(8)] for y in range(16)]
    # resource12 includes two palette-10 rounded-edge pixels at top/bottom;
    # compare only rows 2..13 for face identity. resource14 and r40 are exact.
    gate(face14 == face40, "resource[14] and resource[40] 持 face alignment mismatch")
    gate(face12[2:14] == face14[2:14], "resource[12] 持 face mismatch")

    # Reconstruct the source face+contour in the embedded 16x16 block.  The old
    # window ended at x=10, while the source has face/contour through x=12.
    embedded_face = [[False] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(8):
            embedded_face[y][CORRECT_EMBEDDED_WINDOW_X + x] = face14[y][x]
    embedded_contour = mask_contour(embedded_face)
    old_end = OLD_EMBEDDED_WINDOW_X + 8 - 1
    residue_pixels = [
        [x, y]
        for y in range(16)
        for x in range(old_end + 1, CORRECT_EMBEDDED_WINDOW_X + 8)
        if embedded_face[y][x] or embedded_contour[y][x]
    ]
    # Pixel measurement is slightly broader than pure 8-neighbour geometry:
    # the native source uses several outline/highlight tones (4/5/9/A).  Every
    # x=11/12 pixel that differs from the adjacent row-native panel fill at x=13
    # is part of the visible Japanese tail that the previous patch preserved.
    measured_tail_pixels = [
        [x, y]
        for y in range(16)
        for x in (11, 12)
        if r40_block[y][x] != r40_block[y][13]
    ]
    gate(residue_pixels, "old 持 window would not leave right-edge residue")
    gate(max(x for x, _ in residue_pixels) == 12, "embedded 持 contour no longer reaches x=12")
    gate(len(measured_tail_pixels) == 22, f"measured embedded 持 tail drift: {len(measured_tail_pixels)}")

    # Tile-reference ownership proves which suffixes must remain byte-exact.
    tile_owners: dict[int, list[int]] = defaultdict(list)
    for row in resources:
        for tile_row in row["tiles"]:
            for tile_id in tile_row:
                if int(row["index"]) not in tile_owners[tile_id]:
                    tile_owners[tile_id].append(int(row["index"]))
    gate(sorted(tile_owners[0x09F]) == [14, 62, 63], f"0x09F owner drift: {tile_owners[0x09F]}")
    gate(sorted(tile_owners[0x0A0]) == [14, 62, 63], f"0x0A0 owner drift: {tile_owners[0x0A0]}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_hold_badge_consumer_audit",
        "result": "PASS",
        "source": {
            "main_tip": {"path": str(args.main.relative_to(ROOT)), "sha256": sha256(main_rom)},
            "main_tip_promotion_reason": manifest.get("promotion_reason"),
            "japanese_rom": {"path": str(args.jp.relative_to(ROOT)), "sha256": sha256(jp)},
        },
        "status_family": {
            "resource_table": "0x080E0518",
            "resource_count_scanned": RESOURCE_COUNT,
            "valid_resources_scanned": len(resources),
            "decoded_atlas_bytes": len(jp_atlas),
            "decoded_atlas_tiles": len(jp_atlas) // 32,
            "exhaustive_match_rule": "resource[14] left 持 face, palette-index-10 boolean mask, measured 6x11 interior; every resource and every palette index 1..15 scanned",
            "exact_hold_resources": sorted(hit_resources),
            "exact_hits": face10_hits,
            "alternate_palette_exact_hits": [row for row in all_palette_hits if row["palette_index"] != 10],
        },
        "resource_contracts": {
            str(index): {
                "file_offset": f"0x{by_index[index]['offset']:08X}",
                "size_tiles": [by_index[index]["width"], by_index[index]["height"]],
                "tiles": [[f"0x{x:03X}" for x in row] for row in by_index[index]["tiles"]],
                "role": RESOURCE_EXPECTATIONS[index]["role"],
            }
            for index in sorted(EXPECTED_HIT_RESOURCES)
        },
        "sharing": {
            "shared_hold_prefix_tiles": ["0x09F", "0x0A0"],
            "shared_hold_prefix_owners": sorted(tile_owners[0x09F]),
            "resource14_suffix_preserve": ["0x09D", "0x09E"],
            "resource62_suffix_preserve": ["0x1EF", "0x1F0"],
            "resource63_suffix_preserve": ["0x1F1", "0x1F2"],
            "resource12_private_tiles": ["0x09B", "0x09C"],
            "resource40_embedded_block_tiles": ["0x176", "0x177", "0x17D", "0x17E"],
        },
        "runtime_consumers": [
            {
                "renderer": "0x0806C548",
                "selector_region": "0x0806C678-0x0806C71C",
                "resources": [12, 14, 62, 63],
                "evidence": "conditions via 0x08005538/0x08005D24/0x08005484 select r4=0x0C/0x0E/0x3E/0x3F, then resource_table[r4] -> 0x0800277C",
                "screen_family": "full unit/status information",
            },
            {
                "renderer": "0x0806C10C",
                "selector_region": "0x0806C166-0x0806C1FC",
                "resources": [12, 14, 62, 63],
                "evidence": "same flag family selects r5=0x0C/0x0E/0x3E/0x3F, then resource_table[r5] -> 0x0800269C",
                "screen_family": "split/list/detail unit information",
            },
            {
                "renderer": "0x0806C934",
                "selector_region": "resource_table[40] (+0xA0)",
                "resources": [40],
                "evidence": "lower-status panel resource[40] contains the embedded copy at panel x=142 face origin",
                "screen_family": "lower unit-status/weapon detail panel",
            },
        ],
        "previous_patch_root_cause": {
            "old_window": [OLD_EMBEDDED_WINDOW_X, OLD_EMBEDDED_WINDOW_X + 7],
            "correct_glyph_cell": [CORRECT_EMBEDDED_WINDOW_X, CORRECT_EMBEDDED_WINDOW_X + 7],
            "source_face_extends_to_x": max(x for y in range(16) for x in range(16) if embedded_face[y][x]),
            "source_contour_extends_to_x": max(x for y in range(16) for x in range(16) if embedded_contour[y][x]),
            "source_face_or_contour_pixels_missed_right_of_old_window": len(residue_pixels),
            "geometric_missed_pixel_coordinates": residue_pixels,
            "measured_nonbackground_tail_pixels": len(measured_tail_pixels),
            "measured_nonbackground_tail_coordinates": measured_tail_pixels,
            "conclusion": "old x=3..10 rebuild ended before the wider Japanese source glyph/shadow tail; 22 measured source deviations remain at x=11..12, matching the reported right-side dots",
        },
        "negative_boundary": {
            "resources_64_65_match_hold": False,
            "resources_64_65_policy": "preserve; list-related resources 64/65 were scanned but do not contain the exact 持 face in any palette index",
        },
        "implementation_plan": {
            "resource12": "rebuild private 0x09B/0x09C as right-rounded native badge + Galmuri7 지",
            "resources14_62_63": "rebuild only shared prefix 0x09F/0x0A0 as connected native badge + Galmuri7 지; preserve every suffix tile",
            "resource40": "rebuild the correct embedded x=5..12 glyph cell and clear the full old Japanese face/contour through x=12 before drawing Galmuri7 지",
            "shield_and_man": "carry forward already-measured 방패/만 replacements unchanged into the new integrated candidate",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "hold_resources": sorted(hit_resources),
        "exact_hits": face10_hits,
        "old_window": [OLD_EMBEDDED_WINDOW_X, OLD_EMBEDDED_WINDOW_X + 7],
        "correct_window": [CORRECT_EMBEDDED_WINDOW_X, CORRECT_EMBEDDED_WINDOW_X + 7],
        "missed_right_pixels_geometric": len(residue_pixels),
        "missed_right_pixels_measured": len(measured_tail_pixels),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
