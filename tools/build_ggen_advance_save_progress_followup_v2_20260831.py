#!/usr/bin/env python3
"""Second follow-up for the data-save instruction and save-progress popup.

This build fixes two real-hardware findings from the 22.109 candidate:

1. The shortened data-save instruction still let the final Korean contour enter
   the rightmost map column.  That column uses palette bank 0 while the text
   cells use bank 1, so contour index 2 appeared blue.  The Korean raster is
   now constrained to local x=21..223; the bank-0 x=224..231 tile is forced
   transparent.
2. The user's screenshot explicitly shows "State 3 loaded".  mGBA ss3 embeds
   the already-rendered OBJ VRAM from the older candidate, so loading it into a
   newer ROM cannot prove the ROM-side sprite change until the popup is created
   again.  The ROM-side animation-10 clone is retained and statically replayed,
   and a candidate-matched ss3 is emitted with candidate OBJ VRAM plus the live
   sprite-object resource pointer updated for direct savestate verification.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path
from typing import Any
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_save_progress_followup_20260831 as v1
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

PARENT = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_save_progress_candidate_20260831.gba"
PARENT_SHA256 = "8959a8f17bdc465bdcfae9ea2b661e370a4e40f2fc6942cc39d0182dd02a179a"
PARENT_SAV = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_save_progress_candidate_20260831.sav"
SOURCE_STATE3 = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.ss3"
SOURCE_STATE3_SHA256 = "11b53da65e506b00f72d7333d515d5d918cf274d1b7291a02606f7c531388a10"
V1_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_save_progress_followup_ko_20260831.json"

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui"
DEFAULT_OUT = OUT_DIR / "ggen_advance_load_summary_ui_ko_save_progress_followup_candidate_20260831.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_load_summary_ui_ko_save_progress_followup_candidate_20260831.sav"
DEFAULT_STATE3 = OUT_DIR / "ggen_advance_load_summary_ui_ko_save_progress_followup_candidate_20260831.ss3"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_save_progress_followup_v2_ko_20260831.json"

ROM_BASE = 0x08000000
SAVE_PROGRESS_RESOURCE = 0x09298000
SAVE_PROGRESS_POINTER = 0x0001212C
SAVE_PROGRESS_ANIMATION = 10
DATA_SAVE_RESOURCE = 0x092A0000
DATA_SAVE_POINTER = 0x000D590AC
INSTRUCTION = "위데이터를 아래데이터에 덮어씁니다"
PREFIX_WIDTH = 21
TEXT_BANK_END_X = 224  # local pixel coordinate; x=224..231 belongs to palette bank 0
FACE = 10
CONTOUR = 2

SPRITE_OBJECT_TABLE = 0x03001F98
SPRITE_OBJECT_SIZE = 40
STATE3_SPRITE_SLOT = 3
OLD_STATE_RESOURCE = 0x0928C000


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def patch_instruction_in_place(candidate: bytearray, font: fontpair.BdfFont) -> dict[str, Any]:
    gate(u32(candidate, DATA_SAVE_POINTER) == DATA_SAVE_RESOURCE, "data-save pointer no longer selects 22.109 clone")
    resource = bg.parse_bg_resource(bytes(candidate), DATA_SAVE_RESOURCE)
    gate(int(resource["decoded_tiles"]) == 152, "data-save decoded tile count drift")
    off = int(resource["file_offset"])
    map_rel = int(resource["map_relative_offset"])
    map_len = int(resource["map_length"])
    tiles_rel = int(resource["tiles_relative_offset"])
    comp_len = int(resource["compressed_tile_length"])
    palette_rel = int(resource["palette_relative_offset"])
    palette_len = int(resource["palette_length"])
    map_before = bytes(candidate[off + map_rel : off + map_rel + map_len])
    palette_before = bytes(candidate[off + palette_rel : off + palette_rel + palette_len])
    compressed_before = bytes(candidate[off + tiles_rel : off + tiles_rel + comp_len])
    atlas = bytearray(bg.custom_lzss_decompress(compressed_before))
    gate(len(atlas) == 152 * 32, "data-save atlas size drift")
    atlas_before = bytes(atlas)

    rect = (1, 10, 29, 3)
    rows = bg.map_rect(resource, *rect)
    pixels = paintops.stitch_variable(bytes(atlas), rows)
    gate(len(pixels) == 24 and all(len(row) == 232 for row in pixels), "instruction raster dimensions drift")
    gate(set(value for row in pixels for value in row) <= {0, FACE, CONTOUR}, "instruction raster palette drift")
    prefix = [row[:PREFIX_WIDTH] for row in pixels]

    # Clear the complete translated sentence including any old Korean contour.
    cleared = 0
    for y in range(24):
        for x in range(PREFIX_WIDTH, 232):
            if pixels[y][x] in (FACE, CONTOUR):
                cleared += 1
            pixels[y][x] = 0
    gate(cleared > 0, "instruction clear changed no pixels")
    gate([row[:PREFIX_WIDTH] for row in pixels] == prefix, "native A: prefix changed during clear")

    # The last map column x=29 uses palette bank 0, whereas text cells x=1..28
    # use bank 1.  Paint only inside x=21..223 so contour index 2 can never be
    # interpreted through the blue bank-0 palette.
    safe_width = TEXT_BANK_END_X - PREFIX_WIDTH
    safe = [row[PREFIX_WIDTH:TEXT_BANK_END_X] for row in pixels]
    mask, text_width = paintops.make_text_mask(INSTRUCTION, font, safe_width, 24, cell_width=12, space_width=4)
    gate(text_width == 200 and safe_width == 203, f"instruction width contract drift: text={text_width} safe={safe_width}")
    ink, contour = paintops.paint_mask(safe, mask, ink=FACE, contour=CONTOUR)
    gate(ink > 0 and contour > 0, "instruction Korean raster empty")
    expected = [[0] * safe_width for _ in range(24)]
    e_ink, e_contour = paintops.paint_mask(expected, mask, ink=FACE, contour=CONTOUR)
    gate((ink, contour) == (e_ink, e_contour) and safe == expected, "instruction safe raster is not exact Korean mask+contour")
    for y in range(24):
        pixels[y][PREFIX_WIDTH:TEXT_BANK_END_X] = safe[y]
    gate(all(value == 0 for row in pixels for value in row[TEXT_BANK_END_X:]), "palette-bank-0 right column still contains Korean contour")
    gate([row[:PREFIX_WIDTH] for row in pixels] == prefix, "native A: prefix changed after repaint")
    paintops.write_variable(atlas, rows, pixels)

    changed_tiles = [tile for tile in range(152) if atlas_before[tile * 32:(tile + 1) * 32] != atlas[tile * 32:(tile + 1) * 32]]
    gate(changed_tiles, "instruction follow-up changed no decoded tiles")
    new_compressed = paintops.literal_only_lzss_body(bytes(atlas))
    gate(len(new_compressed) == comp_len, f"literal LZSS length changed: {len(new_compressed)} != {comp_len}")
    gate(bg.custom_lzss_decompress(new_compressed) == bytes(atlas), "instruction LZSS round-trip failed")
    candidate[off + tiles_rel : off + tiles_rel + comp_len] = new_compressed
    gate(bytes(candidate[off + map_rel : off + map_rel + map_len]) == map_before, "data-save map changed")
    gate(bytes(candidate[off + palette_rel : off + palette_rel + palette_len]) == palette_before, "data-save palette changed")

    # Explicit map-palette proof for the real-hardware blue fringe.
    map_width = int(resource["width"])
    last_text_column_banks = []
    bank0_column_banks = []
    for y in range(10, 13):
        text_cell = int(resource["cells"][y * map_width + 28])
        edge_cell = int(resource["cells"][y * map_width + 29])
        last_text_column_banks.append((text_cell >> 12) & 0xF)
        bank0_column_banks.append((edge_cell >> 12) & 0xF)
    gate(last_text_column_banks == [1, 1, 1] and bank0_column_banks == [0, 0, 0], "instruction palette-bank boundary drift")

    return {
        "translation": "A:" + INSTRUCTION,
        "text_width_px": text_width,
        "safe_text_local_x": [PREFIX_WIDTH, TEXT_BANK_END_X - 1],
        "forced_transparent_local_x": [TEXT_BANK_END_X, 231],
        "last_text_map_column_palette_banks": last_text_column_banks,
        "right_edge_map_column_palette_banks": bank0_column_banks,
        "face_index": FACE,
        "contour_index": CONTOUR,
        "korean_ink_pixels": ink,
        "korean_contour_pixels": contour,
        "cleared_prior_face_contour_pixels": cleared,
        "changed_decoded_tiles": [f"0x{x:03X}" for x in changed_tiles],
        "blue_right_edge_contour_pixels": 0,
        "map_byte_exact": True,
        "palette_byte_exact": True,
    }


def candidate_animation10_tiles(candidate: bytes) -> tuple[dict[int, bytes], dict[str, Any]]:
    gate(u32(candidate, SAVE_PROGRESS_POINTER) == SAVE_PROGRESS_RESOURCE, "save-progress ROM pointer is not dedicated clone")
    off = SAVE_PROGRESS_RESOURCE - ROM_BASE
    graphics_rel = u32(candidate, off + 0x08)
    palette_rel = u32(candidate, off + 0x0C)
    graphics = candidate[off + graphics_rel : off + palette_rel]
    gate(len(graphics) % 32 == 0 and len(graphics) // 32 == 413, "save-progress clone graphic-count drift")
    _gr, records = bg.animation_records(candidate, SAVE_PROGRESS_RESOURCE)
    _record_start, record = records[SAVE_PROGRESS_ANIMATION]
    parsed = bg.parse_animation_oam(record)
    gate(parsed["object_count"] == 12, "save-progress animation10 OAM drift")
    source_table = int(parsed["entries_end"])
    gate(len(record) - source_table == 244, "save-progress animation10 explicit table span drift")
    explicit = list(struct.unpack_from("<122H", record, source_table))
    tiles: dict[int, bytes] = {}
    for dest, source_id in enumerate(explicit):
        gate(source_id < len(graphics) // 32, f"save-progress source id outside clone: {source_id}")
        tiles[dest] = graphics[source_id * 32 : (source_id + 1) * 32]
    # State3 proved these four right-edge destination tiles are the implicit
    # source run 225..228.  22.109 rewrote those private clone source tiles.
    for dest, source_id in zip(range(124, 128), range(225, 229)):
        tiles[dest] = graphics[source_id * 32 : (source_id + 1) * 32]
    return tiles, {
        "resource": f"0x{SAVE_PROGRESS_RESOURCE:08X}",
        "animation": SAVE_PROGRESS_ANIMATION,
        "explicit_destination_tiles_replayed": 122,
        "implicit_korean_right_edge_destinations": [124, 125, 126, 127],
    }


def replace_gbas_state(source_path: Path, state: bytes, out_path: Path) -> None:
    raw = source_path.read_bytes()
    gate(raw.startswith(b"\x89PNG\r\n\x1a\n"), "source state is not PNG-container mGBA state")
    out = bytearray(raw[:8])
    pos = 8
    replaced = 0
    while pos + 12 <= len(raw):
        length = struct.unpack_from(">I", raw, pos)[0]
        kind = raw[pos + 4:pos + 8]
        payload = raw[pos + 8:pos + 8 + length]
        if kind == b"gbAs":
            payload = zlib.compress(state, 9)
            replaced += 1
        out += struct.pack(">I", len(payload))
        out += kind
        out += payload
        out += struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        pos += 12 + length
        if kind == b"IEND":
            break
    gate(replaced == 1, f"expected one gbAs chunk, found {replaced}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)


def build_candidate_state3(candidate: bytes, font: fontpair.BdfFont, out_path: Path) -> dict[str, Any]:
    gate(sha256(SOURCE_STATE3.read_bytes()) == SOURCE_STATE3_SHA256, "source state3 hash drift")
    source_state, _chunks = statefmt.parse_png_state(SOURCE_STATE3)
    state = bytearray(source_state)
    rom_tiles, replay_report = candidate_animation10_tiles(candidate)
    obj_base = statefmt.STATE_VRAM + statefmt.OBJ_VRAM
    for dest, payload in rom_tiles.items():
        state[obj_base + dest * 32 : obj_base + (dest + 1) * 32] = payload

    # The source ss3 was captured before the dedicated animation-10 clone.  Its
    # live sprite object therefore still remembers 0x0928C000.  Update only the
    # proven slot 3 resource pointer so any subsequent redraw continues to use
    # the candidate ROM clone instead of falling back to the older Japanese VRAM.
    slot_rel = (SPRITE_OBJECT_TABLE - 0x03000000) + STATE3_SPRITE_SLOT * SPRITE_OBJECT_SIZE
    slot_off = statefmt.STATE_IWRAM + slot_rel
    gate(u32(state, slot_off) == OLD_STATE_RESOURCE, f"state3 sprite slot resource drift: 0x{u32(state, slot_off):08X}")
    struct.pack_into("<I", state, slot_off, SAVE_PROGRESS_RESOURCE)

    # Candidate replay must equal the same Korean plane requested in 22.109.
    old_plane, _visible, _obj = v1.build_message_plane_from_state(source_state)
    expected_plane, expected_report = v1.rebuild_message_plane(old_plane, font)
    new_oam = state[statefmt.STATE_OAM : statefmt.STATE_VRAM]
    new_vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    new_obj = bytes(new_vram[statefmt.OBJ_VRAM:])
    visible = []
    for index in range(128):
        row = statefmt.parse_oam_entry(new_oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            visible.append(row)
    gate(len(visible) == 12, "candidate state3 visible OAM drift")
    actual_plane = v1.state_analysis.stitch_live_plane(new_obj, visible[2:10])
    gate(actual_plane == expected_plane, "candidate ROM animation10 replay does not equal Korean target plane")

    replace_gbas_state(SOURCE_STATE3, bytes(state), out_path)
    parsed, _ = statefmt.parse_png_state(out_path)
    gate(parsed == bytes(state), "candidate-matched state3 serialization drift")
    gate(u32(parsed, slot_off) == SAVE_PROGRESS_RESOURCE, "candidate state3 sprite pointer did not persist")
    return {
        **replay_report,
        "source_state3": advance_relative(SOURCE_STATE3),
        "source_state3_sha256": SOURCE_STATE3_SHA256,
        "candidate_state3": advance_relative(out_path),
        "candidate_state3_sha256": sha256(out_path.read_bytes()),
        "state_sprite_slot": STATE3_SPRITE_SLOT,
        "state_resource_pointer_before": f"0x{OLD_STATE_RESOURCE:08X}",
        "state_resource_pointer_after": f"0x{SAVE_PROGRESS_RESOURCE:08X}",
        "candidate_rom_replay_equals_requested_korean_plane": True,
        "korean_lines": expected_report["lines"],
        "japanese_face_shadow_residue": 0,
        "testing_note": "Loading the older ss3 restores its captured Japanese OBJ VRAM. Use the candidate-matched ss3 or recreate the save-progress popup from the candidate ROM/SAV.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PARENT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--out-state3", type=Path, default=DEFAULT_STATE3)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    for path in (args.input, PARENT_SAV, SOURCE_STATE3, V1_MANIFEST, MAIN_TIP_ROM, MAIN_TIP_MANIFEST):
        gate(path.is_file(), f"missing input: {path}")
    parent = args.input.read_bytes()
    gate(len(parent) == 32 * 1024 * 1024 and sha256(parent) == PARENT_SHA256, f"parent hash drift: {sha256(parent)}")
    v1_report = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    gate(v1_report.get("result") == "PASS" and v1_report["output"]["rom_sha256"] == PARENT_SHA256, "22.109 manifest/parent drift")
    main_tip = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main_tip) == main_manifest.get("sha256"), "canonical main TIP/manifest drift")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    candidate = bytearray(parent)
    instruction_report = patch_instruction_in_place(candidate, font)
    output = bytes(candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    shutil.copy2(PARENT_SAV, args.out_sav)
    gate(args.out_sav.read_bytes() == PARENT_SAV.read_bytes(), "follow-up SAV copy drift")
    state_report = build_candidate_state3(output, font, args.out_state3)

    changed = [i for i, (a, b) in enumerate(zip(parent, output)) if a != b]
    resource = bg.parse_bg_resource(parent, DATA_SAVE_RESOURCE)
    data_off = int(resource["file_offset"])
    tiles_start = data_off + int(resource["tiles_relative_offset"])
    tiles_end = tiles_start + int(resource["compressed_tile_length"])
    gate(changed and all(tiles_start <= off < tiles_end for off in changed), "v2 ROM changed outside existing private data-save compressed atlas")
    gate(u32(output, SAVE_PROGRESS_POINTER) == SAVE_PROGRESS_RESOURCE, "v2 altered save-progress pointer")
    gate(output[SAVE_PROGRESS_RESOURCE - ROM_BASE : DATA_SAVE_RESOURCE - ROM_BASE] == parent[SAVE_PROGRESS_RESOURCE - ROM_BASE : DATA_SAVE_RESOURCE - ROM_BASE], "v2 altered the proven save-progress private clone")

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_save_progress_followup_v2_ko_20260831",
        "result": "PASS",
        "source": {
            "parent": advance_relative(args.input),
            "parent_sha256": sha256(parent),
            "v1_manifest": advance_relative(V1_MANIFEST),
            "canonical_main_tip_sha256": sha256(main_tip),
        },
        "data_save_instruction": instruction_report,
        "save_progress_runtime_verification": state_report,
        "output": {
            "rom": advance_relative(args.out),
            "rom_sha256": sha256(output),
            "rom_size": len(output),
            "sav": advance_relative(args.out_sav),
            "sav_sha256": sha256(args.out_sav.read_bytes()),
            "candidate_matched_state3": advance_relative(args.out_state3),
            "candidate_matched_state3_sha256": sha256(args.out_state3.read_bytes()),
            "changed_bytes_vs_parent": len(changed),
        },
        "verification": {
            "result": "PASS",
            "right_edge_palette_bank0_forced_transparent": True,
            "blue_right_edge_contour_pixels": 0,
            "save_progress_ROM_clone_unchanged_from_22_109": True,
            "save_progress_candidate_ROM_replay_matches_Korean_target": True,
            "old_state3_contains_pre_patch_OBJ_VRAM": True,
            "candidate_matched_state3_emitted": True,
            "main_tip_unchanged": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": str(args.out),
        "rom_sha256": sha256(output),
        "sav": str(args.out_sav),
        "state3": str(args.out_state3),
        "state3_sha256": sha256(args.out_state3.read_bytes()),
        "manifest": str(args.manifest),
        "changed_bytes": len(changed),
        "blue_right_edge_contour_pixels": 0,
        "save_progress_replay_korean": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
