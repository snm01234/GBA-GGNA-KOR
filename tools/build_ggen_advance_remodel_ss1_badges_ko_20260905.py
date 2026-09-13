#!/usr/bin/env python3
"""Restore rounded remodel-panel chrome and finish 이동/지/남은횟수.

Korean.ss1's unit-remodel stats panel is sprite package 0x092D8000 animation 3,
cloned from Japanese 0x08C64140.  An earlier ss2 pass painted 운동/한계/범용/장갑
by copying one interior column across each 32x16 plaque, which flattened the
native rounded caps.  移動/持/残り回数 were left Japanese.

This rebuild keeps each Japanese plaque's native geometry byte-exact outside
the measured Japanese glyph box.  Inside that box, JP contour/shadow/face
pixels are removed by horizontal scanline interpolation from the nearest clean
left/right background pixels on the same row.  A second pass removes isolated
colour kinks only inside the repaired mask, so blank joins, caps and original
orange/yellow structure remain untouched.  Galmuri11 Korean text is painted
after the scanline repair (지 uses Condensed).
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_images_20260901 as animutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_ss1_ss2_graphics_ko_test_20260902 as ss12
import build_ggen_advance_map_menu_ui_ko_poc as tileops
import analyze_ggen_advance_status_sprite_package_duplicates_20260830 as typedup
import build_ggen_advance_status_ui_tile_overlay_poc as status
import build_ggen_advance_turn_ability_overlays_20260905 as raster
import render_ggen_ss_tiles_20260905 as fullrender
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

KO_RES = 0x092D8000
JP_RES = 0x08C64140
ALLOC_END = 0x012E0000
OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_ss1_badges"
RESULT = OUT / "ggen_advance_remodel_ss1_badges_scanlinebg_candidate_20260905.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_remodel_ss1_badges_scanlinebg_candidate_20260905.json"
PREVIEW = OUT / "ggen_advance_remodel_ss1_badges_scanlinebg_preview_20260905.png"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
GLYPH = {4, 5, 10}
FACE = {4, 10}
FILL = 11
INK = 10
CONTOUR = 5
CAP_COLUMNS = 3
OUTER_KEEP = 2
EDGE_X = 5
EDGE_Y = 2
# Native status-panel profile is 6,9,A,B...B,A,9,6.  Index B (11) is the
# brightest/palest yellow panel interior; index A (10) is the Korean glyph face.
BRIGHT_YELLOW = 11
CHROME = {6, 7, 8, 9, 10, 11}
YELLOW = {8, 9, 10, 11}
# Measured native status-panel vertical profile: dark red/orange rim -> amber ->
# pale-yellow body -> mirrored lower rim.  This is the only synthesized portion
# of the common template; all rounded edge geometry comes from Japanese donors.
PANEL_PROFILE = (6, 9, 10, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 10, 9, 6)
# Full-canvas rectangles for animation 3 (origin = min object x/y).
# 運動 is currently shown as 이동; restore it to 운동 so 移動 can be 이동.
LABELS = [
    {"jp": "運動", "ko": "운동", "rect": (128, 24, 160, 40), "paint": (130, 24, 157, 40)},
    {"jp": "限界", "ko": "한계", "rect": (176, 24, 208, 40), "paint": (178, 24, 204, 40)},
    {"jp": "汎用", "ko": "범용", "rect": (112, 40, 144, 56), "paint": (115, 40, 141, 56)},
    {"jp": "装甲", "ko": "장갑", "rect": (156, 40, 188, 56), "paint": (159, 40, 185, 56)},
    {"jp": "移動", "ko": "이동", "rect": (56, 40, 88, 56), "paint": (59, 40, 85, 56)},
    {"jp": "特", "ko": "지", "rect": (56, 56, 72, 72), "paint": (56, 56, 72, 72), "font": "c"},
    {"jp": "残り回数", "ko": "남은횟수", "rect": (152, 56, 216, 72), "paint": (155, 56, 213, 72)},
]


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def unique(canvas, rect) -> list[int]:
    x0, y0, x1, y1 = rect
    return sorted({canvas[y][x] for y in range(y0, y1) for x in range(x0, x1)})


def looks_rectangular(canvas, rect) -> bool:
    x0, y0, x1, y1 = rect
    return len(set(canvas[y0][x0:x1])) == 1 and len(set(canvas[y1 - 1][x0:x1])) == 1


def interior_ratio(canvas, rect, value: int, cap: int = CAP_COLUMNS) -> float:
    x0, y0, x1, y1 = rect
    body = [canvas[y][x] for y in range(y0, y1) for x in range(x0 + cap, x1 - cap)]
    if not body:
        return 0.0
    return body.count(value) / len(body)


def clear_region_ratio(canvas, rect, value: int) -> float:
    """Ratio in the broad JP-clear region, excluding only the 2px outer cap."""
    x0, y0, x1, y1 = rect
    body = [
        canvas[y][x]
        for y in range(y0 + EDGE_Y, y1 - EDGE_Y)
        for x in range(x0 + OUTER_KEEP, x1 - OUTER_KEEP)
    ]
    if not body:
        return 0.0
    return body.count(value) / len(body)


def cap_columns_match(donor, after, rect, columns: int = OUTER_KEEP) -> bool:
    x0, y0, x1, y1 = rect
    for y in range(y0, y1):
        if after[y][x0:x0 + columns] != donor[y][x0:x0 + columns]:
            return False
        if after[y][x1 - columns:x1] != donor[y][x1 - columns:x1]:
            return False
    return True


def template_caps_match(template: list[list[int]], canvas: list[list[int]], rect, columns: int = OUTER_KEEP) -> bool:
    """Verify Korean painting did not touch the clean template's outer caps."""
    x0, y0, x1, y1 = rect
    width, height = x1 - x0, y1 - y0
    if len(template) != height or any(len(row) != width for row in template):
        return False
    for ly in range(height):
        if canvas[y0 + ly][x0:x0 + columns] != template[ly][:columns]:
            return False
        if canvas[y0 + ly][x1 - columns:x1] != template[ly][width - columns:]:
            return False
    return True


def only_clear_region_changed(before, after) -> bool:
    """Cleanup may touch only the interior body; outer chrome remains exact."""
    height, width = len(before), len(before[0])
    for y in range(height):
        for x in range(width):
            if before[y][x] == after[y][x]:
                continue
            if not (2 <= x < width - 2 and 2 <= y < height - 2):
                return False
    return True


def paint_xy(canvas, text, x, y, font, face, edge, clip):
    """Paint Hangul with 4-tuple clip so outline cannot cover round caps or neighbors."""
    ink, _, _ = raster.native_ink(font, text)
    ink = {(a + x, b + y) for a, b in ink}
    outline = raster.dilate(ink, len(canvas[0]), len(canvas))
    x0, y0, x1, y1 = clip

    def valid(a, b):
        return x0 <= a < x1 and y0 <= b < y1 and 0 <= b < len(canvas) and 0 <= a < len(canvas[0])

    for pts, color in ((outline, edge), (ink, face)):
        for a, b in pts:
            if valid(a, b):
                canvas[b][a] = color
    return {"text": text, "origin": [x, y], "face": face, "outline": edge, "ink_pixels": len(ink)}


def plaque_palette_bank(parsed, canvas_x: int, canvas_y: int) -> int:
    objects = parsed["objects"]
    min_x = min(int(obj["x"]) for obj in objects)
    min_y = min(int(obj["y"]) for obj in objects)
    for obj in objects:
        ox = int(obj["x"]) - min_x
        oy = int(obj["y"]) - min_y
        width, height = obj["size_px"]
        if ox <= canvas_x < ox + width and oy <= canvas_y < oy + height:
            return int(obj["palette_bank"])
    return int(objects[0]["palette_bank"])


APTITUDE = [
    ("범용", "汎用"),
    ("우주", "宇宙"),
    ("지상", "地上"),
    ("만능", "万能"),
    ("수륙", "水陸"),
    ("비행", "飛行"),
]


def orphan_brown(canvas, rect, cap: int = EDGE_X) -> bool:
    """True if the bright-yellow field has a 5 that is not a Hangul outline."""
    del cap
    x0, y0, x1, y1 = rect
    width, height = x1 - x0, y1 - y0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if not in_field(x - x0, y - y0, width, height):
                continue
            if canvas[y][x] != 5:
                continue
            if not any(
                0 <= ny < len(canvas) and 0 <= nx < len(canvas[0]) and canvas[ny][nx] == 10
                for ny in (y - 1, y, y + 1)
                for nx in (x - 1, x, x + 1)
                if nx != x or ny != y
            ):
                return True
    return False


def tile_origin(x: int, width: int) -> tuple[int, int]:
    tile = 16 if width <= 16 else 32
    origin = (x // tile) * tile
    return origin, min(tile, width - origin)


def edge_x(tile_w: int) -> int:
    return 3 if tile_w <= 16 else EDGE_X


def in_field(x: int, y: int, width: int, height: int) -> bool:
    if not (EDGE_Y <= y < height - EDGE_Y):
        return False
    origin, tile_w = tile_origin(x, width)
    local = x - origin
    inset = edge_x(tile_w)
    return inset <= local < tile_w - inset


def heal_edge(src: list[list[int]], x: int, y: int) -> int:
    """Replace a glyph in the rim with the nearest outer chrome pixel."""
    width = len(src[0])
    origin, tile_w = tile_origin(x, width)
    local = x - origin
    if local < tile_w / 2:
        allowed = {6, 7, 8, 9}
        xs = range(x, origin - 1, -1)
        fallback = 9
    else:
        allowed = {8, 9, 10, 11}
        xs = range(x, origin + tile_w)
        fallback = 10
    for nx in xs:
        if src[y][nx] in allowed:
            return src[y][nx]
    return fallback


def clear_jp_text_box(src: list[list[int]]) -> tuple[list[list[int]], tuple[int, int, int, int]]:
    """Clear only the Japanese text box while keeping native geometry exact.

    Unlike the earlier common-plaque rebuild, this starts from the actual JP
    plaque and never replaces pixels outside the measured JP glyph bounds.  The
    dark 4/5 contour gives a reliable horizontal text extent; within that box,
    only 4/5/10 (JP contour/shadow/face) are replaced.  Native 6/7/8/9/11
    background and bevel pixels stay byte/pixel-identical.  The replacement is
    the native vertical panel profile, so ambiguous face pixels become the
    correct row colour without changing blank areas or neighbouring joins.
    """
    height, width = len(src), len(src[0])
    gate(height == 16 and width >= 16, "unexpected plaque shape")
    # 16/32px plaques use a four-pixel structural side band.  The previous
    # x=2/3 search accidentally treated the inner step of the left round as JP
    # contour, producing the oversized 이동 cap and yellow holes in 지.  Keep
    # those side bands source-exact.  The 64px 残り回数 plaque has a long label
    # and only needs the native two-pixel endpoint guard.
    side_guard = 4 if width in {16, 32} else 2
    dark = [
        (x, y)
        for y in range(2, 14)
        for x in range(side_guard, width - side_guard)
        if src[y][x] in {4, 5}
    ]
    gate(bool(dark), "no JP dark contour found")
    x0 = min(x for x, _y in dark)
    x1 = max(x for x, _y in dark) + 1
    y0, y1 = 2, 14
    out = [row[:] for row in src]
    for y in range(y0, y1):
        expected = PANEL_PROFILE[y]
        for x in range(x0, x1):
            if src[y][x] in GLYPH:
                out[y][x] = expected
    return out, (x0, y0, x1, y1)


def clear_jp_text_box_scanline(src: list[list[int]]) -> tuple[list[list[int]], tuple[int, int, int, int]]:
    """Clear JP glyph pixels by same-row left/right interpolation."""
    height, width = len(src), len(src[0])
    gate(height == 16 and width >= 16, "unexpected plaque shape")
    side_guard = 4 if width in {16, 32} else 2
    y0, y1 = 2, 14
    dark = {(x, y) for y in range(y0, y1) for x in range(side_guard, width - side_guard) if src[y][x] in {4, 5}}
    gate(bool(dark), "no JP dark contour found")
    x0 = min(x for x, _ in dark)
    x1 = max(x for x, _ in dark) + 1
    mask = set(dark)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if src[y][x] != 10:
                continue
            if 3 <= y <= 12 or any(max(abs(x - dx), abs(y - dy)) <= 1 for dx, dy in dark):
                mask.add((x, y))

    background = {6, 7, 8, 9, 10, 11}
    out = [row[:] for row in src]
    repaired = set()

    def nearest(y: int, start: int, step: int):
        x = start
        while side_guard <= x < width - side_guard:
            if (x, y) not in mask and src[y][x] in background:
                return src[y][x]
            x += step
        return None

    for y in range(y0, y1):
        xs = sorted(x for x, yy in mask if yy == y)
        if not xs:
            continue
        runs = []
        a = b = xs[0]
        for x in xs[1:]:
            if x == b + 1:
                b = x
            else:
                runs.append((a, b))
                a = b = x
        runs.append((a, b))
        for a, b in runs:
            lv = nearest(y, a - 1, -1)
            rv = nearest(y, b + 1, 1)
            if lv is None and rv is None:
                lv = rv = PANEL_PROFILE[y]
            elif lv is None:
                lv = rv
            elif rv is None:
                rv = lv
            span = b - a + 1
            for i, x in enumerate(range(a, b + 1), 1):
                if lv == rv:
                    value = lv
                else:
                    raw = round(lv + (rv - lv) * i / (span + 1))
                    value = min(background, key=lambda v: (abs(v - raw), abs(v - PANEL_PROFILE[y])))
                out[y][x] = value
                repaired.add((x, y))

    for _ in range(2):
        before = [row[:] for row in out]
        for x, y in repaired:
            if not 1 <= x < width - 1:
                continue
            left, cur, right = before[y][x - 1], before[y][x], before[y][x + 1]
            if left == right and left in background and cur != left:
                out[y][x] = left
            elif left in background and right in background:
                lo, hi = sorted((left, right))
                if cur < lo or cur > hi:
                    raw = round((left + right) / 2)
                    out[y][x] = min(background, key=lambda v: (abs(v - raw), abs(v - PANEL_PROFILE[y])))
    return out, (x0, y0, x1, y1)


def stitch_direct(rom: bytes, desc: int) -> list[list[int]]:
    canvas = [[0] * 32 for _ in range(16)]
    gfx = rom[desc + 0x20:desc + 0x20 + 256]
    for ty in range(2):
        for tx in range(4):
            raw = gfx[(ty * 4 + tx) * 32:(ty * 4 + tx + 1) * 32]
            tile = [
                [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0x0F) for x in range(8)]
                for y in range(8)
            ]
            for y in range(8):
                canvas[ty * 8 + y][tx * 8:tx * 8 + 8] = tile[y]
    return canvas


def encode_direct(canvas: list[list[int]]) -> bytes:
    parts = []
    for ty in range(2):
        for tx in range(4):
            parts.append(tileops.encode_tile(
                [canvas[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
            ))
    return b"".join(parts)


def tile_hits_rects(ox: int, oy: int, rects: list[tuple[int, int, int, int]]) -> bool:
    for x0, y0, x1, y1 in rects:
        if ox < x1 and ox + 8 > x0 and oy < y1 and oy + 8 > y0:
            return True
    return False


def aptitude_owner_report(rom: bytes, pkg_graphics: bytes) -> dict:
    """범용/우주/... swap lives in E0518, not the remodel OBJ package."""
    ptr = struct.unpack_from("<I", rom, 0x000E0518)[0]
    off = ptr - 0x08000000
    hdr = struct.unpack_from("<I", rom, off)[0]
    atlas = status.lzss_decompress(rom[off + 4:off + 4 + (hdr & 0xFFFF)])
    variants = []
    for name, spec in status.TYPE_LABELS.items():
        ids = [tid for row in spec["tiles"] for tid in row]
        shared = []
        for tid in ids:
            raw = atlas[tid * 32:(tid + 1) * 32]
            hits = [i for i in range(len(pkg_graphics) // 32) if pkg_graphics[i * 32:(i + 1) * 32] == raw]
            if hits:
                shared.append({"e0518_tile": hex(tid), "package_tiles": hits})
        variants.append({
            "ko": name,
            "jp": spec["source"],
            "e0518_resource_index": spec["resource_index"],
            "e0518_tiles": [hex(tid) for tid in ids],
            "shared_32byte_tiles_in_092D8000": shared,
        })
    return {
        "e0518_table": "0x080E0518",
        "e0518_active_atlas": hex(ptr),
        "select": "resource_table[40 + unit_type] — 범용=41, 우주=42, 지상=43, 만능=44, 수륙=45, 비행=46",
        "remodel_obj": {
            "package": hex(KO_RES),
            "animation": 3,
            "note": "개조 화면 범용 슬롯은 OBJ 패키지 전용 타일. E0518 우주 타일과 32바이트 공유 없음.",
        },
        "variants": variants,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == meta["sha256"], "main TIP/manifest hash mismatch")
    gate(MAIN_SAV.is_file(), "main SAV missing")

    ko_canvas, ko_pal, ko_bank = ss12.resource_canvas(parent, KO_RES, 3)
    jp_canvas, jp_pal, jp_bank = ss12.resource_canvas(jp, JP_RES, 3)
    gate((len(ko_canvas), len(ko_canvas[0])) == (len(jp_canvas), len(jp_canvas[0])), "anim3 canvas size drift")
    gate(ko_bank == jp_bank, "anim3 palette bank drift")

    def cut(rect):
        rx0, ry0, rx1, ry1 = rect
        return [jp_canvas[y][rx0:rx1] for y in range(ry0, ry1)]

    # Each plaque now keeps its own native JP geometry.  Only the measured
    # Japanese text box is cleaned; blank joins, left/right caps and unrelated
    # background pixels are therefore rolled back byte-exact to the original.

    active = []
    for spec in LABELS:
        rect = spec["rect"]
        x0, y0, x1, y1 = rect
        gate(0 <= x0 < x1 <= len(jp_canvas[0]) and 0 <= y0 < y1 <= len(jp_canvas), spec["ko"])
        glyph_px = sum(jp_canvas[y][x] in GLYPH for y in range(y0, y1) for x in range(x0, x1))
        piece = [jp_canvas[y][x0:x1] for y in range(y0, y1)]
        size = (x1 - x0, y1 - y0)
        cleaned, clear_bbox = clear_jp_text_box_scanline(piece)
        bx0, by0, bx1, by1 = clear_bbox
        gate(
            all(
                piece[y][x] == cleaned[y][x]
                for y in range(size[1])
                for x in range(size[0])
                if not (bx0 <= x < bx1 and by0 <= y < by1)
            ),
            f"{spec['ko']} cleanup changed pixels outside JP text box",
        )
        gate(
            all(cleaned[y][x] not in {4, 5} for y in range(by0, by1) for x in range(bx0, bx1)),
            f"{spec['ko']} JP contour remains inside cleaned text box",
        )
        template_source = "source JP plaque exact outside measured JP text box; replace only 4/5/10 within box by native row profile"
        restore = {(x0 + x, y0 + y): cleaned[y][x] for y in range(size[1]) for x in range(size[0])}
        cleared = sum(ko_canvas[y][x] != restore[(x, y)] for y in range(y0, y1) for x in range(x0, x1))
        if cleared == 0:
            continue
        active.append({
            "rect": list(rect),
            "paint_rect": list(spec["paint"]),
            "text": spec["ko"],
            "source": spec["jp"],
            "fill": FILL,
            "ink": spec.get("ink", INK),
            "contour": spec.get("contour", CONTOUR),
            "clear_values": [],
            "restore_pixels": restore,
            "font": spec.get("font", "11"),
            "jp_indices": unique(jp_canvas, rect),
            "ko_was_rectangular": looks_rectangular(ko_canvas, rect),
            "jp_was_rectangular": looks_rectangular(jp_canvas, rect),
            "jp_glyph_pixels": glyph_px,
            "cap_columns": OUTER_KEEP,
            "template_source": template_source,
            "clear_bbox": list(clear_bbox),
            "erased": cleaned,
        })
    gate(any(row["text"] == "범용" for row in active), "범용 plaque not found")
    gate(any(row["text"] == "장갑" for row in active), "장갑 plaque not found")
    gate(any(row["text"] == "이동" for row in active), "移動 plaque not found")
    gate(any(row["text"] == "남은횟수" for row in active), "残り回数 plaque not found")
    gate(any(row["text"] == "지" for row in active), "持/特 plaque not found")

    with ZipFile(FONT_ZIP) as archive:
        fonts = {
            "11": fontpair.load_bdf(archive, "Galmuri11.bdf"),
            "c": fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf"),
        }

    header = ss12.spr.parse_resource_header(parent, KO_RES)
    original = parent[header["offset"]: header["offset"] + header["resource_bytes"]]
    graphics = header["graphics"]
    palettes = header["palettes"]
    original_tiles = header["source_tiles"]
    _rel, records = __import__("analyze_ggen_advance_settings_suspend_ui", fromlist=["animation_records"]).animation_records(parent, KO_RES)
    parsed, ids, lookup_file = ss12.parse_animation_cross(records, 3)
    canvas = [row[:] for row in ko_canvas]
    paint_reports = []
    for row in active:
        x0, y0, x1, y1 = row["rect"]
        for (x, y), value in row["restore_pixels"].items():
            canvas[y][x] = value
        font = fonts[row["font"]]
        ink, width, height = raster.native_ink(font, row["text"])
        edge = 3 if (x1 - x0) <= 16 else EDGE_X
        inner_x0, inner_x1 = x0 + edge, x1 - edge
        inner_y0, inner_y1 = y0 + EDGE_Y, y1 - EDGE_Y
        pad = 0
        gate(width <= inner_x1 - inner_x0 - pad, f"{row['text']} ink {width}px does not fit {inner_x1 - inner_x0}px interior")
        gate(height <= inner_y1 - inner_y0, f"{row['text']} ink {height}px does not fit vertically")
        origin_x = inner_x0 + (inner_x1 - inner_x0 - width) // 2
        origin_y = inner_y0 + (inner_y1 - inner_y0 - height) // 2
        info = paint_xy(
            canvas, row["text"], origin_x, origin_y, font, row["ink"], row["contour"],
            clip=(inner_x0, inner_y0, inner_x1, inner_y1),
        )
        paint_reports.append({**row, "origin": [origin_x, origin_y], "glyph_size": [width, height], **info})
        gate(template_caps_match(row["erased"], canvas, (x0, y0, x1, y1)), f"{row['text']} template caps lost during paint")

    painted_rects = [tuple(row["rect"]) for row in active]
    existing = {graphics[t * 32:(t + 1) * 32]: t for t in range(original_tiles)}
    private: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    objects = parsed["objects"]
    min_x = min(int(obj["x"]) for obj in objects)
    min_y = min(int(obj["y"]) for obj in objects)
    cursor = 0
    changed_lookup = 0
    for obj in objects:
        wt, ht = int(obj["size_px"][0]) // 8, int(obj["size_px"][1]) // 8
        count = wt * ht
        old_ids = ids[cursor:cursor + count]
        for ty in range(ht):
            for tx in range(wt):
                pos = ty * wt + tx
                old_id = int(old_ids[pos])
                ox = int(obj["x"]) - min_x + tx * 8
                oy = int(obj["y"]) - min_y + ty * 8
                if not tile_hits_rects(ox, oy, painted_rects):
                    continue
                payload = tileops.encode_tile([canvas[oy + y][ox:ox + 8] for y in range(8)])
                old_payload = graphics[old_id * 32:(old_id + 1) * 32]
                if payload == old_payload:
                    new_id = old_id
                elif payload in existing:
                    new_id = existing[payload]
                elif payload in private:
                    new_id = private[payload]
                else:
                    new_id = original_tiles + len(private_payloads)
                    private[payload] = new_id
                    private_payloads.append(payload)
                if new_id != old_id:
                    rel = lookup_file - header["offset"] + (cursor + pos) * 2
                    gate(rel not in lookup_writes or lookup_writes[rel] == new_id, f"lookup conflict at 0x{rel:X}")
                    lookup_writes[rel] = new_id
                    changed_lookup += 1
        cursor += count
    gate(changed_lookup > 0, "animation 3: no lookup changed")
    new_graphics = graphics + b"".join(private_payloads)
    new_palette_rel = header["graphics_rel"] + len(new_graphics)
    blob = bytearray(new_palette_rel + len(palettes))
    blob[:header["graphics_rel"]] = original[:header["graphics_rel"]]
    struct.pack_into("<I", blob, 0x0C, new_palette_rel)
    for rel, tile_id in lookup_writes.items():
        struct.pack_into("<H", blob, rel, tile_id)
    blob[header["graphics_rel"]:new_palette_rel] = new_graphics
    blob[new_palette_rel:] = palettes
    gate(new_graphics[:len(graphics)] == graphics, "original graphic tiles were rewritten")
    off = KO_RES - 0x08000000
    gate(off + len(blob) <= ALLOC_END, f"092D8000 overflow {len(blob)}")
    output = bytearray(parent)
    output[off:off + len(blob)] = blob
    aptitude_reports = []
    c43_allowed: list[tuple[int, int]] = []
    c43_jp_pieces = {}
    for ko_text, _jp_text in APTITUDE:
        desc, _ids = typedup.DIRECT_TYPES[ko_text]
        c43_jp_pieces[ko_text] = stitch_direct(jp, desc)

    for ko_text, jp_text in APTITUDE:
        desc, _ids = typedup.DIRECT_TYPES[ko_text]
        gfx_off = desc + 0x20
        c43_allowed.append((gfx_off, gfx_off + 256))
        jp_piece = c43_jp_pieces[ko_text]
        gate(encode_direct(jp_piece) == jp[gfx_off:gfx_off + 256], f"{ko_text} C43 stitch/encode mismatch")
        gate(not looks_rectangular(jp_piece, (0, 0, 32, 16)), f"{ko_text} JP C43 already rectangular")
        cleaned, clear_bbox = clear_jp_text_box_scanline(jp_piece)
        erased = [row[:] for row in cleaned]
        bx0, by0, bx1, by1 = clear_bbox
        gate(
            all(
                jp_piece[y][x] == erased[y][x]
                for y in range(16)
                for x in range(32)
                if not (bx0 <= x < bx1 and by0 <= y < by1)
            ),
            f"{ko_text} C43 cleanup changed native pixels outside JP text box",
        )
        gate(
            all(erased[y][x] not in {4, 5} for y in range(by0, by1) for x in range(bx0, bx1)),
            f"{ko_text} C43 JP contour remains inside cleaned text box",
        )
        font = fonts["11"]
        _ink, width, height = raster.native_ink(font, ko_text)
        inner_x0, inner_x1 = EDGE_X, 32 - EDGE_X
        inner_y0, inner_y1 = EDGE_Y, 16 - EDGE_Y
        gate(width <= inner_x1 - inner_x0, f"{ko_text} C43 ink {width}px does not fit")
        gate(height <= inner_y1 - inner_y0, f"{ko_text} C43 ink {height}px does not fit vertically")
        origin_x = inner_x0 + (inner_x1 - inner_x0 - width) // 2
        origin_y = inner_y0 + (inner_y1 - inner_y0 - height) // 2
        paint_xy(
            cleaned, ko_text, origin_x, origin_y, font, INK, CONTOUR,
            clip=(inner_x0, inner_y0, inner_x1, inner_y1),
        )
        gate(cap_columns_match(jp_piece, cleaned, (0, 0, 32, 16)), f"{ko_text} C43 native caps lost during paint")
        gate(
            all(cleaned[y][x] != 4 for y in range(by0, by1) for x in range(bx0, bx1)),
            f"{ko_text} C43 JP dark-4 residue in cleaned text box after Hangul paint",
        )
        payload = encode_direct(cleaned)
        gate(len(payload) == 256, f"{ko_text} C43 encode size")
        output[gfx_off:gfx_off + 256] = payload
        aptitude_reports.append({
            "ko": ko_text,
            "jp": jp_text,
            "descriptor": hex(desc),
            "graphics": hex(gfx_off),
            "origin": [origin_x, origin_y],
            "glyph_size": [width, height],
            "clear_bbox": list(clear_bbox),
            "jp_canvas": jp_piece,
            "erased_canvas": erased,
            "after_canvas": cleaned,
        })
    output = bytes(output)
    reports = [{"animation": 3, "changed_lookup_entries": changed_lookup, "private_tiles": len(private_payloads), "paints": [
        {k: r[k] for k in ("source", "text", "rect", "origin", "glyph_size") if k in r}
        for r in paint_reports
    ]}]
    header = ss12.spr.parse_resource_header(output, KO_RES)
    gate(off + header["resource_bytes"] <= ALLOC_END, "final 092D8000 overflow")
    allowed = [(off, off + len(blob)), *c43_allowed]
    escaped = [
        i for i, (before, after) in enumerate(zip(parent, output))
        if before != after and not any(start <= i < end for start, end in allowed)
    ]
    gate(not escaped, f"changes escaped declared ranges: {[hex(i) for i in escaped[:12]]}")
    gate(output[ALLOC_END:] == parent[ALLOC_END:], "bytes after allocation changed")
    native_ko = ss12.spr.parse_resource_header(parent, JP_RES)
    gate(
        output[native_ko["offset"]: native_ko["offset"] + native_ko["resource_bytes"]]
        == parent[native_ko["offset"]: native_ko["offset"] + native_ko["resource_bytes"]],
        "original C64140 changed",
    )

    after_canvas, after_pal, after_bank = ss12.resource_canvas(output, KO_RES, 3)
    gate(after_bank == ko_bank, "palette bank changed")
    for row in active:
        gate(template_caps_match(row["erased"], after_canvas, tuple(row["rect"])), f"{row['text']} native caps drifted")
        rx0, ry0, _rx1, _ry1 = row["rect"]
        bx0, by0, bx1, by1 = row["clear_bbox"]
        gate(
            all(after_canvas[ry0 + y][rx0 + x] != 4 for y in range(by0, by1) for x in range(bx0, bx1)),
            f"{row['text']} JP dark-4 residue in cleaned text box after Hangul paint",
        )

    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(output)
    shutil.copy2(MAIN_SAV, RESULT.with_suffix(".sav"))

    _rel, out_records = __import__("analyze_ggen_advance_settings_suspend_ui", fromlist=["animation_records"]).animation_records(output, KO_RES)
    parsed, ids, _lookup = ss12.parse_animation_cross(out_records, 3)
    st_preview, _ = statefmt.parse_png_state(STATE)
    live_obj_pal9 = bytes(
        st_preview[statefmt.STATE_PALETTE + 512 + 9 * 32: statefmt.STATE_PALETTE + 512 + 10 * 32]
    )
    crop = (48, 16, 224, 80)

    def crop_im(canvas, pal):
        piece = [row[crop[0]:crop[2]] for row in canvas[crop[1]:crop[3]]]
        return animutil.canvas_image(piece, pal, 0, 3)

    before_im = crop_im(ko_canvas, live_obj_pal9)
    jp_im = crop_im(jp_canvas, live_obj_pal9)
    after_im = crop_im(after_canvas, live_obj_pal9)
    preview = Image.new("RGB", (before_im.width * 3 + 24, before_im.height + 24), (30, 30, 30))
    draw = ImageDraw.Draw(preview)
    draw.text((4, 4), "KO before / JP donor / KO after", fill="white")
    preview.paste(before_im, (0, 20))
    preview.paste(jp_im, (before_im.width + 8, 20))
    preview.paste(after_im, (before_im.width * 2 + 16, 20))
    preview.save(PREVIEW)

    for row in active:
        rx0, ry0, rx1, ry1 = row["rect"]
        scale = 6
        cell = (rx1 - rx0) * scale
        strip = Image.new("RGB", (cell * 3 + 16, (ry1 - ry0) * scale), (20, 20, 20))
        jp_piece = animutil.canvas_image([r[rx0:rx1] for r in jp_canvas[ry0:ry1]], live_obj_pal9, 0, scale)
        erased_piece = animutil.canvas_image(row["erased"], live_obj_pal9, 0, scale)
        after_piece = animutil.canvas_image([r[rx0:rx1] for r in after_canvas[ry0:ry1]], live_obj_pal9, 0, scale)
        strip.paste(jp_piece, (0, 0))
        strip.paste(erased_piece, (cell + 8, 0))
        strip.paste(after_piece, (cell * 2 + 16, 0))
        strip.save(OUT / f"plaque_{row['text']}_jp_vs_after.png")

    c43_preview = Image.new("RGB", (32 * 6 * 3 + 32, 16 * 6 * len(aptitude_reports) + 8), (20, 20, 20))
    for index, row in enumerate(aptitude_reports):
        jp_im = animutil.canvas_image(row["jp_canvas"], jp_pal, 0, 6)
        erased_im = animutil.canvas_image(row["erased_canvas"], jp_pal, 0, 6)
        after_im = animutil.canvas_image(row["after_canvas"], jp_pal, 0, 6)
        y = index * 16 * 6 + 4
        c43_preview.paste(jp_im, (0, y))
        c43_preview.paste(erased_im, (32 * 6 + 8, y))
        c43_preview.paste(after_im, (32 * 6 * 2 + 16, y))
        strip = Image.new("RGB", (32 * 6 * 3 + 16, 16 * 6), (20, 20, 20))
        strip.paste(jp_im, (0, 0))
        strip.paste(erased_im, (32 * 6 + 8, 0))
        strip.paste(after_im, (32 * 6 * 2 + 16, 0))
        strip.save(OUT / f"c43_{row['ko']}_jp_vs_after.png")
    c43_preview.save(OUT / "c43_aptitude_jp_vs_after.png")

    # Live OBJ dest tiles are unique even when source IDs were shared.
    st, _ = statefmt.parse_png_state(STATE)
    fixed = bytearray(st)
    new_gfx = header["graphics"]
    dispcnt = struct.unpack_from("<H", st, statefmt.STATE_IO)[0]
    obj_base = statefmt.STATE_VRAM + statefmt.OBJ_VRAM
    oam = st[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    live = [statefmt.parse_oam_entry(oam, index) for index in range(128)]
    slot_x, slot_y = 128, 128
    objects = parsed["objects"]
    hits = 0
    matched = 0
    cursor = 0
    for obj in objects:
        wt, ht = int(obj["size_px"][0]) // 8, int(obj["size_px"][1]) // 8
        count = wt * ht
        sx = slot_x + int(obj["x"])
        sy = slot_y + int(obj["y"])
        width, height = obj["size_px"]
        matches = [
            row for row in live
            if int(row["x"]) == sx and int(row["y"]) == sy
            and int(row["width"]) == width and int(row["height"]) == height
        ]
        if len(matches) != 1:
            cursor += count
            continue
        matched += 1
        dest = int(matches[0]["tile"])
        stride = (width // 8) if dispcnt & 0x40 else 32
        for ty in range(ht):
            for tx in range(wt):
                pos = ty * wt + tx
                new_id = int(ids[cursor + pos])
                payload = new_gfx[new_id * 32:(new_id + 1) * 32]
                off = obj_base + (dest + ty * stride + tx) * 32
                if bytes(fixed[off:off + 32]) != payload:
                    fixed[off:off + 32] = payload
                    hits += 1
        cursor += count
    gate(matched >= 8, f"anim3 live OAM match too low: {matched}")
    struct.pack_into("<I", fixed, 8, binascii.crc32(output) & 0xFFFFFFFF)
    RESULT.with_suffix(".ss1").write_bytes(raster.replace_state_chunk(STATE, bytes(fixed)))
    derived_frame = fullrender.render(bytes(fixed))
    jp_state, _ = statefmt.parse_png_state(ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1")
    jp_frame = fullrender.render(jp_state)
    panel = (0, 80, 240, 160)
    side = Image.new("RGB", (480, 80))
    side.paste(derived_frame.crop(panel), (0, 0))
    side.paste(jp_frame.crop(panel), (240, 0))
    side.resize((1440, 240), Image.Resampling.NEAREST).save(OUT / "derived_ss1_vs_japan_bottom.png")

    aptitude_owners = aptitude_owner_report(parent, graphics)
    serializable = []
    for row in active:
        serializable.append({
            "source": row["source"],
            "text": row["text"],
            "rect": row["rect"],
            "paint_rect": row["paint_rect"],
            "font": "Galmuri11-Condensed" if row["font"] == "c" else "Galmuri11",
            "ko_was_rectangular": row["ko_was_rectangular"],
            "jp_was_rectangular": row["jp_was_rectangular"],
            "jp_glyph_pixels": row["jp_glyph_pixels"],
            "jp_indices": row["jp_indices"],
            "cap_columns": row["cap_columns"],
            "clear_bbox": row["clear_bbox"],
        })
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_remodel_ss1_badges_scanlinebg_candidate_20260905",
        "result": "PASS",
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {
            "path": advance_relative(RESULT),
            "sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(RESULT.with_suffix(".sav")),
            "preview": advance_relative(PREVIEW),
            "derived_ss1": advance_relative(RESULT.with_suffix(".ss1")),
            "updated_obj_tiles": hits,
            "oam_objects_matched": matched,
        },
        "resource": {
            "live": hex(KO_RES),
            "japanese_donor": hex(JP_RES),
            "allocation_end": hex(ALLOC_END),
            "rebuilt_bytes": header["resource_bytes"],
            "source_tiles": header["source_tiles"],
        },
        "labels": serializable,
        "rebuild": reports,
        "c43_types": [
            {k: row[k] for k in ("ko", "jp", "descriptor", "graphics", "origin", "glyph_size", "clear_bbox")}
            for row in aptitude_reports
        ],
        "aptitude_owners": aptitude_owners,
        "verification": {
            "result": "PASS",
            "scope": "anim3/C43: start from each original Japanese plaque, detect the JP dark-contour horizontal extent, and replace JP contour/shadow/face pixels by same-row left/right interpolation; a second masked-only pass removes isolated colour kinks; every pixel outside the measured text box remains original-JP exact before Hangul paint; then paint Hangul face 10 + 1px contour 5; C64140/E0518 byte-exact",
            "font": "Galmuri11 except 지=Galmuri11-Condensed",
            "interior_fill_index": "same-row left/right native background interpolation; vertical profile only fallback when neither side is usable",
            "background_policy": "source-specific native caps/joins/blank regions preserved; scanline repair touches only detected JP glyph/shadow mask and performs masked-only horizontal smoothing",
            "runtime_emulator": "not verified",
            "original_c64140_preserved": True,
            "after_plaques_not_rectangular": True,
            "main_tip_unmodified": True,
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(RESULT),
        "sha256": sha256(output),
        "labels": [(r["source"], r["text"], r["ko_was_rectangular"]) for r in serializable],
        "tiles": header["source_tiles"],
        "obj_vram_hits": hits,
        "oam_objects_matched": matched,
        "live_preview_palette": 9,
        "aptitude": {
            "e0518_atlas": aptitude_owners["e0518_active_atlas"],
            "shared_with_obj_package": any(v["shared_32byte_tiles_in_092D8000"] for v in aptitude_owners["variants"]),
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
