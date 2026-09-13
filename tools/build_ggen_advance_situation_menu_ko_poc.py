#!/usr/bin/env python3
"""Build a situation-menu Korean POC from the approved main TIP.

Scope:
- repaint the dedicated red/yellow fixed graphics: ターン数 / 艦 / 自軍 / 敵軍 / 友軍
  as 턴 수 / 함 / 아군 / 적군 / 우군 using native Galmuri11 12x12,
- translate every stage victory/defeat condition pair selected by 0x08012408,
  i.e. all 38 fallback blobs plus 18 flag-gated override blobs,
- preserve MS, all unrelated atlas tiles, map dimensions, palettes, selector code,
  and the existing approved Korean font allocation.

The rebuilt situation atlas is relocated to 0x01260000 (graphics region).  The
translated condition-pair blobs are allocated at 0x01230000 (inside the
reserved 0x01040000..0x01240000 text region).  Both ranges are required to be
zero-filled in the input main TIP before writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_ROM
import analyze_ggen_advance_situation_menu_ui as situation
import analyze_stage_condition_text as stage_conditions
import build_ggen_advance_ko_poc as fontops
import build_ggen_advance_map_menu_ui_ko_poc as menu_graphics
import build_ggen_advance_unified_rom_poc as unified
import ggen_advance_text_codec as text_codec
import test_ggen_advance_font_pair as fontpair

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_situation_menu" / "ggen_advance_situation_menu_ko_followup_candidate_20260830.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_situation_menu_ko_followup_20260830.json"
PREVIEW = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_situation_menu" / "ggen_advance_situation_menu_fixed_labels_followup_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "973f4a6fd94b27a08835ee309624a5dd87a43b03ce0bcbca453e9e3291c1ffe1"
EXPECTED_JP_SHA256 = situation.EXPECTED_JP_SHA256
ROM_BASE = 0x08000000
GRAPHICS_ALLOC = 0x01260000
CONDITION_ALLOC = 0x01230000
CONDITION_LIMIT = 0x01240000
FACE_INDEX = 0x0B
CONTOUR_INDEX = 0x04

# Clear only the Japanese glyph footprint zone.  Boundary pixels are sampled
# from immediately outside the zone on each scanline, retaining the native
# vertical frame/gradient while removing both bright text and dark contour.
CLEAR_ZONES = {
    "turn_count": (13, 61),
    "ship_count": (5, 20),
    "player_force": (5, 32),
    "enemy_force": (5, 32),
    "friend_force": (5, 32),
}
FORCE_LABEL_ROLES = frozenset({"player_force", "enemy_force", "friend_force"})
CONDITION_ANCHORS = (":", "전", "멸", "키", "라")

# Fully decoded condition-line vocabulary.  These values are deliberately
# concise because 0x08000CA0 advances 12 pixels per 12x12 glyph and the screen
# draws from x=8 to a 240px-wide surface.  Every Korean line is gated to <=19
# display characters.
LINE_TRANSLATIONS = {
    "勝利条件：敵軍全滅": "승리조건:적군 전멸",
    "勝利条件：敵軍全滅または6ターン経過": "승리조건:적군 전멸 또는 6턴 경과",
    "勝利条件：敵母艦の誘導または撃破": "승리조건:적 모함 유도 또는 격파",
    "勝利条件：アークエンジェルの脱出": "승리조건:아크엔젤 탈출",
    "勝利条件：アプサラスⅢ撃破": "승리조건:아프사라스 3 격파",
    "勝利条件：敵軍、第３軍全滅": "승리조건:적군 제3군 전멸",
    "勝利条件：ディアナ女王救出": "승리조건:디아나 여왕 구출",
    "勝利条件：レビル将軍救出": "승리조건:레빌 장군 구출",
    "勝利条件：ソーラ・システム照射阻止": "승리조건:솔라 시스템 조사 저지",
    "勝利条件：リーブラ撃破": "승리조건:리브라 격파",
    "勝利条件：ニムバス撃破": "승리조건:님버스 격파",
    "勝利条件：ギニアス撃破": "승리조건:기니어스 격파",
    "勝利条件：バスク撃破またはターン経過": "승리조건:바스크 격파 또는 턴 경과",
    "敗北条件：キラ撃破": "패배조건:키라 격파",
    "敗北条件：キラ撃破、ナタル撃破": "패배조건:키라 격파,나탈 격파",
    "敗北条件：マリュー撃破、キラ撃破": "패배조건:마류 격파,키라 격파",
    "敗北条件：ホワイトベースが発見される": "패배조건:화이트 베이스 발각",
    "敗北条件：ブライト撃破": "패배조건:브라이트 격파",
    "敗北条件：マリュー撃破": "패배조건:마류 격파",
    "敗北条件：コウ撃破、シナプス撃破": "패배조건:코우 격파,시냅스 격파",
    "敗北条件：シナプス撃破": "패배조건:시냅스 격파",
    "敗北条件：ヒイロ撃破": "패배조건:히이로 격파",
    "敗北条件：マリュー撃破、シナプス撃破": "패배조건:마류 격파,시냅스 격파",
    "敗北条件：マリュー撃破、レイン撃破": "패배조건:마류 격파,레인 격파",
    "敗北条件：マリュー撃破、阻止失敗": "패배조건:마류 격파,저지 실패",
    "敗北条件：ハマーン撃破": "패배조건:하만 격파",
    "敗北条件：自軍全滅": "패배조건:아군 전멸",
    "敗北条件：マリュー撃破、ブライト撃破": "패배조건:마류 격파,브라이트 격파",
    "敗北条件：ユウ撃破": "패배조건:유우 격파",
    "敗北条件：自軍全滅またはマリュー撃破": "패배조건:아군 전멸 또는 마류 격파",
    "敗北条件：母艦撃破": "패배조건:모함 격파",
    "敗北条件：アムロ撃破、マリュー撃破": "패배조건:아무로 격파,마류 격파",
    "敗北条件：アムロ撃破": "패배조건:아무로 격파",
    "敗北条件：ユウ撃破、モーリン撃破": "패배조건:유우 격파,모린 격파",
    "敗北条件：ハマーン撃破、マリュー撃破": "패배조건:하만 격파,마류 격파",
}

SOURCE_NORMALIZATION = {
    # The current forensic 12x12 map aliases this one slot to 壁 in this
    # specific line, while the scenario corpus and game context independently
    # establish ディアナ女王.  Normalize only this exact phrase.
    "勝利条件：ディアナ壁王救出": "勝利条件：ディアナ女王救出",
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def pack_u32(value: int) -> bytes:
    return struct.pack("<I", value)


def parse_map(data: bytes | bytearray, offset: int, expected: tuple[int, int]) -> tuple[int, int, list[int]]:
    width, height = data[offset], data[offset + 1]
    gate((width, height) == expected, f"map dimensions drift at 0x{offset:08X}")
    cells = list(struct.unpack_from(f"<{width*height}H", data, offset + 4))
    return width, height, cells


def map_rect(cells: list[int], map_width: int, x: int, y: int, width: int, height: int) -> list[list[int]]:
    return [[cells[(y + yy) * map_width + x + xx] & 0x03FF for xx in range(width)] for yy in range(height)]


def stitch_rect(atlas: bytes | bytearray, tile_rows: list[list[int]]) -> list[list[int]]:
    height = len(tile_rows) * 8
    width = len(tile_rows[0]) * 8
    pixels = [[0] * width for _ in range(height)]
    for ty, row in enumerate(tile_rows):
        for tx, tile_id in enumerate(row):
            tile = menu_graphics.decode_tile(atlas, tile_id)
            for yy in range(8):
                pixels[ty * 8 + yy][tx * 8 : tx * 8 + 8] = tile[yy]
    return pixels


def clear_native_text(pixels: list[list[int]], role: str) -> tuple[list[list[int]], int]:
    """Legacy scanline clear retained for the already-approved 턴 수 / 함 labels."""
    x0, x1 = CLEAR_ZONES[role]
    width = len(pixels[0])
    gate(0 < x0 < x1 < width, f"clear zone outside box for {role}")
    out = [row[:] for row in pixels]
    changed = 0
    left_sample = x0 - 1
    right_sample = x1
    midpoint = (x0 + x1) // 2
    for y, row in enumerate(out):
        left = row[left_sample]
        right = row[right_sample]
        for x in range(x0, x1):
            value = left if x < midpoint else right
            if row[x] != value:
                changed += 1
            row[x] = value
    gate(changed > 0, f"no native text/background pixels cleared for {role}")
    return out, changed


def source_glyph_footprint(
    pixels: list[list[int]],
    role: str,
    source_text: str,
    jp: bytes,
    source_char_to_slot: dict[str, int],
) -> tuple[set[tuple[int, int]], dict[str, Any]]:
    """Recover only the original Japanese glyph+outline footprint.

    The force labels contain real highlight/background pixels inside the old
    rectangular clear zone.  Clearing that whole rectangle flattened those
    pixels to palette index 2.  The fixed labels were authored from the native
    12x12 source glyphs, so use those bitmaps as a geometry mask and preserve
    everything outside the one-pixel glyph contour.
    """
    height = len(pixels)
    width = len(pixels[0])
    x0, x1 = CLEAR_ZONES[role]
    text_width = len(source_text) * 12
    expected_x = x0 + ((x1 - x0) - text_width) // 2
    glyphs: list[Image.Image] = []
    for char in source_text:
        gate(char in source_char_to_slot, f"source 12x12 glyph slot missing for {char!r}")
        slot = source_char_to_slot[char]
        start = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
        raw = jp[start : start + fontops.FONT_12X12_STRIDE]
        gate(len(raw) == fontops.FONT_12X12_STRIDE, f"source 12x12 glyph truncated for {char!r}")
        glyphs.append(fontops.unpack_12x12(raw))

    best: tuple[tuple[float, int, int, int], int, int, set[tuple[int, int]]] | None = None
    for y_origin in range(0, 5):
        for x_origin in range(max(0, expected_x - 3), min(width - text_width, expected_x + 3) + 1):
            core: set[tuple[int, int]] = set()
            for index, glyph in enumerate(glyphs):
                gx0 = x_origin + index * 12
                for gy in range(12):
                    py = y_origin + gy
                    if not 0 <= py < height:
                        continue
                    for gx in range(12):
                        if glyph.getpixel((gx, gy)):
                            core.add((gx0 + gx, py))
            gate(core, f"empty source glyph footprint for {source_text}")
            matching = sum(pixels[y][x] in {FACE_INDEX, CONTOUR_INDEX} for x, y in core)
            face_hits = sum(pixels[y][x] == FACE_INDEX for x, y in core)
            ratio = matching / len(core)
            # Prefer the strongest palette match, then the visually centered
            # placement when multiple fixed-graphic positions tie.
            score = (ratio, face_hits, -abs(x_origin - expected_x), -abs(y_origin - 2))
            if best is None or score > best[0]:
                best = (score, x_origin, y_origin, core)

    gate(best is not None, f"source glyph footprint search failed for {role}")
    score, x_origin, y_origin, core = best
    gate(score[0] >= 0.98, f"source glyph footprint confidence too low for {role}: {score[0]:.3f}")

    contour: set[tuple[int, int]] = set()
    for x, y in core:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dx or dy):
                    continue
                ox, oy = x + dx, y + dy
                if x0 <= ox < x1 and 0 <= oy < height and (ox, oy) not in core:
                    contour.add((ox, oy))
    footprint = {(x, y) for x, y in core if x0 <= x < x1} | contour
    gate(footprint, f"empty source glyph+contour footprint for {role}")
    return footprint, {
        "source_glyph_origin_px": [x_origin, y_origin],
        "source_glyph_core_pixels": len(core),
        "source_glyph_outline_pixels": len(contour),
        "source_glyph_match_ratio": round(score[0], 6),
        "source_glyph_footprint_pixels": len(footprint),
    }


def clear_native_text_preserve_background(
    pixels: list[list[int]],
    role: str,
    source_text: str,
    jp: bytes,
    source_char_to_slot: dict[str, int],
) -> tuple[list[list[int]], int, set[tuple[int, int]], dict[str, Any]]:
    footprint, metadata = source_glyph_footprint(pixels, role, source_text, jp, source_char_to_slot)
    x0, x1 = CLEAR_ZONES[role]
    height = len(pixels)
    known = [
        (x, y)
        for y in range(height)
        for x in range(x0, x1)
        if (x, y) not in footprint
    ]
    gate(known, f"force-label background has no preserved samples for {role}")
    out = [row[:] for row in pixels]
    changed = 0
    for x, y in footprint:
        # Copy the nearest untouched native background/highlight pixel.  Same
        # scanline is preferred on equal distance so horizontal plaque bands
        # remain intact instead of being replaced by a flat contour color.
        sx, sy = min(
            known,
            key=lambda p: (
                abs(p[0] - x) + abs(p[1] - y),
                abs(p[1] - y),
                abs(p[0] - x),
            ),
        )
        value = pixels[sy][sx]
        if out[y][x] != value:
            changed += 1
        out[y][x] = value
    gate(changed > 0, f"no Japanese force-label glyph pixels repaired for {role}")
    metadata.update({
        "clear_mode": "source_glyph_footprint_nearest_native_background",
        "native_background_pixels_preserved": len(pixels) * len(pixels[0]) - len(footprint),
        "native_pixels_reconstructed": changed,
    })
    return out, changed, footprint, metadata


def render_korean_label(
    background: list[list[int]],
    text: str,
    font: fontpair.BdfFont,
    role: str,
) -> tuple[list[list[int]], int, int, set[tuple[int, int]], set[tuple[int, int]]]:
    height = len(background)
    width = len(background[0])
    gate(height == 16, f"label height drift for {role}")
    parts: list[tuple[Image.Image | None, int]] = []
    for char in text:
        if char == " ":
            parts.append((None, 4))
        else:
            glyph = fontpair.render_12x12_basic(char, font)
            parts.append((glyph, 12))
    text_width = sum(part_width for _glyph, part_width in parts)
    x0, x1 = CLEAR_ZONES[role]
    gate(text_width + 2 <= x1 - x0, f"Korean label does not fit clear zone: {text}")
    x_cursor = x0 + ((x1 - x0) - text_width) // 2
    y_origin = 2
    mask = [[False] * width for _ in range(height)]
    for glyph, part_width in parts:
        if glyph is not None:
            for y in range(12):
                for x in range(12):
                    if glyph.getpixel((x, y)):
                        mask[y_origin + y][x_cursor + x] = True
        x_cursor += part_width

    contour = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if not mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ox, oy = x + dx, y + dy
                    if (dx or dy) and 0 <= ox < width and 0 <= oy < height and not mask[oy][ox]:
                        contour[oy][ox] = True
    ink_positions = {(x, y) for y in range(height) for x in range(width) if mask[y][x]}
    contour_positions = {(x, y) for y in range(height) for x in range(width) if contour[y][x]}
    gate(not (ink_positions & contour_positions), f"Korean face/contour overlap for {role}")
    for y in range(height):
        for x in range(width):
            if contour[y][x]:
                background[y][x] = CONTOUR_INDEX
            if mask[y][x]:
                background[y][x] = FACE_INDEX
    return background, len(ink_positions), len(contour_positions), ink_positions, contour_positions


def split_box_to_new_tiles(atlas: bytearray, pixels: list[list[int]]) -> tuple[list[list[int]], int]:
    rows = len(pixels) // 8
    cols = len(pixels[0]) // 8
    gate(rows == 2, "situation labels must be two tiles high")
    first = len(atlas) // 32
    ids: list[list[int]] = []
    for ty in range(rows):
        row_ids: list[int] = []
        for tx in range(cols):
            tile = [pixels[ty * 8 + yy][tx * 8 : tx * 8 + 8] for yy in range(8)]
            row_ids.append(len(atlas) // 32)
            atlas.extend(menu_graphics.encode_tile(tile))
        ids.append(row_ids)
    return ids, first


def patch_map_rect(candidate: bytearray, map_offset: int, expected: tuple[int, int], x: int, y: int, new_ids: list[list[int]]) -> int:
    width, height, cells = parse_map(candidate, map_offset, expected)
    changed = 0
    for yy, row in enumerate(new_ids):
        for xx, tile_id in enumerate(row):
            gate(tile_id < 0x400, f"tile id exceeds 10-bit map field: {tile_id}")
            index = (y + yy) * width + x + xx
            original = cells[index]
            replacement = (original & ~0x03FF) | tile_id
            if original != replacement:
                changed += 1
            cells[index] = replacement
    struct.pack_into(f"<{width*height}H", candidate, map_offset + 4, *cells)
    return changed


def load_japanese_charmap() -> dict[int, str]:
    path = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[int, str] = {}
    for obj in payload.values():
        if not isinstance(obj, dict):
            continue
        for key, value in obj.items():
            if isinstance(key, str) and key.startswith("0x") and isinstance(value, str):
                result[int(key, 16)] = value
    gate(len(result) >= 1200, f"12x12 Japanese charmap unexpectedly small: {len(result)}")
    return result


def active_font12_location(main_bytes: bytes | bytearray) -> tuple[int, int]:
    address = u32(main_bytes, unified.FONT12_LITERAL_FILE)
    offset = address - ROM_BASE
    size = fontops.FONT_12X12_COUNT * fontops.FONT_12X12_STRIDE
    gate(0 <= offset <= len(main_bytes) - size, f"active 12x12 font outside ROM: 0x{address:08X}")
    return address, offset


def recover_active_hangul_slots(
    main_bytes: bytes,
    font_offset: int,
    font: fontpair.BdfFont,
    chars: set[str],
) -> dict[str, int]:
    """Recover the promoted main TIP's real Hangul slot map from painted glyphs.

    Re-running the mutable apply-charmap allocator after later analysis changes
    is not authoritative for an already-promoted ROM.  Exact raster matching
    against the active relocated font makes the encoder follow what the game
    will actually draw.
    """
    by_glyph: dict[bytes, list[int]] = {}
    for slot in range(fontops.FONT_12X12_COUNT):
        start = font_offset + slot * fontops.FONT_12X12_STRIDE
        raw = bytes(main_bytes[start : start + fontops.FONT_12X12_STRIDE])
        by_glyph.setdefault(raw, []).append(slot)
    result: dict[str, int] = {}
    for char in sorted(chars):
        packed = fontops.pack_12x12(fontpair.render_12x12_basic(char, font))
        hits = by_glyph.get(packed, [])
        gate(len(hits) == 1, f"active 12x12 glyph slot is not unique for {char!r}: {hits}")
        result[char] = hits[0]
    return result


def patch_condition_colon_glyph(
    candidate: bytearray,
    main_bytes: bytes,
    jp: bytes,
    records: list[dict[str, Any]],
    plan: dict[str, Any],
    verified12: dict[str, int],
    jp_charmap: dict[int, str],
    font_offset: int,
    font: fontpair.BdfFont,
) -> tuple[int, int, dict[str, Any]]:
    """Install ':' in one audited-free active 12x12 slot.

    The reviewed Japanese ':' resolves to full-width ： at slot 0x00E3, but the
    promoted Korean font currently paints 값 there.  Do not restore 0x00E3 in
    place because existing Korean text may legitimately use 값.  Instead use a
    slot that is unchanged from JP, not live in remaining 12x12 Japanese text,
    and not one of the already-painted Korean slots.
    """
    native_colon_slot = unified.verified_slot_for(":", verified12)
    gate(native_colon_slot is not None, "reviewed 12x12 colon slot is missing")
    native_start = fontops.FONT_12X12_BASE + native_colon_slot * fontops.FONT_12X12_STRIDE
    native_colon = jp[native_start : native_start + fontops.FONT_12X12_STRIDE]
    gate(len(native_colon) == fontops.FONT_12X12_STRIDE, "native colon glyph truncated")
    active_native_start = font_offset + native_colon_slot * fontops.FONT_12X12_STRIDE
    active_native = bytes(main_bytes[active_native_start : active_native_start + fontops.FONT_12X12_STRIDE])
    gate(active_native != native_colon, "active colon slot is unexpectedly still native; override slot no longer needed")
    value_glyph = fontops.pack_12x12(fontpair.render_12x12_basic("값", font))
    gate(active_native == value_glyph, "active 0x00E3 conflict no longer matches 값")

    _live8, live12 = unified.collect_live_slots(jp, records)
    compatibility_only = {int(slot, 16) for slot in plan["slot_domain"]["compatibility_only_slots"]}
    domain = (
        set(range(unified.SLOT_MIN, unified.SLOT_MAX + 1))
        - unified.RESERVED_GLYPH_SLOTS
        - compatibility_only
        - unified.SPECIAL_SLOTS
    )
    painted: set[int] = set()
    for slot in range(fontops.FONT_12X12_COUNT):
        active_start = font_offset + slot * fontops.FONT_12X12_STRIDE
        original_start = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
        if main_bytes[active_start : active_start + fontops.FONT_12X12_STRIDE] != jp[original_start : original_start + fontops.FONT_12X12_STRIDE]:
            painted.add(slot)
    safe = sorted(domain - live12 - painted, reverse=True)
    ideograph_safe = [
        slot
        for slot in safe
        if len(jp_charmap.get(slot, "")) == 1 and 0x4E00 <= ord(jp_charmap[slot]) <= 0x9FFF
    ]
    gate(ideograph_safe, "no audited-free 12x12 ideograph slot available for colon")
    slot = ideograph_safe[0]
    target_start = font_offset + slot * fontops.FONT_12X12_STRIDE
    original_start = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
    gate(
        main_bytes[target_start : target_start + fontops.FONT_12X12_STRIDE]
        == jp[original_start : original_start + fontops.FONT_12X12_STRIDE],
        f"selected colon slot 0x{slot:04X} is not pristine",
    )
    candidate[target_start : target_start + fontops.FONT_12X12_STRIDE] = native_colon
    gate(
        candidate[target_start : target_start + fontops.FONT_12X12_STRIDE] == native_colon,
        "condition colon glyph patch failed",
    )
    return slot, target_start, {
        "native_reviewed_slot": f"0x{native_colon_slot:04X}",
        "native_reviewed_token": f"0x{0xDF20 + native_colon_slot:04X}",
        "native_slot_active_glyph": "값",
        "override_slot": f"0x{slot:04X}",
        "override_token": f"0x{0xDF20 + slot:04X}",
        "override_file_offset": f"0x{target_start:08X}",
        "replaced_unused_native_char": jp_charmap.get(slot, ""),
        "audited_safe_slot_count": len(safe),
        "remaining_japanese_12x12_slots": len(live12),
        "already_painted_12x12_slots": len(painted),
    }


def condition_char_to_slot(
    chars: set[str],
    hangul_slots: dict[str, int],
    verified12: dict[str, int],
) -> dict[str, int]:
    result: dict[str, int] = {" ": 0x0001}
    for char in sorted(chars):
        if char == " ":
            continue
        if "가" <= char <= "힣":
            gate(char in hangul_slots, f"condition Hangul slot missing for {char!r}")
            result[char] = hangul_slots[char]
            continue
        slot = unified.verified_slot_for(char, verified12)
        gate(slot is not None, f"condition compatibility slot missing for {char!r}")
        result[char] = slot
    return result


def decode_runtime_condition_line(
    data: bytes | bytearray,
    address: int,
    dictionary: list[list[int]],
    slot_to_char: dict[int, str],
) -> tuple[str, list[int]]:
    offset = address - ROM_BASE
    tokens, _raw = text_codec.read_tokens_strict(data, offset)
    slots = text_codec.expand_to_slots(tokens, dictionary)
    decoded = "".join(slot_to_char.get(slot, f"<{slot:04X}>") for slot in slots)
    return decoded, slots


def decode_pair_lines(jp: bytes, pointer: int, charmap: dict[int, str], dictionary: list[list[int]]) -> tuple[str, str]:
    parsed = stage_conditions.parse_pair(jp, pointer)
    def decode_at(address: str) -> str:
        offset = int(address, 16) - ROM_BASE
        tokens, _raw = text_codec.read_tokens_strict(jp, offset)
        slots = text_codec.expand_to_slots(tokens, dictionary)
        return "".join(charmap.get(slot, f"<{slot:04X}>") for slot in slots)
    return decode_at(str(parsed["line1_address"])), decode_at(str(parsed["line2_address"]))


def normalized_source(value: str) -> str:
    return SOURCE_NORMALIZATION.get(value, value)


def encode_condition_line(value: str, mapping12: dict[str, int], verified12: dict[str, int]) -> bytes:
    gate(len(value) <= 19, f"12x12 condition line exceeds 19 cells: {len(value)} {value}")
    encoded, missing = unified.encode_korean_text(value, mapping12, verified_charmap=verified12, strict_punctuation=True)
    gate(encoded is not None and not missing, f"condition encoding failed: {value} missing={missing}")
    gate(encoded.endswith(b"\x00"), "condition encoder did not append NUL")
    body = encoded[:-1]
    gate(len(body) <= 0xFF, f"condition byte length exceeds prefix: {value}")
    return body


def build_pair_blob(victory: str, defeat: str, mapping12: dict[str, int], verified12: dict[str, int]) -> bytes:
    a = encode_condition_line(victory, mapping12, verified12)
    b = encode_condition_line(defeat, mapping12, verified12)
    return bytes((len(a),)) + a + b"\x00" + bytes((len(b),)) + b + b"\x00"


def build_preview(original_boxes: list[tuple[str, list[list[int]]]], patched_boxes: list[tuple[str, list[list[int]]]], path: Path) -> None:
    # Symbolic palette: readability of the glyph/frame edit matters more than
    # reproducing runtime palette-bank RGB in this static audit image.
    palette = {
        0: (0, 0, 0), 1: (20, 40, 20), 2: (20, 70, 45), 3: (40, 95, 55),
        4: (125, 35, 30), 5: (165, 90, 45), 6: (190, 120, 55), 7: (215, 145, 65),
        8: (230, 165, 75), 9: (240, 185, 85), 10: (250, 205, 100), 11: (255, 230, 115),
        12: (245, 120, 80), 13: (245, 145, 85), 14: (250, 190, 100), 15: (255, 245, 155),
    }
    max_width = max(len(p[0]) for _name, p in original_boxes + patched_boxes)
    scale = 4
    gap = 8
    row_height = 16 * scale
    image = Image.new("RGB", (max_width * scale, (len(original_boxes) * 2) * row_height + (len(original_boxes) - 1) * gap), (0, 0, 0))
    y_cursor = 0
    for index in range(len(original_boxes)):
        for collection in (original_boxes, patched_boxes):
            _name, pixels = collection[index]
            tile = Image.new("RGB", (len(pixels[0]), len(pixels)))
            for y, row in enumerate(pixels):
                for x, value in enumerate(row):
                    tile.putpixel((x, y), palette[value])
            image.paste(tile.resize((tile.width * scale, tile.height * scale), Image.Resampling.NEAREST), (0, y_cursor))
            y_cursor += row_height
        if index + 1 < len(original_boxes):
            y_cursor += gap
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--preview", type=Path, default=PREVIEW)
    args = parser.parse_args()

    main_bytes = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(len(main_bytes) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    gate(sha256(main_bytes) == EXPECTED_MAIN_SHA256, f"main TIP SHA-256 drift: {sha256(main_bytes)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM SHA-256 drift: {sha256(jp)}")
    gate(u32(main_bytes, situation.RESOURCE_TABLE) == ROM_BASE + situation.ATLAS_RESOURCE, "situation atlas pointer already redirected")
    for i, expected in enumerate((0x080E59FC, 0, 0x080E6150, 0x080E6604, 0x080E664C)):
        gate(u32(main_bytes, situation.RESOURCE_TABLE + i * 4) == expected, f"situation resource table drift at field {i}")

    header = u32(jp, situation.ATLAS_RESOURCE)
    compressed_length = header & 0xFFFF
    original_atlas = menu_graphics.lzss_decompress(jp[situation.ATLAS_RESOURCE + 4 : situation.ATLAS_RESOURCE + 4 + compressed_length])
    gate(len(original_atlas) == situation.ATLAS_DECODED, "situation atlas decoded size drift")
    atlas = bytearray(original_atlas)

    base_w, base_h, base_cells = parse_map(jp, situation.BASE_MAP, (30, 20))
    friend_w, friend_h, friend_cells = parse_map(jp, situation.FRIEND_OVERLAY_MAP, (11, 3))
    maps = {
        situation.BASE_MAP: (base_w, base_h, base_cells),
        situation.FRIEND_OVERLAY_MAP: (friend_w, friend_h, friend_cells),
    }

    with ZipFile(args.font_zip) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    jp_charmap = load_japanese_charmap()
    source_char_to_slot = {char: slot for slot, char in jp_charmap.items() if len(char) == 1}
    candidate = bytearray(main_bytes)
    original_boxes: list[tuple[str, list[list[int]]]] = []
    patched_boxes: list[tuple[str, list[list[int]]]] = []
    graphic_reports: list[dict[str, Any]] = []
    total_map_cells_changed = 0

    for spec in situation.LABELS:
        map_offset = int(spec["map"])
        map_w, map_h, cells = maps[map_offset]
        x, y = spec["xy"]
        width, height = spec["size"]
        role = str(spec["role"])
        source_ids = map_rect(cells, map_w, x, y, width, height)
        source_pixels = stitch_rect(original_atlas, source_ids)
        source_footprint: set[tuple[int, int]] = set()
        if role in FORCE_LABEL_ROLES:
            clean, cleared, source_footprint, clear_metadata = clear_native_text_preserve_background(
                source_pixels,
                role,
                str(spec["source"]),
                jp,
                source_char_to_slot,
            )
        else:
            clean, cleared = clear_native_text(source_pixels, role)
            clear_metadata = {
                "clear_mode": "legacy_scanline_clear_approved_in_previous_candidate",
                "native_pixels_reconstructed": cleared,
            }
        patched_pixels, ink_pixels, contour_pixels, ink_positions, contour_positions = render_korean_label(
            clean,
            str(spec["ko"]),
            font,
            role,
        )
        if role in FORCE_LABEL_ROLES:
            allowed_pixel_changes = source_footprint | ink_positions | contour_positions
            escaped_changes = [
                (px, py)
                for py in range(len(source_pixels))
                for px in range(len(source_pixels[0]))
                if source_pixels[py][px] != patched_pixels[py][px] and (px, py) not in allowed_pixel_changes
            ]
            gate(not escaped_changes, f"force-label background changed outside glyph regions for {role}: {escaped_changes[:8]}")
            clear_metadata.update({
                "original_pixels_unchanged_outside_source_or_korean_glyph_regions": True,
                "outside_glyph_region_changed_pixels": 0,
                "korean_contour_max_distance_px": 1,
            })
        new_ids, first_tile = split_box_to_new_tiles(atlas, patched_pixels)
        changed_cells = patch_map_rect(candidate, map_offset, (map_w, map_h), x, y, new_ids)
        gate(changed_cells == width * height, f"not every target map cell remapped: {spec['source']}")
        total_map_cells_changed += changed_cells
        original_boxes.append((str(spec["source"]), source_pixels))
        patched_boxes.append((str(spec["ko"]), patched_pixels))
        graphic_reports.append({
            "source": spec["source"],
            "translation": spec["ko"],
            "role": spec["role"],
            "map_file_offset": f"0x{map_offset:08X}",
            "map_xy_tiles": [x, y],
            "size_tiles": [width, height],
            "source_tile_ids": [[f"0x{value:03X}" for value in row] for row in source_ids],
            "new_tile_first": f"0x{first_tile:03X}",
            "new_tile_ids": [[f"0x{value:03X}" for value in row] for row in new_ids],
            **clear_metadata,
            "korean_ink_pixels": ink_pixels,
            "korean_contour_pixels": contour_pixels,
            "font": "Galmuri11.bdf native 12x12",
            "face_index": FACE_INDEX,
            "contour_index": CONTOUR_INDEX,
        })

    gate(len(atlas) // 32 == 202, f"rebuilt situation atlas tile count drift: {len(atlas)//32}")
    rebuilt_resource = menu_graphics.literal_only_compress(bytes(atlas))
    gate(GRAPHICS_ALLOC + len(rebuilt_resource) < CONDITION_LIMIT + 0x400000, "rebuilt situation atlas exceeds graphics region")
    gate(candidate[GRAPHICS_ALLOC : GRAPHICS_ALLOC + len(rebuilt_resource)] == b"\x00" * len(rebuilt_resource), "situation graphics allocation is not zero-filled")
    candidate[GRAPHICS_ALLOC : GRAPHICS_ALLOC + len(rebuilt_resource)] = rebuilt_resource
    candidate[situation.RESOURCE_TABLE : situation.RESOURCE_TABLE + 4] = pack_u32(ROM_BASE + GRAPHICS_ALLOC)

    # The promoted main TIP is the runtime authority for 12x12 Hangul slots.
    # Re-running build_apply_charmap after later allocator/protection changes
    # caused exactly the observed 멸->릭 and 라->땐 drift, so recover slots by
    # exact raster match against the active relocated font instead.
    merged = json.loads((ADVANCE_ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json").read_text(encoding="utf-8"))
    records = list(merged["records"])
    plan = json.loads(unified.PLAN_PATH.read_text(encoding="utf-8"))
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    active_font_address, active_font_offset = active_font12_location(main_bytes)
    condition_chars = {char for text in LINE_TRANSLATIONS.values() for char in text}
    condition_hangul = {char for char in condition_chars if "가" <= char <= "힣"}
    mapping12 = recover_active_hangul_slots(main_bytes, active_font_offset, font, condition_hangul)
    colon_slot, colon_patch_offset, colon_report = patch_condition_colon_glyph(
        candidate,
        main_bytes,
        jp,
        records,
        plan,
        verified12,
        jp_charmap,
        active_font_offset,
        font,
    )
    condition_verified12 = dict(verified12)
    condition_verified12[":"] = colon_slot
    condition_verified12["："] = colon_slot
    runtime_char_slots = condition_char_to_slot(condition_chars, mapping12, condition_verified12)
    runtime_slot_chars: dict[int, str] = {}
    for char, slot in runtime_char_slots.items():
        previous = runtime_slot_chars.get(slot)
        gate(previous is None or previous == char, f"condition runtime slot collision: {previous!r}/{char!r} -> 0x{slot:04X}")
        runtime_slot_chars[slot] = char

    # Compatibility glyphs other than the newly installed colon must still be
    # byte-identical to the clean Japanese font in the active Korean font.
    for char, slot in runtime_char_slots.items():
        if char == " " or char == ":" or "가" <= char <= "힣":
            continue
        active_start = active_font_offset + slot * fontops.FONT_12X12_STRIDE
        original_start = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
        gate(
            main_bytes[active_start : active_start + fontops.FONT_12X12_STRIDE]
            == jp[original_start : original_start + fontops.FONT_12X12_STRIDE],
            f"condition compatibility glyph was repainted for {char!r} at 0x{slot:04X}",
        )

    dictionary12 = text_codec.load_dictionary(jp, text_codec.DICT_12X12_BASE, text_codec.DICT_12X12_END)
    fallback_pointers = {u32(jp, stage_conditions.SEARCH_DB + i * stage_conditions.SEARCH_STRIDE + stage_conditions.PAIR_FIELD) for i in range(stage_conditions.SEARCH_RECORDS)}
    override_pointers = {u32(jp, offset) for offset in stage_conditions.OVERRIDE_LITERAL_OFFSETS}
    source_pointers = sorted(fallback_pointers | override_pointers)
    gate(len(source_pointers) == 56, "condition source pointer count drift")

    cursor = CONDITION_ALLOC
    pointer_map: dict[int, int] = {}
    pair_reports: list[dict[str, Any]] = []
    translated_lines: set[str] = set()
    for pointer in source_pointers:
        source_victory, source_defeat = decode_pair_lines(jp, pointer, jp_charmap, dictionary12)
        normalized_victory = normalized_source(source_victory)
        normalized_defeat = normalized_source(source_defeat)
        gate(normalized_victory in LINE_TRANSLATIONS, f"missing victory translation: {source_victory}")
        gate(normalized_defeat in LINE_TRANSLATIONS, f"missing defeat translation: {source_defeat}")
        victory = LINE_TRANSLATIONS[normalized_victory]
        defeat = LINE_TRANSLATIONS[normalized_defeat]
        blob = build_pair_blob(victory, defeat, mapping12, condition_verified12)
        cursor = (cursor + 3) & ~3
        gate(cursor + len(blob) <= CONDITION_LIMIT, "condition text allocation overflow")
        gate(candidate[cursor : cursor + len(blob)] == b"\x00" * len(blob), f"condition allocation not zero-filled at 0x{cursor:08X}")
        candidate[cursor : cursor + len(blob)] = blob
        new_address = ROM_BASE + cursor
        pointer_map[pointer] = new_address
        parsed_new = stage_conditions.parse_pair(bytes(candidate), new_address)
        decoded_victory, victory_slots = decode_runtime_condition_line(
            candidate,
            int(str(parsed_new["line1_address"]), 16),
            dictionary12,
            runtime_slot_chars,
        )
        decoded_defeat, defeat_slots = decode_runtime_condition_line(
            candidate,
            int(str(parsed_new["line2_address"]), 16),
            dictionary12,
            runtime_slot_chars,
        )
        gate(decoded_victory == victory, f"runtime slot decode mismatch: {decoded_victory!r} != {victory!r}")
        gate(decoded_defeat == defeat, f"runtime slot decode mismatch: {decoded_defeat!r} != {defeat!r}")
        pair_reports.append({
            "source_pair_address": f"0x{pointer:08X}",
            "new_pair_address": f"0x{new_address:08X}",
            "source_victory": source_victory,
            "source_defeat": source_defeat,
            "translation_victory": victory,
            "translation_defeat": defeat,
            "runtime_decoded_victory": decoded_victory,
            "runtime_decoded_defeat": decoded_defeat,
            "runtime_decode_verified": True,
            "victory_slot_count": len(victory_slots),
            "defeat_slot_count": len(defeat_slots),
            "blob_bytes": len(blob),
            "victory_cells": len(victory),
            "defeat_cells": len(defeat),
        })
        translated_lines.update((victory, defeat))
        cursor += len(blob)

    # Redirect every fallback owner in the 64-record DB and every literal used
    # by the 18 override branches.  Do not patch the selector or renderer code.
    fallback_fields_patched = 0
    for index in range(stage_conditions.SEARCH_RECORDS):
        field = stage_conditions.SEARCH_DB + index * stage_conditions.SEARCH_STRIDE + stage_conditions.PAIR_FIELD
        old = u32(jp, field)
        gate(old in pointer_map, f"fallback pair missing from pointer map: 0x{old:08X}")
        current_pointer = u32(main_bytes, field)
        gate(ROM_BASE <= current_pointer < ROM_BASE + len(main_bytes), f"main fallback pointer outside ROM at record {index}: 0x{current_pointer:08X}")
        # The unified translation build has already relocated these still-Japanese
        # pair blobs into expansion space, so the approved main pointer is expected
        # to differ from the clean JP pointer.  Ownership is preserved by record
        # index; this POC replaces that relocated pending copy with the reviewed KO pair.
        candidate[field : field + 4] = pack_u32(pointer_map[old])
        fallback_fields_patched += 1

    override_literals_patched = 0
    for field in stage_conditions.OVERRIDE_LITERAL_OFFSETS:
        old = u32(jp, field)
        gate(old in pointer_map, f"override pair missing from pointer map: 0x{old:08X}")
        current_pointer = u32(main_bytes, field)
        gate(ROM_BASE <= current_pointer < ROM_BASE + len(main_bytes), f"main override pointer outside ROM at 0x{field:08X}: 0x{current_pointer:08X}")
        candidate[field : field + 4] = pack_u32(pointer_map[old])
        override_literals_patched += 1

    # Static decode/length validation of every new pair.
    for old_pointer, new_pointer in pointer_map.items():
        parsed = stage_conditions.parse_pair(bytes(candidate), new_pointer)
        gate(int(parsed["line1_length"]) <= 0xFF and int(parsed["line2_length"]) <= 0xFF, f"new pair length invalid for 0x{old_pointer:08X}")
    gate(len(pair_reports) == 56 and all(bool(row["runtime_decode_verified"]) for row in pair_reports), "not all 56 condition pairs passed runtime-slot decode")

    anchor_reports: list[dict[str, Any]] = []
    for char in CONDITION_ANCHORS:
        slot = runtime_char_slots[char]
        start = active_font_offset + slot * fontops.FONT_12X12_STRIDE
        painted = bytes(candidate[start : start + fontops.FONT_12X12_STRIDE])
        if char == ":":
            native_colon_slot = unified.verified_slot_for(":", verified12)
            gate(native_colon_slot is not None, "colon audit lost reviewed native slot")
            expected_start = fontops.FONT_12X12_BASE + native_colon_slot * fontops.FONT_12X12_STRIDE
            expected_glyph = jp[expected_start : expected_start + fontops.FONT_12X12_STRIDE]
            paint_source = "native Japanese ： glyph copied to audited-free active slot"
        else:
            expected_glyph = fontops.pack_12x12(fontpair.render_12x12_basic(char, font))
            paint_source = "promoted main TIP Galmuri11 glyph recovered by exact raster match"
        gate(painted == expected_glyph, f"anchor painted glyph mismatch for {char!r} at 0x{slot:04X}")
        token = slot if slot <= 0xDF else 0xDF20 + slot
        anchor_reports.append({
            "char": char,
            "slot": f"0x{slot:04X}",
            "token": f"0x{token:02X}" if token <= 0xFF else f"0x{token:04X}",
            "paint_source": paint_source,
            "painted_glyph_exact_match": True,
        })

    font_size = fontops.FONT_12X12_COUNT * fontops.FONT_12X12_STRIDE
    font_changed_positions = [
        active_font_offset + index
        for index, (before, after) in enumerate(
            zip(
                main_bytes[active_font_offset : active_font_offset + font_size],
                candidate[active_font_offset : active_font_offset + font_size],
            )
        )
        if before != after
    ]
    gate(font_changed_positions, "condition colon patch did not change active 12x12 font")
    gate(
        all(colon_patch_offset <= pos < colon_patch_offset + fontops.FONT_12X12_STRIDE for pos in font_changed_positions),
        "active 12x12 font changed outside the audited colon override slot",
    )

    # Code and non-target resource-table fields remain exact.
    gate(candidate[0x0001C5E0:0x0001C764] == main_bytes[0x0001C5E0:0x0001C764], "situation screen Thumb code changed")
    gate(candidate[situation.RESOURCE_TABLE + 4 : situation.RESOURCE_TABLE + 20] == main_bytes[situation.RESOURCE_TABLE + 4 : situation.RESOURCE_TABLE + 20], "situation non-atlas table fields changed")
    gate(candidate[situation.EXTRA_OVERLAY_MAP : situation.EXTRA_OVERLAY_MAP + 4 + 7 * 3 * 2] == main_bytes[situation.EXTRA_OVERLAY_MAP : situation.EXTRA_OVERLAY_MAP + 4 + 7 * 3 * 2], "extra overlay map changed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    build_preview(original_boxes, patched_boxes, args.preview)

    changed = [i for i, (a, b) in enumerate(zip(main_bytes, candidate)) if a != b]
    allowed_ranges: list[tuple[int, int]] = [
        (GRAPHICS_ALLOC, GRAPHICS_ALLOC + len(rebuilt_resource)),
        (CONDITION_ALLOC, cursor),
        (colon_patch_offset, colon_patch_offset + fontops.FONT_12X12_STRIDE),
        (situation.RESOURCE_TABLE, situation.RESOURCE_TABLE + 4),
        (situation.BASE_MAP + 4, situation.BASE_MAP + 4 + 30 * 20 * 2),
        (situation.FRIEND_OVERLAY_MAP + 4, situation.FRIEND_OVERLAY_MAP + 4 + 11 * 3 * 2),
    ]
    for index in range(stage_conditions.SEARCH_RECORDS):
        field = stage_conditions.SEARCH_DB + index * stage_conditions.SEARCH_STRIDE + stage_conditions.PAIR_FIELD
        allowed_ranges.append((field, field + 4))
    for field in stage_conditions.OVERRIDE_LITERAL_OFFSETS:
        allowed_ranges.append((field, field + 4))
    gate(changed and all(any(start <= pos < end for start, end in allowed_ranges) for pos in changed), "changes escaped situation/condition patch scope")

    force_reports = [row for row in graphic_reports if row["role"] in FORCE_LABEL_ROLES]
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_situation_menu_ko_followup_poc",
        "result": "PASS",
        "source": {
            "main_path": str(args.main.relative_to(ADVANCE_ROOT)),
            "main_sha256": sha256(main_bytes),
            "japanese_sha256": sha256(jp),
            "static_analysis": "legacy/analysis/ggen_advance_situation_menu_ui_20260830.json",
        },
        "fixed_graphics": {
            "source_atlas": "0x080E59FC / 150 tiles",
            "relocated_atlas_file_offset": f"0x{GRAPHICS_ALLOC:08X}",
            "relocated_atlas_address": f"0x{ROM_BASE + GRAPHICS_ALLOC:08X}",
            "rebuilt_tiles": len(atlas) // 32,
            "rebuilt_resource_bytes": len(rebuilt_resource),
            "resource_table_pointer_field": f"0x{situation.RESOURCE_TABLE:08X}",
            "map_cells_remapped": total_map_cells_changed,
            "force_label_background_policy": "preserve original pixels outside the exact Japanese source glyph+1px contour footprint; repaint only Korean glyph+1px contour",
            "patches": graphic_reports,
            "preview": str(args.preview.relative_to(ADVANCE_ROOT)),
        },
        "conditions": {
            "allocation_file_offset": f"0x{CONDITION_ALLOC:08X}",
            "allocation_end_file_offset": f"0x{cursor:08X}",
            "active_12x12_font_address": f"0x{active_font_address:08X}",
            "active_12x12_font_file_offset": f"0x{active_font_offset:08X}",
            "slot_source_policy": "recover Hangul slots by exact Galmuri11 raster match against the promoted main TIP active 12x12 font; never recompute the historical apply-charmap for this candidate",
            "active_hangul_chars_recovered": len(mapping12),
            "runtime_char_slots_verified": len(runtime_char_slots),
            "colon_override": colon_report,
            "anchor_audit": anchor_reports,
            "unique_pair_blobs": len(pointer_map),
            "unique_translated_lines": len(translated_lines),
            "runtime_decode_pairs_verified": sum(bool(row["runtime_decode_verified"]) for row in pair_reports),
            "fallback_fields_patched": fallback_fields_patched,
            "override_literals_patched": override_literals_patched,
            "pairs": pair_reports,
            "translation_policy": "all 38 fallback + 18 override pairs; <=19 12x12 cells per line",
        },
        "output": {
            "path": str(args.out.relative_to(ADVANCE_ROOT)),
            "size": len(candidate),
            "sha256": sha256(candidate),
        },
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "five_fixed_labels_rebuilt": len(graphic_reports) == 5,
            "rebuilt_atlas_202_tiles": len(atlas) // 32 == 202,
            "MS_unchanged": True,
            "extra_overlay_map_unchanged": True,
            "all_56_condition_pairs_relocated": len(pointer_map) == 56,
            "all_64_fallback_fields_redirected": fallback_fields_patched == 64,
            "all_18_override_literals_redirected": override_literals_patched == 18,
            "all_56_condition_pairs_runtime_slot_decoded": len(pair_reports) == 56 and all(bool(row["runtime_decode_verified"]) for row in pair_reports),
            "condition_lines_fit_19_cells": all(row["victory_cells"] <= 19 and row["defeat_cells"] <= 19 for row in pair_reports),
            "condition_anchor_token_slot_glyph_match": len(anchor_reports) == len(CONDITION_ANCHORS) and all(bool(row["painted_glyph_exact_match"]) for row in anchor_reports),
            "force_label_background_preserved_outside_glyph_regions": len(force_reports) == 3 and all(bool(row.get("original_pixels_unchanged_outside_source_or_korean_glyph_regions")) for row in force_reports),
            "force_label_contour_confined_to_1px": len(force_reports) == 3 and all(int(row.get("korean_contour_max_distance_px", 0)) == 1 for row in force_reports),
            "situation_screen_code_unchanged": True,
            "active_Korean_Hangul_glyphs_unchanged": True,
            "active_12x12_font_change_confined_to_colon_override_slot": True,
            "active_12x12_font_changed_byte_count": len(font_changed_positions),
            "changes_confined_to_declared_ranges": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": report["output"]["sha256"],
        "changed_bytes": len(changed),
        "fixed_labels": len(graphic_reports),
        "condition_pairs": len(pointer_map),
        "condition_pointer_fields": fallback_fields_patched + override_literals_patched,
        "preview": str(args.preview),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
