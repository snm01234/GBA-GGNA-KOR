#!/usr/bin/env python3
"""Korean Galmuri overlays for the turn-start banner and ability-name popups.

ss2: ターン / 敵軍 攻撃開始 and the sibling 自軍·友軍·第三軍 plates in
resource 0x08165044. Galmuri11 Regular is nearest-neighbour 2x, flat face 8,
solid 2px bottom-right shadow 4 covering the glyph, then 1px white 15 only
on the exterior of face+shadow (not in the gap around the raw Hangul).
自軍/敵軍/友軍 share the 軍 columns: prefixes 아/적/우 are unique-only and
군 is painted once onto the shared tiles so 적군 cannot keep a leftover 군.
Glyphs are placed in the largest solid unique-tile rectangle so shared filler
tile 7 never punches holes in Hangul (ターン's first row and inner gaps).
ss3: yellow ability plates in resource 0x083424A0, Galmuri9 Regular, yellow
face 1/2 + 1px dark-brown contour 7. Labels follow the 28 consecutive
source-id runs in preview order; truncated ラミネート/Iフィールド frames are
reconstructed from the animation ID stream including shared suffix tiles.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
EXPECTED_MAIN_SHA256 = "d8dc5aae0035c141e88e7b9b05b5a081c5121f133f307b821c2d6fefc1a909d4"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
TURN_SOURCE = 0x08165044
TURN_POINTER = 0x0001A248
ABILITY_SOURCE = 0x083424A0
ABILITY_POINTER = 0x0002BA9C
TURN_CLONE = 0x01F62000
ABILITY_CLONE = 0x01F6B000
ALLOCATION_END = 0x01F72000
PARENT_STATE_STEM = (
    ADVANCE_ROOT
    / "outputs"
    / "20260905_ggen_advance_stage_titles"
    / "ggen_advance_stage_entry_titles_ko_candidate_20260905"
)
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_turn_ability_overlays"
OUT_ROM = OUT_DIR / "ggen_advance_turn_ability_overlays_ko_candidate_20260905.gba"
OUT_SAV = OUT_ROM.with_suffix(".sav")
OUT_PREVIEW = OUT_DIR / "ggen_advance_turn_ability_overlays_preview_20260905.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_overlays_ko_candidate_20260905.json"

# Preview-row order of the 28 consecutive source-id runs. ラミネート / Iフィールド /
# FFバリア were previously assigned by tile-range heuristics and landed on the
# wrong Korean strings. FFバリア occupies four runs because two are fragments.
ABILITY_RUN_LABELS = [
    ("分身", "분신"),
    ("分身", "분신"),
    ("分身", "분신"),
    ("フェイズシフト装甲", "페이즈시프트장갑"),
    ("フェイズシフト装甲", "페이즈시프트장갑"),
    ("フェイズシフト装甲", "페이즈시프트장갑"),
    ("ラミネート装甲", "라미네이트장갑"),
    ("ラミネート装甲", "라미네이트장갑"),
    ("ラミネート装甲", "라미네이트장갑"),
    ("ビームコート", "빔코트"),
    ("ビームコート", "빔코트"),
    ("ビームコート", "빔코트"),
    ("Iフィールド", "아이필드"),
    ("Iフィールド", "아이필드"),
    ("Iフィールド", "아이필드"),
    ("Pディフェンサー", "P디펜서"),
    ("Pディフェンサー", "P디펜서"),
    ("Pディフェンサー", "P디펜서"),
    ("FFバリア", "FF배리어"),
    ("FFバリア", "FF배리어"),
    ("FFバリア", "FF배리어"),
    ("FFバリア", "FF배리어"),
    ("月光蝶", "월광접"),
    ("月光蝶", "월광접"),
    ("月光蝶", "월광접"),
    ("光の翼", "빛의날개"),
    ("光の翼", "빛의날개"),
    ("光の翼", "빛의날개"),
]
TURN_FACE = 8
TURN_OUTLINE = 15
TURN_SHADOW = 4
TURN_SCALE = 2
TURN_OUTLINE_R = 1
TURN_SHADOW_D = 2
TURN_FILLER = {6, 7}
# 64x32 source-id maps from animation records (row-major 8x4). Tile 7 is shared
# blank padding and must never be written. Columns 5-7 (軍) are shared across
# 自軍 / 敵軍 / 友軍. Prefix glyphs stay on unique tiles; 군 is written once.
ALLY_FACTION_IDS = [
    7, 7, 53, 54, 55, 56, 57, 58,
    7, 7, 59, 60, 61, 62, 63, 64,
    7, 65, 66, 67, 68, 69, 70, 71,
    7, 72, 73, 74, 75, 76, 77, 78,
]
ENEMY_FACTION_IDS = [
    7, 108, 109, 110, 111, 56, 57, 58,
    7, 112, 113, 114, 115, 62, 63, 64,
    7, 116, 117, 118, 119, 69, 70, 71,
    7, 120, 121, 122, 123, 76, 77, 78,
]
FRIEND_FACTION_IDS = [
    7, 124, 125, 126, 127, 56, 57, 58,
    7, 128, 129, 130, 131, 62, 63, 64,
    7, 132, 133, 134, 135, 69, 70, 71,
    7, 136, 137, 138, 139, 76, 77, 78,
]
THIRD_FACTION_IDS = list(range(140, 172))
SHARED_GUN_IDS = {56, 57, 58, 62, 63, 64, 69, 70, 71, 76, 77, 78}


def mask_faction_ids(ids: list[int], *, keep: set[int] | None = None, drop: set[int] | None = None) -> list[int]:
    out: list[int] = []
    for src in ids:
        if src in TURN_FILLER:
            out.append(src)
        elif drop is not None and src in drop:
            out.append(7)
        elif keep is not None and src not in keep:
            out.append(7)
        else:
            out.append(src)
    return out


GUN_PLATE_IDS = mask_faction_ids(ENEMY_FACTION_IDS, keep=SHARED_GUN_IDS)
ENEMY_PREFIX_IDS = mask_faction_ids(ENEMY_FACTION_IDS, drop=SHARED_GUN_IDS)
FRIEND_PREFIX_IDS = mask_faction_ids(FRIEND_FACTION_IDS, drop=SHARED_GUN_IDS)
ALLY_PREFIX_IDS = mask_faction_ids(ALLY_FACTION_IDS, drop=SHARED_GUN_IDS)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def p32(value: int) -> bytes:
    return struct.pack("<I", value)


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile length drift")
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def encode_tile(pixels: list[list[int]]) -> bytes:
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


def palette_rgb(raw: bytes) -> list[tuple[int, int, int]]:
    return [tuple(((u16(raw, i * 2) >> s) & 31) * 255 // 31 for s in (0, 5, 10)) for i in range(16)]


def render_canvas(canvas: list[list[int]], colors: list[tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", (len(canvas[0]), len(canvas)))
    image.putdata([colors[value] for row in canvas for value in row])
    return image


def resource_blob(rom: bytes, address: int) -> tuple[dict[str, int], bytes]:
    off = address - ROM_BASE
    kind, pal_count, gfx_rel, pal_rel, anim_count = struct.unpack_from("<5I", rom, off)
    gate(kind == 0 and pal_count == 6, f"resource 0x{address:08X} header drift")
    size = pal_rel + pal_count * 32
    return {
        "off": off,
        "pal_count": pal_count,
        "gfx_rel": gfx_rel,
        "pal_rel": pal_rel,
        "anim_count": anim_count,
        "tiles": (pal_rel - gfx_rel) // 32,
        "size": size,
    }, rom[off:off + size]


def pointer_hits(data: bytes, address: int) -> list[int]:
    needle = p32(address)
    hits = []
    start = 0
    while True:
        found = data.find(needle, start)
        if found < 0:
            return hits
        hits.append(found)
        start = found + 1


def native_ink(font: fontpair.BdfFont, text: str, cell: int = 12) -> tuple[set[tuple[int, int]], int, int]:
    """Pack glyphs from a square cell, then crop each to its ink bbox."""
    ink: set[tuple[int, int]] = set()
    cursor = 0
    height = 0
    for char in text:
        if char == " ":
            cursor += cell // 2
            continue
        image = font.render(char, cell, cell)
        xs = [x for y in range(cell) for x in range(cell) if image.getpixel((x, y))]
        ys = [y for y in range(cell) for x in range(cell) if image.getpixel((x, y))]
        gate(xs and ys, f"{font.name} empty glyph {char!r}")
        x0, y0, x1, y1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
        for y in range(y0, y1):
            for x in range(x0, x1):
                if image.getpixel((x, y)):
                    ink.add((cursor + x - x0, y - y0))
                    height = max(height, y - y0 + 1)
        cursor += x1 - x0
    gate(ink, f"empty mask for {text!r}")
    width = max(x for x, _y in ink) + 1
    return ink, width, height


def dilate(points: set[tuple[int, int]], width: int, height: int) -> set[tuple[int, int]]:
    out = set()
    for x, y in points:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < width and 0 <= yy < height:
                    out.add((xx, yy))
    return out


def dilate_n(points: set[tuple[int, int]], width: int, height: int, radius: int) -> set[tuple[int, int]]:
    out = set(points)
    for _ in range(radius):
        out = dilate(out, width, height)
    return out


def scale_ink(ink: set[tuple[int, int]], scale: int) -> set[tuple[int, int]]:
    if scale <= 1:
        return set(ink)
    out: set[tuple[int, int]] = set()
    for x, y in ink:
        for dy in range(scale):
            for dx in range(scale):
                out.add((x * scale + dx, y * scale + dy))
    return out


def objects_from_ids(ids: list[int]) -> list[dict[str, object]]:
    objs: list[dict[str, object]] = []
    width = 0
    remaining = list(ids)
    while remaining:
        if len(remaining) >= 8:
            take, w, h = 8, 32, 16
        elif len(remaining) >= 4:
            take, w, h = 4, 16, 16
        elif len(remaining) >= 2:
            take, w, h = 2, 8, 16
        else:
            take, w, h = 1, 8, 8
        objs.append({"x": width, "y": 0, "w": w, "h": h, "ids": remaining[:take]})
        remaining = remaining[take:]
        width += w
    return objs


def objects_from_run(start: int, count: int) -> list[dict[str, object]]:
    return objects_from_ids(list(range(start, start + count)))


def canvas_from_objects(graphics: bytes, objs: list[dict[str, object]]) -> list[list[int]]:
    width = max(int(o["x"]) + int(o["w"]) for o in objs)
    height = max(int(o["y"]) + int(o["h"]) for o in objs)
    canvas = [[0] * width for _ in range(height)]
    for obj in objs:
        ids = list(obj["ids"])
        tw, th = int(obj["w"]) // 8, int(obj["h"]) // 8
        for ty in range(th):
            for tx in range(tw):
                tile = decode_tile(graphics[ids[ty * tw + tx] * 32:(ids[ty * tw + tx] + 1) * 32])
                ox, oy = int(obj["x"]) + tx * 8, int(obj["y"]) + ty * 8
                for py in range(8):
                    canvas[oy + py][ox:ox + 8] = tile[py]
    return canvas


def write_objects(graphics: bytearray, objs: list[dict[str, object]], canvas: list[list[int]], skip_ids: set[int] | None = None) -> None:
    skip = skip_ids or set()
    for obj in objs:
        ids = list(obj["ids"])
        tw, th = int(obj["w"]) // 8, int(obj["h"]) // 8
        for ty in range(th):
            for tx in range(tw):
                src = ids[ty * tw + tx]
                if src in skip:
                    continue
                ox, oy = int(obj["x"]) + tx * 8, int(obj["y"]) + ty * 8
                tile = [canvas[oy + py][ox:ox + 8] for py in range(8)]
                graphics[src * 32:(src + 1) * 32] = encode_tile(tile)


def animation_records(blob: bytes, hdr: dict[str, int]) -> list[bytes]:
    rels = [u32(blob, 0x14 + i * 4) for i in range(hdr["anim_count"])]
    starts = [0x14 + rel for rel in rels]
    ends = starts[1:] + [hdr["gfx_rel"]]
    return [blob[a:b] for a, b in zip(starts, ends)]


def consecutive_id_runs(records: list[bytes], tile_count: int) -> list[tuple[int, int]]:
    found: dict[int, int] = {}
    for blob in records:
        count = len(blob) // 2
        values = list(struct.unpack_from(f"<{count}H", blob))
        index = 0
        while index < len(values):
            start = values[index]
            if start >= tile_count:
                index += 1
                continue
            length = 1
            while index + length < len(values) and values[index + length] == start + length and start + length < tile_count:
                length += 1
            if length >= 4:
                found[start] = max(found.get(start, 0), length)
            index += max(length, 1)
    runs = sorted((start, length) for start, length in found.items())
    kept = []
    for start, length in runs:
        nested = any(
            other_start <= start and start + length <= other_start + other_len and (other_start, other_len) != (start, length)
            for other_start, other_len in runs
        )
        if not nested:
            kept.append((start, length))
    return kept


def extend_run(records: list[bytes], tile_count: int, start: int, count: int) -> list[int]:
    """Reattach shared suffix/prefix tiles that break consecutive-id detection.

    ラミネート装甲 hold is 86..93 then 60,61,94,65,62,66 (PS 装甲 fragments).
    Iフィールド intro is 131,132 then 133..138 then 106 (ビームコート tail).
    """
    target = list(range(start, start + count))
    best = target
    for blob in records:
        values = list(struct.unpack_from(f"<{len(blob) // 2}H", blob))
        index = 0
        while index <= len(values) - count:
            if list(values[index : index + count]) != target:
                index += 1
                continue
            extra: list[int] = []
            cursor = index + count
            while cursor < len(values):
                nxt = values[cursor]
                if nxt < 8 or nxt >= tile_count:
                    break
                if nxt == 64 and cursor + 1 < len(values) and values[cursor + 1] == 64:
                    break
                if not extra:
                    extra.append(nxt)
                else:
                    prev = extra[-1]
                    if nxt == prev + 1 and nxt > start + count:
                        break
                    extra.append(nxt)
                cursor += 1
                if len(target) + len(extra) >= 16:
                    break
            filler_between = False
            pre: list[int] = []
            cursor = index - 1
            expect = start - 1
            while cursor >= 0 and expect >= 0:
                if values[cursor] == 6:
                    filler_between = True
                    cursor -= 1
                    continue
                if values[cursor] == expect and expect < tile_count:
                    pre.insert(0, values[cursor])
                    cursor -= 1
                    expect -= 1
                    continue
                break
            candidate = pre + ([6] if filler_between else []) + target + extra
            if len(candidate) > len(best):
                best = candidate
            index += 1
    return best


def paint_ability(canvas: list[list[int]], text: str, font: fontpair.BdfFont) -> dict[str, object]:
    height, width = len(canvas), len(canvas[0])
    ink, tw, th = native_ink(font, text)
    if tw > width - 2:
        scale = (width - 2) / tw
        ink = {(min(width - 3, int(x * scale)), y) for x, y in ink}
        tw = max(x for x, _y in ink) + 1
        th = max(y for _x, y in ink) + 1
    x0 = max(1, (width - tw) // 2)
    y0 = max(1, (height - th) // 2)
    placed = {(x0 + x, y0 + y) for x, y in ink if 0 <= x0 + x < width and 0 <= y0 + y < height}
    gate(placed, f"ability glyph clipped: {text}")
    contour = dilate(placed, width, height) - placed
    after = [[0] * width for _ in range(height)]
    for x, y in contour:
        after[y][x] = 7
    for x, y in placed:
        after[y][x] = 1 if y - y0 <= max(0, th // 2) else 2
    return {
        "text": text,
        "origin": [x0, y0],
        "ink": len(placed),
        "contour": len(contour),
        "before": canvas,
        "after": after,
    }


def local_objects(objs: list[dict[str, object]]) -> list[dict[str, object]]:
    x0 = min(int(o["x"]) for o in objs)
    y0 = min(int(o["y"]) for o in objs)
    return [{**o, "x": int(o["x"]) - x0, "y": int(o["y"]) - y0} for o in objs]


def largest_solid_box(objs: list[dict[str, object]]) -> tuple[int, int, int, int]:
    """Largest rectangle of non-filler 8x8 cells, in object-local pixels."""
    cells: set[tuple[int, int]] = set()
    for obj in objs:
        ids = list(obj["ids"])
        tw, th = int(obj["w"]) // 8, int(obj["h"]) // 8
        gate(int(obj["x"]) % 8 == 0 and int(obj["y"]) % 8 == 0, "object not tile-aligned")
        for ty in range(th):
            for tx in range(tw):
                if ids[ty * tw + tx] in TURN_FILLER:
                    continue
                cells.add((int(obj["x"]) // 8 + tx, int(obj["y"]) // 8 + ty))
    gate(cells, "object has no unique tiles")
    xs = [x for x, _y in cells]
    ys = [y for _x, y in cells]
    best_key: tuple[int, int, int, int] | None = None
    best_cell: tuple[int, int, int, int] | None = None
    for y0 in range(min(ys), max(ys) + 1):
        for x0 in range(min(xs), max(xs) + 1):
            if (x0, y0) not in cells:
                continue
            for y1 in range(y0 + 1, max(ys) + 2):
                for x1 in range(x0 + 1, max(xs) + 2):
                    if not all((x, y) in cells for y in range(y0, y1) for x in range(x0, x1)):
                        continue
                    key = (min(x1 - x0, y1 - y0), (x1 - x0) * (y1 - y0), y1 - y0, x1 - x0)
                    if best_key is None or key > best_key:
                        best_key = key
                        best_cell = (x0, y0, x1, y1)
    gate(best_cell is not None, "no solid tile rectangle")
    x0, y0, x1, y1 = best_cell
    return (x0 * 8, y0 * 8, x1 * 8, y1 * 8)


def clear_unique_tiles(canvas: list[list[int]], objs: list[dict[str, object]]) -> None:
    for obj in objs:
        ids = list(obj["ids"])
        tw, th = int(obj["w"]) // 8, int(obj["h"]) // 8
        for ty in range(th):
            for tx in range(tw):
                if ids[ty * tw + tx] in TURN_FILLER:
                    continue
                ox, oy = int(obj["x"]) + tx * 8, int(obj["y"]) + ty * 8
                for py in range(8):
                    canvas[oy + py][ox:ox + 8] = [0] * 8


def paint_turn_field(
    canvas: list[list[int]],
    text: str,
    font: fontpair.BdfFont,
    box: tuple[int, int, int, int],
    align: str = "center",
    gap: int = 0,
) -> dict[str, object]:
    """Flat face, solid 2px BR shadow covering the glyph, 1px white only outside face+shadow."""
    x0, y0, x1, y1 = box
    field_w, field_h = x1 - x0, y1 - y0
    ink, tw, th = native_ink(font, text)
    ink = scale_ink(ink, TURN_SCALE)
    tw *= TURN_SCALE
    th *= TURN_SCALE
    pad_l = pad_t = TURN_OUTLINE_R
    pad_r = pad_b = TURN_OUTLINE_R + TURN_SHADOW_D
    inner_w = field_w - pad_l - pad_r
    inner_h = field_h - pad_t - pad_b
    gate(inner_w >= 4 and inner_h >= 4, f"turn field too small: {text}")
    if tw > inner_w or th > inner_h:
        scale = min(inner_w / tw, inner_h / th)
        ink = {(min(inner_w - 1, int(x * scale)), min(inner_h - 1, int(y * scale))) for x, y in ink}
        tw = max(x for x, _y in ink) + 1
        th = max(y for _x, y in ink) + 1
    if align == "right":
        ox = x1 - pad_r - tw - gap
    elif align == "left":
        ox = x0 + pad_l + gap
    else:
        ox = x0 + pad_l + max(0, (inner_w - tw) // 2)
    ox = min(max(ox, x0 + pad_l), max(x0 + pad_l, x1 - pad_r - tw))
    oy = y0 + pad_t + max(0, (inner_h - th) // 2)
    placed = {(ox + x, oy + y) for x, y in ink if x0 <= ox + x < x1 and y0 <= oy + y < y1}
    gate(len(placed) >= max(8, len(ink) * 3 // 4), f"turn glyph overflow: {text}")
    # Solid BR cover of 1..D px so the 2px shadow does not leave a 1px gap that
    # the white outline would fill around the raw glyph.
    shadow = {
        (x + dx, y + dy)
        for x, y in placed
        for dx in range(0, TURN_SHADOW_D + 1)
        for dy in range(0, TURN_SHADOW_D + 1)
        if (dx or dy) and x0 <= x + dx < x1 and y0 <= y + dy < y1
    }
    body = placed | shadow
    outline = {
        (x, y)
        for x, y in dilate(body, len(canvas[0]), len(canvas)) - body
        if x0 <= x < x1 and y0 <= y < y1
    }
    after = [row[:] for row in canvas]
    for y in range(y0, y1):
        for x in range(x0, x1):
            after[y][x] = 0
    for x, y in outline:
        after[y][x] = TURN_OUTLINE
    for x, y in shadow:
        after[y][x] = TURN_SHADOW
    for x, y in placed:
        after[y][x] = TURN_FACE
    return {"text": text, "box": list(box), "origin": [ox, oy], "ink": len(placed), "after": after, "align": align}


def paint_turn_group(
    graphics: bytearray,
    orig: bytes,
    objs: list[dict[str, object]],
    text: str,
    font: fontpair.BdfFont,
    align: str = "center",
    gap: int = 0,
) -> dict[str, object]:
    """Paint one label into its own objects so overlapping banner OAMs cannot steal pixels."""
    local = local_objects(objs)
    before = canvas_from_objects(orig, local)
    cleared = [row[:] for row in before]
    clear_unique_tiles(cleared, local)
    box = largest_solid_box(local)
    painted = paint_turn_field(cleared, text, font, box, align=align, gap=gap)
    write_objects(graphics, local, painted["after"], skip_ids=TURN_FILLER)
    return {
        "ko": text,
        "box": painted["box"],
        "align": align,
        "tiles": sorted({i for obj in local for i in obj["ids"] if i not in TURN_FILLER}),
        "canvas": [len(before[0]), len(before)],
        "before": before,
        "after": canvas_from_objects(graphics, local),
        "ink": painted["ink"],
    }


def faction_dummy(ids: list[int]) -> list[dict[str, object]]:
    return [{"x": 0, "y": 0, "w": 64, "h": 32, "ids": ids}]


def remap_obj_tiles(dest: bytearray, template: bytes, jp_gfx: bytes, new_gfx: bytes, tile_count: int) -> None:
    """Copy template live OBJ slots that match JP source tiles, writing the Korean clones."""
    lookup = {jp_gfx[i * 32:(i + 1) * 32]: i for i in range(tile_count)}
    obj_base = statefmt.STATE_VRAM + statefmt.OBJ_VRAM
    src_obj = template[obj_base:statefmt.STATE_IWRAM]
    dst_obj = dest[obj_base:statefmt.STATE_IWRAM]
    for tile in range(len(src_obj) // 32):
        src = lookup.get(bytes(src_obj[tile * 32:(tile + 1) * 32]))
        if src is not None:
            dst_obj[tile * 32:(tile + 1) * 32] = bytes(new_gfx[src * 32:(src + 1) * 32])
    dest[obj_base:statefmt.STATE_IWRAM] = dst_obj


def live_turn_objects(state: bytes, graphics: bytes) -> list[dict[str, object]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    lookup = {graphics[i * 32:(i + 1) * 32]: i for i in range(len(graphics) // 32)}
    rows = []
    for index in range(15):
        row = statefmt.parse_oam_entry(oam, index)
        w, h = int(row["width"]), int(row["height"])
        tile0 = int(row["tile"])
        ids = []
        missing = 0
        for ty in range(h // 8):
            for tx in range(w // 8):
                raw = bytes(obj[(tile0 + ty * (w // 8) + tx) * 32:(tile0 + ty * (w // 8) + tx + 1) * 32])
                src = lookup.get(raw)
                if src is None:
                    missing += 1
                    src = 7
                ids.append(src)
        rows.append({
            "oam": index,
            "x": int(row["x"]),
            "y": int(row["y"]),
            "w": w,
            "h": h,
            "ids": ids,
            "missing": missing,
        })
    return rows


def banner_canvas(graphics: bytes, objs: list[dict[str, object]]) -> tuple[list[list[int]], int, int]:
    x0 = min(int(o["x"]) for o in objs)
    y0 = min(int(o["y"]) for o in objs)
    shifted = [{**o, "x": int(o["x"]) - x0, "y": int(o["y"]) - y0} for o in objs]
    return canvas_from_objects(graphics, shifted), x0, y0


def replace_state_chunk(path: Path, state: bytes) -> bytes:
    raw = path.read_bytes()
    out = bytearray(raw[:8])
    pos = 8
    replaced = False
    while pos + 12 <= len(raw):
        length = struct.unpack_from(">I", raw, pos)[0]
        kind = raw[pos + 4:pos + 8]
        payload = raw[pos + 8:pos + 8 + length]
        if kind == b"gbAs":
            payload = zlib.compress(state, 9)
            replaced = True
        out += struct.pack(">I", len(payload)) + kind + payload
        out += struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        pos += 12 + length
        if kind == b"IEND":
            break
    gate(replaced and pos == len(raw), "failed to rewrite mGBA gbAs state chunk")
    return bytes(out)


def assign_ability_labels(runs: list[tuple[int, int]], records: list[bytes], tile_count: int) -> list[dict[str, object]]:
    gate(len(runs) == len(ABILITY_RUN_LABELS), f"ability run count drift: {len(runs)} vs {len(ABILITY_RUN_LABELS)}")
    labels = []
    for (start, count), (jp, ko) in zip(runs, ABILITY_RUN_LABELS):
        ids = extend_run(records, tile_count, start, count)
        labels.append({
            "start": start,
            "count": count,
            "ids": ids,
            "jp": jp,
            "ko": ko,
            "objects": objects_from_ids(ids),
        })
    return labels


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == EXPECTED_MAIN_SHA256 == manifest.get("sha256"), "current main TIP identity drift")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "JP ROM hash drift")
    turn_hdr, turn_src = resource_blob(parent, TURN_SOURCE)
    abil_hdr, abil_src = resource_blob(parent, ABILITY_SOURCE)
    gate(parent[TURN_CLONE:ALLOCATION_END] == b"\0" * (ALLOCATION_END - TURN_CLONE), "clone allocation occupied")
    gate(pointer_hits(parent, TURN_SOURCE) == [TURN_POINTER], f"turn pointer drift: {pointer_hits(parent, TURN_SOURCE)}")
    gate(pointer_hits(parent, ABILITY_SOURCE) == [ABILITY_POINTER], f"ability pointer drift: {pointer_hits(parent, ABILITY_SOURCE)}")
    gate(turn_src == jp[TURN_SOURCE - ROM_BASE:TURN_SOURCE - ROM_BASE + turn_hdr["size"]], "turn resource already changed")
    gate(abil_src == jp[ABILITY_SOURCE - ROM_BASE:ABILITY_SOURCE - ROM_BASE + abil_hdr["size"]], "ability resource already changed")

    with ZipFile(FONT_ZIP) as archive:
        font11 = fontpair.BdfFont.from_bytes(archive.read("Galmuri11.bdf"), "Galmuri11 Regular")
        font9 = fontpair.BdfFont.from_bytes(archive.read("Galmuri9.bdf"), "Galmuri9 Regular")

    turn_clone = bytearray(turn_src)
    abil_clone = bytearray(abil_src)
    turn_gfx = turn_clone[turn_hdr["gfx_rel"]:turn_hdr["pal_rel"]]
    abil_gfx = abil_clone[abil_hdr["gfx_rel"]:abil_hdr["pal_rel"]]
    abil_pal = bytes(abil_clone[abil_hdr["pal_rel"]:abil_hdr["pal_rel"] + 32])
    turn_pal3 = bytes(turn_clone[turn_hdr["pal_rel"] + 3 * 32:turn_hdr["pal_rel"] + 4 * 32])
    turn_pal0 = bytes(turn_clone[turn_hdr["pal_rel"]:turn_hdr["pal_rel"] + 32])

    abil_records = animation_records(bytes(abil_src), abil_hdr)
    runs = consecutive_id_runs(abil_records, abil_hdr["tiles"])
    gate(runs, "no ability source-id runs")
    print(json.dumps({"ability_source_runs": [{"start": s, "count": c} for s, c in runs]}, ensure_ascii=False))
    orig_abil_gfx = bytes(abil_gfx)
    labels = assign_ability_labels(runs, abil_records, abil_hdr["tiles"])
    # Shared 装甲/フィールド fragments must stay with フェイズシフト hold (ss3).
    # Paint every other plate first, snapshot from original tiles, then repaint PS.
    ability_reports: list[dict[str, object] | None] = [None] * len(labels)
    paint_order = [i for i, label in enumerate(labels) if label["ko"] != "페이즈시프트장갑"]
    paint_order += [i for i, label in enumerate(labels) if label["ko"] == "페이즈시프트장갑"]
    for index in paint_order:
        label = labels[index]
        before = canvas_from_objects(orig_abil_gfx, label["objects"])
        painted = paint_ability(before, label["ko"], font9)
        write_objects(abil_gfx, label["objects"], painted["after"], skip_ids={6})
        ability_reports[index] = {
            "jp": label["jp"],
            "ko": label["ko"],
            "tiles": [label["start"], label["start"] + label["count"] - 1],
            "ids": label["ids"],
            "canvas": [len(before[0]), len(before)],
            "ink": painted["ink"],
            "contour": painted["contour"],
            "before": painted["before"],
            "after": painted["after"],
        }
    gate(all(row is not None for row in ability_reports), "ability report hole")
    abil_clone[abil_hdr["gfx_rel"]:abil_hdr["pal_rel"]] = abil_gfx
    gate(abil_clone[abil_hdr["pal_rel"]:] == abil_src[abil_hdr["pal_rel"]:], "ability palettes/OAM changed")

    ss2, _ = statefmt.parse_png_state(PARENT_STATE_STEM.with_suffix(".ss2"))
    ss3, _ = statefmt.parse_png_state(PARENT_STATE_STEM.with_suffix(".ss3"))
    gate(u32(ss2, 8) == binascii.crc32(parent) & 0xFFFFFFFF, "ss2 CRC drift")
    gate(u32(ss3, 8) == binascii.crc32(parent) & 0xFFFFFFFF, "ss3 CRC drift")
    live_objs = live_turn_objects(ss2, bytes(turn_src[turn_hdr["gfx_rel"]:turn_hdr["pal_rel"]]))
    text_objs = [row for row in live_objs if int(row["oam"]) in {1, 2, 3, 4, 5, 6}]
    gate(all(int(row["missing"]) == 0 for row in text_objs), "turn text object has foreign tiles")
    orig_turn_gfx = bytes(turn_gfx)
    banner, _origin_x, _origin_y = banner_canvas(orig_turn_gfx, text_objs)
    top = next(row for row in text_objs if row["oam"] == 6)
    right_objs = [row for row in text_objs if row["oam"] in {1, 2, 3, 4}]
    painted_turn = paint_turn_group(turn_gfx, orig_turn_gfx, [top], "턴", font11)
    painted_attack = paint_turn_group(turn_gfx, orig_turn_gfx, right_objs, "공격개시", font11)
    painted_gun = paint_turn_group(turn_gfx, orig_turn_gfx, faction_dummy(GUN_PLATE_IDS), "군", font11, align="left", gap=1)
    painted_enemy = paint_turn_group(turn_gfx, orig_turn_gfx, faction_dummy(ENEMY_PREFIX_IDS), "적", font11, align="right", gap=1)
    painted_friend = paint_turn_group(turn_gfx, orig_turn_gfx, faction_dummy(FRIEND_PREFIX_IDS), "우", font11, align="right", gap=1)
    painted_ally = paint_turn_group(turn_gfx, orig_turn_gfx, faction_dummy(ALLY_PREFIX_IDS), "아", font11, align="right", gap=1)
    painted_third = paint_turn_group(turn_gfx, orig_turn_gfx, faction_dummy(THIRD_FACTION_IDS), "제3군", font11)
    gate(painted_turn["box"] == [8, 8, 32, 32], f"턴 solid box drift: {painted_turn['box']}")
    gate(painted_gun["box"][0] == 40, f"군 column drift: {painted_gun['box']}")
    faction_reports = [painted_gun, painted_enemy, painted_friend, painted_ally, painted_third]

    turn_clone[turn_hdr["gfx_rel"]:turn_hdr["pal_rel"]] = turn_gfx
    gate(turn_clone[turn_hdr["pal_rel"]:] == turn_src[turn_hdr["pal_rel"]:], "turn palettes/OAM changed")
    gate(turn_clone[:turn_hdr["gfx_rel"]] == turn_src[:turn_hdr["gfx_rel"]], "turn animation records changed")
    gate(abil_clone[:abil_hdr["gfx_rel"]] == abil_src[:abil_hdr["gfx_rel"]], "ability animation records changed")

    candidate = bytearray(parent)
    gate(TURN_CLONE + turn_hdr["size"] <= ABILITY_CLONE, "turn clone overlaps ability clone")
    gate(ABILITY_CLONE + abil_hdr["size"] <= ALLOCATION_END, "ability clone overflows allocation")
    candidate[TURN_CLONE:TURN_CLONE + turn_hdr["size"]] = turn_clone
    candidate[ABILITY_CLONE:ABILITY_CLONE + abil_hdr["size"]] = abil_clone
    candidate[TURN_POINTER:TURN_POINTER + 4] = p32(ROM_BASE + TURN_CLONE)
    candidate[ABILITY_POINTER:ABILITY_POINTER + 4] = p32(ROM_BASE + ABILITY_CLONE)
    allowed = set(range(TURN_POINTER, TURN_POINTER + 4)) | set(range(ABILITY_POINTER, ABILITY_POINTER + 4))
    allowed.update(range(TURN_CLONE, TURN_CLONE + turn_hdr["size"]))
    allowed.update(range(ABILITY_CLONE, ABILITY_CLONE + abil_hdr["size"]))
    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    gate(set(changed) <= allowed, f"diff escape: {len(set(changed) - allowed)} bytes")
    gate(len(candidate) == len(parent), "ROM size drift")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sav_src = MAIN_TIP_ROM.with_suffix(".sav")
    if not sav_src.exists():
        sav_src = PARENT_STATE_STEM.with_suffix(".sav")
    sav_bytes = sav_src.read_bytes()
    keep_existing_sav = OUT_SAV.exists() and OUT_SAV.read_bytes() != sav_bytes
    OUT_ROM.write_bytes(candidate)
    if keep_existing_sav:
        print(json.dumps({"save": "kept_user_changes", "path": advance_relative(OUT_SAV)}, ensure_ascii=False))
    else:
        OUT_SAV.write_bytes(sav_bytes)
    gate(OUT_ROM.read_bytes() == candidate, "ROM readback")

    crc = binascii.crc32(candidate) & 0xFFFFFFFF
    jp_tiles = bytes(turn_src[turn_hdr["gfx_rel"]:turn_hdr["pal_rel"]])
    derived = {}
    for suffix, state in (("ss2", ss2), ("ss3", ss3)):
        out = bytearray(state)
        struct.pack_into("<I", out, 8, crc)
        if suffix == "ss2":
            remap_obj_tiles(out, ss2, jp_tiles, bytes(turn_gfx), turn_hdr["tiles"])
        else:
            obj_base = statefmt.STATE_VRAM + statefmt.OBJ_VRAM
            dest = obj_base + 384 * 32
            payload = b"".join(bytes(abil_gfx[i * 32:(i + 1) * 32]) for i in range(51, 67))
            out[dest:dest + len(payload)] = payload
        path = OUT_DIR / (OUT_ROM.stem + f".{suffix}")
        path.write_bytes(replace_state_chunk(PARENT_STATE_STEM.with_suffix(f".{suffix}"), bytes(out)))
        derived[suffix] = {"path": advance_relative(path), "sha256": sha256(path.read_bytes())}
    ss1_path = OUT_DIR / (OUT_ROM.stem + ".ss1")
    if ss1_path.exists():
        ss1_state, _ = statefmt.parse_png_state(ss1_path)
        out = bytearray(ss1_state)
        struct.pack_into("<I", out, 8, crc)
        remap_obj_tiles(out, ss2, jp_tiles, bytes(turn_gfx), turn_hdr["tiles"])
        ss1_path.write_bytes(replace_state_chunk(ss1_path, bytes(out)))
        derived["ss1"] = {"path": advance_relative(ss1_path), "sha256": sha256(ss1_path.read_bytes())}

    # Preview sheet.
    scale = 4
    faction_previews = []
    for name, ids, pal in (
        ("아군", ALLY_FACTION_IDS, turn_pal0),
        ("우군", FRIEND_FACTION_IDS, turn_pal0),
        ("적군", ENEMY_FACTION_IDS, turn_pal3),
        ("제3군", THIRD_FACTION_IDS, turn_pal3),
    ):
        dummy = faction_dummy(ids)
        colors = palette_rgb(pal)
        before = render_canvas(canvas_from_objects(orig_turn_gfx, dummy), colors).resize((64 * scale, 32 * scale), Image.Resampling.NEAREST)
        after = render_canvas(canvas_from_objects(turn_gfx, dummy), colors).resize((64 * scale, 32 * scale), Image.Resampling.NEAREST)
        faction_previews.append((name, before, after))
    sheet_h = 48
    banner_after, _, _ = banner_canvas(turn_gfx, text_objs)
    before_turn = render_canvas(banner, palette_rgb(turn_pal3)).resize((len(banner[0]) * 2, len(banner) * 2), Image.Resampling.NEAREST)
    after_turn = render_canvas(banner_after, palette_rgb(turn_pal3)).resize((len(banner_after[0]) * 2, len(banner_after) * 2), Image.Resampling.NEAREST)
    after_blue = render_canvas(banner_after, palette_rgb(turn_pal0)).resize((len(banner_after[0]) * 2, len(banner_after) * 2), Image.Resampling.NEAREST)
    sheet_h += before_turn.height + 28
    sheet_h += 18 + sum(max(before.height, 32) + 8 for _n, before, _a in faction_previews)
    for row in ability_reports:
        sheet_h += max(int(row["canvas"][1]) * scale, 32) + 12
    sheet = Image.new("RGB", (920, sheet_h), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 6), "TURN BANNER  ROM tiles  pal3/pal0  face + solid 2px BR shadow + 1px white outside both", fill=(255, 255, 255))
    sheet.paste(before_turn, (8, 24))
    sheet.paste(after_turn, (8 + before_turn.width + 8, 24))
    sheet.paste(after_blue, (8 + (before_turn.width + 8) * 2, 24))
    y = 24 + before_turn.height + 16
    draw.text((8, y - 12), "FACTION PLATES  自軍=아군  友軍=우군  敵軍=적군  第三軍=제3군", fill=(255, 255, 255))
    for name, before, after in faction_previews:
        sheet.paste(before, (8, y))
        sheet.paste(after, (8 + before.width + 12, y))
        draw.text((8 + before.width + after.width + 24, y + 8), name, fill=(255, 255, 255))
        y += max(before.height, 32) + 8
    y += 10
    draw.text((8, y - 12), "ABILITY PLATES  before / after  (3-frame groups; FF has 4 runs)", fill=(255, 255, 255))
    colors = palette_rgb(abil_pal)
    for index, row in enumerate(ability_reports):
        before = render_canvas(row["before"], colors).resize((row["canvas"][0] * scale, row["canvas"][1] * scale), Image.Resampling.NEAREST)
        after = render_canvas(row["after"], colors).resize((row["canvas"][0] * scale, row["canvas"][1] * scale), Image.Resampling.NEAREST)
        sheet.paste(before, (8, y))
        sheet.paste(after, (8 + before.width + 12, y))
        draw.text((8 + before.width + after.width + 24, y + 8), f"{index + 1:02d}  {row['jp']} -> {row['ko']}", fill=(255, 255, 255))
        y += max(before.height, 32) + 12
    sheet.save(OUT_PREVIEW)

    report = {
        "kind": "ggen_advance_turn_ability_overlays_ko_candidate_20260905",
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(OUT_ROM), "size": len(candidate), "sha256": sha256(candidate)},
        "verification": {
            "result": "STATIC_PASS_RUNTIME_PENDING",
            "turn_pointer": hex(TURN_POINTER + ROM_BASE),
            "ability_pointer": hex(ABILITY_POINTER + ROM_BASE),
            "animation_records_preserved": True,
            "palettes_preserved": True,
            "japanese_original_preserved": True,
        },
        "font": {
            "turn": "Galmuri11.bdf Regular 2x, flat face 8, solid 2px BR shadow 4, 1px white 15 only outside face+shadow",
            "ability": "Galmuri9.bdf Regular native bitmap, yellow 1/2 / contour 7",
        },
        "turn": {
            "source": hex(TURN_SOURCE),
            "clone": hex(ROM_BASE + TURN_CLONE),
            "live_texts": ["턴", "적군", "공격개시"],
            "live_boxes": {
                "턴": painted_turn["box"],
                "적": painted_enemy["box"],
                "군": painted_gun["box"],
                "공격개시": painted_attack["box"],
            },
            "sibling_plates": [{k: v for k, v in row.items() if k not in {"before", "after"}} for row in faction_reports],
        },
        "ability": {
            "source": hex(ABILITY_SOURCE),
            "clone": hex(ROM_BASE + ABILITY_CLONE),
            "labels": [{k: v for k, v in row.items() if k not in {"before", "after"}} for row in ability_reports],
        },
        "derived_states": derived,
        "changed_bytes": len(changed),
        "allocation": [hex(TURN_CLONE), hex(ALLOCATION_END)],
        "note": "Main ROM is not promoted. Derived ss2/ss3 rewrite live OBJ VRAM for the captured frames.",
        "save": "kept_user_changes" if keep_existing_sav else "copied_from_parent",
    }
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "STATIC_PASS_RUNTIME_PENDING",
        "rom": advance_relative(OUT_ROM),
        "sha256": sha256(candidate),
        "ability_labels": report["ability"]["labels"],
        "faction_plates": [{k: v for k, v in row.items() if k not in {"before", "after"}} for row in faction_reports],
        "live_boxes": report["turn"]["live_boxes"],
        "preview": advance_relative(OUT_PREVIEW),
        "states": derived,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
