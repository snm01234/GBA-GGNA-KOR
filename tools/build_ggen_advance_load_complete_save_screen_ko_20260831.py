#!/usr/bin/env python3
"""Koreanize load/save completion and the data-save fixed graphic screen.

Parent is the cumulative popup candidate (ロード実行/キャンセル/セーブ実行
already Korean).  Two additional normal-only completion labels are patched in a
new private clone of the shared sprite package:

* animation 4: セーブ完了 -> 세이브완료
* animation 6: ロード完了 -> 로드완료 (fresh state1 is 44/44 exact)

The data-save screen in fresh state2 is fixed BG resource 0x08C78E7C.  A second
private clone translates データセーブ, クリア, プレイ時間, ゲームモード and
preserves the native A: prefix while replacing the Japanese instruction with
"위 데이터를 아래 데이터에 덮어씁니다".  Original resources, prior clones,
maps and palettes remain byte-exact; only unique owner pointers and new
zero-filled expansion allocations change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_load_complete_save_screen_20260831 as analysis
import analyze_ggen_advance_settings_suspend_ui as bg
import build_ggen_advance_load_confirm_popup_ko_20260831 as popup
import build_ggen_advance_load_summary_ui_ko_20260831 as summary
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
PARENT = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_popup_candidate_20260831.gba"
PARENT_SHA256 = "98f4166e72253c3221696bacc85dcda6f4c5434bee67dd2185c84f4ea26d175e"
PARENT_SAV = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_popup_candidate_20260831.sav"
PREVIOUS_POPUP_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_load_confirm_popup_ko_20260831.json"
STATE_ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_load_complete_save_screen_state_20260831.json"

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui"
DEFAULT_OUT = OUT_DIR / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.sav"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_load_complete_save_screen_ko_20260831.json"

OLD_SPRITE_CLONE_OFFSET = 0x01284000
OLD_SPRITE_CLONE_ADDRESS = ROM_BASE + OLD_SPRITE_CLONE_OFFSET
NEW_SPRITE_CLONE_OFFSET = 0x0128C000
NEW_SPRITE_CLONE_ADDRESS = ROM_BASE + NEW_SPRITE_CLONE_OFFSET
SAVE_BG_CLONE_OFFSET = 0x01294000
SAVE_BG_CLONE_ADDRESS = ROM_BASE + SAVE_BG_CLONE_OFFSET

SPRITE_RESOURCE = analysis.SPRITE_RESOURCE
SPRITE_RESOURCE_OFFSET = SPRITE_RESOURCE - ROM_BASE
SPRITE_POINTER_REFS = analysis.SPRITE_POINTER_REFS
SAVE_BG_RESOURCE = analysis.SAVE_BG_RESOURCE
SAVE_BG_OWNER_POINTER = analysis.SAVE_BG_OWNER_POINTER

COMPLETION_TRANSLATIONS = {
    4: ("セーブ完了", "세이브완료"),
    6: ("ロード完了", "로드완료"),
}
SAVE_TRANSLATIONS = {
    "data_save": "데이터세이브",
    "clear": "클리어",
    "play_time": "플레이시간",
    "game_mode": "게임모드",
    "instruction": "위 데이터를 아래 데이터에 덮어씁니다",
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
    out: list[int] = []
    pos = 0
    while True:
        pos = data.find(needle, pos)
        if pos < 0:
            return out
        out.append(pos)
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


def original_sprite_graphics(jp: bytes) -> tuple[bytes, bytes]:
    gate(u32(jp, SPRITE_RESOURCE_OFFSET) == 0, "shared sprite kind drift")
    palette_count = u32(jp, SPRITE_RESOURCE_OFFSET + 4)
    graphics_rel = u32(jp, SPRITE_RESOURCE_OFFSET + 8)
    palette_rel = u32(jp, SPRITE_RESOURCE_OFFSET + 0x0C)
    gate(palette_count == popup.PALETTE_COUNT, "shared sprite palette-count drift")
    gate(graphics_rel == popup.GRAPHICS_REL and palette_rel == popup.PALETTE_REL, "shared sprite layout drift")
    graphics = jp[SPRITE_RESOURCE_OFFSET + graphics_rel:SPRITE_RESOURCE_OFFSET + palette_rel]
    palette = jp[SPRITE_RESOURCE_OFFSET + palette_rel:SPRITE_RESOURCE_OFFSET + palette_rel + palette_count * 32]
    gate(len(graphics) == popup.ORIGINAL_SOURCE_TILES * 32, "shared sprite original tile count drift")
    return graphics, palette


def label_group_origin(parsed: dict[str, Any]) -> tuple[int, int]:
    objects = [parsed["objects"][index] for index in (8, 9, 10)]
    return min(int(obj["x"]) for obj in objects), min(int(obj["y"]) for obj in objects)


def build_completion_sprite_clone(parent: bytes, jp: bytes, font12: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], dict[int, list[list[int]]]]:
    previous_manifest = json.loads(PREVIOUS_POPUP_MANIFEST.read_text(encoding="utf-8"))
    gate(previous_manifest.get("result") == "PASS", "previous popup manifest is not PASS")
    gate(int(str(previous_manifest["patch"]["clone_file_offset"]), 16) == OLD_SPRITE_CLONE_OFFSET, "previous popup clone offset drift")
    gate(int(str(previous_manifest["patch"]["clone_address"]), 16) == OLD_SPRITE_CLONE_ADDRESS, "previous popup clone address drift")

    palette_count = u32(parent, OLD_SPRITE_CLONE_OFFSET + 4)
    graphics_rel = u32(parent, OLD_SPRITE_CLONE_OFFSET + 8)
    palette_rel = u32(parent, OLD_SPRITE_CLONE_OFFSET + 0x0C)
    gate(palette_count == popup.PALETTE_COUNT, "parent popup clone palette-count drift")
    gate(graphics_rel == popup.GRAPHICS_REL, "parent popup clone graphics-relative drift")
    old_clone_size = palette_rel + palette_count * 32
    manifest_size = int(previous_manifest["patch"]["clone_size"])
    gate(old_clone_size == manifest_size, f"parent popup clone size drift: {old_clone_size}/{manifest_size}")
    old_clone = parent[OLD_SPRITE_CLONE_OFFSET:OLD_SPRITE_CLONE_OFFSET + old_clone_size]
    gate(len(old_clone) == old_clone_size, "parent popup clone truncated")
    old_prefix = bytearray(old_clone[:graphics_rel])
    old_graphics = old_clone[graphics_rel:palette_rel]
    old_palette = old_clone[palette_rel:palette_rel + palette_count * 32]
    gate(len(old_graphics) % 32 == 0, "parent popup clone graphics alignment drift")
    old_tile_count = len(old_graphics) // 32
    expected_old_tiles = popup.ORIGINAL_SOURCE_TILES + int(previous_manifest["patch"]["buttons"]["materialization"]["private_source_tiles_appended"])
    gate(old_tile_count == expected_old_tiles, f"parent popup clone tile count drift: {old_tile_count}/{expected_old_tiles}")

    jp_graphics, jp_palette = original_sprite_graphics(jp)
    gate(old_graphics[:len(jp_graphics)] == jp_graphics, "parent popup clone rewrote native 262 source tiles")
    gate(old_palette == jp_palette, "parent popup clone palette differs from native")

    payload_to_id: dict[bytes, int] = {}
    for tile_id in range(old_tile_count):
        payload_to_id.setdefault(old_graphics[tile_id * 32:(tile_id + 1) * 32], tile_id)
    appended_payloads: list[bytes] = []
    private_payload_to_id: dict[bytes, int] = {}
    allowed_prefix_changes = set(range(0x0C, 0x10))
    reports: dict[str, Any] = {}
    expected_canvases: dict[int, list[list[int]]] = {}

    for animation, (jp_text, ko_text) in COMPLETION_TRANSLATIONS.items():
        parsed, source = analysis.cross_source_map(jp, animation)
        gate(parsed["object_count"] == 11 and source["total_source_entries"] == 44, f"completion animation {animation} structure drift")
        source_pixels = popup.stitch_button(jp_graphics, parsed, source, (8, 9, 10))
        patched_pixels, render_report = popup.rebuild_button(source_pixels, ko_text, font12, focus=False)
        expected_canvases[animation] = patched_pixels
        group_x0, group_y0 = label_group_origin(parsed)
        source_start_rel = int(source["source_start_relative"])
        cursor = 0
        changed_entries = 0
        remapped_label_ids: list[int] = []
        for obj in parsed["objects"]:
            obj_index = int(obj["index"])
            wt = int(obj["size_px"][0]) // 8
            ht = int(obj["size_px"][1]) // 8
            count = wt * ht
            if obj_index not in (8, 9, 10):
                cursor += count
                continue
            for ty in range(ht):
                for tx in range(wt):
                    local = ty * wt + tx
                    entry_index = cursor + local
                    old_source_id = int(source["source_ids"][entry_index])
                    payload = popup.tile_payload_from_canvas(patched_pixels, obj, group_x0, group_y0, tx, ty)
                    old_payload = jp_graphics[old_source_id * 32:(old_source_id + 1) * 32]
                    if payload == old_payload:
                        new_id = old_source_id
                    else:
                        new_id = payload_to_id.get(payload, -1)
                        if new_id < 0:
                            new_id = private_payload_to_id.get(payload, -1)
                        if new_id < 0:
                            new_id = old_tile_count + len(appended_payloads)
                            gate(new_id <= 0xFFFF, "completion private tile ID overflow")
                            private_payload_to_id[payload] = new_id
                            appended_payloads.append(payload)
                    write_at = source_start_rel + entry_index * 2
                    gate(write_at + 2 <= graphics_rel, f"completion animation {animation} source lookup outside prefix")
                    before = struct.unpack_from("<H", old_prefix, write_at)[0]
                    gate(before == old_source_id, f"completion animation {animation} source lookup drift at entry {entry_index}: {before}/{old_source_id}")
                    struct.pack_into("<H", old_prefix, write_at, new_id)
                    allowed_prefix_changes.update((write_at, write_at + 1))
                    changed_entries += new_id != old_source_id
                    remapped_label_ids.append(new_id)
            cursor += count
        gate(cursor == 44, f"completion animation {animation} source cursor drift")
        gate(len(remapped_label_ids) == 20, f"completion animation {animation} label source count drift")
        render_report.update({
            "source": jp_text,
            "animation": animation,
            "source_lookup_relative": f"0x{source_start_rel:04X}",
            "label_entry_range": [24, 43],
            "source_label_ids": source["source_ids"][24:44],
            "remapped_label_ids": remapped_label_ids,
            "source_lookup_entries_changed": changed_entries,
            "normal_only": True,
        })
        reports[jp_text] = render_report

    new_graphics = old_graphics + b"".join(appended_payloads)
    new_palette_rel = graphics_rel + len(new_graphics)
    struct.pack_into("<I", old_prefix, 0x0C, new_palette_rel)
    new_clone = bytearray(new_palette_rel + len(old_palette))
    new_clone[:graphics_rel] = old_prefix
    new_clone[graphics_rel:new_palette_rel] = new_graphics
    new_clone[new_palette_rel:] = old_palette

    # Strong preservation gate: compare the old/new prefixes and allow only the
    # palette-rel field plus the selected completion source lookup entries.
    original_prefix = old_clone[:graphics_rel]
    prefix_diff = {i for i, (a, b) in enumerate(zip(original_prefix, new_clone[:graphics_rel])) if a != b}
    gate(prefix_diff <= allowed_prefix_changes, f"completion clone changed unexpected prefix bytes: {sorted(prefix_diff - allowed_prefix_changes)[:16]}")
    gate(new_graphics[:len(old_graphics)] == old_graphics, "completion clone rewrote prior graphics")
    gate(bytes(new_clone[new_palette_rel:]) == old_palette, "completion clone palette changed")

    # Reconstruct both patched labels through their final remapped source maps.
    final_graphics = bytes(new_graphics)
    for animation, expected in expected_canvases.items():
        parsed, source = analysis.cross_source_map(jp, animation)
        total = int(source["total_source_entries"])
        start_rel = int(source["source_start_relative"])
        ids = list(struct.unpack_from(f"<{total}H", new_clone, start_rel))
        by_object: list[list[int]] = []
        cursor = 0
        for obj in parsed["objects"]:
            count = int(obj["tile_count"])
            by_object.append(ids[cursor:cursor + count])
            cursor += count
        final_pixels = popup.stitch_button(final_graphics, parsed, {"by_object": by_object}, (8, 9, 10))
        gate(final_pixels == expected, f"completion animation {animation} final source-map raster mismatch")

    return bytes(new_clone), {
        "old_clone_address": f"0x{OLD_SPRITE_CLONE_ADDRESS:08X}",
        "new_clone_address": f"0x{NEW_SPRITE_CLONE_ADDRESS:08X}",
        "old_source_tiles": old_tile_count,
        "completion_private_tiles_appended": len(appended_payloads),
        "new_source_tiles": len(new_graphics) // 32,
        "old_palette_relative_offset": f"0x{palette_rel:04X}",
        "new_palette_relative_offset": f"0x{new_palette_rel:04X}",
        "previous_popup_graphics_byte_exact_preserved": True,
        "native_262_graphics_byte_exact_preserved": True,
        "palette_byte_exact": True,
        "buttons": reports,
    }, expected_canvases


def target_map_indices(resource: dict[str, Any]) -> set[int]:
    indices: set[int] = set()
    for rects in analysis.SAVE_TARGET_RECTS.values():
        for rect in rects:
            indices.update(analysis.rect_indices(resource, rect))
    return indices


def patch_instruction(atlas: bytearray, resource: dict[str, Any], font12: fontpair.BdfFont) -> dict[str, Any]:
    rect = (1, 10, 29, 3)
    rows = bg.map_rect(resource, *rect)
    pixels = paintops.stitch_variable(bytes(atlas), rows)
    gate(len(pixels) == 24 and all(len(row) == 232 for row in pixels), "data-save instruction dimensions drift")
    before = [row[:] for row in pixels]
    before_counts: dict[int, int] = {}
    for row in pixels:
        for value in row:
            before_counts[value] = before_counts.get(value, 0) + 1
    gate(set(before_counts) <= {0, 2, 10}, f"data-save instruction palette drift: {sorted(before_counts)}")

    # State2 proves A occupies x=0..18, x=19..20 is blank, and the Japanese
    # sentence occupies x=21..222.  Preserve the native A: pixels byte-exact.
    prefix_width = 21
    native_prefix = [row[:prefix_width] for row in before]
    source_cleared = 0
    for y in range(24):
        for x in range(prefix_width, 232):
            if pixels[y][x] in (2, 10):
                pixels[y][x] = 0
                source_cleared += 1
    gate(source_cleared > 0, "data-save instruction Japanese glyphs were not cleared")
    gate(all(value == 0 for row in pixels for value in row[prefix_width:]), "data-save instruction Japanese residue survived clear")
    gate([row[:prefix_width] for row in pixels] == native_prefix, "data-save native A: prefix changed during clear")

    region_width = 232 - prefix_width
    region = [row[prefix_width:] for row in pixels]
    mask, text_width = paintops.make_text_mask(SAVE_TRANSLATIONS["instruction"], font12, region_width, 24, cell_width=12, space_width=4)
    ink, contour = paintops.paint_mask(region, mask, ink=10, contour=2)
    gate((ink, contour) > (0, 0), "data-save Korean instruction raster empty")
    expected_region = [[0] * region_width for _ in range(24)]
    e_ink, e_contour = paintops.paint_mask(expected_region, mask, ink=10, contour=2)
    gate((ink, contour) == (e_ink, e_contour) and region == expected_region, "data-save Korean instruction is not exact mask+contour")
    for y in range(24):
        pixels[y][prefix_width:] = region[y]
    gate([row[:prefix_width] for row in pixels] == native_prefix, "data-save A: prefix changed after Korean repaint")
    paintops.write_variable(atlas, rows, pixels)
    return {
        "source": "A:上のデータを下のデータに上書きします",
        "translation": "A:" + SAVE_TRANSLATIONS["instruction"],
        "map_rect": list(rect),
        "native_prefix_x": [0, 20],
        "japanese_clear_x": [21, 231],
        "face_index": 10,
        "contour_index": 2,
        "source_face_contour_pixels_cleared": source_cleared,
        "korean_text_width_px": text_width,
        "korean_ink_pixels": ink,
        "korean_contour_pixels": contour,
        "native_A_colon_byte_exact_preserved": True,
        "japanese_face_shadow_residue": 0,
    }


def build_save_bg_clone(parent: bytes, font12: fontpair.BdfFont, font8: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], bytes]:
    gate(pointer_hits(parent, SAVE_BG_RESOURCE) == [SAVE_BG_OWNER_POINTER], "data-save fixed resource owner is not unique")
    resource = bg.parse_bg_resource(parent, SAVE_BG_RESOURCE)
    gate(int(resource["decoded_tiles"]) == 152, f"data-save decoded tile count drift: {resource['decoded_tiles']}")
    source_off = int(resource["file_offset"])
    map_rel = int(resource["map_relative_offset"])
    map_len = int(resource["map_length"])
    tiles_rel = int(resource["tiles_relative_offset"])
    comp_len = int(resource["compressed_tile_length"])
    palette_rel = int(resource["palette_relative_offset"])
    palette_len = int(resource["palette_length"])
    original_map = parent[source_off + map_rel:source_off + map_rel + map_len]
    original_comp = parent[source_off + tiles_rel:source_off + tiles_rel + comp_len]
    original_palette = parent[source_off + palette_rel:source_off + palette_rel + palette_len]
    original_atlas = bg.custom_lzss_decompress(original_comp)
    gate(len(original_atlas) == 152 * 32, "data-save atlas size drift")

    indices = target_map_indices(resource)
    target_tiles = {int(resource["cells"][idx]) & 0x03FF for idx in indices}
    outside_tiles = {int(resource["cells"][idx]) & 0x03FF for idx in range(600) if idx not in indices}
    gate(len(indices) == 191 and len(target_tiles) == 149 and not (target_tiles & outside_tiles), "data-save target ownership drift")

    atlas = bytearray(original_atlas)
    reports: dict[str, Any] = {}
    reports["data_save"] = summary.patch_rect(atlas, resource, (10, 1, 10, 2), SAVE_TRANSLATIONS["data_save"], 11, font12, "12x12")
    reports["clear"] = summary.patch_rect(atlas, resource, (25, 4, 4, 2), SAVE_TRANSLATIONS["clear"], 11, font8, "condensed_8x16")
    reports["play_time"] = summary.patch_rect(atlas, resource, (1, 7, 8, 2), SAVE_TRANSLATIONS["play_time"], 11, font12, "12x12")
    reports["game_mode"] = summary.patch_rect(atlas, resource, (15, 7, 9, 2), SAVE_TRANSLATIONS["game_mode"], 11, font12, "12x12")
    reports["instruction"] = patch_instruction(atlas, resource, font12)

    # Repeated lower slot labels must pick up the exact same source tiles.
    gate(bg.map_rect(resource, 25, 4, 4, 2) == bg.map_rect(resource, 25, 14, 4, 2), "data-save clear duplicate map drift")
    gate(bg.map_rect(resource, 1, 7, 8, 2) == bg.map_rect(resource, 1, 17, 8, 2), "data-save play-time duplicate map drift")
    gate(bg.map_rect(resource, 15, 7, 9, 2) == bg.map_rect(resource, 15, 17, 9, 2), "data-save game-mode duplicate map drift")

    changed_tiles = [tile for tile in range(152) if original_atlas[tile * 32:(tile + 1) * 32] != atlas[tile * 32:(tile + 1) * 32]]
    gate(changed_tiles and set(changed_tiles) <= target_tiles, "data-save atlas changed outside target tiles")

    compressed = paintops.literal_only_lzss_body(bytes(atlas))
    gate(bg.custom_lzss_decompress(compressed) == bytes(atlas), "data-save clone LZSS round-trip failed")
    header = bytearray(parent[source_off:source_off + 16])
    new_map_rel = 0x10
    new_tiles_rel = new_map_rel + len(original_map)
    gate(new_tiles_rel == 0x4C0, "data-save 30x20 map layout drift")
    new_palette_rel = (new_tiles_rel + len(compressed) + 3) & ~3
    clone = bytearray(new_palette_rel + len(original_palette))
    clone[:16] = header
    struct.pack_into("<HHHHHH", clone, 4, new_map_rel, len(original_map), new_tiles_rel, len(compressed), new_palette_rel, len(original_palette))
    clone[new_map_rel:new_map_rel + len(original_map)] = original_map
    clone[new_tiles_rel:new_tiles_rel + len(compressed)] = compressed
    clone[new_palette_rel:new_palette_rel + len(original_palette)] = original_palette

    gate(clone[new_map_rel:new_map_rel + len(original_map)] == original_map, "data-save clone map changed")
    gate(clone[new_palette_rel:] == original_palette, "data-save clone palette changed")
    return bytes(clone), {
        "source_resource": f"0x{SAVE_BG_RESOURCE:08X}",
        "new_clone_address": f"0x{SAVE_BG_CLONE_ADDRESS:08X}",
        "decoded_tiles": 152,
        "target_map_cells": len(indices),
        "target_source_tiles": len(target_tiles),
        "changed_decoded_tiles": [f"0x{x:03X}" for x in changed_tiles],
        "map_byte_exact": True,
        "palette_byte_exact": True,
        "duplicate_slot_labels_share_korean_tiles": True,
        "targets": reports,
    }, bytes(atlas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PARENT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    for path in (args.input, JP_ROM, PARENT_SAV, PREVIOUS_POPUP_MANIFEST, STATE_ANALYSIS):
        gate(path.is_file(), f"missing input: {path}")
    parent = args.input.read_bytes()
    jp = JP_ROM.read_bytes()
    gate(len(parent) == 32 * 1024 * 1024, "parent must be 32 MiB")
    gate(sha256(parent) == PARENT_SHA256, f"parent popup candidate hash drift: {sha256(parent)}")
    state_report = json.loads(STATE_ANALYSIS.read_text(encoding="utf-8"))
    gate(state_report.get("result") == "PASS", "fresh state analysis is not PASS")
    gate(state_report["parent"]["sha256"] == PARENT_SHA256, "state analysis parent hash drift")

    # Re-run the live ownership gates inside the builder so a stale JSON alone
    # cannot authorize the patch.
    live1 = analysis.state1_report(jp)
    live2 = analysis.state2_report(jp, parent)
    gate(live1["all_obj_tiles_exact"] == 44 and live1["animation"] == 6, "load-complete live state gate failed")
    gate(live2["bg1"]["atlas_exact"] == 152 and live2["bg1"]["map_exact"] == 600, "data-save live state gate failed")

    for off in SPRITE_POINTER_REFS:
        gate(u32(parent, off) == OLD_SPRITE_CLONE_ADDRESS, f"parent popup sprite pointer drift at 0x{off:08X}")
    gate(u32(parent, SAVE_BG_OWNER_POINTER) == SAVE_BG_RESOURCE, "parent data-save BG owner pointer drift")

    with ZipFile(FONT_ZIP) as archive:
        font12 = fontpair.load_bdf(archive, "Galmuri11.bdf")
        font8 = fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf")
    sprite_clone, sprite_report, expected_buttons = build_completion_sprite_clone(parent, jp, font12)
    save_clone, save_report, save_atlas = build_save_bg_clone(parent, font12, font8)

    gate(NEW_SPRITE_CLONE_OFFSET + len(sprite_clone) <= SAVE_BG_CLONE_OFFSET, "new sprite clone overlaps data-save clone allocation")
    gate(SAVE_BG_CLONE_OFFSET + len(save_clone) <= len(parent), "data-save clone exceeds ROM")
    gate(all(value == 0 for value in parent[NEW_SPRITE_CLONE_OFFSET:NEW_SPRITE_CLONE_OFFSET + len(sprite_clone)]), "new sprite clone allocation is not zero-filled")
    gate(all(value == 0 for value in parent[SAVE_BG_CLONE_OFFSET:SAVE_BG_CLONE_OFFSET + len(save_clone)]), "data-save clone allocation is not zero-filled")

    candidate = bytearray(parent)
    candidate[NEW_SPRITE_CLONE_OFFSET:NEW_SPRITE_CLONE_OFFSET + len(sprite_clone)] = sprite_clone
    candidate[SAVE_BG_CLONE_OFFSET:SAVE_BG_CLONE_OFFSET + len(save_clone)] = save_clone
    for off in SPRITE_POINTER_REFS:
        struct.pack_into("<I", candidate, off, NEW_SPRITE_CLONE_ADDRESS)
    struct.pack_into("<I", candidate, SAVE_BG_OWNER_POINTER, SAVE_BG_CLONE_ADDRESS)

    # Verify final sprite clone through its source lookups.
    final_sprite_graphics_rel = u32(candidate, NEW_SPRITE_CLONE_OFFSET + 8)
    final_sprite_palette_rel = u32(candidate, NEW_SPRITE_CLONE_OFFSET + 0x0C)
    final_sprite_graphics = bytes(candidate[NEW_SPRITE_CLONE_OFFSET + final_sprite_graphics_rel:NEW_SPRITE_CLONE_OFFSET + final_sprite_palette_rel])
    for animation, expected in expected_buttons.items():
        parsed, source = analysis.cross_source_map(jp, animation)
        total = int(source["total_source_entries"])
        source_rel = int(source["source_start_relative"])
        ids = list(struct.unpack_from(f"<{total}H", candidate, NEW_SPRITE_CLONE_OFFSET + source_rel))
        by_object: list[list[int]] = []
        cursor = 0
        for obj in parsed["objects"]:
            count = int(obj["tile_count"])
            by_object.append(ids[cursor:cursor + count])
            cursor += count
        final_pixels = popup.stitch_button(final_sprite_graphics, parsed, {"by_object": by_object}, (8, 9, 10))
        gate(final_pixels == expected, f"final completion animation {animation} raster drift")

    # Parse the final BG clone at its actual ROM address.
    final_bg = bg.parse_bg_resource(bytes(candidate), SAVE_BG_CLONE_ADDRESS)
    final_comp = bytes(candidate[SAVE_BG_CLONE_OFFSET + int(final_bg["tiles_relative_offset"]):SAVE_BG_CLONE_OFFSET + int(final_bg["tiles_relative_offset"]) + int(final_bg["compressed_tile_length"])])
    gate(bg.custom_lzss_decompress(final_comp) == save_atlas, "final data-save clone atlas drift")

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    allowed_pointer_bytes = set(range(SAVE_BG_OWNER_POINTER, SAVE_BG_OWNER_POINTER + 4))
    for off in SPRITE_POINTER_REFS:
        allowed_pointer_bytes.update(range(off, off + 4))
    escaped = [i for i in changed if i not in allowed_pointer_bytes and not (NEW_SPRITE_CLONE_OFFSET <= i < NEW_SPRITE_CLONE_OFFSET + len(sprite_clone)) and not (SAVE_BG_CLONE_OFFSET <= i < SAVE_BG_CLONE_OFFSET + len(save_clone))]
    gate(not escaped, f"candidate changed bytes outside private clones/owner pointers: {escaped[:16]}")
    gate(len(candidate) == len(parent), "candidate ROM size changed")

    # Original and prior private resources remain byte-exact.
    previous_popup = json.loads(PREVIOUS_POPUP_MANIFEST.read_text(encoding="utf-8"))
    old_clone_size = int(previous_popup["patch"]["clone_size"])
    gate(candidate[OLD_SPRITE_CLONE_OFFSET:OLD_SPRITE_CLONE_OFFSET + old_clone_size] == parent[OLD_SPRITE_CLONE_OFFSET:OLD_SPRITE_CLONE_OFFSET + old_clone_size], "previous popup clone changed")
    save_source = bg.parse_bg_resource(parent, SAVE_BG_RESOURCE)
    save_source_off = int(save_source["file_offset"])
    save_source_end = save_source_off + max(int(save_source["map_relative_offset"]) + int(save_source["map_length"]), int(save_source["tiles_relative_offset"]) + int(save_source["compressed_tile_length"]), int(save_source["palette_relative_offset"]) + int(save_source["palette_length"]))
    gate(candidate[save_source_off:save_source_end] == parent[save_source_off:save_source_end], "original data-save resource changed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    output = bytes(candidate)
    args.out.write_bytes(output)
    args.out_sav.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PARENT_SAV, args.out_sav)
    gate(args.out_sav.read_bytes() == PARENT_SAV.read_bytes(), "candidate SAV copy is not byte-exact")

    main_tip = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main_tip) == main_manifest.get("sha256"), "canonical main TIP/manifest drift while building candidate")

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_load_complete_save_screen_ko_20260831",
        "result": "PASS",
        "source": {
            "parent": advance_relative(args.input),
            "parent_sha256": sha256(parent),
            "state_analysis": advance_relative(STATE_ANALYSIS),
            "state1_sha256": live1["sha256"],
            "state2_sha256": live2["sha256"],
            "canonical_main_tip_sha256": sha256(main_tip),
        },
        "translations": {
            "セーブ完了": "세이브완료",
            "ロード完了": "로드완료",
            "データセーブ": "데이터세이브",
            "クリア": "클리어",
            "プレイ時間": "플레이시간",
            "ゲームモード": "게임모드",
            "A:上のデータを下のデータに上書きします": "A:위 데이터를 아래 데이터에 덮어씁니다",
        },
        "sprite_completion": {
            "old_clone_file_offset": f"0x{OLD_SPRITE_CLONE_OFFSET:08X}",
            "new_clone_file_offset": f"0x{NEW_SPRITE_CLONE_OFFSET:08X}",
            "new_clone_size": len(sprite_clone),
            "owner_pointer_refs": [f"0x{x:08X}" for x in SPRITE_POINTER_REFS],
            **sprite_report,
        },
        "data_save_fixed_graphics": {
            "source_resource": f"0x{SAVE_BG_RESOURCE:08X}",
            "owner_pointer_file_offset": f"0x{SAVE_BG_OWNER_POINTER:08X}",
            "clone_file_offset": f"0x{SAVE_BG_CLONE_OFFSET:08X}",
            "clone_address": f"0x{SAVE_BG_CLONE_ADDRESS:08X}",
            "clone_size": len(save_clone),
            **save_report,
        },
        "output": {
            "rom": advance_relative(args.out),
            "rom_sha256": sha256(output),
            "rom_size": len(output),
            "sav": advance_relative(args.out_sav),
            "sav_sha256": sha256(args.out_sav.read_bytes()),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "state1_animation6_44_of_44_exact_before_patch": True,
            "state2_resource_152_of_152_tiles_600_of_600_map_exact_before_patch": True,
            "save_complete_animation4_normal_only_patched": True,
            "load_complete_animation6_normal_only_patched": True,
            "animations5_and7_unidentified_suffix_variants_left_untouched": True,
            "prior_popup_clone_byte_exact_preserved": True,
            "native_shared_sprite_262_tiles_byte_exact_preserved": True,
            "data_save_original_resource_byte_exact_preserved": True,
            "data_save_target_tiles_private": True,
            "data_save_native_A_colon_preserved": True,
            "japanese_face_shadow_residue_zero_in_all_new_targets": True,
            "changes_restricted_to_two_private_clones_and_five_owner_pointers": True,
            "canonical_main_tip_modified": False,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "rom": str(args.out),
        "rom_sha256": sha256(output),
        "sav": str(args.out_sav),
        "manifest": str(args.manifest),
        "changed_bytes": len(changed),
        "completion_private_tiles": sprite_report["completion_private_tiles_appended"],
        "data_save_changed_tiles": len(save_report["changed_decoded_tiles"]),
        "translations": manifest["translations"],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
