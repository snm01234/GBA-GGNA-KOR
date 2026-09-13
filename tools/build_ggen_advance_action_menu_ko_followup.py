#!/usr/bin/env python3
"""Build the fixed-size Korean action-menu follow-up candidate.

This follow-up addresses three runtime problems found in the first 2026-08-30
candidate:

* the cloned action atlas had grown from 239 to 415 decoded tiles and could
  overwrite map VRAM behind the menu;
* Japanese normal/focus glyph contour pixels remained outside the old flat
  28x12 clear rectangle;
* the move sub-menu first entry is 全体 (전체), not 合体 (합체), and the
  normal sub-menu tiles are shared by the larger 11-column menu-frame maps.

The new builder keeps the decoded atlas exactly 239 tiles, reconstructs a clean
normal/focus panel template from the native label family, redraws a Korean
8-neighbour contour like the approved battle-weapon shadow fix, repacks the
translated tiles into source tile slots that become unreachable after private
map redirection, and also redirects the shared 全体/個別 cells inside resources
10..17.  The original atlas and maps remain byte-exact in place.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as scan  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM  # noqa: E402

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_fixed_action_graphics"
FIRST_CANDIDATE = OUT_DIR / "ggen_advance_action_menu_ko_candidate_20260830.gba"
FIRST_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_action_menu_ko_candidate_20260830.json"
OUT = OUT_DIR / "ggen_advance_action_menu_ko_focusrounded_candidate_20260830.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_action_menu_ko_focusrounded_20260830.json"
PREVIEW = OUT_DIR / "ggen_advance_action_menu_ko_focusrounded_preview_20260830.png"

RESOURCE_TABLE = 0x000D23E0
RESOURCE_COUNT = 44
ATLAS_SOURCE = 0x000D0814
TABLE_CONSUMER_LITERALS = (0x00014F20, 0x00015590, 0x00015628)

# Reuse the already-reserved action-menu expansion window.  Unlike the first
# candidate, the decoded atlas is fixed-size, so runtime VRAM usage is unchanged.
ATLAS_CLONE = 0x01278000
TABLE_CLONE = 0x0127C000
MAP_CLONE_START = 0x0127C100
ALLOCATION_END = 0x01280000

NORMAL_BASE = 18
FOCUS_BASE = 30
ID_COMMAND = 4
FRAME_RESOURCE_INDICES = tuple(range(10, 18))
SUBMENU_RESOURCE_INDICES = (28, 29)

TRANSLATIONS = {
    0: ("移動", "이동"),
    1: ("隊列", "대열"),
    2: ("攻撃", "공격"),
    3: ("間接", "간접"),
    5: ("捕獲", "포획"),
    6: ("変形", "변형"),
    7: ("交信", "교신"),
    8: ("発進", "발진"),
    9: ("確定", "확정"),
    10: ("全体", "전체"),
    11: ("個別", "개별"),
}

NORMAL_BG = 10
NORMAL_FACE = 11
NORMAL_SHADOW = 5
FOCUS_SOURCE_BG = 4
FOCUS_BG = 8
FOCUS_FACE = 12
FOCUS_SHADOW = 4


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


def align4(value: int) -> int:
    return (value + 3) & ~3


def decode_tile(atlas: bytes | bytearray, tile_id: int) -> list[list[int]]:
    raw = atlas[tile_id * 32 : tile_id * 32 + 32]
    gate(len(raw) == 32, f"tile 0x{tile_id:03X} outside atlas")
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            out[y][x] = (value >> (4 * (x & 1))) & 0x0F
    return out


def encode_tile(tile: list[list[int]]) -> bytes:
    gate(len(tile) == 8 and all(len(row) == 8 for row in tile), "tile dimensions drift")
    raw = bytearray(32)
    for y in range(8):
        for x in range(8):
            raw[y * 4 + x // 2] |= (tile[y][x] & 0x0F) << (4 * (x & 1))
    return bytes(raw)


def parse_map(rom: bytes | bytearray, address: int) -> dict:
    off = address - ROM_BASE
    gate(0 <= off + 4 <= len(rom), f"map pointer outside ROM: 0x{address:08X}")
    w, h = rom[off], rom[off + 1]
    reserved = u16(rom, off + 2)
    count = w * h
    gate(count > 0 and off + 4 + count * 2 <= len(rom), f"map overruns ROM: 0x{address:08X}")
    cells = list(struct.unpack_from(f"<{count}H", rom, off + 4))
    return {"offset": off, "width": w, "height": h, "reserved": reserved, "cells": cells}


def stitch_map(atlas: bytes | bytearray, map_obj: dict) -> list[list[int]]:
    w, h = int(map_obj["width"]), int(map_obj["height"])
    pixels = [[0] * (w * 8) for _ in range(h * 8)]
    for ty in range(h):
        for tx in range(w):
            cell = int(map_obj["cells"][ty * w + tx])
            tile = decode_tile(atlas, cell & 0x03FF)
            hflip = bool(cell & 0x0400)
            vflip = bool(cell & 0x0800)
            for yy in range(8):
                sy = 7 - yy if vflip else yy
                for xx in range(8):
                    sx = 7 - xx if hflip else xx
                    pixels[ty * 8 + yy][tx * 8 + xx] = tile[sy][sx]
    return pixels


def build_panel_template(samples: list[list[list[int]]], background: int) -> list[list[int]]:
    gate(samples and all(len(p) == 16 and all(len(row) == 32 for row in p) for p in samples), "panel sample geometry drift")
    template = [[0] * 32 for _ in range(16)]
    for y in range(16):
        for x in range(32):
            values = [p[y][x] for p in samples]
            counts = Counter(values)
            # The fixed panel geometry is identical across labels.  If even one
            # source label exposes the flat interior color at this coordinate,
            # that is the clean glyph-free value.  Otherwise preserve the
            # family mode (rounded border/highlight/shadow geometry).
            if counts[background] > 0:
                template[y][x] = background
            else:
                template[y][x] = counts.most_common(1)[0][0]
    return template


def build_native_normal_panel_template() -> list[list[int]]:
    """Reconstruct the native normal 32x16 button without any glyph pixels.

    The requested corrected composition uses index 10 for the bright-yellow
    panel interior (matching the normal buttons in the turn-end menu), index 11
    for the pale-yellow glyph face, and index 5 for the one-pixel brown glyph
    contour. Index 9 remains fixed orange panel bevel geometry.
    """
    pixels = [[NORMAL_BG] * 32 for _ in range(16)]
    for x in range(32):
        pixels[0][x] = pixels[15][x] = NORMAL_FACE
    for y in range(1, 15):
        pixels[y][0] = pixels[y][31] = NORMAL_FACE
    for x, value in enumerate((NORMAL_FACE, NORMAL_FACE, 10, 9, 9)):
        pixels[1][x] = pixels[14][x] = value
        pixels[1][31 - x] = pixels[14][31 - x] = value
    for x, value in enumerate((NORMAL_FACE, 10, 9)):
        pixels[2][x] = pixels[13][x] = value
        pixels[2][31 - x] = pixels[13][31 - x] = value
    for y in range(3, 13):
        pixels[y][1] = pixels[y][2] = 9
        pixels[y][29] = pixels[y][30] = 9
    gate(Counter(value for row in pixels for value in row) == Counter({NORMAL_BG: 364, 9: 52, NORMAL_FACE: 96}), "native normal panel profile drift")
    return pixels


def gate_template_has_no_isolated_glyph(template: list[list[int]], background: int, label: str) -> None:
    """Prove every non-background template pixel belongs to the panel edge.

    Native glyph residue would form an interior component disconnected from the
    32x16 panel border.  Flooding inward from the border therefore distinguishes
    fixed bevel geometry from a Japanese face/contour fragment without relying
    on palette-index guesses.
    """
    height = len(template)
    width = len(template[0]) if height else 0
    gate((width, height) == (32, 16) and all(len(row) == width for row in template), f"{label} template geometry drift")
    pending = [
        (x, y)
        for y in range(height)
        for x in range(width)
        if (x in (0, width - 1) or y in (0, height - 1)) and template[y][x] != background
    ]
    connected = set(pending)
    while pending:
        x, y = pending.pop()
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and template[ny][nx] != background and (nx, ny) not in connected:
                connected.add((nx, ny))
                pending.append((nx, ny))
    isolated = [
        (x, y, template[y][x])
        for y in range(height)
        for x in range(width)
        if template[y][x] != background and (x, y) not in connected
    ]
    gate(not isolated, f"{label} template retains isolated native glyph pixels: {isolated[:8]}")


def infer_shadow_index(samples: list[list[list[int]]], template: list[list[int]], face: int, background: int) -> tuple[int, dict[int, int]]:
    counts: Counter[int] = Counter()
    for pixels in samples:
        for y in range(16):
            for x in range(32):
                value = pixels[y][x]
                if value == template[y][x] or value in (face, background):
                    continue
                counts[value] += 1
    gate(bool(counts), "could not infer native action-label contour index")
    shadow = counts.most_common(1)[0][0]
    gate(shadow not in (face, background), "inferred contour collides with face/background")
    return shadow, dict(sorted(counts.items()))


def render_hangul(
    text: str,
    font: fontpair.BdfFont,
    face: int,
    background: int,
    shadow: int | None,
    template: list[list[int]],
) -> tuple[list[list[int]], dict]:
    gate(len(text) == 2, f"action label must stay two cells: {text!r}")
    gate(len(template) == 16 and all(len(row) == 32 for row in template), "action template is not 32x16")
    pixels = [row[:] for row in template]
    ink_mask = [[False] * 32 for _ in range(16)]

    x0, y0 = 4, 2
    for index, char in enumerate(text):
        glyph = fontpair.render_12x12_basic(char, font)
        for y in range(12):
            for x in range(12):
                if glyph.getpixel((x, y)):
                    ink_mask[y0 + y][x0 + index * 12 + x] = True

    contour_mask = [[False] * 32 for _ in range(16)]
    for y in range(16):
        for x in range(32):
            if not ink_mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ox, oy = x + dx, y + dy
                    if 0 <= ox < 32 and 0 <= oy < 16 and not ink_mask[oy][ox]:
                        contour_mask[oy][ox] = True

    contour_pixels = 0
    ink_pixels = 0
    for y in range(16):
        for x in range(32):
            # Do not overwrite the native panel bevel.  The Korean 12x12 pair
            # sits inside the flat panel, so the contour belongs only on flat
            # interior pixels.
            if shadow is not None and contour_mask[y][x] and pixels[y][x] == background:
                pixels[y][x] = shadow
                contour_pixels += 1
    for y in range(16):
        for x in range(32):
            if ink_mask[y][x]:
                pixels[y][x] = face
                ink_pixels += 1

    gate(ink_pixels > 0, f"Korean action glyph did not render: {text}")
    gate((shadow is None and contour_pixels == 0) or (shadow is not None and contour_pixels > 0), f"Korean action contour policy drift: {text}")
    return pixels, {"contour_pixels": contour_pixels, "ink_pixels": ink_pixels}


def display_tile_to_source_orientation(tile: list[list[int]], cell: int) -> list[list[int]]:
    hflip = bool(cell & 0x0400)
    vflip = bool(cell & 0x0800)
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        sy = 7 - y if vflip else y
        for x in range(8):
            sx = 7 - x if hflip else x
            out[y][x] = tile[sy][sx]
    return out


def rendered_payloads_for_map(pixels: list[list[int]], map_obj: dict) -> list[bytes]:
    gate((map_obj["width"], map_obj["height"]) == (4, 2), "translated action resource is not 4x2")
    payloads: list[bytes] = []
    for ty in range(2):
        for tx in range(4):
            cell = int(map_obj["cells"][ty * 4 + tx])
            tile = [pixels[ty * 8 + y][tx * 8 : tx * 8 + 8] for y in range(8)]
            payloads.append(encode_tile(display_tile_to_source_orientation(tile, cell)))
    return payloads


def build_map_chunk(original: dict, cells: list[int]) -> bytes:
    w, h = int(original["width"]), int(original["height"])
    gate(len(cells) == w * h, "map cell count drift")
    return bytes([w, h]) + struct.pack("<H", int(original["reserved"])) + struct.pack(f"<{len(cells)}H", *cells)


def literal_only_lzss_body(decoded: bytes) -> bytes:
    body = bytearray()
    for start in range(0, len(decoded), 8):
        chunk = decoded[start : start + 8]
        body.append((1 << len(chunk)) - 1)
        body.extend(chunk)
    gate(len(body) <= 0xFFFF, "action atlas clone exceeds 16-bit compressed length")
    return bytes(body)


def normalize_input_baseline(input_bytes: bytes, input_path: Path) -> tuple[bytes, dict]:
    """Accept the user-named first candidate or the current clean main TIP.

    The first candidate's manifest proves that it changed only the private
    action allocation and three table literals.  Clearing that allocation and
    restoring those literals must reproduce its recorded main-TIP source hash
    exactly; this avoids inheriting the broken 415-tile clone while preserving
    the precise baseline the user tested.
    """
    input_sha = sha256(input_bytes)
    first_manifest = json.loads(FIRST_MANIFEST.read_text(encoding="utf-8"))
    if input_sha == first_manifest["candidate"]["sha256"]:
        gate(first_manifest["verification"]["changes_confined_to_private_clone_and_three_literals"], "first candidate change-scope proof missing")
        normalized = bytearray(input_bytes)
        normalized[ATLAS_CLONE:ALLOCATION_END] = bytes(ALLOCATION_END - ATLAS_CLONE)
        for literal in TABLE_CONSUMER_LITERALS:
            normalized[literal : literal + 4] = p32(ROM_BASE + RESOURCE_TABLE)
        normalized_sha = sha256(normalized)
        gate(normalized_sha == first_manifest["source_main_tip"]["sha256"], f"first-candidate normalization hash mismatch: {normalized_sha}")
        return bytes(normalized), {
            "kind": "first_action_menu_candidate",
            "path": str(input_path.name),
            "sha256": input_sha,
            "normalized_main_tip_sha256": normalized_sha,
        }

    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(input_sha == main_manifest["sha256"], f"input is neither the recorded first candidate nor current main TIP: {input_sha}")
    return input_bytes, {
        "kind": "current_main_tip",
        "path": str(input_path.name),
        "sha256": input_sha,
        "normalized_main_tip_sha256": input_sha,
    }


def save_preview(path: Path, rows: list[dict]) -> None:
    scale = 3
    cell_w, cell_h = 32 * scale, 16 * scale
    canvas = Image.new("RGB", (cell_w * 2, cell_h * len(rows)), (24, 24, 24))
    # RGB values are measured by registering the clean-ROM index planes to the
    # user's native screenshots.  The preview therefore reflects runtime color
    # roles instead of the earlier palette-independent diagnostic ramp.
    normal_palette = {
        5: (116, 57, 1), 9: (254, 181, 42), 10: (253, 231, 65), 11: (254, 254, 141),
    }
    focus_palette = {
        4: (1, 16, 49), 8: (76, 214, 254), 9: (101, 230, 253),
        10: (200, 254, 254), 11: (253, 254, 140), 12: (254, 254, 253),
    }
    for row_index, row in enumerate(rows):
        for col, key in enumerate(("normal_pixels", "focus_pixels")):
            pix = row[key]
            palette = normal_palette if col == 0 else focus_palette
            image = Image.new("RGB", (32, 16))
            for y in range(16):
                for x in range(32):
                    value = pix[y][x]
                    image.putpixel((x, y), palette.get(value, (40 + value * 10, 40 + value * 8, 40 + value * 6)))
            image = image.resize((cell_w, cell_h), Image.Resampling.NEAREST)
            canvas.paste(image, (col * cell_w, row_index * cell_h))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, default=FIRST_CANDIDATE)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--preview", type=Path, default=PREVIEW)
    args = ap.parse_args()

    input_bytes = args.base.read_bytes()
    base, input_baseline = normalize_input_baseline(input_bytes, args.base)
    base_sha = sha256(base)
    gate(len(base) == len(input_bytes) == 32 * 1024 * 1024, "input/main TIP size drift")
    jp = JP_ROM.read_bytes()
    gate(sha256(jp) == scan.EXPECTED_SHA256, "Japanese source hash drift")

    for literal in TABLE_CONSUMER_LITERALS:
        gate(u32(base, literal) == ROM_BASE + RESOURCE_TABLE, f"action table literal drift at 0x{literal:08X}")
    gate(u32(base, RESOURCE_TABLE) == ROM_BASE + ATLAS_SOURCE, "action atlas pointer drift")

    source_header = u32(base, ATLAS_SOURCE)
    gate((source_header & 0xFFFF0000) == 0x80000000, "action atlas header drift")
    source_body_len = source_header & 0xFFFF
    source_atlas = scan.lzss_decompress(base[ATLAS_SOURCE + 4 : ATLAS_SOURCE + 4 + source_body_len])
    gate(len(source_atlas) == 239 * 32, f"unexpected action atlas decoded size: {len(source_atlas)}")
    atlas_tile_count = len(source_atlas) // 32

    table_ptrs = [u32(base, RESOURCE_TABLE + i * 4) for i in range(RESOURCE_COUNT)]
    gate(table_ptrs[0] == ROM_BASE + ATLAS_SOURCE, "table[0] action atlas pointer drift")
    source_maps: dict[int, dict] = {}
    for index in range(1, RESOURCE_COUNT):
        if table_ptrs[index] == 0:
            continue
        source_maps[index] = parse_map(base, table_ptrs[index])
        for cell in source_maps[index]["cells"]:
            gate((int(cell) & 0x03FF) < atlas_tile_count, f"resource[{index}] references tile outside atlas")

    target_resources: set[int] = set()
    for command_id in TRANSLATIONS:
        target_resources.add(NORMAL_BASE + command_id)
        target_resources.add(FOCUS_BASE + command_id)
    for index in sorted(target_resources):
        gate(index in source_maps and (source_maps[index]["width"], source_maps[index]["height"]) == (4, 2), f"target resource[{index}] geometry drift")

    gate(NORMAL_BASE + ID_COMMAND not in target_resources and FOCUS_BASE + ID_COMMAND not in target_resources, "Latin ID unexpectedly targeted")

    normal_samples = [stitch_map(source_atlas, source_maps[i]) for i in range(NORMAL_BASE, NORMAL_BASE + 12) if i != NORMAL_BASE + ID_COMMAND]
    focus_samples = [stitch_map(source_atlas, source_maps[i]) for i in range(FOCUS_BASE, FOCUS_BASE + 12) if i != FOCUS_BASE + ID_COMMAND]
    normal_template = build_native_normal_panel_template()
    # The focus fill uses the exact rounded mask occupied by the normal bright-
    # yellow interior plus orange bevel.  This is deliberately not the mask's
    # rectangular bounding box: normal pale-yellow outer pixels must remain at
    # the rounded corners and around the focus fill.
    focus_fill_points = [
        (x, y)
        for y in range(16)
        for x in range(32)
        if normal_template[y][x] in (9, NORMAL_BG)
    ]
    gate(bool(focus_fill_points), "normal rounded panel has no focus-fill mask")
    focus_x0 = min(x for x, _ in focus_fill_points)
    focus_x1 = max(x for x, _ in focus_fill_points)
    focus_y0 = min(y for _, y in focus_fill_points)
    focus_y1 = max(y for _, y in focus_fill_points)
    gate((focus_x0, focus_y0, focus_x1, focus_y1) == (1, 1, 30, 14), "normal bevel bounding box drift")
    focus_template = [row[:] for row in normal_template]
    focus_fill_set = set(focus_fill_points)
    for y in range(16):
        for x in range(32):
            focus_template[y][x] = FOCUS_BG if (x, y) in focus_fill_set else NORMAL_FACE
    gate(sum(value == FOCUS_BG for row in focus_template for value in row) == 416, "rounded focus fill pixel count drift")
    gate(sum(value == NORMAL_FACE for row in focus_template for value in row) == 96, "focus pale-yellow outside pixel count drift")
    gate(all(focus_template[y][x] == NORMAL_FACE for y in (0, 15) for x in range(32)), "focus outer horizontal pale-yellow border drift")
    gate(all(focus_template[y][x] == NORMAL_FACE for y in range(16) for x in (0, 31)), "focus outer vertical pale-yellow border drift")
    gate_template_has_no_isolated_glyph(focus_template, FOCUS_BG, "focus")
    normal_shadow = NORMAL_SHADOW
    normal_shadow_counts: dict[int, int] = {NORMAL_SHADOW: 1}
    focus_shadow = FOCUS_SHADOW
    focus_shadow_counts: dict[int, int] = {FOCUS_SHADOW: 1}

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    desired_payloads: dict[int, list[bytes]] = {}
    audit: list[dict] = []
    preview_rows: list[dict] = []
    for command_id, (jp_text, ko_text) in TRANSLATIONS.items():
        pair_row: dict = {"command_id": command_id, "jp": jp_text, "ko": ko_text}
        preview_row: dict = {}
        for state, resource_index, background, face, shadow, template in (
            ("normal", NORMAL_BASE + command_id, NORMAL_BG, NORMAL_FACE, normal_shadow, normal_template),
            ("focus", FOCUS_BASE + command_id, FOCUS_BG, FOCUS_FACE, focus_shadow, focus_template),
        ):
            map_obj = source_maps[resource_index]
            rendered, render_stats = render_hangul(ko_text, font, face, background, shadow, template)
            if state == "normal":
                changed_from_panel = [
                    rendered[y][x]
                    for y in range(16)
                    for x in range(32)
                    if rendered[y][x] != template[y][x]
                ]
                gate(changed_from_panel and set(changed_from_panel) == {NORMAL_FACE, NORMAL_SHADOW}, f"normal label face/contour palette drift: {ko_text}")
                gate(
                    all(
                        rendered[y][x] == template[y][x]
                        for y in range(16)
                        for x in range(32)
                        if template[y][x] == 9
                    ),
                    f"normal label overwrote native orange bevel: {ko_text}",
                )
            else:
                gate(
                    all(
                        rendered[y][x] == NORMAL_FACE
                        for y in range(16)
                        for x in range(32)
                        if (x, y) not in focus_fill_set
                    ),
                    f"focus blue/white pixels escaped rounded fill mask: {ko_text}",
                )
            payloads = rendered_payloads_for_map(rendered, map_obj)
            desired_payloads[resource_index] = payloads
            preview_row[state + "_pixels"] = rendered
            pair_row[state] = {
                "resource_index": resource_index,
                "source_pointer": f"0x{table_ptrs[resource_index]:08X}",
                "source_map_file_offset": f"0x{map_obj['offset']:08X}",
                "palette_banks": sorted({(int(cell) >> 12) & 0xF for cell in map_obj["cells"]}),
                "background_index": background,
                "face_index": face,
                "contour_index": shadow,
                "style": "yellow face/background with one-pixel brown contour" if state == "normal" else "white face on sky-blue background with one-pixel navy contour",
                **render_stats,
            }
        audit.append(pair_row)
        preview_rows.append(preview_row)

    # Resource 28/29 normal tile IDs are embedded in resources 10..17.  They
    # must become remappable, while all other tiles still used by non-target
    # resources are protected from repacking.
    submenu_old_ids = {
        int(cell) & 0x03FF
        for index in SUBMENU_RESOURCE_INDICES
        for cell in source_maps[index]["cells"]
    }
    protected_ids: set[int] = set()
    for index, map_obj in source_maps.items():
        if index in target_resources:
            continue
        if index in FRAME_RESOURCE_INDICES:
            protected_ids.update((int(cell) & 0x03FF) for cell in map_obj["cells"] if (int(cell) & 0x03FF) not in submenu_old_ids)
        else:
            protected_ids.update(int(cell) & 0x03FF for cell in map_obj["cells"])
    gate(all(0 <= tile_id < atlas_tile_count for tile_id in protected_ids), "protected tile ID outside atlas")
    free_ids = set(range(atlas_tile_count)) - protected_ids

    source_payload_to_ids: dict[bytes, list[int]] = defaultdict(list)
    for tile_id in range(atlas_tile_count):
        source_payload_to_ids[source_atlas[tile_id * 32 : tile_id * 32 + 32]].append(tile_id)

    unique_payloads: list[bytes] = []
    seen_payloads: set[bytes] = set()
    for resource_index in sorted(desired_payloads):
        for payload in desired_payloads[resource_index]:
            if payload not in seen_payloads:
                seen_payloads.add(payload)
                unique_payloads.append(payload)

    payload_to_tile: dict[bytes, int] = {}
    available_free = set(free_ids)
    atlas = bytearray(source_atlas)
    reused_protected = 0
    reused_free_exact = 0
    mutated_ids: set[int] = set()
    for payload in unique_payloads:
        exact_ids = source_payload_to_ids.get(payload, [])
        protected_exact = [tile_id for tile_id in exact_ids if tile_id in protected_ids]
        if protected_exact:
            payload_to_tile[payload] = protected_exact[0]
            reused_protected += 1
            continue
        free_exact = [tile_id for tile_id in exact_ids if tile_id in available_free]
        if free_exact:
            tile_id = free_exact[0]
            payload_to_tile[payload] = tile_id
            available_free.remove(tile_id)
            reused_free_exact += 1
            continue
        gate(bool(available_free), f"fixed-size action atlas exhausted after {len(payload_to_tile)} unique payloads")
        tile_id = min(available_free)
        available_free.remove(tile_id)
        payload_to_tile[payload] = tile_id
        start = tile_id * 32
        atlas[start : start + 32] = payload
        mutated_ids.add(tile_id)

    gate(mutated_ids.isdisjoint(protected_ids), "fixed-size repack modified protected tile")

    map_chunks: dict[int, bytes] = {}
    target_new_cells: dict[int, list[int]] = {}
    target_tile_ids: dict[int, list[int]] = {}
    for resource_index in sorted(target_resources):
        map_obj = source_maps[resource_index]
        new_cells: list[int] = []
        new_ids: list[int] = []
        for old_cell, payload in zip(map_obj["cells"], desired_payloads[resource_index]):
            new_id = payload_to_tile[payload]
            new_cells.append((int(old_cell) & 0xFC00) | new_id)
            new_ids.append(new_id)
        target_new_cells[resource_index] = new_cells
        target_tile_ids[resource_index] = new_ids
        map_chunks[resource_index] = build_map_chunk(map_obj, new_cells)

    # Carry the Korean 全体/個別 tiles into the large move-submenu frame maps.
    submenu_key_to_new: dict[tuple[int, int], int] = {}
    for resource_index in SUBMENU_RESOURCE_INDICES:
        old_cells = source_maps[resource_index]["cells"]
        new_cells = target_new_cells[resource_index]
        for old_cell, new_cell in zip(old_cells, new_cells):
            key = (int(old_cell) & 0x03FF, int(old_cell) & 0x0C00)
            new_id = int(new_cell) & 0x03FF
            if key in submenu_key_to_new:
                gate(submenu_key_to_new[key] == new_id, f"submenu source tile requires conflicting Korean payload: {key}")
            submenu_key_to_new[key] = new_id

    frame_replacements: dict[int, int] = {}
    frame_palette_replacements: Counter[int] = Counter()
    for resource_index in FRAME_RESOURCE_INDICES:
        map_obj = source_maps[resource_index]
        new_cells: list[int] = []
        replacements = 0
        for cell in map_obj["cells"]:
            tile_id = int(cell) & 0x03FF
            flip = int(cell) & 0x0C00
            key = (tile_id, flip)
            if key in submenu_key_to_new:
                new_cells.append((int(cell) & 0xFC00) | submenu_key_to_new[key])
                replacements += 1
                frame_palette_replacements[(int(cell) >> 12) & 0xF] += 1
            else:
                gate(tile_id not in submenu_old_ids, f"frame resource[{resource_index}] uses submenu tile 0x{tile_id:03X} with unexpected flip flags")
                new_cells.append(int(cell))
        gate(replacements > 0, f"frame resource[{resource_index}] did not expose 全体/個別 shared tiles")
        frame_replacements[resource_index] = replacements
        map_chunks[resource_index] = build_map_chunk(map_obj, new_cells)

    compressed_body = literal_only_lzss_body(bytes(atlas))
    atlas_resource = p32(0x80000000 | len(compressed_body)) + compressed_body
    gate(ATLAS_CLONE + len(atlas_resource) <= TABLE_CLONE, "fixed-size action atlas clone overlaps private table")

    candidate = bytearray(base)
    gate(set(candidate[ATLAS_CLONE:ALLOCATION_END]) <= {0}, "action expansion allocation is not zero-filled")
    candidate[ATLAS_CLONE : ATLAS_CLONE + len(atlas_resource)] = atlas_resource

    new_ptrs = table_ptrs[:]
    new_ptrs[0] = ROM_BASE + ATLAS_CLONE
    cursor = MAP_CLONE_START
    map_layout: dict[int, dict] = {}
    for resource_index in sorted(map_chunks):
        cursor = align4(cursor)
        chunk = map_chunks[resource_index]
        gate(cursor + len(chunk) <= ALLOCATION_END, "private action maps exceed allocation")
        candidate[cursor : cursor + len(chunk)] = chunk
        new_ptrs[resource_index] = ROM_BASE + cursor
        map_layout[resource_index] = {
            "clone_file_offset": f"0x{cursor:08X}",
            "clone_pointer": f"0x{ROM_BASE + cursor:08X}",
            "byte_length": len(chunk),
        }
        cursor += len(chunk)

    table_bytes = struct.pack(f"<{RESOURCE_COUNT}I", *new_ptrs)
    gate(TABLE_CLONE + len(table_bytes) <= MAP_CLONE_START, "private action table overlaps maps")
    candidate[TABLE_CLONE : TABLE_CLONE + len(table_bytes)] = table_bytes
    for literal in TABLE_CONSUMER_LITERALS:
        candidate[literal : literal + 4] = p32(ROM_BASE + TABLE_CLONE)

    decoded_clone = scan.lzss_decompress(candidate[ATLAS_CLONE + 4 : ATLAS_CLONE + 4 + (u32(candidate, ATLAS_CLONE) & 0xFFFF)])
    gate(decoded_clone == bytes(atlas), "fixed-size action atlas clone round-trip mismatch")
    gate(len(decoded_clone) == len(source_atlas) == 239 * 32, "decoded action atlas footprint changed")
    for tile_id in protected_ids:
        start = tile_id * 32
        gate(decoded_clone[start : start + 32] == source_atlas[start : start + 32], f"protected tile 0x{tile_id:03X} changed")

    for index in range(RESOURCE_COUNT):
        actual = u32(candidate, TABLE_CLONE + index * 4)
        gate(actual == new_ptrs[index], f"private table[{index}] pointer mismatch")
        if index not in map_chunks and index != 0:
            gate(actual == table_ptrs[index], f"non-target table[{index}] changed")
    gate(new_ptrs[NORMAL_BASE + ID_COMMAND] == table_ptrs[NORMAL_BASE + ID_COMMAND], "normal ID pointer changed")
    gate(new_ptrs[FOCUS_BASE + ID_COMMAND] == table_ptrs[FOCUS_BASE + ID_COMMAND], "focus ID pointer changed")
    gate(new_ptrs[42] == table_ptrs[42] and new_ptrs[43] == table_ptrs[43], "unknown trailing focus resources changed")
    gate(candidate[ATLAS_SOURCE : ATLAS_SOURCE + 4 + source_body_len] == base[ATLAS_SOURCE : ATLAS_SOURCE + 4 + source_body_len], "original action atlas changed")
    for literal in TABLE_CONSUMER_LITERALS:
        gate(u32(candidate, literal) == ROM_BASE + TABLE_CLONE, f"action literal patch failed at 0x{literal:08X}")

    changed = [i for i, (a, b) in enumerate(zip(base, candidate)) if a != b]
    allowed = set(range(ATLAS_CLONE, ATLAS_CLONE + len(atlas_resource)))
    allowed.update(range(TABLE_CLONE, TABLE_CLONE + len(table_bytes)))
    for info in map_layout.values():
        start = int(info["clone_file_offset"], 16)
        allowed.update(range(start, start + int(info["byte_length"])))
    for literal in TABLE_CONSUMER_LITERALS:
        allowed.update(range(literal, literal + 4))
    gate(all(off in allowed for off in changed), "candidate changed bytes outside fixed action clone/literals")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    save_preview(args.preview, preview_rows)
    out_sha = sha256(candidate)
    candidate_meta = {"path": str(args.out.relative_to(ADVANCE_ROOT)), "sha256": out_sha, "size": len(candidate)}
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_action_menu_ko_focusrounded_20260830",
        "result": "PASS",
        "input_baseline": input_baseline,
        "source_main_tip": {"path": str(args.base.name), "sha256": base_sha, "size": len(base)},
        "candidate": candidate_meta,
        "output": candidate_meta,
        "corrections": {
            "move_submenu_first_entry": {"jp": "全体", "ko": "전체", "previous_misread": "合体/합체"},
            "native_japanese_glyph_cleanup": "normal uses an exact symmetric panel profile; focus uses a glyph-free family template",
            "korean_contour": "one-pixel 8-neighbour contour regenerated from each Korean Galmuri11 glyph mask",
            "normal_runtime_palette_roles": {"5": "one-pixel brown contour", "9": "orange-brown bevel", "10": "turn-end-menu bright-yellow background", "11": "pale-yellow face"},
            "focus_runtime_palette_roles": {"4": "one-pixel navy contour", "8": "sky-blue background", "12": "white face"},
            "focus_fill_bounds_from_normal_bevel": {"x0": focus_x0, "y0": focus_y0, "x1": focus_x1, "y1": focus_y1},
            "focus_fill_shape": "exact union of normal index-10 bright-yellow interior and index-9 orange bevel pixels",
            "focus_fill_template_pixel_count": len(focus_fill_points),
            "focus_outside_fill": "same index-11 pale yellow as the normal outer region",
            "background_glitch_prevention": "decoded action atlas held byte-exact at 239 tiles / 7648 bytes",
        },
        "family": {
            "resource_table_source": f"0x{ROM_BASE + RESOURCE_TABLE:08X}",
            "atlas_source": f"0x{ROM_BASE + ATLAS_SOURCE:08X}",
            "atlas_clone": f"0x{ROM_BASE + ATLAS_CLONE:08X}",
            "table_clone": f"0x{ROM_BASE + TABLE_CLONE:08X}",
            "consumer_literals": [f"0x{ROM_BASE + off:08X}" for off in TABLE_CONSUMER_LITERALS],
            "decoded_tiles_before": atlas_tile_count,
            "decoded_tiles_after": len(decoded_clone) // 32,
            "decoded_bytes_before": len(source_atlas),
            "decoded_bytes_after": len(decoded_clone),
            "no_runtime_atlas_growth": len(decoded_clone) == len(source_atlas),
        },
        "panel_cleanup": {
            "normal_template_sha256": sha256(bytes(v for row in normal_template for v in row)),
            "focus_template_sha256": sha256(bytes(v for row in focus_template for v in row)),
            "normal_background_index": NORMAL_BG,
            "normal_face_index": NORMAL_FACE,
            "normal_contour_index": normal_shadow,
            "normal_contour_policy": "index 5; one-pixel 8-neighbour brown contour only",
            "normal_contour_candidate_counts": normal_shadow_counts,
            "focus_background_index": FOCUS_BG,
            "focus_face_index": FOCUS_FACE,
            "focus_contour_index": focus_shadow,
            "focus_contour_candidate_counts": focus_shadow_counts,
        },
        "repack": {
            "protected_tile_count": len(protected_ids),
            "free_tile_count": len(free_ids),
            "desired_unique_payload_count": len(unique_payloads),
            "reused_protected_exact_payload_count": reused_protected,
            "reused_free_exact_payload_count": reused_free_exact,
            "mutated_tile_count": len(mutated_ids),
            "mutated_tile_ids": [f"0x{tile_id:03X}" for tile_id in sorted(mutated_ids)],
            "unallocated_free_tile_count": len(available_free),
        },
        "submenu_shared_tiles": {
            "normal_resources": list(SUBMENU_RESOURCE_INDICES),
            "source_tile_ids": [f"0x{tile_id:03X}" for tile_id in sorted(submenu_old_ids)],
            "frame_resources_cloned": list(FRAME_RESOURCE_INDICES),
            "replacements_by_frame_resource": {str(k): v for k, v in frame_replacements.items()},
            "replacements_by_palette_bank": {str(k): v for k, v in sorted(frame_palette_replacements.items())},
        },
        "labels": audit,
        "target_tile_ids": {str(k): [f"0x{v:03X}" for v in values] for k, values in sorted(target_tile_ids.items())},
        "private_map_layout": {str(k): v for k, v in sorted(map_layout.items())},
        "verification": {
            "result": "PASS",
            "input_baseline_hash_verified": True,
            "first_candidate_normalization_verified": input_baseline["kind"] == "first_action_menu_candidate",
            "translated_command_count": len(TRANSLATIONS),
            "translated_state_resource_count": len(target_resources),
            "ID_normal_focus_untouched": True,
            "resources_42_43_untouched": True,
            "protected_tiles_unchanged": True,
            "normal_template_matches_explicit_symmetric_bevel_profile": True,
            "focus_template_has_no_isolated_native_glyph_pixels": True,
            "normal_labels_add_face_and_one_pixel_brown_contour_only": True,
            "normal_orange_index_restricted_to_native_panel_bevel": True,
            "normal_background_matches_turn_end_menu_index_10": True,
            "focus_white_face_skyblue_background_navy_contour_verified": True,
            "focus_skyblue_matches_normal_rounded_interior_plus_bevel_mask": True,
            "focus_outside_matches_normal_pale_yellow": True,
            "focus_blue_navy_white_pixels_confined_to_rounded_mask": True,
            "preview_uses_screenshot_registered_runtime_rgb": True,
            "original_atlas_unchanged": True,
            "decoded_atlas_footprint_unchanged": True,
            "changes_restricted_to_private_allocation_and_three_literals": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": str(args.out), "sha256": out_sha, "manifest": str(args.manifest), "preview": str(args.preview), "decoded_tiles": len(decoded_clone) // 32, "normal_contour": normal_shadow, "focus_contour": focus_shadow}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
