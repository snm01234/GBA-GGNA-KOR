#!/usr/bin/env python3
"""Bind main-tip ss1/ss2 develop-menu buttons to ROM sprite packages.

state1 (改造 normal + 強化 focus) is live OBJ from package 0x08C5D5F0
animations 2 and 1.  state2 (分解実行 focus + キャンセル normal) is live OBJ
from package 0x08C5FD14 animation 4.  Sibling package 0x08C4654C uses the same
48x16 + 64x16 popup grammar on the resupply/disposal hangar path.

This analyzer is read-only.
"""
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
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
STATE1 = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
STATE2 = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_develop_menu_buttons_state_20260901.json"

DEV_RESOURCE = 0x08C5D5F0
POPUP_RESOURCE = 0x08C5FD14
SUPPLY_RESOURCE = 0x08C4654C
SPRITE_OBJECT_TABLE = 0x03001F98
SPRITE_OBJECT_SIZE = 40
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
STATE1_SHA256 = "c7b8f3dafd46f5d52d604ce645c168f3ac166b5cdc374c968329af8aeb4170d4"
STATE2_SHA256 = "36d3b23a9bd82b59d235593955edcc52c0242de42b3c9a038577129cc4ff500b"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def pointer_hits(data: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    hits: list[int] = []
    cursor = 0
    while True:
        found = data.find(needle, cursor)
        if found < 0:
            return hits
        hits.append(found)
        cursor = found + 1


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "tile must be 32 bytes")
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            out[y][x] = (value >> (4 * (x & 1))) & 0x0F
    return out


def parse_resource_header(rom: bytes, address: int) -> dict[str, Any]:
    off = address - ROM_BASE
    kind = u32(rom, off)
    palette_count = u32(rom, off + 4)
    graphics_rel = u32(rom, off + 8)
    palette_rel = u32(rom, off + 0x0C)
    anim_count = u32(rom, off + 0x10)
    graphics_bytes = palette_rel - graphics_rel
    gate(kind == 0 and palette_count == 6, f"resource 0x{address:08X} is not kind0/6-palette sprite")
    gate(graphics_bytes > 0 and graphics_bytes % 32 == 0, f"resource 0x{address:08X} graphics size drift")
    gate(1 <= anim_count <= 16, f"resource 0x{address:08X} animation count drift")
    return {
        "address": address,
        "offset": off,
        "palette_count": palette_count,
        "graphics_rel": graphics_rel,
        "palette_rel": palette_rel,
        "animation_count": anim_count,
        "source_tiles": graphics_bytes // 32,
        "resource_bytes": palette_rel + palette_count * 32,
        "graphics": rom[off + graphics_rel:off + palette_rel],
        "palettes": rom[off + palette_rel:off + palette_rel + palette_count * 32],
    }


def find_marker(record: bytes) -> int | None:
    start = 0
    while True:
        pos = record.find(b"\x40\x00\x40\x00", start)
        if pos < 0:
            return None
        if pos + 0x2C <= len(record) and 1 <= u16(record, pos + 0x22) <= 64:
            return pos
        start = pos + 2


def parse_animation(records: list[tuple[int, bytes]], index: int) -> tuple[dict[str, Any], list[int]]:
    record = records[index][1]
    marker = find_marker(record)
    gate(marker is not None, f"animation {index} metasprite marker missing")
    sliced = record[marker:]
    parsed = sprite.parse_animation_oam(sliced)
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    blob = b"".join(item[1] for item in records[index:])[marker:]
    gate(parsed["entries_end"] + total * 2 <= len(blob), f"animation {index} source lookup truncated")
    ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
    return parsed, ids


def stitch(graphics: bytes, parsed: dict[str, Any], ids: list[int], indices: list[int]) -> list[list[int]]:
    objects = parsed["objects"]
    by_object: list[list[int]] = []
    cursor = 0
    for obj in objects:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor:cursor + count])
        cursor += count
    objs = [objects[i] for i in indices]
    x0 = min(int(obj["x"]) for obj in objs)
    y0 = min(int(obj["y"]) for obj in objs)
    x1 = max(int(obj["x"]) + int(obj["size_px"][0]) for obj in objs)
    y1 = max(int(obj["y"]) + int(obj["size_px"][1]) for obj in objs)
    canvas = [[0] * (x1 - x0) for _ in range(y1 - y0)]
    for i in indices:
        obj = objects[i]
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        src = by_object[i]
        gate(len(src) == wt * ht, "source lookup length drift")
        for ty in range(ht):
            for tx in range(wt):
                tile = decode_tile(graphics[src[ty * wt + tx] * 32:(src[ty * wt + tx] + 1) * 32])
                ox = int(obj["x"]) - x0 + tx * 8
                oy = int(obj["y"]) - y0 + ty * 8
                for yy in range(8):
                    canvas[oy + yy][ox:ox + 8] = tile[yy]
    return canvas


def live_tiles(obj: bytes, dest: list[int]) -> list[bytes]:
    return [bytes(obj[tile * 32:tile * 32 + 32]) for tile in dest]


def match_dest_to_source(obj: bytes, graphics: bytes, dest: list[int], source_ids: list[int]) -> int:
    gate(len(dest) == len(source_ids), "dest/source length drift")
    exact = 0
    for dest_id, source_id in zip(dest, source_ids):
        live = bytes(obj[dest_id * 32:dest_id * 32 + 32])
        expected = graphics[source_id * 32:(source_id + 1) * 32]
        exact += live == expected
    return exact


def list_slots(iwram: bytes) -> list[dict[str, Any]]:
    rows = []
    base = SPRITE_OBJECT_TABLE - 0x03000000
    for index in range(80):
        off = base + index * SPRITE_OBJECT_SIZE
        ptr = u32(iwram, off)
        if not (0x08000000 <= ptr <= 0x0A000000):
            continue
        rows.append({
            "slot": index,
            "resource": f"0x{ptr:08X}",
            "x": u16(iwram, off + 0x0A),
            "y": u16(iwram, off + 0x0C),
            "anim": iwram[off + 0x11],
        })
    return rows


def visible_oam(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    rows = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            rows.append(row)
    return sorted(rows, key=lambda r: (r["y"], r["x"], r["index"]))


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    main_rom = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(jp) == EXPECTED_JP_SHA256, "JP ROM hash drift")
    gate(sha256(main_rom) == manifest["sha256"], "main TIP/manifest hash drift")
    gate(sha256(STATE1.read_bytes()) == STATE1_SHA256, "state1 hash drift")
    gate(sha256(STATE2.read_bytes()) == STATE2_SHA256, "state2 hash drift")

    s1, _ = statefmt.parse_png_state(STATE1)
    s2, _ = statefmt.parse_png_state(STATE2)
    obj1 = s1[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    obj2 = s2[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    iw1 = s1[statefmt.STATE_IWRAM:statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    iw2 = s2[statefmt.STATE_IWRAM:statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    vis1 = visible_oam(s1)
    vis2 = visible_oam(s2)

    gate(len(vis1) == 4, f"state1 visible OAM drift: {len(vis1)}")
    gate([(r["x"], r["y"], r["width"], r["height"], r["tile"], r["palette_bank"]) for r in vis1] == [
        (192, 120, 32, 16, 0, 0),
        (224, 120, 16, 16, 8, 0),
        (192, 136, 32, 16, 30, 1),
        (224, 136, 16, 16, 38, 1),
    ], "state1 button OAM geometry drift")

    slots1 = list_slots(iw1)
    slots2 = list_slots(iw2)
    kaizo_slot = next(row for row in slots1 if row["resource"] == f"0x{DEV_RESOURCE:08X}" and row["anim"] == 2)
    kyoka_slot = next(row for row in slots1 if row["resource"] == f"0x{DEV_RESOURCE:08X}" and row["anim"] == 1)
    popup_slot = next(row for row in slots2 if row["resource"] == f"0x{POPUP_RESOURCE:08X}" and row["anim"] == 4)
    gate((kaizo_slot["x"], kaizo_slot["y"]) == (192, 120), "state1 改造 slot anchor drift")
    gate((kyoka_slot["x"], kyoka_slot["y"]) == (192, 136), "state1 強化 slot anchor drift")
    gate((popup_slot["x"], popup_slot["y"]) == (80, 56), "state2 popup slot anchor drift")

    headers = {name: parse_resource_header(jp, addr) for name, addr in (
        ("develop", DEV_RESOURCE),
        ("dismantle_popup", POPUP_RESOURCE),
        ("supply", SUPPLY_RESOURCE),
    )}
    for name, header in headers.items():
        main_header = parse_resource_header(main_rom, header["address"])
        gate(main_header["graphics"] == header["graphics"], f"{name} graphics already differ in main TIP")
        gate(main_header["palettes"] == header["palettes"], f"{name} palettes already differ in main TIP")

    _gr, dev_records = sprite.animation_records(jp, DEV_RESOURCE)
    _gr, pop_records = sprite.animation_records(jp, POPUP_RESOURCE)
    parsed1, ids1 = parse_animation(dev_records, 1)
    parsed2, ids2 = parse_animation(dev_records, 2)
    parsed4, ids4 = parse_animation(pop_records, 4)
    gate(ids2 == list(range(20, 32)), "改造 normal source ids drift")
    gate(ids1[:12] == [0, 12, 13, 14, 4, 15, 16, 17, 18, 9, 19, 11], "強化 focus source ids drift")
    gate(match_dest_to_source(obj1, headers["develop"]["graphics"], list(range(0, 12)), ids2) == 12, "state1 改造 dest 0-11 mismatch")
    gate(match_dest_to_source(obj1, headers["develop"]["graphics"], list(range(30, 42)), ids1) == 12, "state1 強化 dest 30-41 mismatch")

    by_object: list[list[int]] = []
    cursor = 0
    for obj in parsed4["objects"]:
        count = int(obj["tile_count"])
        by_object.append(ids4[cursor:cursor + count])
        cursor += count
    bunkai_ids = by_object[6] + by_object[7]
    cancel_ids = by_object[8] + by_object[9]
    gate(bunkai_ids == list(range(53, 69)), "分解実行 source ids drift")
    gate(cancel_ids == list(range(69, 85)), "キャンセル source ids drift")
    gate(match_dest_to_source(obj2, headers["dismantle_popup"]["graphics"], list(range(520, 536)), bunkai_ids) == 16, "state2 分解実行 dest mismatch")
    gate(match_dest_to_source(obj2, headers["dismantle_popup"]["graphics"], list(range(536, 552)), cancel_ids) == 16, "state2 キャンセル dest mismatch")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_develop_menu_buttons_state_20260901",
        "result": "PASS",
        "main_tip_sha256": sha256(main_rom),
        "state1": {
            "path": advance_relative(STATE1),
            "sha256": STATE1_SHA256,
            "resource": f"0x{DEV_RESOURCE:08X}",
            "visible_oam": vis1,
            "slots": slots1,
            "semantic": {
                "改造_normal_blue": {"anim": 2, "screen": [192, 120, 48, 16], "pal": 0, "source_ids": ids2},
                "強化_focus_orange": {"anim": 1, "screen": [192, 136, 48, 16], "pal": 1, "source_ids": ids1},
            },
            "live_match": {"改造": "12/12", "強化": "12/12"},
        },
        "state2": {
            "path": advance_relative(STATE2),
            "sha256": STATE2_SHA256,
            "resource": f"0x{POPUP_RESOURCE:08X}",
            "visible_oam_count": len(vis2),
            "slots": slots2,
            "semantic": {
                "分解実行_focus": {"anim": 4, "screen": [88, 64, 64, 16], "pal": 7, "source_ids": bunkai_ids},
                "キャンセル_normal": {"anim": 4, "screen": [88, 80, 64, 16], "pal": 8, "source_ids": cancel_ids},
            },
            "live_match": {"分解実行": "16/16", "キャンセル": "16/16"},
        },
        "packages": {
            name: {
                "address": f"0x{header['address']:08X}",
                "file_offset": f"0x{header['offset']:08X}",
                "source_tiles": header["source_tiles"],
                "animation_count": header["animation_count"],
                "resource_bytes": header["resource_bytes"],
                "pointer_hits": [f"0x{x:08X}" for x in pointer_hits(jp, header["address"])],
            }
            for name, header in headers.items()
        },
        "similar_kind": {
            "supply_package": f"0x{SUPPLY_RESOURCE:08X}",
            "reason": "same kind0 48x16 button + 12-OBJ 64x16 confirm-popup grammar as the develop/dismantle packages",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(OUT),
        "state1": report["state1"]["semantic"],
        "state2": report["state2"]["semantic"],
        "packages": {k: v["pointer_hits"] for k, v in report["packages"].items()},
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
