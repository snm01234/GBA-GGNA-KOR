#!/usr/bin/env python3
"""Follow up the data-save instruction and save-progress warning graphics.

Parent: cumulative 22.108 candidate.  This build shortens the data-save
instruction to avoid the right-edge overflow and translates state3 animation 10
("セーブ中です / 電源を切らないでください") in a dedicated sprite clone.
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

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_save_progress_state_20260831 as state_analysis
import analyze_ggen_advance_settings_suspend_ui as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_map_menu_ui_ko_poc as tileops
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
PARENT = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.gba"
PARENT_SHA256 = "41d1fe82be15df92c3797febde4fc1201717fa3dddf84c43b9711b952dfe0509"
PARENT_SAV = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.sav"
STATE3 = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.ss3"
STATE_ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_save_progress_state_20260831.json"

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui"
DEFAULT_OUT = OUT_DIR / "ggen_advance_load_summary_ui_ko_save_progress_candidate_20260831.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_load_summary_ui_ko_save_progress_candidate_20260831.sav"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_save_progress_followup_ko_20260831.json"

CURRENT_SHARED_CLONE = 0x0928C000
CURRENT_SHARED_CLONE_OFFSET = CURRENT_SHARED_CLONE - ROM_BASE
SAVE_PROGRESS_CLONE_OFFSET = 0x01298000
SAVE_PROGRESS_CLONE = ROM_BASE + SAVE_PROGRESS_CLONE_OFFSET
SAVE_PROGRESS_POINTER = 0x0001212C
SAVE_PROGRESS_ANIMATION = 10

CURRENT_SAVE_BG = 0x09294000
CURRENT_SAVE_BG_OFFSET = CURRENT_SAVE_BG - ROM_BASE
SAVE_BG_FOLLOWUP_OFFSET = 0x012A0000
SAVE_BG_FOLLOWUP = ROM_BASE + SAVE_BG_FOLLOWUP_OFFSET
SAVE_BG_POINTER = 0x000D590AC

MESSAGE_LINES = ("세이브중입니다", "전원을 끄지말아주세요")
INSTRUCTION = "위데이터를 아래데이터에 덮어씁니다"
TEXT_OBJECTS = tuple(range(2, 10))
MESSAGE_INK = 11
MESSAGE_CONTOUR = 2
MESSAGE_BG = {9, 10}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def pointer_hits(data: bytes, value: int) -> list[int]:
    needle = struct.pack("<I", value)
    hits: list[int] = []
    pos = 0
    while True:
        pos = data.find(needle, pos)
        if pos < 0:
            return hits
        hits.append(pos)
        pos += 1


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    out: list[list[str]] = []
    start = prev = offsets[0]
    for value in offsets[1:]:
        if value != prev + 1:
            out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
            start = value
        prev = value
    out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return out


def encode_tile(pixels: list[list[int]]) -> bytes:
    return tileops.encode_tile(pixels)


def live_obj_tile(obj_vram: bytes, tile: int) -> bytes:
    return bytes(obj_vram[tile * 32 : (tile + 1) * 32])


def build_message_plane_from_state(state: bytes) -> tuple[list[list[int]], list[dict[str, Any]], bytes]:
    oam = state[statefmt.STATE_OAM : statefmt.STATE_VRAM]
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    obj_vram = bytes(vram[statefmt.OBJ_VRAM :])
    visible = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            visible.append(row)
    gate(len(visible) == 12, "state3 visible OAM count drift")
    plane = state_analysis.stitch_live_plane(obj_vram, visible[2:10])
    return plane, visible, obj_vram


def rebuild_message_plane(source: list[list[int]], font: fontpair.BdfFont) -> tuple[list[list[int]], dict[str, Any]]:
    gate(len(source) == 48 and all(len(row) == 144 for row in source), "save-progress plane dimensions drift")
    clean = [row[:] for row in source]
    row_backgrounds: list[dict[str, int]] = []
    cleared = 0
    for y0, y1 in ((9, 23), (25, 39)):
        for y in range(y0, y1):
            samples = [clean[y][x] for x in range(2, 140) if clean[y][x] in MESSAGE_BG]
            gate(samples, f"save-progress row {y} lacks yellow background sample")
            bg_index = Counter(samples).most_common(1)[0][0]
            row_backgrounds.append({"y": y, "index": bg_index})
            for x in range(2, 140):
                if clean[y][x] != bg_index:
                    cleared += 1
                clean[y][x] = bg_index
    gate(cleared > 0, "save-progress Japanese clear changed no pixels")
    clean_base = [row[:] for row in clean]

    lines: list[dict[str, Any]] = []
    for text, y_origin in zip(MESSAGE_LINES, (10, 26)):
        mask, text_width = paintops.make_text_mask(text, font, 144, 48, y_origin=y_origin)
        gate(text_width <= 136, f"save-progress text too wide: {text!r} -> {text_width}px")
        ink, contour = paintops.paint_mask(clean, mask, ink=MESSAGE_INK, contour=MESSAGE_CONTOUR, clip=(2, 9, 140, 39))
        gate(ink > 0 and contour > 0, f"save-progress Korean raster empty: {text}")
        lines.append({"translation": text, "y_origin": y_origin, "text_width_px": text_width, "korean_ink_pixels": ink, "korean_contour_pixels": contour})

    expected = [row[:] for row in clean_base]
    for text, y_origin in zip(MESSAGE_LINES, (10, 26)):
        mask, _ = paintops.make_text_mask(text, font, 144, 48, y_origin=y_origin)
        paintops.paint_mask(expected, mask, ink=MESSAGE_INK, contour=MESSAGE_CONTOUR, clip=(2, 9, 140, 39))
    gate(expected == clean, "save-progress final plane is not clean native panel + Korean masks")
    return clean, {
        "source_pixels_replaced": cleared,
        "clear_bands": [[2, 9, 140, 23], [2, 25, 140, 39]],
        "row_background_indices": row_backgrounds,
        "face_index": MESSAGE_INK,
        "contour_index": MESSAGE_CONTOUR,
        "lines": lines,
        "japanese_face_shadow_residue": 0,
    }


def build_save_progress_clone(parent: bytes, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any]]:
    gate(u32(parent, SAVE_PROGRESS_POINTER) == CURRENT_SHARED_CLONE, "save-progress pointer parent drift")
    gate(u16(parent, 0x000120DC) == 0x230A, "save-progress call no longer selects animation 10")
    off = CURRENT_SHARED_CLONE_OFFSET
    gate(u32(parent, off) == 0 and u32(parent, off + 4) == 6, "shared popup clone header drift")
    graphics_rel = u32(parent, off + 0x08)
    palette_rel = u32(parent, off + 0x0C)
    animation_count = u32(parent, off + 0x10)
    gate(graphics_rel == 0x0E04 and animation_count == 12, "shared popup clone layout drift")
    old_size = palette_rel + 6 * 32
    original = parent[off : off + old_size]
    original_graphics = bytearray(original[graphics_rel:palette_rel])
    old_tile_count = len(original_graphics) // 32
    gate(old_tile_count == 360, f"shared popup clone tile count drift: {old_tile_count}")
    palette = original[palette_rel : palette_rel + 6 * 32]

    _gr, records = bg.animation_records(parent, CURRENT_SHARED_CLONE)
    record_start, record = records[SAVE_PROGRESS_ANIMATION]
    parsed = bg.parse_animation_oam(record)
    gate(parsed["object_count"] == 12, "save-progress animation10 object count drift")
    record_rel = record_start - off
    source_table_rel = record_rel + int(parsed["entries_end"])
    gate(len(record) - int(parsed["entries_end"]) == 244, "save-progress animation10 source table span drift")

    state, _chunks = statefmt.parse_png_state(STATE3)
    source_plane, visible, obj_vram = build_message_plane_from_state(state)
    patched_plane, plane_report = rebuild_message_plane(source_plane, font)
    # State geometry must be the same animation10 placement proved by analyzer.
    for index, src in enumerate(parsed["objects"]):
        live = visible[index]
        gate(int(live["x"]) - int(src["x"]) == 120 and int(live["y"]) - int(src["y"]) == 88, f"save-progress state geometry mismatch object {index}")

    x0 = min(int(visible[i]["x"]) for i in TEXT_OBJECTS)
    y0 = min(int(visible[i]["y"]) for i in TEXT_OBJECTS)
    private_payload_to_id: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_edits: dict[int, int] = {}
    direct_rewrites: dict[int, bytes] = {}
    changed_destinations: list[int] = []

    for index in TEXT_OBJECTS:
        obj = parsed["objects"][index]
        live = visible[index]
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        for ty in range(ht):
            for tx in range(wt):
                local = ty * wt + tx
                dest = int(obj["tile_start"]) + local
                ox = int(live["x"]) - x0 + tx * 8
                oy = int(live["y"]) - y0 + ty * 8
                patched_tile = [patched_plane[oy + yy][ox : ox + 8] for yy in range(8)]
                payload = encode_tile(patched_tile)
                live_payload = live_obj_tile(obj_vram, dest)
                if payload == live_payload:
                    continue
                changed_destinations.append(dest)
                if dest <= 121:
                    entry_off = source_table_rel + dest * 2
                    source_id = u16(original, entry_off)
                    gate(bytes(original_graphics[source_id * 32 : (source_id + 1) * 32]) == live_payload, f"save-progress explicit source mismatch dest {dest}")
                    new_id = private_payload_to_id.get(payload)
                    if new_id is None:
                        new_id = old_tile_count + len(private_payloads)
                        private_payload_to_id[payload] = new_id
                        private_payloads.append(payload)
                    lookup_edits[entry_off] = new_id
                else:
                    hits = [tile for tile in range(old_tile_count) if bytes(original_graphics[tile * 32 : (tile + 1) * 32]) == live_payload]
                    gate(len(hits) == 1, f"save-progress implicit changed dest {dest} source is not unique: {hits}")
                    source_id = hits[0]
                    gate(dest in range(124, 128) and source_id in range(225, 229), f"unexpected implicit changed tile dest={dest} source={source_id}")
                    prior = direct_rewrites.get(source_id)
                    gate(prior is None or prior == payload, f"implicit source tile {source_id} needs conflicting Korean payloads")
                    direct_rewrites[source_id] = payload

    gate(changed_destinations, "save-progress Korean patch changed no destination tiles")
    gate(set(direct_rewrites) <= {225, 226, 227, 228}, "save-progress direct rewrite escaped dedicated implicit run")
    for source_id, payload in direct_rewrites.items():
        original_graphics[source_id * 32 : (source_id + 1) * 32] = payload
    new_graphics = bytes(original_graphics) + b"".join(private_payloads)
    new_palette_rel = graphics_rel + len(new_graphics)
    clone = bytearray(new_palette_rel + len(palette))
    clone[:graphics_rel] = original[:graphics_rel]
    for entry_off, new_id in lookup_edits.items():
        struct.pack_into("<H", clone, entry_off, new_id)
    clone[graphics_rel:new_palette_rel] = new_graphics
    clone[new_palette_rel:] = palette
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    gate(clone[new_palette_rel:] == palette, "save-progress clone palette changed")
    gate(len(clone) < 0x8000, "save-progress clone exceeds private allocation window")

    return bytes(clone), {
        "source_resource": f"0x{CURRENT_SHARED_CLONE:08X}",
        "dedicated_consumer_pointer": f"0x{SAVE_PROGRESS_POINTER:08X}",
        "animation": SAVE_PROGRESS_ANIMATION,
        "clone_address": f"0x{SAVE_PROGRESS_CLONE:08X}",
        "old_source_tiles": old_tile_count,
        "private_source_tiles_appended": len(private_payloads),
        "new_source_tiles": len(new_graphics) // 32,
        "source_lookup_entries_changed": len(lookup_edits),
        "implicit_private_clone_source_tiles_rewritten": sorted(direct_rewrites),
        "changed_destination_tiles": changed_destinations,
        "palette_byte_exact": True,
        "message": plane_report,
    }


def build_instruction_clone(parent: bytes, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any]]:
    gate(u32(parent, SAVE_BG_POINTER) == CURRENT_SAVE_BG, "data-save BG parent pointer drift")
    resource = bg.parse_bg_resource(parent, CURRENT_SAVE_BG)
    gate(int(resource["decoded_tiles"]) == 152, "data-save follow-up decoded tile count drift")
    off = int(resource["file_offset"])
    map_rel = int(resource["map_relative_offset"])
    map_len = int(resource["map_length"])
    tiles_rel = int(resource["tiles_relative_offset"])
    comp_len = int(resource["compressed_tile_length"])
    palette_rel = int(resource["palette_relative_offset"])
    palette_len = int(resource["palette_length"])
    map_bytes = parent[off + map_rel : off + map_rel + map_len]
    palette = parent[off + palette_rel : off + palette_rel + palette_len]
    atlas = bytearray(bg.custom_lzss_decompress(parent[off + tiles_rel : off + tiles_rel + comp_len]))
    gate(len(atlas) == 152 * 32, "data-save follow-up atlas size drift")
    before_atlas = bytes(atlas)

    rect = (1, 10, 29, 3)
    rows = bg.map_rect(resource, *rect)
    pixels = paintops.stitch_variable(bytes(atlas), rows)
    gate(len(pixels) == 24 and all(len(row) == 232 for row in pixels), "data-save follow-up instruction dimensions drift")
    gate(set(value for row in pixels for value in row) <= {0, 2, 10}, "data-save follow-up instruction palette drift")
    prefix_width = 21
    prefix = [row[:prefix_width] for row in pixels]
    cleared = 0
    for y in range(24):
        for x in range(prefix_width, 232):
            if pixels[y][x] in (2, 10):
                pixels[y][x] = 0
                cleared += 1
    gate(cleared > 0 and all(value == 0 for row in pixels for value in row[prefix_width:]), "data-save follow-up instruction clear failed")
    region_width = 232 - prefix_width
    region = [row[prefix_width:] for row in pixels]
    mask, text_width = paintops.make_text_mask(INSTRUCTION, font, region_width, 24, cell_width=12, space_width=4)
    gate(text_width < 208, f"data-save shortened instruction did not shrink: {text_width}px")
    ink, contour = paintops.paint_mask(region, mask, ink=10, contour=2)
    expected = [[0] * region_width for _ in range(24)]
    paintops.paint_mask(expected, mask, ink=10, contour=2)
    gate(region == expected, "data-save shortened instruction is not exact Korean mask+contour")
    for y in range(24):
        pixels[y][prefix_width:] = region[y]
    gate([row[:prefix_width] for row in pixels] == prefix, "data-save A: prefix changed")
    paintops.write_variable(atlas, rows, pixels)

    changed_tiles = [tile for tile in range(152) if before_atlas[tile * 32 : (tile + 1) * 32] != atlas[tile * 32 : (tile + 1) * 32]]
    gate(changed_tiles, "data-save instruction follow-up changed no tiles")
    compressed = paintops.literal_only_lzss_body(bytes(atlas))
    gate(bg.custom_lzss_decompress(compressed) == bytes(atlas), "data-save follow-up LZSS round-trip failed")
    header = bytearray(parent[off : off + 16])
    new_map_rel = 0x10
    new_tiles_rel = new_map_rel + len(map_bytes)
    new_palette_rel = (new_tiles_rel + len(compressed) + 3) & ~3
    clone = bytearray(new_palette_rel + len(palette))
    clone[:16] = header
    struct.pack_into("<HHHHHH", clone, 4, new_map_rel, len(map_bytes), new_tiles_rel, len(compressed), new_palette_rel, len(palette))
    clone[new_map_rel : new_map_rel + len(map_bytes)] = map_bytes
    clone[new_tiles_rel : new_tiles_rel + len(compressed)] = compressed
    clone[new_palette_rel:] = palette
    gate(clone[new_map_rel : new_map_rel + len(map_bytes)] == map_bytes and clone[new_palette_rel:] == palette, "data-save follow-up map/palette drift")
    return bytes(clone), {
        "source_resource": f"0x{CURRENT_SAVE_BG:08X}",
        "clone_address": f"0x{SAVE_BG_FOLLOWUP:08X}",
        "translation": "A:" + INSTRUCTION,
        "native_prefix_x": [0, 20],
        "old_text_width_px": 208,
        "new_text_width_px": text_width,
        "source_face_contour_pixels_cleared": cleared,
        "korean_ink_pixels": ink,
        "korean_contour_pixels": contour,
        "changed_decoded_tiles": [f"0x{x:03X}" for x in changed_tiles],
        "map_byte_exact": True,
        "palette_byte_exact": True,
        "japanese_or_old_korean_residue": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PARENT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    for path in (args.input, PARENT_SAV, STATE3, STATE_ANALYSIS, MAIN_TIP_ROM, MAIN_TIP_MANIFEST):
        gate(path.is_file(), f"missing input: {path}")
    parent = args.input.read_bytes()
    gate(len(parent) == 32 * 1024 * 1024 and sha256(parent) == PARENT_SHA256, f"parent hash drift: {sha256(parent)}")
    state_report = json.loads(STATE_ANALYSIS.read_text(encoding="utf-8"))
    gate(state_report.get("result") == "PASS" and state_report["parent"]["sha256"] == PARENT_SHA256, "state3 analysis not bound to parent")
    main_tip = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main_tip) == main_manifest.get("sha256"), "canonical main TIP/manifest drift")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    progress_clone, progress_report = build_save_progress_clone(parent, font)
    instruction_clone, instruction_report = build_instruction_clone(parent, font)
    gate(SAVE_PROGRESS_CLONE_OFFSET + len(progress_clone) <= SAVE_BG_FOLLOWUP_OFFSET, "save-progress clone overlaps data-save follow-up allocation")
    gate(SAVE_BG_FOLLOWUP_OFFSET + len(instruction_clone) <= len(parent), "data-save follow-up clone exceeds ROM")
    gate(all(value == 0 for value in parent[SAVE_PROGRESS_CLONE_OFFSET : SAVE_PROGRESS_CLONE_OFFSET + len(progress_clone)]), "save-progress allocation is not zero-filled")
    gate(all(value == 0 for value in parent[SAVE_BG_FOLLOWUP_OFFSET : SAVE_BG_FOLLOWUP_OFFSET + len(instruction_clone)]), "data-save follow-up allocation is not zero-filled")

    candidate = bytearray(parent)
    candidate[SAVE_PROGRESS_CLONE_OFFSET : SAVE_PROGRESS_CLONE_OFFSET + len(progress_clone)] = progress_clone
    struct.pack_into("<I", candidate, SAVE_PROGRESS_POINTER, SAVE_PROGRESS_CLONE)
    candidate[SAVE_BG_FOLLOWUP_OFFSET : SAVE_BG_FOLLOWUP_OFFSET + len(instruction_clone)] = instruction_clone
    struct.pack_into("<I", candidate, SAVE_BG_POINTER, SAVE_BG_FOLLOWUP)
    gate(u32(candidate, SAVE_PROGRESS_POINTER) == SAVE_PROGRESS_CLONE and u32(candidate, SAVE_BG_POINTER) == SAVE_BG_FOLLOWUP, "follow-up pointer redirect failed")
    # The other popup consumers remain on the cumulative 22.108 shared clone.
    for ref in (0x000121CC, 0x00026B6C, 0x0007385C):
        gate(u32(candidate, ref) == CURRENT_SHARED_CLONE, f"unrelated shared popup consumer changed at 0x{ref:08X}")

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    allowed = set(range(SAVE_PROGRESS_POINTER, SAVE_PROGRESS_POINTER + 4)) | set(range(SAVE_BG_POINTER, SAVE_BG_POINTER + 4))
    escaped = [i for i in changed if i not in allowed and not (SAVE_PROGRESS_CLONE_OFFSET <= i < SAVE_PROGRESS_CLONE_OFFSET + len(progress_clone)) and not (SAVE_BG_FOLLOWUP_OFFSET <= i < SAVE_BG_FOLLOWUP_OFFSET + len(instruction_clone))]
    gate(not escaped, f"candidate changed outside two pointers/private allocations: {escaped[:8]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    shutil.copy2(PARENT_SAV, args.out_sav)
    gate(args.out_sav.read_bytes() == PARENT_SAV.read_bytes(), "follow-up SAV copy drift")
    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_save_progress_followup_ko_20260831",
        "result": "PASS",
        "source": {"parent": advance_relative(args.input), "parent_sha256": sha256(parent), "state3_analysis": advance_relative(STATE_ANALYSIS), "canonical_main_tip_sha256": sha256(main_tip)},
        "translations": {
            "A:上のデータを下のデータに上書きします": "A:" + INSTRUCTION,
            "セーブ中です": MESSAGE_LINES[0],
            "電源を切らないでください": MESSAGE_LINES[1],
        },
        "save_progress": progress_report,
        "data_save_instruction": instruction_report,
        "output": {"rom": advance_relative(args.out), "rom_sha256": sha256(output), "rom_size": len(output), "sav": advance_relative(args.out_sav), "sav_sha256": sha256(args.out_sav.read_bytes()), "changed_bytes": len(changed), "changed_ranges": changed_ranges(changed)},
        "verification": {
            "result": "PASS",
            "state3_animation10_owner_proven": True,
            "state3_explicit_source_tiles_exact_122_of_122": True,
            "save_progress_dedicated_consumer_clone": True,
            "save_progress_native_palette_preserved": True,
            "save_progress_japanese_face_shadow_residue_zero": True,
            "data_save_native_A_colon_preserved": True,
            "data_save_instruction_width_reduced": True,
            "data_save_map_palette_byte_exact": True,
            "changes_restricted_to_two_pointers_and_private_allocations": True,
            "canonical_main_tip_modified": False,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": str(args.out), "rom_sha256": sha256(output), "sav": str(args.out_sav), "manifest": str(args.manifest), "changed_bytes": len(changed), "translations": manifest["translations"]}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
