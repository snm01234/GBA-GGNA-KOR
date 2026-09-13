#!/usr/bin/env python3
"""Koreanize the load/save confirmation popup normal/focus OBJ graphics.

Parent is the approved-on-screen load-summary follow-up candidate.  The fresh
mGBA ss1 proves the confirmation popup is animation 3 of shared sprite package
0x08C7504C: yellow normal ロード実行 on top and blue focused キャンセル below.
Animations 2/3 are the two focus states of that pair; animations 0/1 are the
parallel セーブ実行 / キャンセル pair and are translated as the structurally
identical similar area.

The original shared package is not rewritten.  A private clone keeps all 262
native source tiles byte-exact, appends only Korean button variants, remaps the
source-tile lookup entries of animations 0..3, and redirects the four remaining
consumers of 0x08C7504C.  The already-separated suspend consumer at 0x08020B98
continues to use its own 0x09274000 clone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_load_confirm_popup_state_20260831 as state_analysis  # noqa: E402
import analyze_ggen_advance_settings_suspend_ui as sprite  # noqa: E402
import build_ggen_advance_map_menu_ui_ko_poc as tileops  # noqa: E402
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP  # noqa: E402

ROM_BASE = 0x08000000
RESOURCE = sprite.SUSPEND_RESOURCE
RESOURCE_OFFSET = RESOURCE - ROM_BASE
RESOURCE_POINTER_REFS = [0x0001212C, 0x000121CC, 0x00026B6C, 0x0007385C]
SUSPEND_POINTER_REF = 0x00020B98
SUSPEND_CLONE_ADDRESS = 0x09274000

PARENT = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_followup_candidate_20260831.gba"
PARENT_SHA256 = "63484e87005c3efe5426dda6829160a7c45b9076e5b88db6c5f60eaeecea3422"
PARENT_SAV = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_followup_candidate_20260831.sav"
STATE = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_followup_candidate_20260831.ss1"
STATE_SHA256 = "af54d9bc82b144f68c7f8a4bd99f9be5d4598e718571632d525531457cc800fe"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui"
DEFAULT_OUT = OUT_DIR / "ggen_advance_load_summary_ui_ko_popup_candidate_20260831.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_load_summary_ui_ko_popup_candidate_20260831.sav"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_load_confirm_popup_ko_preview_20260831.png"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_load_confirm_popup_ko_20260831.json"
CLONE_OFFSET = 0x01284000
CLONE_ADDRESS = ROM_BASE + CLONE_OFFSET

PALETTE_COUNT = 6
GRAPHICS_REL = 0x0E04
PALETTE_REL = 0x2EC4
ORIGINAL_SOURCE_TILES = 262

FOCUS_OBJECTS = (8, 9, 10)
NORMAL_OBJECTS = (11, 12, 13)
FOCUS_FACE = 12
FOCUS_CONTOUR = 1
NORMAL_FACE = 11
NORMAL_CONTOUR = 5
CLEAR_X0 = 5
CLEAR_X1 = 70  # exclusive; covers every source glyph/contour pixel, preserves caps
EXPECTED_NORMAL_ROWS = [11, 9] + [10] * 12 + [9, 11]
EXPECTED_FOCUS_ROWS = [8, 9] + [10] * 12 + [9, 8]

TRANSLATIONS = {
    "load_execute": "로드실행",
    "cancel": "캔슬",
    "save_execute": "세이브실행",
}

# animation -> (focused semantic, normal semantic)
ANIMATION_BUTTONS = {
    0: ("save_execute", "cancel"),
    1: ("cancel", "save_execute"),
    2: ("load_execute", "cancel"),
    3: ("cancel", "load_execute"),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def pointer_hits(data: bytes, value: int) -> list[int]:
    needle = struct.pack("<I", value)
    hits: list[int] = []
    cursor = 0
    while True:
        found = data.find(needle, cursor)
        if found < 0:
            return hits
        hits.append(found)
        cursor = found + 1


def decode_tile(graphics: bytes | bytearray, tile_id: int) -> list[list[int]]:
    return tileops.decode_tile(graphics, tile_id)


def stitch_button(graphics: bytes | bytearray, parsed: dict[str, Any], source: dict[str, Any], object_indices: tuple[int, int, int]) -> list[list[int]]:
    objects = [parsed["objects"][index] for index in object_indices]
    x0 = min(int(obj["x"]) for obj in objects)
    y0 = min(int(obj["y"]) for obj in objects)
    x1 = max(int(obj["x"]) + int(obj["size_px"][0]) for obj in objects)
    y1 = max(int(obj["y"]) + int(obj["size_px"][1]) for obj in objects)
    gate((x1 - x0, y1 - y0) == (80, 16), "button geometry drift")
    pixels = [[0] * 80 for _ in range(16)]
    for index in object_indices:
        obj = parsed["objects"][index]
        ids = source["by_object"][index]
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        gate(len(ids) == wt * ht, "button source lookup length drift")
        for ty in range(ht):
            for tx in range(wt):
                tile = decode_tile(graphics, int(ids[ty * wt + tx]))
                ox = int(obj["x"]) - x0 + tx * 8
                oy = int(obj["y"]) - y0 + ty * 8
                for yy in range(8):
                    pixels[oy + yy][ox:ox + 8] = tile[yy]
    return pixels


def make_12x12_mask(text: str, font: fontpair.BdfFont) -> tuple[list[list[bool]], int]:
    return paintops.make_text_mask(text, font, 80, 16, cell_width=12, space_width=4)


def rebuild_button(source_pixels: list[list[int]], text: str, font: fontpair.BdfFont, *, focus: bool) -> tuple[list[list[int]], dict[str, Any]]:
    gate(len(source_pixels) == 16 and all(len(row) == 80 for row in source_pixels), "button source raster dimensions drift")
    face = FOCUS_FACE if focus else NORMAL_FACE
    contour = FOCUS_CONTOUR if focus else NORMAL_CONTOUR
    expected_rows = EXPECTED_FOCUS_ROWS if focus else EXPECTED_NORMAL_ROWS
    pixels = [row[:] for row in source_pixels]

    # The two button styles use a fixed horizontal gradient band.  Some source
    # labels (notably the focused save action) reach unusually far left, so a
    # local side-column mode is not a reliable background estimator for every
    # animation.  Use the style's native row pattern, but require that each
    # source row still contains that expected chrome color before restoration.
    row_backgrounds = expected_rows[:]

    source_text_pixels = 0
    for y in range(16):
        for x in range(CLEAR_X0, CLEAR_X1):
            if pixels[y][x] in (face, contour):
                pixels[y][x] = row_backgrounds[y]
                source_text_pixels += 1
    gate(source_text_pixels > 0, f"{text}: no Japanese face/contour pixels cleared")
    clean_base = [row[:] for row in pixels]

    mask, text_width = make_12x12_mask(text, font)
    ink, outline = paintops.paint_mask(pixels, mask, ink=face, contour=contour)
    gate(ink > 0 and outline > 0, f"{text}: Korean raster empty")

    expected = [row[:] for row in clean_base]
    expected_ink, expected_outline = paintops.paint_mask(expected, mask, ink=face, contour=contour)
    gate((expected_ink, expected_outline) == (ink, outline), f"{text}: Korean contour accounting drift")
    gate(expected == pixels, f"{text}: final raster is not clean base + Korean mask/contour")

    # Explicit residue gate: before Korean repaint, the entire original text
    # well contains only the recovered native gradient/chrome.
    for y in range(16):
        for x in range(CLEAR_X0, CLEAR_X1):
            if source_pixels[y][x] in (face, contour):
                gate(clean_base[y][x] == row_backgrounds[y], f"{text}: Japanese residue at {x},{y}")

    return pixels, {
        "translation": text,
        "style": "focus_blue" if focus else "normal_yellow",
        "font": "Galmuri11.bdf native 12x12",
        "face_index": face,
        "contour_index": contour,
        "clear_x": [CLEAR_X0, CLEAR_X1 - 1],
        "row_background_indices": row_backgrounds,
        "source_face_contour_pixels_cleared": source_text_pixels,
        "korean_text_width_px": text_width,
        "korean_ink_pixels": ink,
        "korean_contour_pixels": outline,
        "japanese_face_shadow_residue": 0,
    }


def tile_payload_from_canvas(canvas: list[list[int]], obj: dict[str, Any], group_x0: int, group_y0: int, tx: int, ty: int) -> bytes:
    ox = int(obj["x"]) - group_x0 + tx * 8
    oy = int(obj["y"]) - group_y0 + ty * 8
    tile = [canvas[oy + yy][ox:ox + 8] for yy in range(8)]
    return tileops.encode_tile(tile)


def build_clone(jp: bytes, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], dict[tuple[str, bool], list[list[int]]]]:
    gate(u32(jp, RESOURCE_OFFSET + 0x00) == 0, "sprite resource kind drift")
    gate(u32(jp, RESOURCE_OFFSET + 0x04) == PALETTE_COUNT, "sprite palette count drift")
    gate(u32(jp, RESOURCE_OFFSET + 0x08) == GRAPHICS_REL, "sprite graphics offset drift")
    gate(u32(jp, RESOURCE_OFFSET + 0x0C) == PALETTE_REL, "sprite palette offset drift")
    original_size = PALETTE_REL + PALETTE_COUNT * 32
    original = jp[RESOURCE_OFFSET:RESOURCE_OFFSET + original_size]
    gate(len(original) == original_size, "source sprite resource truncated")
    original_graphics = original[GRAPHICS_REL:PALETTE_REL]
    gate(len(original_graphics) == ORIGINAL_SOURCE_TILES * 32, "source graphic tile count drift")
    palette = original[PALETTE_REL:PALETTE_REL + PALETTE_COUNT * 32]

    _graphics_rel, records = sprite.animation_records(jp, RESOURCE)
    parsed: dict[int, dict[str, Any]] = {}
    sources: dict[int, dict[str, Any]] = {}
    record_starts: dict[int, int] = {}
    for animation in range(4):
        start, record = records[animation]
        p = sprite.parse_animation_oam(record)
        s = sprite.parse_animation_source_tiles(record, p)
        gate(p["object_count"] == 14 and s["total_source_entries"] == 66, f"animation {animation} popup record drift")
        parsed[animation] = p
        sources[animation] = s
        record_starts[animation] = start

    # Strong state binding: animation 3 must reproduce every live popup OBJ tile
    # from the fresh ss1, including frame and both choice rows.
    state, _chunks = state_analysis.statefmt.parse_png_state(STATE)
    vram = state[state_analysis.statefmt.STATE_VRAM:state_analysis.statefmt.STATE_IWRAM]
    live_obj = vram[state_analysis.statefmt.OBJ_VRAM:]
    p3, s3 = parsed[3], sources[3]
    for obj in p3["objects"]:
        source_ids = s3["by_object"][int(obj["index"])]
        dest = int(obj["tile_start"])
        for local, source_id in enumerate(source_ids):
            expected = original_graphics[int(source_id) * 32:int(source_id) * 32 + 32]
            actual = bytes(live_obj[(dest + local) * 32:(dest + local) * 32 + 32])
            gate(actual == expected, f"fresh state animation3 OBJ/source mismatch at dest {dest+local} source {source_id}")

    # Derive the native yellow/blue row bands once from the measured animation
    # 3 state, where x=4..9 is text-free for both visible rows.  Other action
    # labels can extend into that side sample, so all variants reuse these
    # state-proven chrome bands during glyph removal.
    measured_focus = stitch_button(original_graphics, p3, s3, FOCUS_OBJECTS)
    measured_normal = stitch_button(original_graphics, p3, s3, NORMAL_OBJECTS)
    for y, expected in ((0, 8), (1, 9), (2, 10), (14, 9), (15, 8)):
        gate(measured_focus[y].count(expected) >= 8, f"measured focus chrome row {y} lost expected index {expected}")
    for y, expected in ((0, 11), (1, 9), (2, 10), (14, 9), (15, 11)):
        gate(measured_normal[y].count(expected) >= 8, f"measured normal chrome row {y} lost expected index {expected}")

    # The save pair is structurally parallel to the measured load pair: both
    # pairs reuse the exact normal/focus cancel source maps and replace only the
    # top action label; the final 行/caps are shared between load/save focus.
    gate(sources[2]["by_object"][11:14] == sources[0]["by_object"][11:14], "load/save cancel-normal source sharing drift")
    gate(sources[3]["by_object"][8:11] == sources[1]["by_object"][8:11], "load/save cancel-focus source sharing drift")
    gate(sources[2]["by_object"][10] == sources[0]["by_object"][10], "load/save focus rightmost 行/cap sharing drift")

    original_canvases: dict[tuple[str, bool], list[list[int]]] = {}
    patched_canvases: dict[tuple[str, bool], list[list[int]]] = {}
    reports: dict[str, Any] = {}

    for animation, (focus_semantic, normal_semantic) in ANIMATION_BUTTONS.items():
        for focus, semantic, object_indices in (
            (True, focus_semantic, FOCUS_OBJECTS),
            (False, normal_semantic, NORMAL_OBJECTS),
        ):
            key = (semantic, focus)
            source_canvas = stitch_button(original_graphics, parsed[animation], sources[animation], object_indices)
            if key in original_canvases:
                gate(source_canvas == original_canvases[key], f"duplicate source canvas drift for {key}")
                continue
            original_canvases[key] = source_canvas
            patched, report = rebuild_button(source_canvas, TRANSLATIONS[semantic], font, focus=focus)
            patched_canvases[key] = patched
            reports[f"{semantic}_{'focus' if focus else 'normal'}"] = report

    gate(set(patched_canvases) == {
        ("load_execute", True), ("load_execute", False),
        ("cancel", True), ("cancel", False),
        ("save_execute", True), ("save_execute", False),
    }, "button variant coverage drift")

    existing_payload_to_id: dict[bytes, int] = {}
    for tile_id in range(ORIGINAL_SOURCE_TILES):
        payload = original_graphics[tile_id * 32:tile_id * 32 + 32]
        existing_payload_to_id.setdefault(payload, tile_id)
    private_payload_to_id: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    animation_maps: dict[str, Any] = {}

    for animation, (focus_semantic, normal_semantic) in ANIMATION_BUTTONS.items():
        p, s = parsed[animation], sources[animation]
        record_rel = record_starts[animation] - RESOURCE_OFFSET
        source_table_rel = record_rel + int(s["source_table_offset"])
        entry_offset = 0
        per_object_offsets: list[int] = []
        for obj in p["objects"]:
            per_object_offsets.append(entry_offset)
            entry_offset += int(obj["tile_count"])
        gate(entry_offset == 66, f"animation {animation} source entry total drift")
        anim_report: dict[str, Any] = {}

        for focus, semantic, object_indices in (
            (True, focus_semantic, FOCUS_OBJECTS),
            (False, normal_semantic, NORMAL_OBJECTS),
        ):
            canvas = patched_canvases[(semantic, focus)]
            objects = [p["objects"][index] for index in object_indices]
            gx0 = min(int(obj["x"]) for obj in objects)
            gy0 = min(int(obj["y"]) for obj in objects)
            before_ids: list[int] = []
            after_ids: list[int] = []
            for index in object_indices:
                obj = p["objects"][index]
                ids = s["by_object"][index]
                wt = int(obj["size_px"][0]) // 8
                ht = int(obj["size_px"][1]) // 8
                for ty in range(ht):
                    for tx in range(wt):
                        pos = ty * wt + tx
                        old_id = int(ids[pos])
                        payload = tile_payload_from_canvas(canvas, obj, gx0, gy0, tx, ty)
                        old_payload = original_graphics[old_id * 32:old_id * 32 + 32]
                        if payload == old_payload:
                            new_id = old_id
                        elif payload in existing_payload_to_id:
                            new_id = existing_payload_to_id[payload]
                        else:
                            new_id = private_payload_to_id.get(payload, -1)
                            if new_id < 0:
                                new_id = ORIGINAL_SOURCE_TILES + len(private_payloads)
                                gate(new_id <= 0xFFFF, "private source tile ID overflow")
                                private_payload_to_id[payload] = new_id
                                private_payloads.append(payload)
                        lookup_index = per_object_offsets[index] + pos
                        lookup_offset = source_table_rel + lookup_index * 2
                        previous = lookup_writes.get(lookup_offset)
                        gate(previous is None or previous == new_id, f"conflicting source lookup write at 0x{lookup_offset:X}")
                        lookup_writes[lookup_offset] = new_id
                        before_ids.append(old_id)
                        after_ids.append(new_id)
            anim_report[f"{'focus' if focus else 'normal'}_{semantic}"] = {
                "objects": list(object_indices),
                "original_source_ids": [f"0x{x:03X}" for x in before_ids],
                "remapped_source_ids": [f"0x{x:03X}" for x in after_ids],
                "changed_entries": sum(a != b for a, b in zip(before_ids, after_ids)),
            }
        animation_maps[str(animation)] = anim_report

    graphics = original_graphics + b"".join(private_payloads)
    new_palette_rel = GRAPHICS_REL + len(graphics)
    clone = bytearray(new_palette_rel + len(palette))
    clone[:GRAPHICS_REL] = original[:GRAPHICS_REL]
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    for rel, new_id in lookup_writes.items():
        struct.pack_into("<H", clone, rel, new_id)
    clone[GRAPHICS_REL:new_palette_rel] = graphics
    clone[new_palette_rel:new_palette_rel + len(palette)] = palette

    expected_pre = bytearray(original[:GRAPHICS_REL])
    struct.pack_into("<I", expected_pre, 0x0C, new_palette_rel)
    for rel, new_id in lookup_writes.items():
        struct.pack_into("<H", expected_pre, rel, new_id)
    gate(clone[:GRAPHICS_REL] == expected_pre, "clone pre-graphics bytes changed outside animation0-3 source lookup/header")
    gate(graphics[:len(original_graphics)] == original_graphics, "clone rewrote original 262 source graphics")
    gate(clone[new_palette_rel:] == palette, "clone palette changed")

    reports["materialization"] = {
        "original_source_tiles": ORIGINAL_SOURCE_TILES,
        "private_source_tiles_appended": len(private_payloads),
        "source_tiles_after_append": len(graphics) // 32,
        "source_lookup_entries_written": len(lookup_writes),
        "source_lookup_entries_changed": sum(
            struct.unpack_from("<H", original, rel)[0] != new_id for rel, new_id in lookup_writes.items()
        ),
        "old_palette_relative_offset": f"0x{PALETTE_REL:04X}",
        "new_palette_relative_offset": f"0x{new_palette_rel:04X}",
        "animation_maps": animation_maps,
    }
    return bytes(clone), reports, patched_canvases


def render_preview(canvases: dict[tuple[str, bool], list[list[int]]], palette: bytes, path: Path) -> None:
    def rgb555(value: int) -> tuple[int, int, int]:
        return ((value & 31) * 8, ((value >> 5) & 31) * 8, ((value >> 10) & 31) * 8)

    banks: dict[int, list[tuple[int, int, int]]] = {}
    for bank in (0, 1):
        banks[bank] = [rgb555(struct.unpack_from("<H", palette, (bank * 16 + i) * 2)[0]) for i in range(16)]

    scale = 4
    margin = 8
    canvas = Image.new("RGB", (80 * scale + margin * 2, (16 * scale + margin) * 3 + margin), (32, 32, 32))
    for row, semantic in enumerate(("load_execute", "cancel", "save_execute")):
        # show normal left half and focus right half by stacking two 80x16 rows
        # within the same 80x16 preview width is impossible; use normal for even
        # scanlines and focus as a second block immediately below via a 160-wide
        # temporary, then resize the outer canvas lazily if needed.
        pass

    # Rebuild as 160x(3*16) with normal/focus side-by-side.
    out = Image.new("RGB", (160 * scale + margin * 2, 48 * scale + margin * 4), (32, 32, 32))
    for row, semantic in enumerate(("load_execute", "cancel", "save_execute")):
        for col, focus in enumerate((False, True)):
            pixels = canvases[(semantic, focus)]
            bank = 1 if focus else 0
            small = Image.new("RGB", (80, 16))
            for y in range(16):
                for x in range(80):
                    small.putpixel((x, y), banks[bank][pixels[y][x]])
            enlarged = small.resize((80 * scale, 16 * scale), Image.Resampling.NEAREST)
            out.paste(enlarged, (margin + col * 80 * scale, margin + row * (16 * scale + margin)))
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    rows: list[list[str]] = []
    start = prev = offsets[0]
    for value in offsets[1:]:
        if value != prev + 1:
            rows.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
            start = value
        prev = value
    rows.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PARENT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    parent = args.input.read_bytes()
    jp = JP_ROM.read_bytes()
    gate(len(parent) == 32 * 1024 * 1024, "parent must be 32 MiB")
    gate(sha256(parent) == PARENT_SHA256, f"parent hash drift: {sha256(parent)}")
    gate(STATE.is_file() and sha256(STATE.read_bytes()) == STATE_SHA256, "fresh popup state hash drift")

    original_size = PALETTE_REL + PALETTE_COUNT * 32
    original_resource = jp[RESOURCE_OFFSET:RESOURCE_OFFSET + original_size]
    gate(parent[RESOURCE_OFFSET:RESOURCE_OFFSET + original_size] == original_resource, "parent original C7504C resource is no longer JP byte-exact")
    gate(pointer_hits(parent, RESOURCE) == RESOURCE_POINTER_REFS, f"remaining shared resource refs drift: {[hex(x) for x in pointer_hits(parent, RESOURCE)]}")
    gate(u32(parent, SUSPEND_POINTER_REF) == SUSPEND_CLONE_ADDRESS, "suspend consumer no longer uses its private clone")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
    clone, report, canvases = build_clone(jp, font)
    gate(CLONE_OFFSET + len(clone) <= len(parent), "popup clone exceeds ROM")
    gate(all(value == 0 for value in parent[CLONE_OFFSET:CLONE_OFFSET + len(clone)]), "popup clone allocation is not zero-filled")

    candidate = bytearray(parent)
    candidate[CLONE_OFFSET:CLONE_OFFSET + len(clone)] = clone
    for ref in RESOURCE_POINTER_REFS:
        struct.pack_into("<I", candidate, ref, CLONE_ADDRESS)

    gate(candidate[RESOURCE_OFFSET:RESOURCE_OFFSET + original_size] == original_resource, "candidate rewrote original shared sprite package")
    gate(u32(candidate, SUSPEND_POINTER_REF) == SUSPEND_CLONE_ADDRESS, "candidate disturbed suspend private clone pointer")
    gate(pointer_hits(bytes(candidate), RESOURCE) == [], "candidate still has an unredirected original C7504C consumer")
    clone_hits = pointer_hits(bytes(candidate), CLONE_ADDRESS)
    gate(clone_hits == RESOURCE_POINTER_REFS, f"popup clone refs drift: {[hex(x) for x in clone_hits]}")

    # Parse the clone in-place and reconstruct animation 0..3 buttons from the
    # remapped source lookup to prove the final ROM contains exactly the Korean
    # canvases generated above.
    _graphics_rel, records = sprite.animation_records(bytes(candidate), CLONE_ADDRESS)
    clone_palette_rel = u32(candidate, CLONE_OFFSET + 0x0C)
    clone_graphics = bytes(candidate[CLONE_OFFSET + GRAPHICS_REL:CLONE_OFFSET + clone_palette_rel])
    semantic_seen: dict[tuple[str, bool], list[list[int]]] = {}
    for animation, (focus_semantic, normal_semantic) in ANIMATION_BUTTONS.items():
        p = sprite.parse_animation_oam(records[animation][1])
        s = sprite.parse_animation_source_tiles(records[animation][1], p)
        for focus, semantic, objects in (
            (True, focus_semantic, FOCUS_OBJECTS),
            (False, normal_semantic, NORMAL_OBJECTS),
        ):
            actual = stitch_button(clone_graphics, p, s, objects)
            gate(actual == canvases[(semantic, focus)], f"final clone raster mismatch: animation {animation} {semantic} focus={focus}")
            previous = semantic_seen.get((semantic, focus))
            gate(previous is None or previous == actual, f"duplicate final semantic raster drift: {semantic} focus={focus}")
            semantic_seen[(semantic, focus)] = actual

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    allowed_pointer = set()
    for ref in RESOURCE_POINTER_REFS:
        allowed_pointer.update(range(ref, ref + 4))
    escaped = [i for i in changed if i not in allowed_pointer and not (CLONE_OFFSET <= i < CLONE_OFFSET + len(clone))]
    gate(not escaped, f"changes escaped pointer/clone ranges: {escaped[:12]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    copied_sav = False
    sav_sha = None
    if PARENT_SAV.is_file():
        shutil.copy2(PARENT_SAV, args.out_sav)
        gate(args.out_sav.read_bytes() == PARENT_SAV.read_bytes(), "SAV copy drift")
        copied_sav = True
        sav_sha = sha256(args.out_sav.read_bytes())

    palette = original_resource[PALETTE_REL:PALETTE_REL + PALETTE_COUNT * 32]
    render_preview(canvases, palette, args.preview)

    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_load_confirm_popup_ko_20260831",
        "result": "PASS",
        "source": {
            "parent": str(args.input.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "parent_sha256": sha256(parent),
            "state": str(STATE.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "state_sha256": STATE_SHA256,
            "japanese_resource": f"0x{RESOURCE:08X}",
        },
        "ownership": {
            "state_animation": 3,
            "state_semantics": {
                "normal_yellow": "ロード実行",
                "focus_blue": "キャンセル",
            },
            "state_animation3_all_66_obj_tiles_match_resource_source_lookup": True,
            "resource_original_refs_before": [f"0x{x:08X}" for x in RESOURCE_POINTER_REFS],
            "suspend_private_ref": f"0x{SUSPEND_POINTER_REF:08X}",
            "suspend_private_resource": f"0x{SUSPEND_CLONE_ADDRESS:08X}",
            "similar_pair": {
                "animations": [0, 1],
                "semantic": "セーブ実行 / キャンセル",
                "evidence": "same 14-OBJ geometry; exact cancel normal/focus source maps reused; alternate top action replaces load label and shares final 行/caps",
            },
        },
        "patch": {
            "clone_file_offset": f"0x{CLONE_OFFSET:08X}",
            "clone_address": f"0x{CLONE_ADDRESS:08X}",
            "clone_size": len(clone),
            "translations": {
                "ロード実行": TRANSLATIONS["load_execute"],
                "キャンセル": TRANSLATIONS["cancel"],
                "セーブ実行": TRANSLATIONS["save_execute"],
            },
            "styles": {
                "normal_yellow": {"face": NORMAL_FACE, "contour": NORMAL_CONTOUR},
                "focus_blue": {"face": FOCUS_FACE, "contour": FOCUS_CONTOUR},
            },
            "buttons": report,
            "redirected_refs": [f"0x{x:08X}" for x in RESOURCE_POINTER_REFS],
        },
        "output": {
            "rom": str(args.out.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "rom_sha256": sha256(output),
            "sav": str(args.out_sav.relative_to(ADVANCE_ROOT)).replace("\\", "/") if copied_sav else None,
            "sav_sha256": sav_sha,
            "preview": str(args.preview.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "parent_hash_verified": True,
            "fresh_state_hash_verified": True,
            "original_C7504C_resource_byte_exact": True,
            "original_262_source_graphics_byte_exact_in_clone": True,
            "palette_byte_exact": True,
            "animations_0_3_oam_geometry_byte_exact": True,
            "animations_0_3_final_rasters_exact_clean_base_plus_korean_mask_contour": True,
            "japanese_face_shadow_residue": 0,
            "normal_and_focus_both_translated": True,
            "similar_save_execute_pair_translated": True,
            "suspend_private_clone_pointer_preserved": True,
            "changes_restricted_to_four_resource_refs_and_private_clone": True,
            "canonical_main_tip_modified": False,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "rom": str(args.out),
        "rom_sha256": sha256(output),
        "sav": str(args.out_sav) if copied_sav else None,
        "preview": str(args.preview),
        "manifest": str(args.manifest),
        "changed_bytes": len(changed),
        "private_tiles": report["materialization"]["private_source_tiles_appended"],
        "translations": manifest["patch"]["translations"],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
