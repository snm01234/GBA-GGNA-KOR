#!/usr/bin/env python3
"""Bind the fresh load-complete and data-save states to ROM graphics.

State1 is the post-load completion popup.  Its 11 visible OBJs are animation 6
of shared sprite package 0x08C7504C and all 44 destination tiles match that
animation's source lookup exactly.  Animation 4 is the parallel save-complete
member of the same normal-only completion family.

State2 is the data-save screen.  BG1 charblock 0 / screenblock 14 is byte-exact
to fixed BG resource 0x08C78E7C (152/152 tiles, 600/600 map cells).  The fixed
Japanese graphics are データセーブ, クリア, プレイ時間, ゲームモード and the
A: instruction strip.  The repeated upper/lower labels share source tiles only
with their same semantic duplicate; the complete target set has no users
outside those selected cells.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
PARENT = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_popup_candidate_20260831.gba"
STATE1 = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_popup_candidate_20260831.ss1"
STATE2 = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_popup_candidate_20260831.ss2"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_load_complete_save_screen_state_20260831.json"

SPRITE_RESOURCE = 0x08C7504C
OLD_SPRITE_CLONE = 0x09284000
SPRITE_POINTER_REFS = (0x0001212C, 0x000121CC, 0x00026B6C, 0x0007385C)
SAVE_BG_RESOURCE = 0x08C78E7C
SAVE_BG_OWNER_POINTER = 0x00D590AC

SAVE_TARGET_RECTS = {
    "data_save": ((10, 1, 10, 2),),
    "clear": ((25, 4, 4, 2), (25, 14, 4, 2)),
    "play_time": ((1, 7, 8, 2), (1, 17, 8, 2)),
    "game_mode": ((15, 7, 9, 2), (15, 17, 9, 2)),
    "instruction": ((1, 10, 29, 3),),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


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


def cross_source_map(jp: bytes, animation: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the source lookup even when it crosses the next animation pointer.

    Completion animations 4..7 place the 44-entry u16 source lookup directly
    after their OAM list.  The final entries intentionally live in the prefix
    bytes before the next animation's metasprite marker, so the generic parser
    (which slices records at the next pointer) is too conservative here.
    """
    resource_off = SPRITE_RESOURCE - ROM_BASE
    _graphics_rel, records = bg.animation_records(jp, SPRITE_RESOURCE)
    start, record = records[animation]
    parsed = bg.parse_animation_oam(record)
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    source_start = start + int(parsed["entries_end"])
    gate(source_start + total * 2 <= resource_off + u32(jp, resource_off + 8), f"animation {animation} source map overruns graphics start")
    ids = list(struct.unpack_from(f"<{total}H", jp, source_start))
    by_object: list[list[int]] = []
    cursor = 0
    for obj in parsed["objects"]:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor:cursor + count])
        cursor += count
    gate(cursor == total, f"animation {animation} source map length drift")
    return parsed, {
        "source_start": source_start,
        "source_start_relative": source_start - resource_off,
        "source_ids": ids,
        "by_object": by_object,
        "total_source_entries": total,
    }


def visible_oam(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    rows = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            rows.append(row)
    return rows


def state1_report(jp: bytes) -> dict[str, Any]:
    state, chunks = statefmt.parse_png_state(STATE1)
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    gate(u16(io, 0) & 0x1000, "state1 OBJ layer disabled")
    gate(u16(io, 0) & 0x40, "state1 is not OBJ 1D mapping")
    visible = visible_oam(state)
    gate(len(visible) == 11, f"state1 completion popup OAM count drift: {len(visible)}")
    expected_geometry = [
        (88, 68, 0, 32, 8, 1), (120, 68, 4, 32, 8, 1), (152, 68, 8, 16, 8, 1),
        (88, 92, 10, 32, 8, 1), (120, 92, 14, 32, 8, 1), (152, 92, 18, 16, 8, 1),
        (80, 68, 20, 8, 16, 1), (80, 84, 22, 8, 16, 1),
        (88, 76, 24, 32, 16, 0), (120, 76, 32, 32, 16, 0), (152, 76, 40, 16, 16, 0),
    ]
    actual_geometry = [(int(r["x"]), int(r["y"]), int(r["tile"]), int(r["width"]), int(r["height"]), int(r["palette_bank"])) for r in visible]
    gate(actual_geometry == expected_geometry, "state1 completion popup geometry drift")

    resource_off = SPRITE_RESOURCE - ROM_BASE
    graphics_rel = u32(jp, resource_off + 8)
    palette_rel = u32(jp, resource_off + 0x0C)
    graphics = jp[resource_off + graphics_rel:resource_off + palette_rel]
    gate(len(graphics) % 32 == 0, "shared sprite graphics alignment drift")
    parsed6, source6 = cross_source_map(jp, 6)
    parsed4, source4 = cross_source_map(jp, 4)
    gate(parsed6["object_count"] == parsed4["object_count"] == 11, "completion family object-count drift")
    gate(source6["source_ids"][:24] == source4["source_ids"][:24], "save/load completion frame source maps differ")

    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    obj = vram[statefmt.OBJ_VRAM:]
    matches = 0
    cursor = 0
    for ob in parsed6["objects"]:
        count = int(ob["tile_count"])
        dest = int(ob["tile_start"])
        ids = source6["source_ids"][cursor:cursor + count]
        for local, source_id in enumerate(ids):
            live = bytes(obj[(dest + local) * 32:(dest + local + 1) * 32])
            native = graphics[int(source_id) * 32:(int(source_id) + 1) * 32]
            matches += live == native
        cursor += count
    gate(matches == 44, f"state1 does not match animation 6: {matches}/44")

    return {
        "path": str(STATE1.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
        "sha256": sha256(STATE1.read_bytes()),
        "chunks": [row["kind"] for row in chunks],
        "visible_oam": actual_geometry,
        "animation": 6,
        "semantic": "ロード完了",
        "all_obj_tiles_exact": matches,
        "save_complete_parallel_animation": 4,
        "save_complete_parallel_semantic": "セーブ完了",
        "animation4_label_source_ids": source4["source_ids"][24:44],
        "animation6_label_source_ids": source6["source_ids"][24:44],
        "completion_label_objects": [8, 9, 10],
        "completion_style": "normal_yellow_palette0_only",
    }


def rect_indices(resource: dict[str, Any], rect: tuple[int, int, int, int]) -> set[int]:
    x, y, width, height = rect
    mw = int(resource["width"])
    return {(y + yy) * mw + x + xx for yy in range(height) for xx in range(width)}


def state2_report(jp: bytes, parent: bytes) -> dict[str, Any]:
    state, chunks = statefmt.parse_png_state(STATE2)
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    bg1cnt = u16(io, 10)
    charblock = (bg1cnt >> 2) & 3
    screenblock = (bg1cnt >> 8) & 31
    gate((charblock, screenblock) == (0, 14), f"state2 BG1 binding drift: {charblock}/{screenblock}")

    resource = bg.parse_bg_resource(jp, SAVE_BG_RESOURCE)
    off = int(resource["file_offset"])
    comp = jp[off + int(resource["tiles_relative_offset"]):off + int(resource["tiles_relative_offset"]) + int(resource["compressed_tile_length"])]
    atlas = bg.custom_lzss_decompress(comp)
    gate(int(resource["decoded_tiles"]) == 152, f"data-save tile count drift: {resource['decoded_tiles']}")
    exact_tiles = 0
    char_base = charblock * 0x4000
    for tile in range(152):
        live = bytes(vram[char_base + tile * 32:char_base + (tile + 1) * 32])
        exact_tiles += live == atlas[tile * 32:(tile + 1) * 32]
    gate(exact_tiles == 152, f"state2 data-save atlas mismatch: {exact_tiles}/152")

    live_cells = [u16(vram, screenblock * 0x800 + (y * 32 + x) * 2) for y in range(20) for x in range(30)]
    exact_map = sum((a & 0x03FF) == (b & 0x03FF) for a, b in zip(live_cells, resource["cells"]))
    gate(exact_map == 600, f"state2 data-save map mismatch: {exact_map}/600")
    gate(pointer_hits(parent, SAVE_BG_RESOURCE) == [SAVE_BG_OWNER_POINTER], "data-save BG owner pointer is not unique in parent")

    target_indices: set[int] = set()
    per_target: dict[str, Any] = {}
    for key, rects in SAVE_TARGET_RECTS.items():
        indices: set[int] = set()
        for rect in rects:
            indices.update(rect_indices(resource, rect))
        target_indices.update(indices)
        per_target[key] = {
            "rects": [list(rect) for rect in rects],
            "map_cells": len(indices),
            "source_tiles": sorted({int(resource["cells"][idx]) & 0x03FF for idx in indices}),
        }
    target_tiles = {int(resource["cells"][idx]) & 0x03FF for idx in target_indices}
    outside_tiles = {int(resource["cells"][idx]) & 0x03FF for idx in range(600) if idx not in target_indices}
    gate(len(target_indices) == 191, f"data-save target cell count drift: {len(target_indices)}")
    gate(len(target_tiles) == 149, f"data-save target tile count drift: {len(target_tiles)}")
    gate(not (target_tiles & outside_tiles), f"data-save target tiles shared outside target cells: {sorted(target_tiles & outside_tiles)}")

    instruction_rows = bg.map_rect(resource, 1, 10, 29, 3)
    instruction = paintops.stitch_variable(atlas, instruction_rows)
    gate(len(instruction) == 24 and all(len(row) == 232 for row in instruction), "instruction raster dimensions drift")
    indices = {value for row in instruction for value in row}
    gate(indices <= {0, 2, 10} and 2 in indices and 10 in indices, f"instruction palette indices drift: {sorted(indices)}")
    active_columns = [x for x in range(232) if any(instruction[y][x] in (2, 10) for y in range(24))]
    runs: list[list[int]] = []
    for x in active_columns:
        if not runs or x != runs[-1][-1] + 1:
            runs.append([])
        runs[-1].append(x)
    compact_runs = [[run[0], run[-1]] for run in runs]
    gate(compact_runs == [[0, 13], [15, 18], [21, 222]], f"instruction A:/Japanese runs drift: {compact_runs}")

    return {
        "path": str(STATE2.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
        "sha256": sha256(STATE2.read_bytes()),
        "chunks": [row["kind"] for row in chunks],
        "bg1": {"charblock": charblock, "screenblock": screenblock, "atlas_exact": exact_tiles, "map_exact": exact_map},
        "resource": f"0x{SAVE_BG_RESOURCE:08X}",
        "owner_pointer": f"0x{SAVE_BG_OWNER_POINTER:08X}",
        "target_cells": len(target_indices),
        "target_tiles": len(target_tiles),
        "target_tiles_shared_outside": 0,
        "targets": per_target,
        "instruction": {
            "source": "A:上のデータを下のデータに上書きします",
            "active_column_runs": compact_runs,
            "native_A_colon_run": [0, 18],
            "japanese_text_run": [21, 222],
            "palette_indices": sorted(indices),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    for path in (JP_ROM, PARENT, STATE1, STATE2):
        gate(path.is_file(), f"missing input: {path}")
    jp = JP_ROM.read_bytes()
    parent = PARENT.read_bytes()
    gate(all(u32(parent, off) == OLD_SPRITE_CLONE for off in SPRITE_POINTER_REFS), "parent shared-sprite pointer redirect drift")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_load_complete_save_screen_state_20260831",
        "result": "PASS",
        "parent": {
            "path": str(PARENT.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "sha256": sha256(parent),
        },
        "state1_load_complete": state1_report(jp),
        "state2_data_save": state2_report(jp, parent),
        "verification": {
            "state1_animation6_obj_source_exact": True,
            "animation4_parallel_save_complete_family_identified": True,
            "state2_bg1_resource_exact": True,
            "state2_target_tiles_private_to_selected_semantics": True,
            "state2_instruction_A_prefix_separated_from_japanese_run": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "state1_sha256": report["state1_load_complete"]["sha256"],
        "state1_animation": report["state1_load_complete"]["animation"],
        "state2_sha256": report["state2_data_save"]["sha256"],
        "state2_resource": report["state2_data_save"]["resource"],
        "state2_target_tiles": report["state2_data_save"]["target_tiles"],
        "out": str(args.out),
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
