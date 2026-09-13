#!/usr/bin/env python3
"""Build a fixed-size/palette-preserving Korean status UI tile-overlay PoC.

This patch does not invoke the text engine.  It edits the decoded 4bpp UI tile
atlas used by the pilot/unit status screens.  The measured Japanese label tiles are rebuilt on the native panel background
pattern, then Korean glyphs are painted with the original light-ink/dark-contour
palette entries.  The decoded atlas dimensions and palette resource are left
unchanged.

The original atlas is custom-LZSS compressed.  For the PoC we rebuild the exact
same 16,608-byte decoded atlas and store it in the 32 MiB graphics append region
using a valid literal-only stream for the game's existing decoder.  The resource
pointer table entry is redirected to the rebuilt atlas.  `運動` and `移動` keep
the original three shared tiles: the Korean replacements are aligned so their
common second syllable `동` produces byte-identical shared tile data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import FONT_ZIP  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402

JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
DEFAULT_OUT = ROOT / "outputs" / "20260829_ggen_advance_status_ui" / "ggen_advance_status_ui_tile_overlay_followup_v10_galmuri7_intervalbg_20260829.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_ui_tile_overlay_followup_v10_galmuri7_intervalbg_20260829.json"
DEFAULT_PREVIEW = ROOT / "outputs" / "20260829_ggen_advance_status_ui" / "ggen_advance_status_ui_tile_overlay_followup_v10_galmuri7_intervalbg_preview_20260829.png"

EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
RESOURCE_TABLE = 0x000E0518
ATLAS_RESOURCE = 0x000DC848
ATLAS_EXPECTED_DECODED = 16608
GRAPHICS_ALLOC = 0x01240000
GRAPHICS_ADDRESS = 0x09240000
UNIT_MAP = 0x000DF588

BACKGROUND_TEMPLATE_TILE = 0x012
INK_INDEX = 10
# The original Japanese stat glyphs use this dark-brown index as a 1-pixel
# contour around the light glyph, not as a rectangular backing fill.
OUTLINE_INDEX = 5

PILOT_LABELS = {
    "근접": {"tiles": [[0x044, 0x045, 0x046, 0x047], [0x04D, 0x04E, 0x04F, 0x050]], "box": (4, 2)},
    "조종계": {"tiles": [[0x048, 0x049, 0x04A, 0x04B, 0x04C], [0x051, 0x052, 0x053, 0x054, 0x055]], "box": (5, 2)},
    "사격": {"tiles": [[0x058, 0x059, 0x05A, 0x05B], [0x062, 0x063, 0x064, 0x065]], "box": (4, 2)},
    "반응": {"tiles": [[0x06A, 0x06B, 0x06C, 0x06D], [0x072, 0x073, 0x074, 0x075]], "box": (4, 2)},
}
UNIT_LABELS = {
    "운동": {"tiles": [[0x146, 0x147, 0x148, 0x149], [0x14E, 0x14F, 0x150, 0x151]], "box": (4, 2)},
    "장갑": {"tiles": [[0x14A, 0x14B, 0x14C, 0x14D], [0x152, 0x153, 0x154, 0x155]], "box": (4, 2)},
    "한계": {"tiles": [[0x156, 0x157, 0x158, 0x159], [0x15D, 0x15E, 0x15F, 0x160]], "box": (4, 2)},
    "이동": {"tiles": [[0x15A, 0x15B, 0x15C, 0x149], [0x161, 0x162, 0x150, 0x151]], "box": (4, 2)},
}
TYPE_LABELS = {
    "범용": {"tiles": [[0x1A8, 0x1A9, 0x1AA, 0x1AB], [0x1AC, 0x1AD, 0x1AE, 0x1AF]], "box": (4, 2), "source": "汎用", "resource_index": 41},
    "우주": {"tiles": [[0x1B0, 0x1B1, 0x1B2, 0x1B3], [0x1B4, 0x1B5, 0x1B6, 0x1B7]], "box": (4, 2), "source": "宇宙", "resource_index": 42},
    "지상": {"tiles": [[0x1B8, 0x1B9, 0x1BA, 0x1BB], [0x1BC, 0x1BD, 0x1BE, 0x1BF]], "box": (4, 2), "source": "地上", "resource_index": 43},
    "만능": {"tiles": [[0x1C0, 0x1C1, 0x1C2, 0x1C3], [0x1C4, 0x1C5, 0x1C6, 0x1C7]], "box": (4, 2), "source": "万能", "resource_index": 44},
    "수륙": {"tiles": [[0x1C8, 0x1C9, 0x1CA, 0x1CB], [0x1CC, 0x1CD, 0x1CE, 0x1CF]], "box": (4, 2), "source": "水陸", "resource_index": 45},
    "비행": {"tiles": [[0x1D0, 0x1D1, 0x1D2, 0x1D3], [0x1D4, 0x1D5, 0x1D6, 0x1D7]], "box": (4, 2), "source": "飛行", "resource_index": 46},
}
LOWER_STATUS_LABELS = {
    "ID효과": {"tiles": [[0x0C3, 0x0C4, 0x0C5, 0x0C6], [0x0CA, 0x0CB, 0x0CC, 0x0CD]], "box": (4, 2), "glyph_mode": "8x16"},
    "공격": {"tiles": [[0x17F, 0x180, 0x181, 0x182], [0x18A, 0x18B, 0x18C, 0x18D]], "box": (4, 2)},
    "명중": {"tiles": [[0x195, 0x196, 0x197, 0x198], [0x199, 0x19A, 0x19B, 0x19C]], "box": (4, 2)},
    "회피": {"tiles": [[0x1A0, 0x1A1, 0x1A2, 0x1A3], [0x1A4, 0x1A5, 0x1A6, 0x1A7]], "box": (4, 2)},
    "남은횟수": {"tiles": [[0x183, 0x184, 0x185, 0x186, 0x187, 0x188, 0x189], [0x18E, 0x18F, 0x190, 0x191, 0x192, 0x193, 0x194]], "box": (7, 2)},
}
SHARED_MOTION_TILES = (0x149, 0x150, 0x151)

# Weapon-row fixed graphics.  Resource[36..39] repeats these columns for each
# weapon line.  The Japanese glyphs are encoded directly into the 4bpp atlas,
# not through the text renderer.  Values D/E/F are the native bright glyph
# tones while value 4 is the measured interior fill of the green mini badge.
WEAPON_BADGE_LABELS = {
    "실": {"source": "実", "tiles": [[0x163], [0x16A]], "box": (1, 2), "role": "physical_weapon_type", "background": "left_single"},
    "공": {"source": "攻", "tiles": [[0x164], [0x16B]], "box": (1, 2), "role": "attack_column", "background": "center_single"},
    "명": {"source": "命", "tiles": [[0x165], [0x16C]], "box": (1, 2), "role": "hit_column", "background": "center_single"},
    "탄": {"source": "弾", "tiles": [[0x166], [0x16D]], "box": (1, 2), "role": "ammo_column", "background": "center_single"},
    # The right-most 2-character weapon category is dynamic.  The four resources
    # 54..57 are composed from shared glyph tiles: 射/近 + 単/全.  Keep that
    # sharing in Korean as 사/근 + 단/전 so all combinations remain valid.
    "사": {"source": "射", "tiles": [[0x168], [0x16E]], "box": (1, 2), "role": "weapon_category_ranged", "background": "category_left"},
    "근": {"source": "近", "tiles": [[0x1ED], [0x1EE]], "box": (1, 2), "role": "weapon_category_melee", "background": "category_left"},
    "단": {"source": "単", "tiles": [[0x1EB], [0x1EC]], "box": (1, 2), "role": "weapon_category_single", "background": "category_right"},
    "전": {"source": "全", "tiles": [[0x169], [0x16F]], "box": (1, 2), "role": "weapon_category_all", "background": "category_right"},
}
WEAPON_BADGE_SHADOW_INDEX = 4
WEAPON_BADGE_INK_INDEX = 15
WEAPON_BADGE_SOURCE_GLYPH_INDICES = {4, 13, 14, 15}
INTERVAL_BADGE = {
    "text": "간",
    "source": "間",
    "resource_index": 53,
    "tiles": [[0x1E7, 0x1E8], [0x1E9, 0x1EA]],
    "box": (2, 2),
}
INTERVAL_INK_INDEX = 15
INTERVAL_SHADOW_INDEX = 4
INTERVAL_NATIVE_GREEN_BACKGROUND = [
    "666666666666669A", "6667777777777669",
    *(["8888888888888766"] * 12),
    "6667777777777669", "666666666666669A",
]
WEAPON_BADGE_BACKGROUNDS = {
    "center_single": [
        "789AA987", "77777777",
        *(["88888888"] * 12),
        "77777777", "789AA987",
    ],
    "left_single": [
        "A9766666", "96677777", "76788888",
        *(["67888888"] * 10),
        "76788888", "96677777", "A9766666",
    ],
    "category_left": [
        "66666666", "66677777",
        *(["88888888"] * 12),
        "66677777", "66666666",
    ],
    "category_right": [
        "6666669A", "77777669",
        *(["88888766"] * 12),
        "77777669", "6666669A",
    ],
}

# Map popup-menu graphics use a completely separate atlas/table from the status
# UI.  Resource[2] contains the normal five command rows; resource[4..8] are
# independent 8x2 focus overlays selected by the cursor in 0x08021A8C.
MENU_RESOURCE_TABLE = 0x000D354C
MENU_ATLAS_RESOURCE = 0x000D2490
MENU_ATLAS_EXPECTED_DECODED = 6944
MENU_GRAPHICS_ALLOC = 0x01250000
MENU_GRAPHICS_ADDRESS = 0x09250000
MENU_NORMAL_MAP = 0x000D311C
MENU_ALT_MAP = 0x000D3238
MENU_COMMANDS = {
    "턴 종료": {
        "source": "ターン終了",
        "normal": [[0x008, 0x009, 0x00A, 0x00B, 0x00C, 0x00D, 0x00E, 0x00F], [0x011, 0x012, 0x013, 0x014, 0x015, 0x016, 0x017, 0x018]],
        "focus": [[0x07C, 0x07D, 0x07E, 0x07F, 0x080, 0x081, 0x082, 0x083], [0x084, 0x085, 0x086, 0x087, 0x088, 0x089, 0x08A, 0x08B]],
        "cursor": 0,
    },
    "중단": {
        "source": "中断",
        "normal": [[0x019, 0x01A, 0x01B, 0x01C, 0x01D, 0x01E, 0x01A, 0x01F], [0x020, 0x021, 0x022, 0x023, 0x024, 0x025, 0x021, 0x026]],
        "focus": [[0x08C, 0x08D, 0x08E, 0x08F, 0x090, 0x091, 0x08D, 0x092], [0x093, 0x094, 0x095, 0x096, 0x097, 0x098, 0x094, 0x099]],
        "cursor": 1,
    },
    "상황": {
        "source": "状況",
        "normal": [[0x019, 0x01A, 0x027, 0x028, 0x029, 0x02A, 0x01A, 0x01F], [0x020, 0x021, 0x02B, 0x02C, 0x02D, 0x02E, 0x021, 0x026]],
        "focus": [[0x08C, 0x08D, 0x09A, 0x09B, 0x09C, 0x09D, 0x08D, 0x092], [0x093, 0x094, 0x09E, 0x09F, 0x0A0, 0x0A1, 0x094, 0x099]],
        "cursor": 2,
    },
    "부대목록": {
        "source": "部隊一覧",
        "normal": [[0x02F, 0x030, 0x031, 0x032, 0x033, 0x034, 0x035, 0x036], [0x037, 0x038, 0x039, 0x03A, 0x03B, 0x03C, 0x03D, 0x03E]],
        "focus": [[0x0A2, 0x0A3, 0x0A4, 0x0A5, 0x0A6, 0x0A7, 0x0A8, 0x0A9], [0x0AA, 0x0AB, 0x0AC, 0x0AD, 0x086, 0x0AE, 0x0AF, 0x0B0]],
        "cursor": 3,
    },
    "설정": {
        "source": "設定",
        "normal": [[0x019, 0x01A, 0x03F, 0x040, 0x041, 0x042, 0x01A, 0x01F], [0x020, 0x021, 0x043, 0x044, 0x045, 0x046, 0x021, 0x026]],
        "focus": [[0x08C, 0x08D, 0x0B1, 0x0B2, 0x0B3, 0x0B4, 0x08D, 0x092], [0x093, 0x094, 0x0B5, 0x0B6, 0x0B7, 0x0B8, 0x094, 0x099]],
        "cursor": 4,
    },
}
MENU_NORMAL_INK_INDEX = 5
MENU_NORMAL_CONTOUR_INDEX = 11
MENU_FOCUS_INK_INDEX = 12
MENU_FOCUS_CONTOUR_INDEX = 4

ID_EFFECT_SHARED_TAIL_TOP = 0x0C7
ID_EFFECT_SHARED_TAIL_BOTTOM = 0x0CE
ID_EFFECT_RESOURCE40_TAIL_TOP = 0x173
ID_EFFECT_RESOURCE40_TAIL_BOTTOM = 0x178
ID_EFFECT_EDGE_TOP = 0x0C8
ID_EFFECT_EDGE_BOTTOM = 0x0CF


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def lzss_decompress(payload: bytes) -> bytes:
    ring = bytearray(4096)
    ring_pos = 4078
    out = bytearray()
    src = 0
    flags = 0
    while src < len(payload):
        flags >>= 1
        if (flags & 0x100) == 0:
            flags = payload[src] | 0xFF00
            src += 1
            if src > len(payload):
                break
        if flags & 1:
            gate(src < len(payload), "literal overruns compressed stream")
            value = payload[src]
            src += 1
            out.append(value)
            ring[ring_pos] = value
            ring_pos = (ring_pos + 1) & 0xFFF
        else:
            gate(src + 1 < len(payload), "back-reference overruns compressed stream")
            lo = payload[src]
            hi = payload[src + 1]
            src += 2
            offset = lo | ((hi & 0xF0) << 4)
            length = (hi & 0x0F) + 3
            for index in range(length):
                value = ring[(offset + index) & 0xFFF]
                out.append(value)
                ring[ring_pos] = value
                ring_pos = (ring_pos + 1) & 0xFFF
    return bytes(out)


def literal_only_compress(decoded: bytes) -> bytes:
    body = bytearray()
    for start in range(0, len(decoded), 8):
        chunk = decoded[start : start + 8]
        body.append((1 << len(chunk)) - 1)
        body.extend(chunk)
    gate(len(body) <= 0xFFFF, "compressed body exceeds decoder's 16-bit length")
    return struct.pack("<I", 0x80000000 | len(body)) + bytes(body)


def decode_tile(atlas: bytes | bytearray, tile_id: int) -> list[list[int]]:
    start = tile_id * 32
    gate(start + 32 <= len(atlas), f"tile 0x{tile_id:03X} outside atlas")
    tile = [[0] * 8 for _ in range(8)]
    raw = atlas[start : start + 32]
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            tile[y][x] = (value >> (4 * (x & 1))) & 0x0F
    return tile


def encode_tile(atlas: bytearray, tile_id: int, tile: list[list[int]]) -> None:
    start = tile_id * 32
    gate(start + 32 <= len(atlas), f"tile 0x{tile_id:03X} outside atlas")
    raw = bytearray(32)
    for y in range(8):
        for x in range(8):
            raw[y * 4 + x // 2] |= (tile[y][x] & 0x0F) << (4 * (x & 1))
    atlas[start : start + 32] = raw


def render_label(
    text: str,
    width: int,
    height: int,
    font: fontpair.BdfFont,
    background_tile: list[list[int]],
    glyph_mode: str = "12x12",
) -> tuple[list[list[int]], list[list[bool]], list[list[bool]]]: 
    # Measured from the original atlas: label cells are NOT transparent.  They
    # are derived from generic panel tile 0x012.  Its scanlines are the native
    # red/orange/yellow/pale-yellow panel background.  Palette index 0 is pink
    # on this screen, which explains the v2 magenta rectangle.
    gate(height == 16, f"status label height must remain native 16px: {text}={height}")
    # A complete status row is 16 px high.  Tile 0x012 is its upper 8 px;
    # the lower half is the vertical mirror.  This yields the measured native
    # scanline profile 6,9,A,Bx10,A,9,6 with no artificial separator at y=8.
    background_strip = background_tile + list(reversed(background_tile))
    pixels = [
        [background_strip[y][x % 8] for x in range(width)]
        for y in range(height)
    ]
    if glyph_mode == "8x16":
        glyphs = [fontpair.render_condensed_8x16_basic(char, font) for char in text]
        cell_width, cell_height = 8, 16
    else:
        gate(glyph_mode == "12x12", f"unsupported status glyph mode: {glyph_mode}")
        glyphs = [fontpair.render_12x12_basic(char, font) for char in text]
        cell_width, cell_height = 12, 12
    ink_width = cell_width * len(glyphs)
    gate(ink_width <= width, f"status label exceeds native box: {text} {ink_width}>{width}")
    x0 = (width - ink_width) // 2
    y0 = (height - cell_height) // 2
    ink_mask = [[False] * width for _ in range(height)]

    for index, glyph in enumerate(glyphs):
        for y in range(cell_height):
            for x in range(cell_width):
                if not glyph.getpixel((x, y)):
                    continue
                px = x0 + index * cell_width + x
                py = y0 + y
                if 0 <= px < width and 0 <= py < height:
                    ink_mask[py][px] = True

    # Match the original Japanese label style: a one-pixel contour wraps the
    # glyph on every side.  This is an 8-neighbour dilation, not a lower-right
    # drop shadow.
    outline_mask = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if not ink_mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ox, oy = x + dx, y + dy
                    if 0 <= ox < width and 0 <= oy < height and not ink_mask[oy][ox]:
                        outline_mask[oy][ox] = True

    for y in range(height):
        for x in range(width):
            if outline_mask[y][x]:
                pixels[y][x] = OUTLINE_INDEX
    for y in range(height):
        for x in range(width):
            if ink_mask[y][x]:
                pixels[y][x] = INK_INDEX

    used = {value for row in pixels for value in row}
    template_used = {value for row in background_tile for value in row}
    gate(used <= template_used | {INK_INDEX, OUTLINE_INDEX}, f"unexpected palette index in {text}: {sorted(used)}")
    return pixels, ink_mask, outline_mask


def apply_label(
    atlas: bytearray,
    text: str,
    spec: dict,
    font: fontpair.BdfFont,
    background_tile: list[list[int]],
) -> dict:
    tile_rows = spec["tiles"]
    cols, rows = spec["box"]
    gate(len(tile_rows) == rows and all(len(row) == cols for row in tile_rows), f"tile shape mismatch: {text}")
    glyph_mode = str(spec.get("glyph_mode") or "12x12")
    pixels, ink_mask, outline_mask = render_label(
        text, cols * 8, rows * 8, font, background_tile, glyph_mode
    )
    background_pixels = 0
    for y in range(rows * 8):
        for x in range(cols * 8):
            if not ink_mask[y][x] and not outline_mask[y][x]:
                background_pixels += 1
                gate(
                    pixels[y][x] == (background_tile + list(reversed(background_tile)))[y][x % 8],
                    f"background template drift in {text} at {x},{y}",
                )
    gate(background_pixels > 0, f"label has no preserved background pixels: {text}")
    changed = []
    for ty in range(rows):
        for tx in range(cols):
            tile_id = tile_rows[ty][tx]
            tile = [row[tx * 8 : (tx + 1) * 8] for row in pixels[ty * 8 : (ty + 1) * 8]]
            before = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            encode_tile(atlas, tile_id, tile)
            after = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            changed.append({
                "tile_id": f"0x{tile_id:03X}",
                "changed_bytes": sum(a != b for a, b in zip(before, after)),
                "before_sha256": sha256(before),
                "after_sha256": sha256(after),
            })
    return {
        "text": text,
        "size_pixels": [cols * 8, rows * 8],
        "glyph_mode": glyph_mode,
        "background_template_tile": f"0x{BACKGROUND_TEMPLATE_TILE:03X}",
        "background_pixels_preserved": background_pixels,
        "ink_pixels": sum(sum(1 for value in row if value) for row in ink_mask),
        "outline_pixels": sum(sum(1 for value in row if value) for row in outline_mask),
        "outline_style": "8-neighbour 1px full contour",
        "tiles": changed,
    }


def clear_id_effect_residual_tail(
    atlas: bytearray,
    clean_atlas: bytes,
    background_tile: list[list[int]],
) -> dict:
    """Remove the measured right-edge residue of the original `ID効果` glyph.

    The first four 8x16 cells (0x0C3..0x0C6 / 0x0CA..0x0CD) contain the main
    label body and are already replaced by `ID효과`.  The final Japanese glyph
    extends into one extra cell.  resource[40] uses 0x173/0x178 for that cell;
    resources[16..19] use the left five pixels of 0x0C7/0x0CE, whose right three
    pixels are the native panel edge.  Clear only the glyph-bearing part and
    preserve the edge pixels byte-for-byte.
    """
    top_bg = background_tile
    bottom_bg = list(reversed(background_tile))

    clean_shared_top = decode_tile(clean_atlas, ID_EFFECT_SHARED_TAIL_TOP)
    clean_shared_bottom = decode_tile(clean_atlas, ID_EFFECT_SHARED_TAIL_BOTTOM)
    clean_r40_top = decode_tile(clean_atlas, ID_EFFECT_RESOURCE40_TAIL_TOP)
    clean_r40_bottom = decode_tile(clean_atlas, ID_EFFECT_RESOURCE40_TAIL_BOTTOM)
    edge_top_before = bytes(
        atlas[ID_EFFECT_EDGE_TOP * 32 : ID_EFFECT_EDGE_TOP * 32 + 32]
    )
    edge_bottom_before = bytes(
        atlas[ID_EFFECT_EDGE_BOTTOM * 32 : ID_EFFECT_EDGE_BOTTOM * 32 + 32]
    )

    # Measured structural proof: the Japanese tail in the shared and resource40
    # variants is identical in columns 0..4.  resource40 has plain panel
    # background in columns 5..7, while the shared variant substitutes its own
    # panel-edge geometry there.
    for y in range(8):
        for x in range(5):
            gate(
                clean_shared_top[y][x] == clean_r40_top[y][x],
                f"ID effect top-tail structure drift at {x},{y}",
            )
            gate(
                clean_shared_bottom[y][x] == clean_r40_bottom[y][x],
                f"ID effect bottom-tail structure drift at {x},{y}",
            )
        for x in range(5, 8):
            gate(
                clean_r40_top[y][x] == top_bg[y][x],
                f"resource40 ID effect top-tail background drift at {x},{y}",
            )
            gate(
                clean_r40_bottom[y][x] == bottom_bg[y][x],
                f"resource40 ID effect bottom-tail background drift at {x},{y}",
            )

    # resource[40]: the entire extra cell is label tail on ordinary panel
    # background, so restore it to the native background template.
    encode_tile(atlas, ID_EFFECT_RESOURCE40_TAIL_TOP, top_bg)
    encode_tile(atlas, ID_EFFECT_RESOURCE40_TAIL_BOTTOM, bottom_bg)

    # resources[16..19]: clear only the left five glyph-bearing pixels and keep
    # the three right-edge pixels exactly as the original asset encoded them.
    patched_shared_top = [row[:] for row in clean_shared_top]
    patched_shared_bottom = [row[:] for row in clean_shared_bottom]
    for y in range(8):
        for x in range(5):
            patched_shared_top[y][x] = top_bg[y][x]
            patched_shared_bottom[y][x] = bottom_bg[y][x]
    encode_tile(atlas, ID_EFFECT_SHARED_TAIL_TOP, patched_shared_top)
    encode_tile(atlas, ID_EFFECT_SHARED_TAIL_BOTTOM, patched_shared_bottom)

    gate(
        bytes(atlas[ID_EFFECT_EDGE_TOP * 32 : ID_EFFECT_EDGE_TOP * 32 + 32])
        == edge_top_before,
        "ID effect top edge tile changed unexpectedly",
    )
    gate(
        bytes(atlas[ID_EFFECT_EDGE_BOTTOM * 32 : ID_EFFECT_EDGE_BOTTOM * 32 + 32])
        == edge_bottom_before,
        "ID effect bottom edge tile changed unexpectedly",
    )

    return {
        "source_label": "ID効果",
        "korean_label": "ID효과",
        "main_body_tiles": [
            ["0x0C3", "0x0C4", "0x0C5", "0x0C6"],
            ["0x0CA", "0x0CB", "0x0CC", "0x0CD"],
        ],
        "resource40_tail_tiles_cleared": ["0x173", "0x178"],
        "shared_tail_tiles_partial_clear": ["0x0C7", "0x0CE"],
        "shared_tail_clear_columns": [0, 4],
        "shared_edge_columns_preserved": [5, 7],
        "edge_tiles_preserved": ["0x0C8", "0x0CF"],
        "resource40_tail_restored_to_native_background": True,
        "shared_panel_edge_preserved": True,
    }


def render_galmuri7_badge(char: str, font: fontpair.BdfFont) -> Image.Image:
    """Render one native Galmuri7 glyph into the unchanged 8x16 badge cell.

    Galmuri7 Korean BBX is 7x7, so unlike the v9 Galmuri9 pass there is no
    horizontal resize at all.  This avoids the `공 -> 긍`-like distortion that
    came from forcing 9px-wide Galmuri9 glyphs into an 8px tile column.
    """
    glyph = font.glyphs.get(ord(char))
    gate(glyph is not None, f"Galmuri7 glyph missing: {char}")
    gate(glyph.height == 7 and glyph.width in (6, 7), f"unexpected Galmuri7 BBX for {char}: {glyph.width}x{glyph.height}")
    native = font.render(char, glyph.width, glyph.height)
    canvas = Image.new("1", (8, 16), 0)
    canvas.paste(native, ((8 - native.width) // 2, (16 - native.height) // 2))
    return canvas


def apply_interval_badge(atlas: bytearray, font: fontpair.BdfFont) -> dict:
    """Replace the 16x16 間 badge with a native green-background `간` badge.

    v9 kept the original resource[53] dark interior, which measured in-game as
    a black-filled block rather than a glyph contour.  v10 rebuilds only this
    16x16 badge from the measured native green category background, then draws
    a native 7x7 Galmuri7 `간` with palette-4 contour and palette-15 ink.
    """
    spec = INTERVAL_BADGE
    tiles = spec["tiles"]
    gate(len(INTERVAL_NATIVE_GREEN_BACKGROUND) == 16 and all(len(row) == 16 for row in INTERVAL_NATIVE_GREEN_BACKGROUND), "interval native green template shape mismatch")
    # Rebuild only this 16x16 badge from the measured native-green pattern.
    # This removes the v9 full black interior while preserving the same palette
    # family, frame geometry, 4bpp format and 2x2 resource dimensions.
    pixels = [[int(ch, 16) for ch in row] for row in INTERVAL_NATIVE_GREEN_BACKGROUND]

    glyph_info = font.glyphs.get(ord(spec["text"]))
    gate(glyph_info is not None, "Galmuri7 glyph missing: 간")
    gate((glyph_info.width, glyph_info.height) == (7, 7), f"unexpected Galmuri7 BBX for 간: {glyph_info.width}x{glyph_info.height}")
    glyph = font.render(spec["text"], glyph_info.width, glyph_info.height)
    x0 = (16 - glyph.width) // 2
    y0 = (16 - glyph.height) // 2
    ink_mask = [[False] * 16 for _ in range(16)]
    for y in range(glyph.height):
        for x in range(glyph.width):
            if glyph.getpixel((x, y)):
                ink_mask[y0 + y][x0 + x] = True

    contour_mask = [[False] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            if not ink_mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ox, oy = x + dx, y + dy
                    if 0 <= ox < 16 and 0 <= oy < 16 and not ink_mask[oy][ox]:
                        contour_mask[oy][ox] = True
    for y in range(16):
        for x in range(16):
            if contour_mask[y][x]:
                pixels[y][x] = INTERVAL_SHADOW_INDEX
    for y in range(16):
        for x in range(16):
            if ink_mask[y][x]:
                pixels[y][x] = INTERVAL_INK_INDEX

    ink_pixels = sum(sum(1 for value in row if value) for row in ink_mask)
    contour_pixels = sum(sum(1 for value in row if value) for row in contour_mask)

    changed = []
    for ty in range(2):
        for tx in range(2):
            tile_id = tiles[ty][tx]
            before = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            tile = [row[tx * 8 : (tx + 1) * 8] for row in pixels[ty * 8 : (ty + 1) * 8]]
            encode_tile(atlas, tile_id, tile)
            after = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            changed.append({
                "tile_id": f"0x{tile_id:03X}",
                "changed_bytes": sum(a != b for a, b in zip(before, after)),
                "before_sha256": sha256(before),
                "after_sha256": sha256(after),
            })
    return {
        "text": spec["text"],
        "source": spec["source"],
        "resource_index": spec["resource_index"],
        "size_pixels": [16, 16],
        "glyph_mode": "Galmuri7 native 7x7 centered with 1px contour",
        "ink_pixels": ink_pixels,
        "contour_pixels": contour_pixels,
        "background_template": "native green 16x16 category badge",
        "background_black_fill_removed": True,
        "shadow_palette_index": INTERVAL_SHADOW_INDEX,
        "ink_palette_index": INTERVAL_INK_INDEX,
        "tiles": changed,
    }


def apply_weapon_badge(
    atlas: bytearray,
    text: str,
    spec: dict,
    font: fontpair.BdfFont,
) -> dict:
    """Erase one fixed Japanese mini-badge glyph and paint Korean in-place.

    The resource[36..39] weapon rows use green 8x16/16x16 badges.  Their glyph
    pixels are the D/E/F palette tones; the badge interior itself is palette 4.
    Border/gradient pixels stay untouched.  We therefore clear only D/E/F and
    then draw the Korean glyph with the same native high-tone palette family.
    """
    tile_rows = spec["tiles"]
    cols, rows = spec["box"]
    gate(rows == 2, f"weapon badge must be 16px high: {text}")
    gate(len(tile_rows) == rows and all(len(row) == cols for row in tile_rows), f"weapon badge tile shape mismatch: {text}")

    width, height = cols * 8, 16
    pixels = [[0] * width for _ in range(height)]
    source_glyph_mask = [[False] * width for _ in range(height)]
    for ty in range(rows):
        for tx in range(cols):
            tile = decode_tile(atlas, tile_rows[ty][tx])
            for py in range(8):
                for px in range(8):
                    x, y = tx * 8 + px, ty * 8 + py
                    value = tile[py][px]
                    pixels[y][x] = value
                    if value in WEAPON_BADGE_SOURCE_GLYPH_INDICES:
                        source_glyph_mask[y][x] = True

    source_glyph_pixels = sum(sum(1 for value in row if value) for row in source_glyph_mask)
    gate(source_glyph_pixels > 0, f"weapon badge source glyph mask missing: {text}")

    background_name = spec.get("background")
    gate(background_name in WEAPON_BADGE_BACKGROUNDS, f"weapon badge background template missing: {text}")
    template_rows = WEAPON_BADGE_BACKGROUNDS[background_name]
    gate(len(template_rows) == 16 and all(len(row) == 8 for row in template_rows), f"weapon badge template shape mismatch: {text}")
    background = [[int(ch, 16) for ch in row] for row in template_rows]
    # The Japanese glyph consists of a dark index-4 shadow plus D/E/F bright
    # pixels.  v7 cleared only D/E/F, which left the black Japanese shadow in
    # game.  Restore the measured native green badge background under the full
    # 4/D/E/F source-glyph footprint before drawing Korean.
    for y in range(height):
        for x in range(width):
            if source_glyph_mask[y][x]:
                pixels[y][x] = background[y][x % 8]

    glyphs = [render_galmuri7_badge(char, font) for char in text]
    gate(len(glyphs) * 8 <= width, f"weapon badge Korean text exceeds native box: {text}")
    x0 = (width - len(glyphs) * 8) // 2
    ink_mask = [[False] * width for _ in range(height)]
    for index, glyph in enumerate(glyphs):
        for y in range(16):
            for x in range(8):
                if glyph.getpixel((x, y)):
                    px = x0 + index * 8 + x
                    if 0 <= px < width:
                        ink_mask[y][px] = True

    contour_mask = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if not ink_mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ox, oy = x + dx, y + dy
                    if 0 <= ox < width and 0 <= oy < height and not ink_mask[oy][ox]:
                        contour_mask[oy][ox] = True

    for y in range(height):
        for x in range(width):
            if contour_mask[y][x]:
                pixels[y][x] = WEAPON_BADGE_SHADOW_INDEX
    for y in range(height):
        for x in range(width):
            if ink_mask[y][x]:
                pixels[y][x] = WEAPON_BADGE_INK_INDEX

    changed = []
    for ty in range(rows):
        for tx in range(cols):
            tile_id = tile_rows[ty][tx]
            before = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            tile = [row[tx * 8 : (tx + 1) * 8] for row in pixels[ty * 8 : (ty + 1) * 8]]
            encode_tile(atlas, tile_id, tile)
            after = bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
            changed.append({
                "tile_id": f"0x{tile_id:03X}",
                "changed_bytes": sum(a != b for a, b in zip(before, after)),
                "before_sha256": sha256(before),
                "after_sha256": sha256(after),
            })

    return {
        "text": text,
        "source": spec.get("source"),
        "role": spec.get("role"),
        "size_pixels": [width, height],
        "glyph_mode": "Galmuri7 native 7x7 centered in 8x16",
        "source_glyph_pixels_cleared": source_glyph_pixels,
        "ink_pixels": sum(sum(1 for value in row if value) for row in ink_mask),
        "contour_pixels": sum(sum(1 for value in row if value) for row in contour_mask),
        "background_template": background_name,
        "shadow_palette_index": WEAPON_BADGE_SHADOW_INDEX,
        "ink_palette_index": WEAPON_BADGE_INK_INDEX,
        "tiles": changed,
    }


def build_preview(atlas: bytes, labels: list[tuple[str, dict]], out: Path) -> None:
    scale = 3
    padding = 8
    widths = [spec["box"][0] * 8 for _, spec in labels]
    canvas_w = max(widths) * scale + padding * 2
    canvas_h = sum(spec["box"][1] * 8 * scale + 22 for _, spec in labels) + padding
    image = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    y_cursor = padding
    # Approximate screen colours only for the PNG preview.  The ROM patch does
    # not alter palette data; these values mirror the measured status-screen
    # palette closely enough to inspect shape/background placement.
    palette = {
        4: (20, 45, 35, 255),
        5: (116, 57, 1, 255),
        6: (239, 41, 15, 255),
        9: (255, 181, 40, 255),
        10: (251, 229, 59, 255),
        11: (255, 255, 141, 255),
        13: (80, 115, 80, 255),
        14: (210, 235, 210, 255),
        15: (255, 255, 255, 255),
    }
    for text, spec in labels:
        cols, rows = spec["box"]
        for ty in range(rows):
            for tx in range(cols):
                tile = decode_tile(atlas, spec["tiles"][ty][tx])
                for py in range(8):
                    for px in range(8):
                        rgb = palette.get(tile[py][px], (80, 80, 80, 255))
                        gx = padding + (tx * 8 + px) * scale
                        gy = y_cursor + (ty * 8 + py) * scale
                        for sy in range(scale):
                            for sx in range(scale):
                                image.putpixel((gx + sx, gy + sy), rgb)
        y_cursor += rows * 8 * scale + 22
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", type=Path, default=MAIN_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    args = parser.parse_args()

    jp = JP_ROM.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "clean Japanese ROM hash mismatch")
    main_rom = args.main.read_bytes()
    gate(len(main_rom) == 32 * 1024 * 1024, "base main ROM must be 32 MiB")

    header = struct.unpack_from("<I", jp, ATLAS_RESOURCE)[0]
    gate(header & 0x80000000, "UI atlas is not compressed")
    compressed_length = header & 0xFFFF
    original_compressed = jp[ATLAS_RESOURCE + 4 : ATLAS_RESOURCE + 4 + compressed_length]
    decoded = lzss_decompress(original_compressed)
    gate(len(decoded) == ATLAS_EXPECTED_DECODED, f"decoded atlas size drift: {len(decoded)}")
    atlas = bytearray(decoded)
    background_tile = decode_tile(decoded, BACKGROUND_TEMPLATE_TILE)
    expected_background_tile = (
        [[6] * 8]
        + [[9] * 8]
        + [[10] * 8]
        + [[11] * 8 for _ in range(5)]
    )
    gate(
        background_tile == expected_background_tile,
        f"status background template tile 0x{BACKGROUND_TEMPLATE_TILE:03X} drift",
    )

    # Every atlas tile is referenced by at least one resource.  In particular,
    # 0x1F3..0x1FA belong to resource[64] and must not be repurposed as scratch
    # tiles.  Preserve that resource byte-for-byte in this follow-up.
    resource64_tiles_before = bytes(atlas[0x1F3 * 32 : 0x1FB * 32])

    with ZipFile(args.font_zip) as archive:
        font12 = fontpair.load_bdf(archive, "Galmuri11.bdf")
        font8 = fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf")
        font7 = fontpair.load_bdf(archive, "Galmuri7.bdf")

    label_reports = []
    for text, spec in PILOT_LABELS.items():
        label_reports.append(apply_label(atlas, text, spec, font12, background_tile))

    # 運動/移動 share three source tiles.  Their Korean replacements share the
    # same second syllable 동, so keep the original map and verify the shared
    # tile payload stays byte-identical when 이동 is painted after 운동.
    for text in ("운동", "장갑", "한계"):
        label_reports.append(apply_label(atlas, text, UNIT_LABELS[text], font12, background_tile))
    shared_motion_after_undong = {
        tile_id: bytes(atlas[tile_id * 32 : tile_id * 32 + 32])
        for tile_id in SHARED_MOTION_TILES
    }
    label_reports.append(apply_label(atlas, "이동", UNIT_LABELS["이동"], font12, background_tile))
    for tile_id, expected in shared_motion_after_undong.items():
        gate(
            bytes(atlas[tile_id * 32 : tile_id * 32 + 32]) == expected,
            f"운동/이동 shared 동 tile diverged: 0x{tile_id:03X}",
        )

    for text, spec in TYPE_LABELS.items():
        label_reports.append(apply_label(atlas, text, spec, font12, background_tile))
    for text, spec in LOWER_STATUS_LABELS.items():
        face = font8 if spec.get("glyph_mode") == "8x16" else font12
        label_reports.append(apply_label(atlas, text, spec, face, background_tile))
    id_effect_tail_cleanup = clear_id_effect_residual_tail(
        atlas, decoded, background_tile
    )

    weapon_badge_reports = []
    for text, spec in WEAPON_BADGE_LABELS.items():
        weapon_badge_reports.append(apply_weapon_badge(atlas, text, spec, font7))
    interval_badge_report = apply_interval_badge(atlas, font7)

    gate(
        bytes(atlas[0x1F3 * 32 : 0x1FB * 32]) == resource64_tiles_before,
        "resource[64] tiles 0x1F3..0x1FA were modified",
    )

    rebuilt_resource = literal_only_compress(bytes(atlas))
    rebuilt_decoded = lzss_decompress(rebuilt_resource[4:])
    gate(rebuilt_decoded == bytes(atlas), "rebuilt compressed atlas round-trip mismatch")

    candidate = bytearray(main_rom)
    original_pointer = struct.unpack_from("<I", candidate, RESOURCE_TABLE)[0]
    gate(
        original_pointer in {0x080DC848, GRAPHICS_ADDRESS},
        f"resource table[0] pointer drift: 0x{original_pointer:08X}",
    )
    if original_pointer == 0x080DC848:
        gate(
            candidate[GRAPHICS_ALLOC : GRAPHICS_ALLOC + len(rebuilt_resource)] == bytes(len(rebuilt_resource)),
            "graphics allocation is not empty in unpatched base main",
        )
    candidate[GRAPHICS_ALLOC : GRAPHICS_ALLOC + len(rebuilt_resource)] = rebuilt_resource
    struct.pack_into("<I", candidate, RESOURCE_TABLE, GRAPHICS_ADDRESS)

    # Hard constraints requested by the user.
    gate(len(atlas) == len(decoded), "decoded atlas size changed")
    gate(candidate[UNIT_MAP : UNIT_MAP + 1284] == main_rom[UNIT_MAP : UNIT_MAP + 1284], "unit tilemap changed")
    gate(candidate[0x000E0288:0x000E0294] == main_rom[0x000E0288:0x000E0294], "nearby resource table data changed unexpectedly")
    # Palette and tilemaps are not patched.  The only original-half change is
    # resource_table[0], redirecting the atlas to the rebuilt graphics blob.
    allowed = set(range(RESOURCE_TABLE, RESOURCE_TABLE + 4))
    unexpected = [i for i in range(0x01000000) if candidate[i] != main_rom[i] and i not in allowed]
    gate(not unexpected, f"unexpected original-half changes: {unexpected[:8]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    labels_for_preview = (
        list(PILOT_LABELS.items())
        + list(UNIT_LABELS.items())
        + list(TYPE_LABELS.items())
        + list(LOWER_STATUS_LABELS.items())
        + list(WEAPON_BADGE_LABELS.items())
        + [(INTERVAL_BADGE["text"], INTERVAL_BADGE)]
    )
    build_preview(bytes(atlas), labels_for_preview, args.preview)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_ui_tile_overlay_poc",
        "result": "PASS",
        "source_main": {"path": str(args.main.relative_to(ROOT)), "sha256": sha256(main_rom), "size": len(main_rom)},
        "output": {"path": str(args.out.relative_to(ROOT)), "sha256": sha256(candidate), "size": len(candidate)},
        "constraints": {
            "decoded_atlas_size_before": len(decoded),
            "decoded_atlas_size_after": len(atlas),
            "tile_format": "GBA 4bpp 8x8",
            "palette_modified": False,
            "background_template_tile": f"0x{BACKGROUND_TEMPLATE_TILE:03X}",
            "background_template_rows_16px": [
                "66666666",
                "99999999",
                "AAAAAAAA",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "BBBBBBBB",
                "AAAAAAAA",
                "99999999",
                "66666666",
            ],
            "ink_palette_index": INK_INDEX,
            "outline_palette_index": OUTLINE_INDEX,
            "palette_zero_used_for_background": False,
            "background_outside_glyph_outline_preserved_from_native_template": True,
            "outline_style": "8-neighbour 1px full contour",
            "label_boxes_only": True,
            "resource_dimensions_changed": False,
        },
        "atlas": {
            "original_resource_file_offset": f"0x{ATLAS_RESOURCE:08X}",
            "original_compressed_length": compressed_length,
            "decoded_size": len(decoded),
            "rebuilt_resource_file_offset": f"0x{GRAPHICS_ALLOC:08X}",
            "rebuilt_resource_address": f"0x{GRAPHICS_ADDRESS:08X}",
            "rebuilt_compressed_length": len(rebuilt_resource) - 4,
            "decoded_sha256_before": sha256(decoded),
            "decoded_sha256_after": sha256(atlas),
            "round_trip_verified": True,
        },
        "labels": label_reports,
        "weapon_badges": weapon_badge_reports,
        "interval_badge": interval_badge_report,
        "id_effect_tail_cleanup": id_effect_tail_cleanup,
        "tilemap_remap": [],
        "shared_tile_policy": {
            "運動_移動_shared_tiles": [f"0x{tile_id:03X}" for tile_id in SHARED_MOTION_TILES],
            "korean_shared_component": "동",
            "shared_payload_verified_identical": True,
            "resource64_tiles_0x1F3_0x1FA_preserved": True,
        },
        "weapon_row_followup": {
            "source_resources": [36, 37, 38, 39],
            "row_tilemap_offsets": ["0x000DFA8C", "0x000DFB10", "0x000DFC14", "0x000DFD98"],
            "translations": {"実": "실", "攻": "공", "命": "명", "弾": "탄", "射単": "사단", "近単": "근단", "射全": "사전", "近全": "근전", "間": "간"},
            "small_badge_font": "Galmuri7.bdf (native 7x7 centered in unchanged 8x16 cell; no horizontal resize)",
            "interval_badge": {"resource": 53, "tiles": ["0x1E7", "0x1E8", "0x1E9", "0x1EA"], "font": "Galmuri7 native 7x7", "placement": "centered in original 16x16 box with 1px contour", "background": "native green category badge template; no full black fill"},
            "fixed_columns": {
                "attack": {"x": 15, "tiles": ["0x164", "0x16B"]},
                "hit": {"x": 21, "tiles": ["0x165", "0x16C"]},
                "ammo": {"x": 25, "tiles": ["0x166", "0x16D"]},
                "category_overlay": {"resources": [54, 55, 56, 57], "tiles": ["射=0x168/0x16E", "近=0x1ED/0x1EE", "単=0x1EB/0x1EC", "全=0x169/0x16F"]},
            },
            "dynamic_type_badge": {
                "resource_48": "実 -> 실 (8x16 source-font shape score 0.774)",
                "resource_49": "alternate/beam badge preserved pending exact semantic audit",
                "resource_50": "alternate badge preserved pending exact semantic audit",
                "resource_54": "射単 -> 사단",
                "resource_55": "近単 -> 근단",
                "resource_56": "射全 -> 사전",
                "resource_57": "近全 -> 근전"
            },
            "policy": "small badges: restore full Japanese 4/D/E/F footprint, draw native Galmuri7 with palette 15 ink + palette 4 contour; interval badge: remove the v9 black fill, rebuild the measured native green 16x16 background, and overlay centered Galmuri7 간 with contour only",
        },
        "lower_status_followup": {
            "source_resource_index": 40,
            "source_resource_file_offset": "0x000DFF9C",
            "translations": {"ID効果": "ID효과", "攻撃": "공격", "命中": "명중", "回避": "회피", "残り回数": "남은횟수"},
            "ID効果_shared_resource_indices": [16, 17, 18, 19, 40],
        },
        "preview": str(args.preview.relative_to(ROOT)),
        "verification": {
            "result": "PASS",
            "original_half_allowed_change_bytes": len(allowed),
            "original_half_unexpected_change_bytes": 0,
            "resource_pointer_redirected": True,
            "palette_untouched": True,
            "tilemaps_untouched": True,
            "decoded_size_unchanged": True,
            "compression_round_trip": True,
            "native_background_template_verified": True,
            "palette_zero_not_used_in_generated_labels": True,
            "full_contour_outline_verified": True,
            "shared_motion_tiles_verified": True,
            "resource64_preserved": True,
            "id_effect_resource40_tail_cleared": True,
            "id_effect_shared_tail_partial_clear_verified": True,
            "id_effect_shared_edge_tiles_preserved": True,
            "weapon_badges_translated": len(weapon_badge_reports),
            "weapon_badge_font_galmuri7": True,
            "interval_badge_translated": interval_badge_report["text"] == "간",
            "weapon_badge_tilemaps_untouched": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": sha256(candidate),
        "manifest": str(args.manifest),
        "preview": str(args.preview),
        "decoded_size": len(atlas),
        "palette_modified": False,
        "labels": len(label_reports),
        "weapon_badges": len(weapon_badge_reports),
        "interval_badge": interval_badge_report["text"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
