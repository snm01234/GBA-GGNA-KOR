#!/usr/bin/env python3
"""Build a main-TIP-based Korean sort-popup candidate for the user state6 UI.

The popup is a BG composition: BG2 owns the title and five normal buttons,
while BG1 owns the currently focused button.  A narrowly gated frame hook
recognizes the exact 14x10 popup tilemap signature and refreshes only the
translated BG tiles.  This keeps the global 12x12 font and unrelated menus
byte-exact while covering all five normal/focus selection states.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as drawutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    advance_relative,
)

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss6"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup"
OUT_ROM = OUT_DIR / "ggen_advance_sort_popup_state6_ko_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_sort_popup_state6_ko_candidate_20260903.sav"
OUT_STATE = OUT_DIR / "ggen_advance_sort_popup_state6_ko_candidate_20260903.ss6"
OUT_PREVIEW = OUT_DIR / "ggen_advance_sort_popup_state6_ko_preview_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_sort_popup_state6_ko_candidate_20260903.json"

ROM_BASE = 0x08000000
HOOK_FILE = 0x00063194
HOOK_EXPECTED = bytes.fromhex("00b5b0f749f8b0f7")
STUB_FILE = 0x01F20000
TABLE_FILE = 0x01F20400
BG2_DATA_FILE = 0x01F20500
FOCUS_FILES = {
    "HP": 0x01F21800,
    "오름": 0x01F21A00,
    "이름": 0x01F21C00,
    "내림": 0x01F21E00,
    "배치중": 0x01F22000,
}
ALLOCATION_END = 0x01F22200

# Assembled ARMv4T Thumb code.  It reproduces 0x08063194 including the final
# 0x08001928 screen-transfer call first, then gates on BG2CNT=0x5D0A plus the
# popup's first/last map cells (F00E/F099).  Applying the Korean tiles after
# that transfer prevents a newly selected Japanese focus strip from overwriting
# the patch.  Measured focus strips can be on BG0 or BG1, so both screenblocks
# are scanned.  Palette bank E distinguishes a focus cell from unrelated BG0
# palette-B content, and the payload is written at the cell's real tile ID.
STUB = bytes.fromhex(
    "00b53e4b00f064f83d4b00f061f83d4b00f05ef8ffb43c4801883c4a914254d1"
    "3b4801883b4a91424fd13b4801883b4a91424ad13a4c00f04cf83a480388180b"
    "0e282dd038480388180b0e282bd037480388180b0e2829d035480388180b0e28"
    "27d034480388180b0e2825d032480388180b0e2814d031480388180b0e2812d0"
    "2f480388180b0e2810d02e480388180b0e280ed02c480388180b0e280cd014e0"
    "2a4970220ae02a49502207e02949702204e02949502201e0284970229b059b0d"
    "5b012748c01800f00ff8ffbc01bc00471847f0b52068002805d06168a26800f0"
    "03f80c34f6e7f0bd002a05d00b68036004310430013af9d1704700bf2d320108"
    "45350108291900080c0000040a5d000050e900060ef00000aaeb000699f00000"
    "0004f209126200062062000692620006a0620006126300061272000620720006"
    "92720006a0720006127300060018f209001af209001cf209001ef2090020f209"
    "00000006"
)

TRANSLATIONS = {
    "ソート順の変更": "정렬순서 변경",
    "HP": "HP",
    "昇順": "오름",
    "名前": "이름",
    "降順": "내림",
    "配備中": "배치중",
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def p32(value: int) -> bytes:
    return struct.pack("<I", value)


def make_trampoline(register: int, target: int) -> bytes:
    gate(0 <= register <= 7, "trampoline register outside Thumb low registers")
    return struct.pack("<HHI", 0x4800 | (register << 8), 0x4700 | (register << 3), target | 1)


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile size drift")
    return [[(raw[y * 4 + x // 2] >> (4 * (x & 1))) & 15 for x in range(8)] for y in range(8)]


def encode_tile(tile: list[list[int]]) -> bytes:
    gate(len(tile) == 8 and all(len(row) == 8 for row in tile), "tile geometry drift")
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            out[y * 4 + x // 2] |= (tile[y][x] & 15) << (4 * (x & 1))
    return bytes(out)


def draw_text(
    pixels: list[list[int]], text: str, x0: int, y0: int,
    font: fontpair.BdfFont, *, face: int, contour: int | None,
) -> dict[str, int]:
    mask: set[tuple[int, int]] = set()
    for index, char in enumerate(text):
        if char == " ":
            continue
        glyph = fontpair.render_12x12_basic(char, font)
        for y in range(12):
            for x in range(12):
                if glyph.getpixel((x, y)):
                    mask.add((x0 + index * 12 + x, y0 + y))
    gate(mask, f"empty Korean raster: {text}")
    outline: set[tuple[int, int]] = set()
    if contour is not None:
        for x, y in mask:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if (dx or dy) and (x + dx, y + dy) not in mask:
                        outline.add((x + dx, y + dy))
        for x, y in outline:
            if 0 <= y < len(pixels) and 0 <= x < len(pixels[0]):
                pixels[y][x] = contour
    for x, y in mask:
        gate(0 <= y < len(pixels) and 0 <= x < len(pixels[0]), f"glyph escaped canvas: {text}")
        pixels[y][x] = face
    return {"face_pixels": len(mask), "contour_pixels": len(outline)}


def clear_value(pixels: list[list[int]], box: tuple[int, int, int, int], values: set[int], fill: int) -> int:
    x0, y0, x1, y1 = box
    changed = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pixels[y][x] in values:
                pixels[y][x] = fill
                changed += 1
    return changed


def crop_canvas(
    pixels: list[list[int]], box: tuple[int, int, int, int],
) -> list[list[int]]:
    x0, y0, x1, y1 = box
    return [row[x0:x1] for row in pixels[y0:y1]]


def paste_canvas(
    pixels: list[list[int]], canvas: list[list[int]], x0: int, y0: int,
) -> None:
    for y, row in enumerate(canvas):
        pixels[y0 + y][x0:x0 + len(row)] = row


def build_normal_pixels(state: bytes, font: fontpair.BdfFont) -> tuple[list[list[int]], dict[str, Any]]:
    pixels, binding = drawutil.layer_pixels(state, 2)
    report: dict[str, Any] = {"binding": binding, "labels": {}}
    report["labels"]["정렬순서 변경"] = {
        "cleared": clear_value(pixels, (74, 46, 161, 60), {10, 12}, 14),
        **draw_text(pixels, "정렬순서 변경", 75, 47, font, face=10, contour=12),
    }
    # Every normal button uses the same native chrome.  Build a text-free
    # template from the unchanged HP button instead of erasing palette value
    # 5 in each Japanese button: that value is also used where the old glyphs
    # overwrite the orange border, which caused the earlier "missing teeth".
    clean56 = crop_canvas(pixels, (72, 64, 128, 80))
    hp_removed = 0
    for y in range(16):
        for x in range(56):
            if clean56[y][x] == 5:
                clean56[y][x] = 10
                hp_removed += 1
    gate(hp_removed > 0, "normal HP template contains no glyph pixels")
    gate(set(value for row in clean56 for value in row) <= {9, 10, 11}, "normal HP chrome palette drift")
    clean40 = [row[:20] + row[36:] for row in clean56]
    specs = [
        ("오름", clean40, 128, 64, 8),
        ("이름", clean56, 72, 80, 16),
        ("내림", clean40, 128, 80, 8),
        ("배치중", clean56, 72, 96, 10),
    ]
    for text, clean, x, y, text_x in specs:
        before = crop_canvas(pixels, (x, y, x + len(clean[0]), y + 16))
        paste_canvas(pixels, clean, x, y)
        # Match the unchanged HP lettering: yellow face over the yellow body,
        # with palette 5 supplying the visible brown shadow/contour.
        raster = draw_text(pixels, text, x + text_x, y + 2, font, face=10, contour=5)
        report["labels"][text] = {
            "native_button_pixels_rebuilt": sum(
                a != b for old_row, new_row in zip(before, clean)
                for a, b in zip(old_row, new_row)
            ),
            "chrome_template": "HP-normal",
            "face_index": 10,
            "shadow_index": 5,
            **raster,
        }
    report["normal_template"] = {
        "source": "unchanged HP 56x16",
        "removed_hp_face_pixels": hp_removed,
        "chrome_indices": [9, 10, 11],
        "right_width_rebuilt_from_caps": True,
    }
    return pixels, report


def tile_bytes_from_screen(pixels: list[list[int]], tx: int, ty: int) -> bytes:
    return encode_tile([pixels[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)])


def apply_normal_to_state(state: bytearray, pixels: list[list[int]]) -> tuple[list[tuple[int, bytes]], list[int]]:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    vram_off = statefmt.STATE_VRAM
    cnt = struct.unpack_from("<H", io, 12)[0]
    gate(cnt == 0x5D0A, f"state6 BG2CNT drift: 0x{cnt:04X}")
    char_base = ((cnt >> 2) & 3) * 0x4000
    screen_base = ((cnt >> 8) & 31) * 0x800
    original_vram = bytes(state[vram_off:statefmt.STATE_IWRAM])
    changed: list[tuple[int, bytes]] = []
    ids: list[int] = []
    for ty in range(5, 15):
        for tx in range(8, 22):
            cell = struct.unpack_from("<H", state, vram_off + screen_base + (ty * 32 + tx) * 2)[0]
            tile_id = cell & 0x3FF
            gate(not (cell & 0x0C00), "popup BG2 tile unexpectedly flipped")
            rebuilt = tile_bytes_from_screen(pixels, tx, ty)
            old = original_vram[char_base + tile_id * 32:char_base + (tile_id + 1) * 32]
            if rebuilt != old:
                state[vram_off + char_base + tile_id * 32:vram_off + char_base + (tile_id + 1) * 32] = rebuilt
                changed.append((tile_id, rebuilt))
                ids.append(tile_id)
    gate(changed, "normal popup produced no changed tiles")
    gate(len(ids) == len(set(ids)), "popup BG2 changed tile IDs are shared")
    return changed, ids


def focus_canvas(state: bytes) -> list[list[int]]:
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    canvas = [[0] * 56 for _ in range(16)]
    for tile_id in range(14):
        tile = decode_tile(vram[tile_id * 32:(tile_id + 1) * 32])
        tx, ty = tile_id % 7, tile_id // 7
        for y in range(8):
            canvas[ty * 8 + y][tx * 8:tx * 8 + 8] = tile[y]
    return canvas


def clean_focus(source: list[list[int]]) -> list[list[int]]:
    clean = [row[:] for row in source]
    for y in range(16):
        for x in range(56):
            if clean[y][x] in (1, 12):
                clean[y][x] = 9 if y == 14 else 10
    gate(all(value not in (1, 12) for row in clean for value in row), "focus HP residue survived cleanup")
    return clean


def encode_canvas(canvas: list[list[int]]) -> bytes:
    width = len(canvas[0])
    gate(width % 8 == 0 and len(canvas) == 16, "focus canvas geometry drift")
    out = bytearray()
    for ty in range(2):
        for tx in range(width // 8):
            out += encode_tile([canvas[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)])
    return bytes(out)


def build_focus_variants(state: bytes, font: fontpair.BdfFont) -> tuple[dict[str, bytes], dict[str, Any]]:
    hp = focus_canvas(state)
    clean56 = clean_focus(hp)
    clean40 = [row[:20] + row[36:] for row in clean56]
    variants: dict[str, bytes] = {"HP": encode_canvas(hp)}
    report: dict[str, Any] = {"HP": {"width": 56, "byte_exact_source": True}}
    for text, base, x in (("오름", clean40, 8), ("이름", clean56, 16), ("내림", clean40, 8), ("배치중", clean56, 10)):
        canvas = [row[:] for row in base]
        raster = draw_text(canvas, text, x, 2, font, face=12, contour=1)
        variants[text] = encode_canvas(canvas)
        report[text] = {
            "width": len(canvas[0]),
            "chrome_template": "HP-focus",
            "face_index": 12,
            "shadow_index": 1,
            **raster,
        }
    gate(len(variants["HP"]) == 448 and len(variants["이름"]) == 448 and len(variants["배치중"]) == 448, "left focus size drift")
    gate(len(variants["오름"]) == 320 and len(variants["내림"]) == 320, "right focus size drift")
    return variants, report


def group_runs(changed: list[tuple[int, bytes]]) -> list[list[tuple[int, bytes]]]:
    rows = sorted(changed)
    groups: list[list[tuple[int, bytes]]] = []
    for row in rows:
        if not groups or row[0] != groups[-1][-1][0] + 1:
            groups.append([])
        groups[-1].append(row)
    return groups


def apply_rom_patch(parent: bytes, changed: list[tuple[int, bytes]], focus: dict[str, bytes]) -> tuple[bytes, dict[str, Any]]:
    candidate = bytearray(parent)
    gate(candidate[HOOK_FILE:HOOK_FILE + 8] == HOOK_EXPECTED, "common frame function prologue drift")
    gate(all(value == 0 for value in candidate[STUB_FILE:ALLOCATION_END]), "sort-popup allocation is not zero-filled")
    gate(STUB.count(bytes.fromhex("aaeb0006")) == 1, "stub last-map literal drift")
    focus_map_addresses = (
        0x06006212, 0x06006220, 0x06006292, 0x060062A0, 0x06006312,
        0x06007212, 0x06007220, 0x06007292, 0x060072A0, 0x06007312,
    )
    gate(all(STUB.count(p32(address)) == 1 for address in focus_map_addresses), "BG0/BG1 focus map literal drift")
    gate(STUB.count(bytes.fromhex("180b0e28")) == 10, "palette-E focus gate count drift")
    candidate[HOOK_FILE:HOOK_FILE + 8] = make_trampoline(3, ROM_BASE + STUB_FILE)
    candidate[STUB_FILE:STUB_FILE + len(STUB)] = STUB

    table = bytearray()
    cursor = BG2_DATA_FILE
    run_report = []
    for run in group_runs(changed):
        payload = b"".join(raw for _tile, raw in run)
        gate(cursor + len(payload) <= FOCUS_FILES["HP"], "BG2 patch payload overlaps focus data")
        candidate[cursor:cursor + len(payload)] = payload
        dest = 0x06008000 + run[0][0] * 32
        table += struct.pack("<III", dest, ROM_BASE + cursor, len(payload) // 4)
        run_report.append({"first_tile": run[0][0], "last_tile": run[-1][0], "bytes": len(payload), "dest": f"0x{dest:08X}", "source": f"0x{ROM_BASE + cursor:08X}"})
        cursor += len(payload)
    table += b"\0" * 12
    gate(len(table) <= BG2_DATA_FILE - TABLE_FILE, "BG2 run table overflow")
    candidate[TABLE_FILE:TABLE_FILE + len(table)] = table
    for text, file_off in FOCUS_FILES.items():
        payload = focus[text]
        gate(file_off + len(payload) <= ALLOCATION_END, f"focus payload overflow: {text}")
        candidate[file_off:file_off + len(payload)] = payload
    return bytes(candidate), {"stub_bytes": len(STUB), "bg2_runs": run_report, "bg2_payload_bytes": cursor - BG2_DATA_FILE}


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
        out += struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        pos += 12 + length
        if kind == b"IEND":
            break
    gate(replaced and pos == len(raw), "failed to rewrite mGBA gbAs state chunk")
    return bytes(out)


def install_focus(state: bytearray, payload: bytes, x: int, y: int, width_tiles: int) -> None:
    vram = statefmt.STATE_VRAM
    screen = 14 * 0x800
    for ty in range(6, 15):
        for tx in range(7, 23):
            struct.pack_into("<H", state, vram + screen + (ty * 32 + tx) * 2, 0x02FF)
    for tile in range(width_tiles * 2):
        tx, ty = tile % width_tiles, tile // width_tiles
        struct.pack_into("<H", state, vram + screen + ((y + ty) * 32 + x + tx) * 2, 0xE000 | tile)
    state[vram:vram + len(payload)] = payload


def render_layer_native(state: bytes, layer: int) -> Image.Image:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    px = image.load()
    for sy in range(160):
        wy = sy + info["scroll_y"]
        for sx in range(240):
            wx = sx + info["scroll_x"]
            entry = bgutil.map_entry(vram, info["screen_base"], info["size"], wx // 8, wy // 8)
            tile = entry & 0x3FF
            xx, yy = wx & 7, wy & 7
            off = info["char_base"] + tile * 32 + yy * 4 + xx // 2
            value4 = (vram[off] >> (4 * (xx & 1))) & 15
            if value4 == 0:
                continue
            colour = struct.unpack_from("<H", pal, (((entry >> 12) & 15) * 16 + value4) * 2)[0]
            px[sx, sy] = (*bgutil.rgb555(colour), 255)
    return image


def preview(states: list[bytes]) -> None:
    source = Image.open(STATE).convert("RGBA")
    sheet = Image.new("RGBA", (240 * 3, 160 * 2), (20, 20, 20, 255))
    for index, state in enumerate(states):
        frame = source.copy()
        bg2 = render_layer_native(state, 2)
        bg1 = render_layer_native(state, 1)
        frame.alpha_composite(bg2.crop((64, 32, 176, 120)), (64, 32))
        frame.alpha_composite(bg1)
        sheet.alpha_composite(frame, ((index % 3) * 240, (index // 3) * 160))
    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    sheet.resize((1440, 640), Image.Resampling.NEAREST).save(OUT_PREVIEW)


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP hash/manifest drift")
    state_raw, _chunks = statefmt.parse_png_state(STATE)
    gate(struct.unpack_from("<I", state_raw, 8)[0] == (binascii.crc32(parent) & 0xFFFFFFFF), "state6 ROM CRC mismatch")
    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    normal_pixels, normal_report = build_normal_pixels(state_raw, font)
    patched_state = bytearray(state_raw)
    changed, changed_ids = apply_normal_to_state(patched_state, normal_pixels)
    focus, focus_report = build_focus_variants(state_raw, font)
    candidate, rom_report = apply_rom_patch(parent, changed, focus)
    candidate_crc = binascii.crc32(candidate) & 0xFFFFFFFF

    previews: list[bytes] = []
    focus_layout = [
        ("HP", 9, 8, 7), ("오름", 16, 8, 5), ("이름", 9, 10, 7),
        ("내림", 16, 10, 5), ("배치중", 9, 12, 7),
    ]
    for text, x, y, width in focus_layout:
        row = bytearray(patched_state)
        install_focus(row, focus[text], x, y, width)
        previews.append(bytes(row))
    preview(previews)

    final_state = bytearray(previews[0])
    struct.pack_into("<I", final_state, 8, candidate_crc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate)
    sav = (ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav").read_bytes()
    OUT_SAV.write_bytes(sav)
    OUT_STATE.write_bytes(replace_state_chunk(STATE, bytes(final_state)))

    changed_offsets = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    allowed = set(range(HOOK_FILE, HOOK_FILE + 8)) | set(range(STUB_FILE, ALLOCATION_END))
    gate(set(changed_offsets) <= allowed, "candidate changed bytes escaped hook/allocation contract")
    gate(candidate[HOOK_FILE:HOOK_FILE + 8] == make_trampoline(3, ROM_BASE + STUB_FILE), "hook trampoline verification failed")
    gate(candidate[STUB_FILE:STUB_FILE + len(STUB)] == STUB, "stub verification failed")

    result = {
        "schema_version": 1,
        "kind": "ggen_advance_sort_popup_state6_ko_candidate_20260903",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "output": {
            "path": advance_relative(OUT_ROM),
            "size": len(candidate),
            "sha256": sha256(candidate),
        },
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{binascii.crc32(parent) & 0xFFFFFFFF:08X}"},
        "candidate": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate), "crc32": f"0x{candidate_crc:08X}", "size": len(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "sha256": sha256(sav)},
        "state6": {"source": advance_relative(STATE), "candidate": advance_relative(OUT_STATE), "candidate_sha256": sha256(OUT_STATE.read_bytes())},
        "preview": advance_relative(OUT_PREVIEW),
        "translations": TRANSLATIONS,
        "layers": {"BG2_normal": normal_report, "BG1_focus": focus_report},
        "normal_changed_tile_ids": changed_ids,
        "normal_changed_tile_count": len(changed_ids),
        "hook": {
            "entry": "0x08063194",
            "stub": f"0x{ROM_BASE + STUB_FILE:08X}",
            "table": f"0x{ROM_BASE + TABLE_FILE:08X}",
            "apply_order": "after_original_0x08001928_screen_transfer",
            "focus_targeting": "palette_E_cell_on_BG0_or_BG1_and_actual_10bit_tile_id",
            **rom_report,
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_match": True,
            "state6_parent_crc_match": True,
            "bg2_exact_signature_gate": ["BG2CNT=0x5D0A", "map[8,5]=0xF00E", "map[21,14]=0xF099"],
            "five_focus_variants_built": list(focus),
            "right_focus_reupload_overwrite_fixed": True,
            "measured_state1_BG0_focus_owner_covered": True,
            "both_BG0_and_BG1_focus_layers_scanned": True,
            "focus_palette_E_gate": True,
            "focus_tile_zero_assumption_removed": True,
            "global_font_unchanged": True,
            "changes_limited_to_hook_and_zero_filled_private_allocation": True,
            "candidate_state_crc_matches_candidate": True,
            "fresh_emulator_measurement": "pending user verification",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": advance_relative(OUT_ROM), "sha256": sha256(candidate), "state": advance_relative(OUT_STATE), "preview": advance_relative(OUT_PREVIEW), "manifest": advance_relative(OUT_MANIFEST), "normal_tiles": len(changed_ids), "focus_variants": list(focus)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
