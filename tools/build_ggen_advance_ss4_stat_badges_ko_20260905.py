#!/usr/bin/env python3
"""Koreanize the proven ss4 ID-effect/stat badge family in the E0518 atlas.

The current ss4 screenshot binds 命中 and 反応 to status resources 24 and 27.
Native 12x12 glyph-shape matching also closes sibling resources 21=運動,
23=威力 and 25=装甲.  Resource 28 is a byte-identical alias of resource 21,
so patching 21 covers both consumers.

Every badge is a 32x16 raster.  Resource 24 (命中) is cleaned first and then
manually repaired into one canonical common background: its interrupted 1px
orange top line and 1px blue arrow line are reconnected, the left dark remnant
is replaced with yellow, and the right dark transition remnant is replaced with
green while the native rounded/cap geometry is otherwise retained.  That exact
clean canvas is then reused for resources 21/23/24/25/27 before Korean paint.
Korean Galmuri11 face uses a vertical 7->6->5 yellow-to-amber gradient and its
one-pixel outline uses dark index 3 instead of erroneous orange 5.

Uncertain resources 20/22 and resource 26 (which shares cap tiles with 20) are
left byte-exact rather than guessed.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import build_ggen_advance_status_ui_tile_overlay_poc as status
import build_ggen_advance_turn_ability_overlays_20260905 as raster
import render_ggen_ss_tiles_20260905 as fullrender
import test_ggen_advance_font_pair as fontpair
from ggen_ss_tiles_common_20260905 import ROOT, gallery
from ggen_advance_project_paths import FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM

TABLE = 0x000E0518
OUT = ROOT / "outputs" / "20260905_ggen_advance_ss4_stat_badges"
PREVIOUS_RESULT = OUT / "ggen_advance_ss4_stat_badges_ko_candidate_20260905.gba"
RESULT = OUT / "ggen_advance_ss4_stat_badges_ko_commonbg_gradient_candidate_20260905.gba"
MANIFEST = OUT / "manifest_commonbg_gradient.json"
VERIFY_LOG = OUT / "verification_commonbg_gradient.log"
STATE = ROOT / "SD Gundam GGeneration Advance (Korean).ss4"
# resource index, JP, KO, semantic evidence score
TARGETS = [
    # User-reported ss4 pair first so their before/clean/after previews are first.
    (24, "命中", "명중", 0.8311688311688312),
    (27, "反応", "반응", 0.84472049689441),
    (21, "運動", "운동", 0.7068273092369478),
    (23, "威力", "위력", 0.6461538461538462),
    (25, "装甲", "장갑", 0.8415300546448088),
]
# Native Galmuri11 placements.  The 1px outline stays strictly inside x=0..23,
# y=1..13, leaving the complete x=24..31 cap column and y=0/15 plaque edges
# byte-exact.  These are deliberately much larger than the previous Galmuri7
# candidate while still fitting the 32x16 resource.
ORIGINS = {24: (1, 2), 27: (1, 2), 21: (1, 2), 23: (2, 2), 25: (1, 2)}
ALIASES = {28: 21}
WITHHELD = {
    20: "semantic identity not yet closed strongly enough",
    22: "semantic identity not yet closed strongly enough",
    26: "semantic evidence suggests 回復, but its right-cap tiles are shared with resource 20; keep byte-exact until 20 is closed",
}
TEXT_X0 = 0
TEXT_X1 = 24  # complete fourth 8px tile column is native cap; never write it
TEXT_Y0 = 1
TEXT_Y1 = 15  # row 15 remains the native outer frame
FAMILY = tuple(range(20, 28))
JP_GLYPH_INDICES = {5, 6, 7}
FACE = 7
FACE_GRADIENT = (7, 6, 5)  # top -> middle -> bottom, ss4 bank-13 yellow/amber ramp
OUTLINE = 3
JP_ORIGIN = (1, 2)  # stat-family semantic match for all five JP labels
GREEN_INDICES = {12, 13, 14}
BLUE_INDICES = {8, 9, 10, 11, 15}
STRUCTURE_INDICES = GREEN_INDICES | BLUE_INDICES | {4}
GREEN_BG = 14
MAX_ARROW_GAP = 6


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_map(data: bytes, index: int) -> dict:
    obj = sem.parse_map(data, u32(data, TABLE + index * 4))
    assert obj is not None and (obj["width"], obj["height"]) == (4, 2), index
    return obj


def stitch(atlas: bytes | bytearray, obj: dict) -> list[list[int]]:
    return sem.stitch(bytes(atlas), obj)


def copy_canvas(c: list[list[int]]) -> list[list[int]]:
    return [row[:] for row in c]


def edge_round_pixels(before: list[list[int]]) -> set[tuple[int, int]]:
    """Preserve native yellow/orange round-edge components at the left/top edge.

    JP glyph face also uses indices 5/6/7, so palette value alone is not enough.
    Only components physically connected to x=0 are plaque-edge structure and
    are protected.  The actual JP labels start at semantic origin (1,2), so
    unrelated 5/6/7 highlight pixels along the top row are not protected.
    """
    pending = {
        (x, y)
        for y in range(TEXT_Y0, TEXT_Y1)
        for x in range(TEXT_X0, TEXT_X1)
        if before[y][x] in JP_GLYPH_INDICES
    }
    keep: set[tuple[int, int]] = set()
    while pending:
        seed = pending.pop()
        comp = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    p = (x + dx, y + dy)
                    if p in pending:
                        pending.remove(p)
                        comp.add(p)
                        stack.append(p)
        if any(x == 0 for x, _y in comp):
            keep |= comp
    return keep


def nearest_green(before: list[list[int]], x: int, y: int) -> int:
    for radius in range(1, 9):
        values = []
        for ny in range(max(TEXT_Y0, y - 1), min(TEXT_Y1, y + 2)):
            for nx in range(max(TEXT_X0, x - radius), min(TEXT_X1, x + radius + 1)):
                if max(abs(nx - x), abs(ny - y)) != radius and ny != y:
                    continue
                value = before[ny][nx]
                if value in GREEN_INDICES:
                    values.append(value)
        if values:
            return Counter(values).most_common(1)[0][0]
    return GREEN_BG


def bridged_blue_index(before: list[list[int]], x: int, y: int) -> int | None:
    """Bridge only short glyph-occluded gaps in an already-visible blue arrow row."""
    left = None
    right = None
    for nx in range(x - 1, TEXT_X0 - 1, -1):
        if before[y][nx] in BLUE_INDICES:
            left = (nx, before[y][nx])
            break
    for nx in range(x + 1, TEXT_X1):
        if before[y][nx] in BLUE_INDICES:
            right = (nx, before[y][nx])
            break
    if left is None or right is None:
        return None
    if right[0] - left[0] > MAX_ARROW_GAP:
        return None
    if left[1] == right[1]:
        return left[1]
    return left[1] if x - left[0] <= right[0] - x else right[1]


def clean_body(before: list[list[int]]) -> tuple[list[list[int]], dict, set[tuple[int, int]]]:
    """Remove JP text/shadow while preserving the native badge geometry.

    Only the semantic JP text footprint x=1..23,y=1..14 is eligible for cleanup.
    Existing green/blue/white/red structure stays byte-exact.  Non-structural
    dark/JP pixels are reconstructed as green except when bounded by a short
    blue run on the same row, in which case the hidden arrow segment is restored.
    The complete x=0 left edge, yellow/orange edge components, x=24..31 cap and
    y=0/15 outer frame remain native.
    """
    out = copy_canvas(before)
    round_keep = edge_round_pixels(before)
    zone = {
        (x, y)
        for y in range(TEXT_Y0, TEXT_Y1)
        for x in range(1, TEXT_X1)
    }
    rewrite = {
        (x, y)
        for x, y in zone
        if before[y][x] not in STRUCTURE_INDICES and (x, y) not in round_keep
    }
    arrow_restored = 0
    green_restored = 0
    for x, y in sorted(rewrite, key=lambda p: (p[1], p[0])):
        blue = bridged_blue_index(before, x, y)
        if blue is not None:
            out[y][x] = blue
            arrow_restored += 1
        else:
            out[y][x] = nearest_green(before, x, y)
            green_restored += 1

    jp_face_before = sum(before[y][x] in JP_GLYPH_INDICES for x, y in rewrite)
    dark_before = sum(before[y][x] == OUTLINE for x, y in rewrite)
    jp_face_after = sum(out[y][x] in JP_GLYPH_INDICES for x, y in rewrite)
    dark_after = sum(out[y][x] == OUTLINE for x, y in rewrite)
    assert jp_face_after == 0
    assert dark_after == 0
    assert all(out[y][x] == before[y][x] for x, y in round_keep)
    assert all(out[y][0] == before[y][0] for y in range(16))
    assert all(out[y][x] == before[y][x] for y in range(16) for x in range(TEXT_X1, 32))
    assert out[0] == before[0] and out[15] == before[15]
    assert all(
        out[y][x] == before[y][x]
        for y in range(16) for x in range(32)
        if (x, y) not in rewrite
    )
    # All native visible structure must remain exact; only glyph-covered gaps may
    # gain reconstructed blue/green pixels.
    assert all(
        out[y][x] == before[y][x]
        for y in range(16) for x in range(32)
        if before[y][x] in STRUCTURE_INDICES
    )

    return out, {
        "rewritten_pixels": len(rewrite),
        "native_face_shade_pixels_removed": jp_face_before,
        "native_dark_pixels_removed_from_body": dark_before,
        "native_face_shade_residue": jp_face_after,
        "native_dark_shadow_residue": dark_after,
        "arrow_gap_pixels_restored": arrow_restored,
        "green_pixels_restored": green_restored,
        "left_round_pixels_preserved": len(round_keep),
        "left_edge_byte_exact": True,
        "native_structure_indices_preserved": sorted(STRUCTURE_INDICES),
        "arrow_bridge_max_gap": MAX_ARROW_GAP,
        "donor_policy": "no sibling donor; preserve native structure and bridge only short same-row blue gaps, otherwise nearest native green",
        "mask_bbox": [1, TEXT_Y0, TEXT_X1, TEXT_Y1],
    }, rewrite


def build_common_background(hit_before: list[list[int]]) -> tuple[list[list[int]], dict]:
    """Finalize resource-24 clean into the canonical common badge background."""
    common, base_info, _ = clean_body(hit_before)

    # 1px orange highlight: reconnect the green-cut middle segment.
    orange_repairs = []
    for x in range(5, 24):
        if common[1][x] != 5:
            common[1][x] = 5
            orange_repairs.append((x, 1))

    # Left dark remnant belongs to the rounded yellow boundary.
    left_yellow_repairs = []
    for y in range(4, 7):
        if common[y][0] == OUTLINE:
            common[y][0] = 7
            left_yellow_repairs.append((0, y))

    # Right dark transition remnant is body-side green, not Korean shadow.
    right_green_repairs = []
    for y in range(3, 11):
        for x in (24, 25):
            if common[y][x] == OUTLINE:
                common[y][x] = GREEN_BG
                right_green_repairs.append((x, y))

    # 1px blue arrow line: reconnect the green-cut middle segment only.
    blue_repairs = []
    for x in range(2, 13):
        if common[12][x] != 8:
            common[12][x] = 8
            blue_repairs.append((x, 12))

    # The repaired clean background itself must contain no black residue.
    remaining_dark = [(x, y) for y in range(1, 15) for x in range(32) if common[y][x] == OUTLINE]
    assert not remaining_dark, remaining_dark
    assert all(common[1][x] == 5 for x in range(0, 28))
    assert all(common[y][0] == 7 for y in range(3, 12))
    assert all(common[12][x] == 8 for x in range(0, 25))

    return common, {
        "source_resource": 24,
        "base_cleanup": base_info,
        "orange_line_repairs": [list(p) for p in orange_repairs],
        "left_yellow_repairs": [list(p) for p in left_yellow_repairs],
        "right_green_repairs": [list(p) for p in right_green_repairs],
        "blue_line_repairs": [list(p) for p in blue_repairs],
        "remaining_dark_pixels": 0,
        "policy": "resource24 clean + explicit 1px line/edge repairs; reused byte-identically as common pre-text background",
    }


def paint(c: list[list[int]], text: str, font, origin: tuple[int, int]) -> dict:
    ink, w, h = raster.native_ink(font, text)
    x0, y0 = origin
    ink = {(x + x0, y + y0) for x, y in ink}
    dilated = raster.dilate(ink, 32, 16)
    outline_only = dilated - ink
    assert all(TEXT_X0 <= x < TEXT_X1 and TEXT_Y0 <= y < TEXT_Y1 for x, y in dilated), (text, x0, y0, w, h)
    for x, y in outline_only:
        c[y][x] = OUTLINE

    # Original-style vertical face ramp: pale yellow at the top, stronger yellow
    # in the middle, amber/yellow at the bottom.  Shadow remains a separate 1px 3.
    face_counts = Counter()
    for x, y in ink:
        rel = y - y0
        if rel * 3 < h:
            colour = FACE_GRADIENT[0]
        elif rel * 3 < h * 2:
            colour = FACE_GRADIENT[1]
        else:
            colour = FACE_GRADIENT[2]
        c[y][x] = colour
        face_counts[colour] += 1
    return {
        "origin": [x0, y0], "ink_width": w, "ink_height": h,
        "face_gradient": list(FACE_GRADIENT),
        "face_gradient_counts": {str(k): v for k, v in sorted(face_counts.items())},
        "outline": OUTLINE, "ink_pixels": len(ink),
        "outline_pixels": len(outline_only), "outline_radius": 1,
    }


def tile_updates(before: list[list[int]], after: list[list[int]], obj: dict) -> dict[int, bytes]:
    updates = {}
    for n, cell in enumerate(obj["cells"]):
        x0 = (n % 4) * 8
        y0 = (n // 4) * 8
        tile = [row[x0:x0 + 8] for row in after[y0:y0 + 8]]
        if cell & 0x400:
            tile = [list(reversed(row)) for row in tile]
        if cell & 0x800:
            tile = list(reversed(tile))
        payload = raster.encode_tile(tile)
        tid = cell & 0x3FF
        if tid in updates:
            assert updates[tid] == payload, ("shared tile conflict", tid)
        updates[tid] = payload
    return updates


def main() -> int:
    # The immediately preceding candidate is the requested binary base.  Keep it
    # byte-exact outside the E0518 atlas stream.  The current promoted main TIP is
    # only a reference because it may have advanced since that candidate was made.
    current_main = MAIN_TIP_ROM.read_bytes()
    current_meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    assert sha256(current_main) == current_meta["sha256"], "main TIP / manifest drift"
    previous = PREVIOUS_RESULT.read_bytes()
    parent = previous
    parent_crc = binascii.crc32(parent) & 0xFFFFFFFF

    atlas_ptr = u32(parent, TABLE)
    atlas_off = atlas_ptr - 0x08000000
    header = u32(parent, atlas_off)
    assert header & 0x80000000
    body_len = header & 0xFFFF
    old_blob = parent[atlas_off:atlas_off + 4 + body_len]
    atlas = bytearray(status.lzss_decompress(old_blob[4:]))
    assert len(atlas) == status.ATLAS_EXPECTED_DECODED == 519 * 32

    # Use the Japanese ROM as the clean native donor well.  The previous
    # candidate's target tiles are intentionally not trusted because they contain
    # the black-fill/Galmuri7 defect we are correcting.
    jp = (ROOT / "SD Gundam GGeneration Advance (Japan).gba").read_bytes()
    jp_ptr = u32(jp, TABLE) - 0x08000000
    jp_head = u32(jp, jp_ptr)
    jp_atlas = status.lzss_decompress(jp[jp_ptr + 4:jp_ptr + 4 + (jp_head & 0xFFFF)])
    assert len(jp_atlas) == len(atlas)
    # Korean main/candidate use the relocated atlas; the Japanese ROM keeps the
    # original atlas address.  Pointer equality is therefore not required.
    assert u32(parent, TABLE) == u32(current_main, TABLE)
    for idx, _src, _ko, _score in TARGETS:
        base_obj = parse_map(parent, idx)
        jp_obj = parse_map(jp, idx)
        assert [c & 0x3FF for c in base_obj["cells"]] == [c & 0x3FF for c in jp_obj["cells"]], idx

    # Resource 28 is a real map alias of 21.
    assert [c & 0x3FF for c in parse_map(parent, 28)["cells"]] == [c & 0x3FF for c in parse_map(parent, 21)["cells"]]

    # Current ss4 proves 命中 / 反応 are BG1, source atlas tile +1, palette bank 13.
    state, _ = statefmt.parse_png_state(STATE)
    bg1 = bg.bg_info(state, 1)
    assert not bg1["color_8bpp"]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    live_proof = {}
    for idx, label, xs in ((24, "명중", (64, 72, 80, 88)), (27, "반응", (96, 104, 112, 120))):
        obj = parse_map(parent, idx)
        source_ids = [c & 0x3FF for c in obj["cells"]]
        seen = []
        for row_i, sy in enumerate((104, 112)):
            for col_i, sx in enumerate(xs):
                wx, wy = sx + bg1["scroll_x"], sy + bg1["scroll_y"]
                entry = bg.map_entry(vram, bg1["screen_base"], bg1["size"], wx // 8, wy // 8)
                live_tid = entry & 0x3FF
                src_tid = source_ids[row_i * 4 + col_i]
                assert live_tid == src_tid + 1, (label, sx, sy, live_tid, src_tid)
                assert ((entry >> 12) & 15) == 13
                raw = bytes(vram[bg1["char_base"] + live_tid * 32:bg1["char_base"] + (live_tid + 1) * 32])
                assert raw == bytes(jp_atlas[src_tid * 32:(src_tid + 1) * 32])
                seen.append({"screen": [sx, sy], "source_tile": src_tid, "live_tile": live_tid, "palette": 13})
        live_proof[label] = seen

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    # Re-verify against the exact live ss4 palette bank 13, rather than using
    # palette assumptions from another screen/state.
    live_colors = raster.palette_rgb(state[statefmt.STATE_PALETTE + 13 * 32:statefmt.STATE_PALETTE + 14 * 32])
    assert live_colors[FACE] == (255, 255, 139), live_colors
    assert live_colors[OUTLINE] == (32, 16, 49), live_colors
    assert live_colors[5] == (255, 180, 41), live_colors  # old orange contour; do not reuse
    assert live_colors[14] == (106, 255, 65), live_colors  # native green backing/frame
    assert live_colors[8] == (65, 82, 197) and live_colors[15] == (255, 255, 255), live_colors
    # Build one canonical background from the user-selected resource-24 clean.
    family_canvases = {idx: stitch(jp_atlas, parse_map(parent, idx)) for idx in FAMILY}
    common_background, common_background_info = build_common_background(family_canvases[24])
    common_signature = tuple(tuple(row) for row in common_background)

    pending: dict[int, bytes] = {}
    reports = []
    previews = []
    preview_triplets = {}

    for idx, source, ko, score in TARGETS:
        obj = parse_map(parent, idx)
        before = family_canvases[idx]
        clean = copy_canvas(common_background)
        assert tuple(tuple(row) for row in clean) == common_signature
        cleanup_mask = {
            (x, y) for y in range(16) for x in range(32)
            if clean[y][x] != before[y][x]
        }
        assert clean[0] == common_background[0] and clean[15] == common_background[15]
        after = copy_canvas(clean)
        paint_info = paint(after, ko, font, ORIGINS[idx])
        updates = tile_updates(before, after, obj)
        changed = []
        for tid, new in updates.items():
            old = bytes(jp_atlas[tid * 32:(tid + 1) * 32])
            if old == new:
                continue
            if tid in pending:
                assert pending[tid] == new, ("cross-resource tile conflict", idx, tid)
            pending[tid] = new
            changed.append(tid)
        triplet = [
            (f"{source}->{ko} before", raster.render_canvas(before, live_colors)),
            (f"{ko} common clean", raster.render_canvas(clean, live_colors)),
            (f"{ko} gradient after", raster.render_canvas(after, live_colors)),
        ]
        previews.extend(triplet)
        preview_triplets[idx] = triplet
        reports.append({
            "resource_index": idx, "source": source, "ko": ko, "semantic_score": score,
            "tiles": [c & 0x3FF for c in obj["cells"]], "changed_tiles": changed,
            "cleanup": {
                "common_background_source": 24,
                "common_background_byte_identical_before_text": True,
                "changed_from_native_pixels": len(cleanup_mask),
                "before_palette_counts": {str(k): v for k, v in sorted(Counter(v for row in before for v in row).items())},
                "common_clean_palette_counts": {str(k): v for k, v in sorted(Counter(v for row in clean for v in row).items())},
            },
            **paint_info,
        })

    # Resource 28 must inherit exactly the resource-21 Korean raster.
    alias_before = stitch(jp_atlas, parse_map(parent, 28))
    alias_after_atlas = bytearray(jp_atlas)
    for tid, new in pending.items():
        alias_after_atlas[tid * 32:(tid + 1) * 32] = new
    alias_after = stitch(alias_after_atlas, parse_map(parent, 28))
    target21_after = stitch(alias_after_atlas, parse_map(parent, 21))
    assert alias_after == target21_after and alias_before == stitch(jp_atlas, parse_map(parent, 21))

    # Withheld sibling resources remain byte-exact, including all shared tiles not
    # intentionally changed. None of our selected resources shares tiles with 20/22/26.
    target_ids = {tid for r in reports for tid in r["tiles"]}
    for idx in WITHHELD:
        ids = {c & 0x3FF for c in parse_map(parent, idx)["cells"]}
        assert not (ids & target_ids), ("withheld resource shares patched tile", idx, sorted(ids & target_ids))

    patched_atlas = bytearray(atlas)
    for tid, new in pending.items():
        patched_atlas[tid * 32:(tid + 1) * 32] = new
    new_blob = status.literal_only_compress(bytes(patched_atlas))
    assert len(new_blob) == len(old_blob), (len(new_blob), len(old_blob))
    assert status.lzss_decompress(new_blob[4:]) == patched_atlas

    candidate = bytearray(parent)
    candidate[atlas_off:atlas_off + len(old_blob)] = new_blob
    assert candidate[:atlas_off] == parent[:atlas_off] and candidate[atlas_off + len(old_blob):] == parent[atlas_off + len(old_blob):]

    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(candidate)
    shutil.copy2(PREVIOUS_RESULT.with_suffix(".sav"), RESULT.with_suffix(".sav"))
    overall_preview = OUT / "ss4_stat_badges_before_commonclean_gradient_after.png"
    gallery(previews, overall_preview, 7)
    common_template_preview = OUT / "resource24_common_background_template.png"
    gallery([
        ("resource24 native before", raster.render_canvas(family_canvases[24], live_colors)),
        ("resource24 repaired common clean", raster.render_canvas(common_background, live_colors)),
    ], common_template_preview, 9)
    per_resource_previews = {
        24: OUT / "resource24_hit_before_commonclean_gradient_after.png",
        27: OUT / "resource27_reaction_before_commonclean_gradient_after.png",
        21: OUT / "resource21_motion_before_commonclean_gradient_after.png",
        23: OUT / "resource23_power_before_commonclean_gradient_after.png",
        25: OUT / "resource25_armor_before_commonclean_gradient_after.png",
    }
    for resource_index, preview_path in per_resource_previews.items():
        gallery(preview_triplets[resource_index], preview_path, 9)

    # Derived ss4 updates only the two currently resident target badges plus any
    # other target-family tiles already resident elsewhere, by exact source raw.
    candidate_crc = binascii.crc32(candidate) & 0xFFFFFFFF
    fixed = bytearray(state)
    changed_live = []
    for idx, source, ko, _score in TARGETS:
        obj = parse_map(parent, idx)
        for cell in obj["cells"]:
            sid = cell & 0x3FF
            old = bytes(jp_atlas[sid * 32:(sid + 1) * 32])
            new = bytes(patched_atlas[sid * 32:(sid + 1) * 32])
            if old == new:
                continue
            # Current ss4 loader uses source+1 in BG charblock 0 for this family.
            live_tid = sid + 1
            off = statefmt.STATE_VRAM + bg1["char_base"] + live_tid * 32
            if bytes(state[off:off + 32]) == old:
                fixed[off:off + 32] = new
                changed_live.append({"source_tile": sid, "live_tile": live_tid, "state_offset": f"0x{off:05X}"})
    struct.pack_into("<I", fixed, 8, candidate_crc)
    derived_state = RESULT.with_suffix(".ss4")
    derived_state.write_bytes(raster.replace_state_chunk(STATE, bytes(fixed)))
    bg1_after_path = OUT / "ss4_bg1_after_commonbg_gradient.png"
    bg.render_bg(bytes(fixed), bg.bg_info(bytes(fixed), 1), bg1_after_path)
    # Replace the stale full-state preview from the earlier broken candidate.
    # The renderer writes temporary reconstructed BG layers under OUT as part of
    # the composite process; the final image below is the current derived ss4.
    fullrender.OUT = OUT
    full_after = fullrender.render(bytes(fixed))
    full_after_path = OUT / "ss4_after_full_commonbg_gradient.png"
    full_after.resize((960, 640), Image.Resampling.NEAREST).save(full_after_path)

    current_main_crc = binascii.crc32(current_main) & 0xFFFFFFFF
    manifest = {
        "kind": "ggen_advance_ss4_stat_badges_ko_common_background_gradient_candidate_20260905",
        "parent": {
            "path": str(PREVIOUS_RESULT.relative_to(ROOT)), "sha256": sha256(parent), "crc32": f"0x{parent_crc:08X}",
            "preservation": "selected previous candidate is byte-exact outside its E0518 compressed atlas stream",
        },
        "current_main_reference": {
            "path": str(MAIN_TIP_ROM.relative_to(ROOT)), "sha256": sha256(current_main), "crc32": f"0x{current_main_crc:08X}",
            "note": "reference only; not used as binary base because main TIP advanced after the selected candidate",
        },
        "output": {"path": str(RESULT.relative_to(ROOT)), "sha256": sha256(candidate), "crc32": f"0x{candidate_crc:08X}", "size": len(candidate)},
        "atlas": {"table": f"0x{TABLE:08X}", "pointer": f"0x{atlas_ptr:08X}", "file_offset": f"0x{atlas_off:08X}", "compressed_bytes": len(old_blob), "decoded_tiles": len(atlas) // 32},
        "targets": reports,
        "aliases": {str(k): v for k, v in ALIASES.items()},
        "withheld": {str(k): v for k, v in WITHHELD.items()},
        "ss4_live_proof": live_proof,
        "ss4_palette_bank13": {str(i): list(rgb) for i, rgb in enumerate(live_colors)},
        "common_background": common_background_info,
        "cleanup_policy": {
            "template_source": "resource 24 (命中) structured clean",
            "orange_1px_line": "row y=1 repaired across x=5..23 with palette index 5",
            "left_dark_remnant": "x=0,y=4..6 replaced with yellow index 7",
            "right_dark_remnant": "dark index-3 pixels at x=24..25,y=3..10 replaced with green index 14",
            "blue_1px_arrow_line": "row y=12 repaired across x=2..12 with blue index 8",
            "reuse": "the repaired 32x16 resource-24 clean is copied byte-identically to all five targets before Korean paint",
        },
        "derived_state": {"path": str(derived_state.relative_to(ROOT)), "updated_tiles": changed_live},
        "verification": {
            "result": "PASS",
            "source_targets_were_jp_native": True,
            "previous_candidate_scope_verified": True,
            "common_background_identical_all_targets_before_text": all(r["cleanup"]["common_background_byte_identical_before_text"] for r in reports),
            "common_background_dark_residue": common_background_info["remaining_dark_pixels"],
            "orange_line_continuous": all(common_background[1][x] == 5 for x in range(28)),
            "left_yellow_boundary_continuous": all(common_background[y][0] == 7 for y in range(3, 12)),
            "blue_arrow_line_continuous": all(common_background[12][x] == 8 for x in range(25)),
            "font": "Galmuri11 Regular",
            "korean_face_gradient_indices_top_mid_bottom": list(FACE_GRADIENT),
            "korean_face_gradient_rgb": {str(i): list(live_colors[i]) for i in FACE_GRADIENT},
            "korean_outline_index": OUTLINE,
            "korean_outline_rgb": list(live_colors[OUTLINE]),
            "outline_radius": 1,
            "compression_roundtrip": True,
            "rom_scope": "only current E0518 relocated atlas compressed stream",
            "runtime": "candidate ROM/derived ss4 generated for user verification; main TIP not promoted",
        },
        "artifacts": {
            "derived_ss4": str(derived_state.relative_to(ROOT)),
            "common_background_template": str(common_template_preview.relative_to(ROOT)),
            "overall_comparison": str(overall_preview.relative_to(ROOT)),
            "resource_comparisons": {str(k): str(v.relative_to(ROOT)) for k, v in per_resource_previews.items()},
            "bg1_commonbg_gradient": str(bg1_after_path.relative_to(ROOT)),
            "full_ss4_commonbg_gradient": str(full_after_path.relative_to(ROOT)),
            "verification_log": str(VERIFY_LOG.relative_to(ROOT)),
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    VERIFY_LOG.write_text(
        "\n".join([
            "PASS ss4 stat badge common-background + gradient candidate",
            f"previous_candidate={PREVIOUS_RESULT.relative_to(ROOT)} sha256={sha256(previous)}",
            "previous_scope=parent byte-exact outside E0518 compressed atlas stream",
            "common_background_source=resource24 명중 structured clean",
            f"orange_line_repairs={common_background_info['orange_line_repairs']}",
            f"left_yellow_repairs={common_background_info['left_yellow_repairs']}",
            f"right_green_repairs={common_background_info['right_green_repairs']}",
            f"blue_line_repairs={common_background_info['blue_line_repairs']}",
            f"common_background_remaining_dark={common_background_info['remaining_dark_pixels']}",
            "all_targets_reuse_same_32x16_common_background=true",
            f"font=Galmuri11.bdf native; face_gradient={FACE_GRADIENT}; shadow index {OUTLINE}; shadow radius 1px",
            f"palette13_gradient=" + ",".join(f"{i}:{live_colors[i]}" for i in FACE_GRADIENT) + f" shadow={live_colors[OUTLINE]}",
            *[
                f"resource {r['resource_index']} {r['ko']}: common_changed_from_native={r['cleanup']['changed_from_native_pixels']} gradient_counts={r['face_gradient_counts']} ink={r['ink_width']}x{r['ink_height']} origin={r['origin']}"
                for r in reports
            ],
            f"candidate={RESULT.relative_to(ROOT)} sha256={sha256(candidate)} crc32=0x{candidate_crc:08X}",
            f"derived_ss4={derived_state.relative_to(ROOT)} updated_live_tiles={len(changed_live)}",
            "main_tip_promoted=false",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(RESULT.relative_to(ROOT)), "sha256": sha256(candidate),
        "targets": [{"resource": r["resource_index"], "ko": r["ko"], "changed": len(r["changed_tiles"])} for r in reports],
        "alias_28": "운동 resource 21 graphics reused",
        "withheld": WITHHELD,
        "derived_ss4_changed_tiles": len(changed_live),
        "preview": str(overall_preview.relative_to(ROOT)),
        "priority_previews": [
            str(per_resource_previews[24].relative_to(ROOT)),
            str(per_resource_previews[27].relative_to(ROOT)),
        ],
        "all_resource_previews": {str(k): str(v.relative_to(ROOT)) for k, v in per_resource_previews.items()},
        "bg1_after": str(bg1_after_path.relative_to(ROOT)),
        "full_after": str(full_after_path.relative_to(ROOT)),
        "verification_log": str(VERIFY_LOG.relative_to(ROOT)),
        "manifest": str(MANIFEST.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
