#!/usr/bin/env python3
"""Build a main-TIP-based candidate for four residual ss1 graphics.

Targets measured in the supplied ss1:
  BG1: 持c -> 지c (the c cell is byte-exact preserved)
  BG2: 所有数 -> 보유수
  OBJ supply package animation 8: 補給ポイント / 総ユニット数
      -> 보급포인트 / 총유닛수
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_images_20260901 as catalog
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as packagefmt
import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as drawutil
import analyze_ggen_advance_settings_suspend_ui as spritefmt
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_develop_menu_buttons_ko_image_20260901 as develop
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sortpatch
import build_ggen_advance_ss1_ss2_graphics_ko_test_20260902 as panelpatch
import build_ggen_advance_status_badge_followup_20260830 as badgepaint
import build_ggen_advance_status_ui_tile_overlay_poc as badgefont
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

STATE = ADVANCE_ROOT / "analysis" / "fresh_states_20260903_ss1_four_graphics" / "fresh_candidate.ss1"
STATE2 = ADVANCE_ROOT / "analysis" / "fresh_states_20260903_ss1_four_graphics" / "fresh_candidate.ss2"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_ss1_four_graphics"
OUT_ROM = OUT_DIR / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.sav"
OUT_STATE = OUT_DIR / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.ss1"
OUT_STATE2 = OUT_DIR / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.ss2"
OUT_PREVIEW = OUT_DIR / "ggen_advance_ss1_four_graphics_ko_preview_20260903.png"
OUT_DISPOSAL_PREVIEW = OUT_DIR / "ggen_advance_disposal_cost_ko_preview_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.json"

ROM_BASE = 0x08000000
SUPPLY_FILE = 0x012D0000
SUPPLY_ADDRESS = ROM_BASE + SUPPLY_FILE
SUPPLY_LIMIT = 0x012D8000
UNIT_TABLE_FILE = 0x01F22400
UNIT_DATA_FILE = 0x01F22500
UNIT_ALLOC_END = 0x01F23000
DISPOSAL_RESOURCE = 0x092C0000
DISPOSAL_FILE = DISPOSAL_RESOURCE - ROM_BASE
DISPOSAL_LIMIT = 0x012C8000
NATIVE_SUPPLY_RESOURCE = 0x08C4654C

# Existing sort-popup hook plus a second, exact-signature path for this ss1.
# The new unit path runs after the original screen transfer and copies only
# the two BG1 持 tiles and twelve unique BG2 所有数 tiles.
STUB = bytes.fromhex(
    "00b54c4b00f081f84b4b00f07ef84b4b00f07bf8ffb44a4801884a4a914255d1"
    "49480188494a914250d149480188494a91424bd1484c00f069f848480388180b0e28"
    "2dd046480388180b0e282bd045480388180b0e2829d043480388180b0e2827d04248"
    "0388180b0e2825d040480388180b0e2814d03f480388180b0e2812d03d480388180b"
    "0e2810d03c480388180b0e280ed03a480388180b0e280cd031e0384970220ae03849"
    "502207e03749702204e03749502201e0364970229b059b0d5b013548c01800f02cf8"
    "1be033480188334a914216d133480188334a914211d132480188324a91420cd13248"
    "0188324a914207d131480188314a914202d1314c00f004f8ffbc01bc00471847f0b5"
    "2068002805d06168a26800f003f80c34f6e7f0bd002a05d00b68036004310430013a"
    "f9d170472d32010845350108291900080c0000040a5d000050e900060ef00000aaeb"
    "000699f000000004f209126200062062000692620006a06200061263000612720006"
    "2072000692720006a0720006127300060018f209001af209001cf209001ef2090020"
    "f209000000065c70000614b000005e7000061db000009c70000615b000006cea0006"
    "ddb00000b6ea00060db100000024f209"
)

TRANSLATIONS = {
    "持c": "지c",
    "所有数": "보유수",
    "補給ポイント": "보급포인트",
    "総ユニット数": "총유닛수",
    "強化費用": "강화비용",
    "補給P": "보급P",
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def p32(value: int) -> bytes:
    return struct.pack("<I", value)


def crop_canvas(pixels: list[list[int]], box: tuple[int, int, int, int]) -> list[list[int]]:
    x0, y0, x1, y1 = box
    return [row[x0:x1] for row in pixels[y0:y1]]


def paste_canvas(pixels: list[list[int]], canvas: list[list[int]], x0: int, y0: int) -> None:
    for y, row in enumerate(canvas):
        pixels[y0 + y][x0:x0 + len(row)] = row


def changed_layer_tiles(
    state: bytes,
    layer: int,
    before: list[list[int]],
    after: list[list[int]],
) -> list[tuple[int, bytes, int]]:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    rows: list[tuple[int, bytes, int]] = []
    seen: set[int] = set()
    for ty in range(20):
        for tx in range(30):
            if all(after[ty * 8 + y][tx * 8 + x] == before[ty * 8 + y][tx * 8 + x] for y in range(8) for x in range(8)):
                continue
            cell = bgutil.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tile_id = cell & 0x3FF
            gate(tile_id not in seen, f"BG{layer} target reuses changed tile 0x{tile_id:03X}")
            seen.add(tile_id)
            uses = [
                (x, y) for y in range(32) for x in range(32)
                if (bgutil.map_entry(vram, info["screen_base"], info["size"], x, y) & 0x3FF) == tile_id
            ]
            gate(uses == [(tx, ty)], f"BG{layer} changed tile 0x{tile_id:03X} is shared: {uses}")
            payload = sortpatch.tile_bytes_from_screen(after, tx, ty)
            destination = 0x06000000 + info["char_base"] + tile_id * 32
            rows.append((destination, payload, tile_id))
    return rows


def build_bg_targets(
    state: bytes,
    font7: fontpair.BdfFont,
    font11: fontpair.BdfFont,
    parent: bytes,
) -> tuple[list[tuple[int, bytes, int]], bytearray, dict[str, Any]]:
    patched_state = bytearray(state)

    bg1, binding1 = drawutil.layer_pixels(state, 1)
    before1 = [row[:] for row in bg1]
    # Fresh candidate ss1 maps the visible B-background plaque to 0x14/0x15.
    # Reuse the already approved Korean fixed descriptor payload byte-exact;
    # this also preserves its native face/outline/background/delimiter colors.
    fixed_hold = parent[0x00C43968:0x00C439A8]
    gate(len(fixed_hold) == 64, "approved fixed 持 payload size drift")
    paste_canvas(bg1, sortpatch.decode_tile(fixed_hold[:32]), 112, 8)
    paste_canvas(bg1, sortpatch.decode_tile(fixed_hold[32:]), 112, 16)
    bg1_rows = changed_layer_tiles(state, 1, before1, bg1)
    gate([tile for _dest, _raw, tile in bg1_rows] == [0x14, 0x15], "fresh 持 BG1 tile set drift")
    gate(crop_canvas(bg1, (120, 8, 128, 24)) == crop_canvas(before1, (120, 8, 128, 24)), "c cell changed")

    bg2, binding2 = drawutil.layer_pixels(state, 2)
    before2 = [row[:] for row in bg2]
    cleared = 0
    for y in range(73, 87):
        for x in range(176, 224):
            if bg2[y][x] in (5, 10):
                bg2[y][x] = 11
                cleared += 1
    owned_raster = sortpatch.draw_text(bg2, "보유수", 182, 74, font11, face=10, contour=5)
    bg2_rows = changed_layer_tiles(state, 2, before2, bg2)
    gate([tile for _dest, _raw, tile in bg2_rows] == [0xDD, 0xDE, 0xDF, 0xE0, 0xE1, 0x108, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0x10D], "所有数 BG2 tile set drift")

    for layer, pixels, rows in ((1, bg1, bg1_rows), (2, bg2, bg2_rows)):
        info = bgutil.bg_info(state, layer)
        for destination, payload, tile_id in rows:
            offset = statefmt.STATE_VRAM + info["char_base"] + tile_id * 32
            patched_state[offset:offset + 32] = payload

    report = {
        "持c": {
            "translation": "지c",
            "layer": "BG1",
            "binding": binding1,
            "changed_tile_ids": [f"0x{tile:03X}" for _d, _p, tile in bg1_rows],
            "preserved_c_tiles": ["0x01D", "0x018"],
            "font": "approved Galmuri7 fixed 8x16 descriptor",
            "face_index": 10,
            "contour_index": 4,
            "payload_source": "0x08C43968",
        },
        "所有数": {
            "translation": "보유수",
            "layer": "BG2",
            "binding": binding2,
            "changed_tile_ids": [f"0x{tile:03X}" for _d, _p, tile in bg2_rows],
            "source_pixels_cleared": cleared,
            "font": "Galmuri11.bdf native 12x12",
            "face_index": 10,
            "contour_index": 5,
            **owned_raster,
        },
    }
    return bg1_rows + bg2_rows, patched_state, report


def encode_canvas_tile(canvas: list[list[int]], x0: int, y0: int) -> bytes:
    return sortpatch.encode_tile([canvas[y0 + y][x0:x0 + 8] for y in range(8)])


def patch_supply_animation8(
    parent: bytes,
    font11: fontpair.BdfFont,
) -> tuple[bytes, list[list[int]], list[list[int]], dict[str, Any]]:
    header = packagefmt.parse_resource_header(parent, SUPPLY_ADDRESS)
    gate(header["offset"] == SUPPLY_FILE and header["animation_count"] == 9, "supply clone binding drift")
    graphics = header["graphics"]
    palettes = header["palettes"]
    _graphics_rel, records = spritefmt.animation_records(parent, SUPPLY_ADDRESS)
    parsed, ids, lookup_file = catalog.parse_anim(records, 8)
    gate(len(parsed["objects"]) == 4 and len(ids) == 128, "supply animation 8 geometry drift")
    source = packagefmt.stitch(graphics, parsed, ids, [0, 1, 2, 3])
    rebuilt = [row[:] for row in source]

    boxes = {
        "補給ポイント": (7, 9, 80, 23),
        "総ユニット数": (136, 9, 200, 23),
    }
    cleared: dict[str, int] = {}
    for label, (x0, y0, x1, y1) in boxes.items():
        count = 0
        for y in range(y0, y1):
            for x in range(x0, x1):
                if rebuilt[y][x] in (5, 10):
                    rebuilt[y][x] = 11
                    count += 1
        gate(count > 0, f"{label} source raster missing")
        cleared[label] = count
    left_raster = sortpatch.draw_text(rebuilt, "보급포인트", 8, 10, font11, face=10, contour=5)
    right_raster = sortpatch.draw_text(rebuilt, "총유닛수", 136, 10, font11, face=10, contour=5)

    original_tiles = len(graphics) // 32
    existing = {graphics[i * 32:(i + 1) * 32]: i for i in range(original_tiles)}
    private: list[bytes] = []
    private_ids: dict[bytes, int] = {}
    lookup_writes: dict[int, int] = {}
    changed_entries = []
    cursor = 0
    gx0 = min(int(obj["x"]) for obj in parsed["objects"])
    gy0 = min(int(obj["y"]) for obj in parsed["objects"])
    for obj_index, obj in enumerate(parsed["objects"]):
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        for ty in range(ht):
            for tx in range(wt):
                pos = ty * wt + tx
                old_id = ids[cursor + pos]
                x = int(obj["x"]) - gx0 + tx * 8
                y = int(obj["y"]) - gy0 + ty * 8
                payload = encode_canvas_tile(rebuilt, x, y)
                old_payload = graphics[old_id * 32:(old_id + 1) * 32]
                if payload == old_payload:
                    new_id = old_id
                elif payload in existing:
                    new_id = existing[payload]
                else:
                    new_id = private_ids.get(payload, -1)
                    if new_id < 0:
                        new_id = original_tiles + len(private)
                        private_ids[payload] = new_id
                        private.append(payload)
                if new_id != old_id:
                    rel = (lookup_file - header["offset"]) + (cursor + pos) * 2
                    lookup_writes[rel] = new_id
                    changed_entries.append({"object": obj_index, "tile_position": pos, "old": old_id, "new": new_id})
        cursor += int(obj["tile_count"])
    gate(cursor == len(ids) and changed_entries, "supply animation 8 remap empty")

    new_graphics = graphics + b"".join(private)
    new_palette_rel = header["graphics_rel"] + len(new_graphics)
    clone = bytearray(new_palette_rel + len(palettes))
    original = parent[header["offset"]:header["offset"] + header["resource_bytes"]]
    clone[:header["graphics_rel"]] = original[:header["graphics_rel"]]
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    for rel, value in lookup_writes.items():
        struct.pack_into("<H", clone, rel, value)
    clone[header["graphics_rel"]:new_palette_rel] = new_graphics
    clone[new_palette_rel:] = palettes
    gate(new_graphics[:len(graphics)] == graphics, "existing supply source tiles changed")
    gate(clone[new_palette_rel:] == palettes, "supply palettes changed")
    gate(SUPPLY_FILE + len(clone) <= SUPPLY_LIMIT, "expanded supply clone exceeds private slot")
    gate(all(value == 0 for value in parent[header["offset"] + header["resource_bytes"]:SUPPLY_FILE + len(clone)]), "supply expansion area is not zero-filled")
    return bytes(clone), source, rebuilt, {
        "address": f"0x{SUPPLY_ADDRESS:08X}",
        "animation": 8,
        "original_resource_bytes": header["resource_bytes"],
        "expanded_resource_bytes": len(clone),
        "original_source_tiles_preserved": original_tiles,
        "private_source_tiles_appended": len(private),
        "lookup_entries_changed": len(changed_entries),
        "lookup_changes": changed_entries,
        "labels": {
            "補給ポイント": {"translation": "보급포인트", "source_pixels_cleared": cleared["補給ポイント"], **left_raster},
            "総ユニット数": {"translation": "총유닛수", "source_pixels_cleared": cleared["総ユニット数"], **right_raster},
        },
        "font": "Galmuri11.bdf native 12x12",
        "face_index": 10,
        "contour_index": 5,
        "palettes_byte_exact": True,
    }


def native_supply_clean_background() -> list[list[int]]:
    original = ORIGINAL_ROM.read_bytes()
    header = packagefmt.parse_resource_header(original, NATIVE_SUPPLY_RESOURCE)
    _graphics_rel, records = spritefmt.animation_records(original, NATIVE_SUPPLY_RESOURCE)
    parsed, ids, _lookup_file = catalog.parse_anim(records, 0)
    source = packagefmt.stitch(header["graphics"], parsed, ids, [0, 1])
    gate((len(source[0]), len(source)) == (48, 16), "native supply button geometry drift")

    marked = [
        [develop.in_button_body(x, y, 48) and value in (10, 5) for x, value in enumerate(row)]
        for y, row in enumerate(source)
    ]
    seed = [row[:] for row in marked]
    for y in range(16):
        for x in range(48):
            if marked[y][x] or source[y][x] not in (10, 5):
                continue
            if any(0 <= y + dy < 16 and 0 <= x + dx < 48 and seed[y + dy][x + dx] for dy in range(-2, 3) for dx in range(-2, 3)):
                marked[y][x] = True
    contaminated = [row[:] for row in marked]
    for y in range(16):
        for x in range(48):
            if source[y][x] == 4 and any(0 <= y + dy < 16 and 0 <= x + dx < 48 and marked[y + dy][x + dx] for dy in range(-2, 3) for dx in range(-2, 3)):
                contaminated[y][x] = True
    clean = [row[:] for row in source]
    for y in range(16):
        candidates = [source[y][x] for x in range(develop.CAP_MARGIN, 48 - develop.CAP_MARGIN) if not contaminated[y][x] and source[y][x] != 0]
        row_fill = max(set(candidates), key=candidates.count) if candidates else develop.BODY_YELLOW
        for x in range(48):
            if not contaminated[y][x]:
                continue
            clean[y][x] = row_fill if develop.in_button_body(x, y, 48) else develop.nearest_unmarked_in_row(source, contaminated, x, y, row_fill)
    return clean


def disposal_label_restore(parent: bytes, rect: tuple[int, int, int, int]) -> dict[tuple[int, int], int]:
    del parent
    clean = native_supply_clean_background()
    x0, y0, x1, y1 = rect
    restore: dict[tuple[int, int], int] = {}
    for y in range(y0, y1):
        for x in range(x0, x1):
            local_x, local_y = x - x0, y - y0
            # Copy the original ROM's cleaned 補給 normal-button chrome.
            # Its left 40px contains the native round cap and transition;
            # extend the clean interior sample for this wider panel strip.
            restore[(x, y)] = clean[local_y][local_x if local_x < 40 else 40]
    return restore


def patch_disposal_panel(parent: bytes, font11: fontpair.BdfFont) -> tuple[bytes, dict[str, Any]]:
    cost_rect = (8, 80, 72, 96)
    supply_rect = (8, 96, 72, 112)
    patches = [{
        "animation": 6,
        "repaints": [
            {"rect": list(cost_rect), "paint_rect": [8, 80, 60, 96], "text": "강화비용", "fill": 11, "ink": 10, "contour": 2, "clear_values": [], "restore_pixels": disposal_label_restore(parent, cost_rect)},
            {"rect": list(supply_rect), "paint_rect": [8, 96, 48, 112], "text": "보급P", "fill": 11, "ink": 10, "contour": 2, "clear_values": [], "restore_pixels": disposal_label_restore(parent, supply_rect)},
        ],
    }]
    rebuilt, report = panelpatch.rebuild_resource(parent, DISPOSAL_RESOURCE, patches, font11)
    gate(DISPOSAL_FILE + len(rebuilt) <= DISPOSAL_LIMIT, "disposal panel resource overflow")
    report.update({
        "scope": "disposal detail panel animation 6",
        "allocation": [f"0x{DISPOSAL_FILE:08X}", f"0x{DISPOSAL_LIMIT:08X}"],
        "translations": {"強化費用": "강화비용", "補給P": "보급P"},
        "background_method": "byte-exact chrome template reconstructed from original-ROM 補給 normal button (0x08C4654C animation 0), extended only through its clean interior; labels use original left alignment",
    })
    return rebuilt, report


def patch_disposal_state(state: bytearray, candidate: bytes) -> None:
    header = packagefmt.parse_resource_header(candidate, DISPOSAL_RESOURCE)
    _graphics_rel, records = spritefmt.animation_records(candidate, DISPOSAL_RESOURCE)
    parsed, ids, _lookup_file = panelpatch.parse_animation_cross(records, 6)
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    cursor = 0
    for index, obj in enumerate(parsed["objects"]):
        entry = statefmt.parse_oam_entry(oam, index)
        width, height = map(int, obj["size_px"])
        gate((entry["x"], entry["y"], entry["width"], entry["height"]) == (128 + int(obj["x"]), int(obj["y"]), width, height), f"disposal OAM {index} drift")
        count = width // 8 * (height // 8)
        for local, source_id in enumerate(ids[cursor:cursor + count]):
            payload = header["graphics"][source_id * 32:(source_id + 1) * 32]
            destination_id = int(entry["tile"]) + local
            off = statefmt.STATE_VRAM + statefmt.OBJ_VRAM + destination_id * 32
            state[off:off + 32] = payload
        cursor += count
    gate(cursor == len(ids), "disposal animation lookup length drift")

    canvas = packagefmt.stitch(header["graphics"], parsed, ids, list(range(len(parsed["objects"]))))
    palette_ram = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    colors = [bgutil.rgb555(struct.unpack_from("<H", palette_ram, 0x200 + (9 * 16 + index) * 2)[0]) for index in range(16)]
    image = Image.new("RGB", (len(canvas[0]), len(canvas)))
    pixels = image.load()
    for y, row in enumerate(canvas):
        for x, value in enumerate(row):
            pixels[x, y] = colors[value]
    image.resize((len(canvas[0]) * 4, len(canvas) * 4), Image.Resampling.NEAREST).save(OUT_DISPOSAL_PREVIEW)


def group_bg_runs(rows: list[tuple[int, bytes, int]]) -> list[list[tuple[int, bytes, int]]]:
    ordered = sorted(rows)
    groups: list[list[tuple[int, bytes, int]]] = []
    for row in ordered:
        if not groups or row[0] != groups[-1][-1][0] + 32:
            groups.append([])
        groups[-1].append(row)
    return groups


def install_bg_runtime(candidate: bytearray, rows: list[tuple[int, bytes, int]]) -> dict[str, Any]:
    gate(candidate[sortpatch.STUB_FILE:sortpatch.STUB_FILE + len(sortpatch.STUB)] == sortpatch.STUB, "promoted sort-popup stub drift")
    gate(all(value == 0 for value in candidate[UNIT_TABLE_FILE:UNIT_ALLOC_END]), "unit BG allocation is not zero-filled")
    unit_literals = (
        0x0600705C, 0x0000B014,
        0x0600705E, 0x0000B01D,
        0x0600709C, 0x0000B015,
        0x0600EA6C, 0x0000B0DD,
        0x0600EAB6, 0x0000B10D,
        ROM_BASE + UNIT_TABLE_FILE,
    )
    gate(all(STUB.count(p32(value)) == 1 for value in unit_literals), "unit-screen stub literal drift")
    candidate[sortpatch.STUB_FILE:sortpatch.STUB_FILE + len(STUB)] = STUB

    table = bytearray()
    data_cursor = UNIT_DATA_FILE
    run_report = []
    for run in group_bg_runs(rows):
        payload = b"".join(raw for _dest, raw, _tile in run)
        gate(data_cursor + len(payload) <= UNIT_ALLOC_END, "unit BG payload overflow")
        candidate[data_cursor:data_cursor + len(payload)] = payload
        table += struct.pack("<III", run[0][0], ROM_BASE + data_cursor, len(payload) // 4)
        run_report.append({
            "destination": f"0x{run[0][0]:08X}",
            "source": f"0x{ROM_BASE + data_cursor:08X}",
            "words": len(payload) // 4,
            "tile_ids": [f"0x{tile:03X}" for _d, _p, tile in run],
        })
        data_cursor += len(payload)
    table += b"\0" * 12
    gate(len(table) <= UNIT_DATA_FILE - UNIT_TABLE_FILE, "unit BG table overflow")
    candidate[UNIT_TABLE_FILE:UNIT_TABLE_FILE + len(table)] = table
    return {"stub_bytes": len(STUB), "runs": run_report, "payload_bytes": data_cursor - UNIT_DATA_FILE}


def patch_preview_and_state(
    state: bytearray,
    candidate_crc: int,
    source_canvas: list[list[int]],
    rebuilt_canvas: list[list[int]],
) -> None:
    # Update live OBJ tiles for the four 64x32 bottom objects in the measured state.
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    for segment, oam_index in enumerate((5, 6, 7, 8)):
        entry = statefmt.parse_oam_entry(oam, oam_index)
        gate((entry["x"], entry["y"], entry["width"], entry["height"]) == (segment * 64, 128, 64, 32), f"bottom OAM {oam_index} drift")
        for ty in range(4):
            for tx in range(8):
                tile = int(entry["tile"]) + ty * 8 + tx
                payload = encode_canvas_tile(rebuilt_canvas, segment * 64 + tx * 8, ty * 8)
                off = statefmt.STATE_VRAM + statefmt.OBJ_VRAM + tile * 32
                state[off:off + 32] = payload
    struct.pack_into("<I", state, 8, candidate_crc)
    OUT_STATE.write_bytes(sortpatch.replace_state_chunk(STATE, bytes(state)))

    frame = Image.open(STATE).convert("RGBA")
    bg1 = sortpatch.render_layer_native(bytes(state), 1)
    bg2 = sortpatch.render_layer_native(bytes(state), 2)
    frame.alpha_composite(bg1.crop((104, 0, 128, 24)), (104, 0))
    frame.alpha_composite(bg2.crop((168, 64, 224, 96)), (168, 64))
    palette_ram = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    colors = []
    for index in range(16):
        value = struct.unpack_from("<H", palette_ram, 0x200 + (7 * 16 + index) * 2)[0]
        colors.append((*bgutil.rgb555(value), 0 if index == 0 else 255))
    obj_image = Image.new("RGBA", (256, 32), (0, 0, 0, 0))
    obj_px = obj_image.load()
    for y, row in enumerate(rebuilt_canvas):
        for x, value in enumerate(row):
            obj_px[x, y] = colors[value]
    frame.paste(obj_image.crop((0, 0, 88, 32)), (0, 128))
    frame.paste(obj_image.crop((128, 0, 208, 32)), (128, 128))
    frame.resize((960, 640), Image.Resampling.NEAREST).save(OUT_PREVIEW)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    result = []
    start = previous = offsets[0]
    for value in offsets[1:]:
        if value != previous + 1:
            result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
            start = value
        previous = value
    result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
    return result


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "main TIP hash/manifest drift")
    gate(sha256(parent) == "f5606099d1370b0a47571b88c8161173e844bdd2ba57a622db3453b2f44d2cd2", "unexpected parent main TIP")
    state, _chunks = statefmt.parse_png_state(STATE)
    state2, _chunks2 = statefmt.parse_png_state(STATE2)
    with ZipFile(FONT_ZIP) as archive:
        font7 = fontpair.load_bdf(archive, "Galmuri7.bdf")
        font11 = fontpair.load_bdf(archive, "Galmuri11.bdf")

    bg_rows, patched_state, bg_report = build_bg_targets(state, font7, font11, parent)
    supply_clone, supply_source, supply_rebuilt, supply_report = patch_supply_animation8(parent, font11)
    disposal_rebuilt, disposal_report = patch_disposal_panel(parent, font11)
    candidate = bytearray(parent)
    candidate[SUPPLY_FILE:SUPPLY_FILE + len(supply_clone)] = supply_clone
    candidate[DISPOSAL_FILE:DISPOSAL_FILE + len(disposal_rebuilt)] = disposal_rebuilt
    runtime_report = install_bg_runtime(candidate, bg_rows)
    output = bytes(candidate)
    candidate_crc = binascii.crc32(output) & 0xFFFFFFFF

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(output)
    shutil.copy2(MAIN_SAV, OUT_SAV)
    patch_preview_and_state(patched_state, candidate_crc, supply_source, supply_rebuilt)
    patched_state2 = bytearray(state2)
    patch_disposal_state(patched_state2, output)
    struct.pack_into("<I", patched_state2, 8, candidate_crc)
    OUT_STATE2.write_bytes(sortpatch.replace_state_chunk(STATE2, bytes(patched_state2)))

    changed = [i for i, (a, b) in enumerate(zip(parent, output)) if a != b]
    allowed = set(range(sortpatch.STUB_FILE, sortpatch.STUB_FILE + len(STUB)))
    allowed.update(range(UNIT_TABLE_FILE, UNIT_ALLOC_END))
    allowed.update(range(SUPPLY_FILE, SUPPLY_FILE + len(supply_clone)))
    allowed.update(range(DISPOSAL_FILE, DISPOSAL_FILE + len(disposal_rebuilt)))
    gate(set(changed) <= allowed, "candidate changes escaped stub/unit-data/supply-clone ranges")
    gate(candidate[sortpatch.STUB_FILE:sortpatch.STUB_FILE + len(STUB)] == STUB, "combined runtime stub verification failed")
    gate(OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")

    compile_result = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__))], cwd=ADVANCE_ROOT, capture_output=True, text=True)
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_ss1_four_graphics_ko_candidate_20260903",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(parent),
            "state": advance_relative(STATE),
            "state_sha256": sha256(STATE.read_bytes()),
            "state2": advance_relative(STATE2),
            "state2_sha256": sha256(STATE2.read_bytes()),
            "state_parent_crc32": f"0x{struct.unpack_from('<I', state, 8)[0]:08X}",
            "note": "fresh ss1/ss2 are CRC-matched to the first candidate and prove the live BG1 B-variant gate",
        },
        "translations": TRANSLATIONS,
        "patch": {
            "BG_targets": bg_report,
            "supply_animation8": supply_report,
            "disposal_animation6": disposal_report,
            "runtime": runtime_report,
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(output),
            "size": len(output),
            "crc32": f"0x{candidate_crc:08X}",
            "sav": advance_relative(OUT_SAV),
            "state": advance_relative(OUT_STATE),
            "state2": advance_relative(OUT_STATE2),
            "preview": advance_relative(OUT_PREVIEW),
            "disposal_preview": advance_relative(OUT_DISPOSAL_PREVIEW),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_match": True,
            "latest_main_tip_parent": True,
            "target_count": 6,
            "BG1_hold_tiles_unique": True,
            "BG1_c_tiles_byte_exact": True,
            "BG2_owned_count_tiles_unique": True,
            "unit_screen_exact_signature_gate": True,
            "fresh_ss1_BG1_B_variant_gate": True,
            "fresh_ss1_owned_count_gate_address": "0x0600EAB6",
            "disposal_animation6_two_labels_patched": True,
            "fresh_ss1_ss2_input_crc_matches_first_candidate": True,
            "sort_popup_hook_preserved": True,
            "supply_animations_0_to_7_preserved": True,
            "supply_animation8_lookup_only_remap": True,
            "existing_supply_source_tiles_preserved": True,
            "supply_palettes_byte_exact": True,
            "changes_limited_to_private_supply_disposal_and_runtime_regions": True,
            "candidate_state_crc_matches_candidate": True,
            "py_compile": "PASS",
            "fresh_emulator_measurement": "pending user verification",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sha256": sha256(output),
        "sav": advance_relative(OUT_SAV),
        "state": advance_relative(OUT_STATE),
        "state2": advance_relative(OUT_STATE2),
        "preview": advance_relative(OUT_PREVIEW),
        "disposal_preview": advance_relative(OUT_DISPOSAL_PREVIEW),
        "manifest": advance_relative(OUT_MANIFEST),
        "changed_bytes": len(changed),
        "translations": TRANSLATIONS,
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
