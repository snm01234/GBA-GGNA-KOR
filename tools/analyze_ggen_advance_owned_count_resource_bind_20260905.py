#!/usr/bin/env python3
"""Prove the live sprite/resource-manager bind for the 所有数 candidate.

Read-only analysis of the Japanese disposal-list savestate.  The loaded-state
comparison identifies resource 0x08C4654C animation 8 as the plaque/background
package; glyph-bearing tile ownership is checked separately.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as dev
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_resource_bind_20260905.json"
TARGET_RESOURCE = 0x08C4654C
TARGET_ANIMATION = 8
SPRITE_OBJECT_TABLE = 0x03001F98
SPRITE_OBJECT_SIZE = 40
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def signed16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def sprite_slots(state: bytes) -> list[dict[str, Any]]:
    iwram = state[statefmt.STATE_IWRAM:statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    base = SPRITE_OBJECT_TABLE - 0x03000000
    rows: list[dict[str, Any]] = []
    for index in range(100):
        off = base + index * SPRITE_OBJECT_SIZE
        ptr = u32(iwram, off)
        if not (0x08000000 <= ptr < 0x0A000000):
            continue
        rows.append({
            "slot": index,
            "iwram_address": f"0x{SPRITE_OBJECT_TABLE + index * SPRITE_OBJECT_SIZE:08X}",
            "resource": f"0x{ptr:08X}",
            "x": signed16(u16(iwram, off + 0x0A)),
            "y": signed16(u16(iwram, off + 0x0C)),
            "animation": iwram[off + 0x11],
            "field_04": f"0x{u16(iwram, off + 0x04):04X}",
            "field_06": f"0x{u16(iwram, off + 0x06):04X}",
            "field_08": f"0x{u16(iwram, off + 0x08):04X}",
            "field_0E": f"0x{u16(iwram, off + 0x0E):04X}",
            "field_10": f"0x{u16(iwram, off + 0x10):04X}",
            "raw_00_17": bytes(iwram[off:off + 0x18]).hex(),
        })
    return rows


def visible_oam(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    rows: list[dict[str, Any]] = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            rows.append(row)
    return rows


def geometry_matches(slot: dict[str, Any], parsed: dict[str, Any], oam: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    sx, sy = int(slot["x"]), int(slot["y"])
    for obj_index, obj in enumerate(parsed["objects"]):
        ex = sx + int(obj["x"])
        ey = sy + int(obj["y"])
        ew, eh = int(obj["size_px"][0]), int(obj["size_px"][1])
        hits = [
            row for row in oam
            if int(row["x"]) == ex and int(row["y"]) == ey
            and int(row["width"]) == ew and int(row["height"]) == eh
        ]
        matches.append({
            "animation_object": obj_index,
            "local_xy": [int(obj["x"]), int(obj["y"])],
            "expected_screen_xy": [ex, ey],
            "size": [ew, eh],
            "oam_hits": [int(row["index"]) for row in hits],
        })
    return matches


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(JP_STATE.exists(), "Japanese ss1 missing")
    state, chunks = statefmt.parse_png_state(JP_STATE)
    state_crc = u32(state, 0x08)
    rom_crc = binascii.crc32(jp) & 0xFFFFFFFF
    gate(state_crc == rom_crc, f"state ROM CRC 0x{state_crc:08X} != JP ROM 0x{rom_crc:08X}")

    slots = sprite_slots(state)
    target_slots = [row for row in slots if row["resource"] == f"0x{TARGET_RESOURCE:08X}"]
    exact_slots = [row for row in target_slots if int(row["animation"]) == TARGET_ANIMATION]

    header = dev.parse_resource_header(jp, TARGET_RESOURCE)
    _graphics_rel, records = dev.sprite.animation_records(jp, TARGET_RESOURCE)
    parsed, source_ids = dev.parse_animation(records, TARGET_ANIMATION)
    oam = visible_oam(state)

    bound_geometry = []
    for slot in exact_slots:
        gm = geometry_matches(slot, parsed, oam)
        bound_geometry.append({
            "slot": slot["slot"],
            "object_count": len(gm),
            "objects_with_oam_geometry_hit": sum(bool(row["oam_hits"]) for row in gm),
            "matches": gm,
        })

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_resource_bind_20260905",
        "result": "PASS" if exact_slots else "FAIL",
        "source": {
            "rom": advance_relative(ORIGINAL_ROM),
            "rom_sha256": sha256(jp),
            "state": advance_relative(JP_STATE),
            "state_sha256": sha256(JP_STATE.read_bytes()),
            "state_rom_crc32": f"0x{state_crc:08X}",
            "png_chunks": chunks,
        },
        "target": {
            "resource": f"0x{TARGET_RESOURCE:08X}",
            "animation": TARGET_ANIMATION,
            "resource_header": {
                "animation_count": header["animation_count"],
                "source_tiles": header["source_tiles"],
                "resource_bytes": header["resource_bytes"],
            },
            "resident_slots": target_slots,
            "exact_resource_animation_slots": exact_slots,
            "animation_object_count": len(parsed["objects"]),
            "animation_source_ids": source_ids,
            "animation_objects": parsed["objects"],
            "geometry_bind": bound_geometry,
        },
        "all_resident_sprite_slots": slots,
        "visible_oam": oam,
        "conclusion": (
            "resource + animation bind proven in the live sprite object manager"
            if exact_slots else
            "target resource/animation is not bound in this captured state"
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": report["result"],
        "out": advance_relative(OUT),
        "target_slots": target_slots,
        "exact_slots": exact_slots,
        "geometry_summary": [
            {"slot": row["slot"], "hits": row["objects_with_oam_geometry_hit"], "objects": row["object_count"]}
            for row in bound_geometry
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if exact_slots else 2


if __name__ == "__main__":
    raise SystemExit(main())
