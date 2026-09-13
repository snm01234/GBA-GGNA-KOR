#!/usr/bin/env python3
"""Bind fresh state3 to the save-progress OBJ animation used by the load/save UI."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
PARENT = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.gba"
PARENT_SHA256 = "41d1fe82be15df92c3797febde4fc1201717fa3dddf84c43b9711b952dfe0509"
STATE = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_complete_save_candidate_20260831.ss3"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_save_progress_state_20260831.json"
SHARED_CLONE = 0x0928C000
ANIMATION = 10
RESOURCE_REF = 0x0001212C
TEXT_OBJECTS = tuple(range(2, 10))


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_obj_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "OBJ tile must be 32 bytes")
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            out[y][x] = (value >> (4 * (x & 1))) & 0x0F
    return out


def stitch_live_plane(obj_vram: bytes, objects: list[dict[str, Any]]) -> list[list[int]]:
    x0 = min(int(o["x"]) for o in objects)
    y0 = min(int(o["y"]) for o in objects)
    x1 = max(int(o["x"]) + int(o["width"]) for o in objects)
    y1 = max(int(o["y"]) + int(o["height"]) for o in objects)
    gate((x1 - x0, y1 - y0) == (144, 48), "state3 text plane geometry drift")
    canvas = [[0] * 144 for _ in range(48)]
    for o in objects:
        wt = int(o["width"]) // 8
        ht = int(o["height"]) // 8
        for ty in range(ht):
            for tx in range(wt):
                tile = int(o["tile"]) + ty * wt + tx
                raw = obj_vram[tile * 32 : (tile + 1) * 32]
                px = decode_obj_tile(bytes(raw))
                ox = int(o["x"]) - x0 + tx * 8
                oy = int(o["y"]) - y0 + ty * 8
                for yy in range(8):
                    canvas[oy + yy][ox : ox + 8] = px[yy]
    return canvas


def main() -> int:
    gate(PARENT.is_file(), f"missing parent: {PARENT}")
    gate(STATE.is_file(), f"missing state3: {STATE}")
    parent = PARENT.read_bytes()
    gate(sha256(parent) == PARENT_SHA256, f"parent hash drift: {sha256(parent)}")
    gate(u32(parent, RESOURCE_REF) == SHARED_CLONE, "state3 consumer no longer points to shared popup clone")
    gate(u16(parent, 0x000120DC) == 0x230A, "save-progress call no longer selects animation 10")

    state, chunks = statefmt.parse_png_state(STATE)
    oam = state[statefmt.STATE_OAM : statefmt.STATE_VRAM]
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    obj_vram = vram[statefmt.OBJ_VRAM :]
    visible = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            visible.append(row)
    gate(len(visible) == 12, f"state3 visible OAM count drift: {len(visible)}")

    _graphics_rel, records = sprite.animation_records(parent, SHARED_CLONE)
    record_start, record = records[ANIMATION]
    parsed = sprite.parse_animation_oam(record)
    gate(parsed["object_count"] == 12, "animation10 OAM count drift")
    anchor_x = int(visible[0]["x"]) - int(parsed["objects"][0]["x"])
    anchor_y = int(visible[0]["y"]) - int(parsed["objects"][0]["y"])
    gate((anchor_x, anchor_y) == (120, 88), f"state3 animation10 anchor drift: {(anchor_x, anchor_y)}")
    for index, (live, src) in enumerate(zip(visible, parsed["objects"])):
        gate(int(live["x"]) == int(src["x"]) + anchor_x, f"state3 x mismatch object {index}")
        gate(int(live["y"]) == int(src["y"]) + anchor_y, f"state3 y mismatch object {index}")
        gate(int(live["tile"]) == int(src["tile_start"]), f"state3 tile mismatch object {index}")
        gate(int(live["width"]) == int(src["size_px"][0]) and int(live["height"]) == int(src["size_px"][1]), f"state3 size mismatch object {index}")
        gate(int(live["palette_bank"]) == 0, f"state3 palette mismatch object {index}")

    resource_off = SHARED_CLONE - ROM_BASE
    graphics_rel = u32(parent, resource_off + 0x08)
    palette_rel = u32(parent, resource_off + 0x0C)
    graphics = parent[resource_off + graphics_rel : resource_off + palette_rel]
    gate(len(graphics) % 32 == 0, "shared clone graphics alignment drift")

    # Animation 10 stores 122 explicit u16 source entries immediately after the
    # OAM list.  They cover destination tiles 0..121 exactly; later right-hand
    # text tiles are source-graphic matches 225..228 plus native fill tiles.
    source_table = int(parsed["entries_end"])
    gate(len(record) - source_table == 244, "animation10 source-table span drift")
    explicit = list(struct.unpack_from("<122H", record, source_table))
    exact = 0
    for dest, source_id in enumerate(explicit):
        expected = graphics[source_id * 32 : (source_id + 1) * 32]
        actual = bytes(obj_vram[dest * 32 : (dest + 1) * 32])
        if expected == actual:
            exact += 1
    gate(exact == 122, f"state3 explicit source lookup mismatch: {exact}/122")

    unresolved: list[dict[str, Any]] = []
    tile_count = len(graphics) // 32
    for dest in range(122, 138):
        actual = bytes(obj_vram[dest * 32 : (dest + 1) * 32])
        hits = [tile for tile in range(tile_count) if graphics[tile * 32 : (tile + 1) * 32] == actual]
        gate(hits, f"state3 destination tile {dest} has no source graphic match")
        unresolved.append({"destination_tile": dest, "source_matches": hits})
    gate([row["source_matches"][0] for row in unresolved[:6]] == [11, 11, 225, 226, 227, 228], "animation10 implicit right-hand source run drift")

    plane = stitch_live_plane(obj_vram, visible[2:10])
    for y0, y1 in ((9, 23), (25, 39)):
        for y in range(y0, y1):
            gate(any(plane[y][x] in (9, 10) for x in range(2, 140)), f"state3 message row {y} lacks yellow fill")
    source_counts = {str(index): sum(row.count(index) for row in plane) for index in range(16)}

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_save_progress_state_20260831",
        "result": "PASS",
        "parent": {"path": str(PARENT.relative_to(ADVANCE_ROOT)).replace("\\", "/"), "sha256": sha256(parent)},
        "state3": {"path": str(STATE.relative_to(ADVANCE_ROOT)).replace("\\", "/"), "sha256": sha256(STATE.read_bytes()), "chunks": [row["kind"] for row in chunks]},
        "ownership": {
            "consumer_pointer_file_offset": f"0x{RESOURCE_REF:08X}",
            "resource": f"0x{SHARED_CLONE:08X}",
            "animation": ANIMATION,
            "animation_record_file_offset": f"0x{record_start:08X}",
            "state_anchor": [anchor_x, anchor_y],
            "visible_oam_count": len(visible),
            "explicit_source_entries_exact": exact,
            "explicit_source_entries_total": len(explicit),
            "implicit_right_source_matches": unresolved,
            "text_plane_objects": list(TEXT_OBJECTS),
            "text_plane_geometry": [144, 48],
            "text_plane_palette_counts": source_counts,
        },
        "source_japanese": ["セーブ中です", "電源を切らないでください"],
        "translation_requested": ["세이브중입니다", "전원을 끄지말아주세요"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "state3_sha256": report["state3"]["sha256"], "animation": ANIMATION, "explicit_source_exact": exact, "out": str(OUT)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
