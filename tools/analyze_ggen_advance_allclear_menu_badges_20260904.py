#!/usr/bin/env python3
"""Analyze the stale all-clear title/submenu badge states against current main TIP.

The states were captured from SD Gundam GGeneration Advance (Korean)_allclear.gba.
They expose the still-Japanese 80x16 menu badges in shared sprite resource
0x08CCFE40.  The current promoted main TIP keeps this resource byte-exact, so
these stale states remain valid ownership evidence even though their ROM CRC is
older than the current main TIP.
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

import analyze_ggen_advance_remaining_ui_states_20260902 as remaining
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
RESOURCE = 0x08CCFE40
OLD_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.gba"
STATES = {
    1: ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.ss1",
    2: ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.ss2",
    3: ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.ss3",
}
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_20260904.json"

# The semantic assignments follow the visible left-to-right menu order supplied
# by the user.  Duplicate animation IDs share the exact same source-tile set.
TARGETS: dict[str, dict[str, Any]] = {
    "はじめから": {"ko": "처음부터", "animations": [0, 9], "state": 1, "live_animation": 0, "center_x": 40},
    "つづきから": {"ko": "이어하기", "animations": [1, 10], "state": 1, "live_animation": 10, "center_x": 120},
    "おまけ": {"ko": "부록", "animations": [2, 11], "state": 1, "live_animation": 2, "center_x": 200},
    "ロード": {"ko": "로드", "animations": [5, 14], "state": 2, "live_animation": 14, "center_x": 72},
    "コンティニュー": {"ko": "컨티뉴", "animations": [21], "state": 2, "live_animation": 21, "center_x": 168},
    "プロフィール": {"ko": "프로필", "animations": [7, 16], "state": 3, "live_animation": 16, "center_x": 168},
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def animation_info(rom: bytes, records: list[tuple[int, bytes]], index: int) -> dict[str, Any]:
    blob = b"".join(record for _off, record in records[index:])
    marker = blob.find(b"\x40\x00\x40\x00")
    gate(marker >= 0, f"animation {index} metasprite marker missing")
    parsed = sprite.parse_animation_oam(blob[marker:])
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    source_start = marker + int(parsed["entries_end"])
    source_end = source_start + total * 2
    gate(source_end <= len(blob), f"animation {index} source table truncated")
    ids = list(struct.unpack_from(f"<{total}H", blob, source_start))
    by_object: list[list[int]] = []
    cursor = 0
    for obj in parsed["objects"]:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor:cursor + count])
        cursor += count
    gate(cursor == total, f"animation {index} source count drift")
    return {
        "index": index,
        "marker": marker,
        "objects": parsed["objects"],
        "source_ids": ids,
        "source_by_object": by_object,
    }


def visible_oam(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    rows = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            rows.append(row)
    return rows


def live_match(
    state: bytes,
    graphics: bytes,
    anim: dict[str, Any],
    center_x: int,
    center_y: int,
) -> dict[str, Any]:
    obj_vram = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    visible = visible_oam(state)
    matched_tiles = 0
    expected_tiles = 0
    bindings = []
    for obj, source_ids in zip(anim["objects"], anim["source_by_object"]):
        sx = center_x + int(obj["x"])
        sy = center_y + int(obj["y"])
        width, height = [int(value) for value in obj["size_px"]]
        matches = [
            row for row in visible
            if int(row["x"]) == sx and int(row["y"]) == sy
            and int(row["width"]) == width and int(row["height"]) == height
        ]
        gate(len(matches) == 1, f"live OAM binding ambiguous at ({sx},{sy}) {width}x{height}")
        row = matches[0]
        dest = int(row["tile"])
        exact = 0
        for local, source_id in enumerate(source_ids):
            live = bytes(obj_vram[(dest + local) * 32:(dest + local + 1) * 32])
            expected = graphics[source_id * 32:(source_id + 1) * 32]
            exact += live == expected
        matched_tiles += exact
        expected_tiles += len(source_ids)
        bindings.append({
            "screen": [sx, sy, width, height],
            "dest_tile": dest,
            "palette_bank": int(row["palette_bank"]),
            "source_ids": source_ids,
            "exact_tiles": exact,
            "tile_count": len(source_ids),
        })
    return {
        "exact_tiles": matched_tiles,
        "tile_count": expected_tiles,
        "result": "PASS" if matched_tiles == expected_tiles else "FAIL",
        "objects": bindings,
    }


def main() -> int:
    old = OLD_ROM.read_bytes()
    main = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(old) == len(main) == 32 * 1024 * 1024, "expected 32 MiB old/current ROMs")
    gate(sha256(main) == main_manifest["sha256"], "current main TIP/manifest hash drift")

    resource_off = RESOURCE - ROM_BASE
    kind, palette_count, graphics_rel, palette_rel, animation_count = struct.unpack_from("<5I", old, resource_off)
    gate((kind, palette_count) == (0, 6), "resource header kind/palette drift")
    gate((graphics_rel, palette_rel, animation_count) == (0x0DE4, 0x2BE4, 26), "resource layout drift")
    resource_bytes = palette_rel + palette_count * 32
    gate(old[resource_off:resource_off + resource_bytes] == main[resource_off:resource_off + resource_bytes], "current main resource already differs from allclear source")
    graphics = old[resource_off + graphics_rel:resource_off + palette_rel]
    gate(len(graphics) == 240 * 32, "source tile count drift")

    _graphics_rel, records = sprite.animation_records(old, RESOURCE)
    animations = {index: animation_info(old, records, index) for index in range(animation_count)}
    # Proven duplicate animation pairs used by the captured states.
    for left, right in ((0, 9), (1, 10), (2, 11), (5, 14), (7, 16)):
        gate(animations[left]["source_ids"] == animations[right]["source_ids"], f"animation duplicate drift {left}/{right}")

    state_rows: dict[str, Any] = {}
    parsed_states: dict[int, bytes] = {}
    old_crc = binascii.crc32(old) & 0xFFFFFFFF
    for number, path in STATES.items():
        raw = path.read_bytes()
        state, _chunks = statefmt.parse_png_state(path)
        state_crc = u32(state, 8)
        gate(state_crc == old_crc, f"ss{number} CRC 0x{state_crc:08X} != allclear ROM 0x{old_crc:08X}")
        parsed_states[number] = state
        slots = remaining.sprite_slots(state)
        resource_slots = [row for row in slots if row["resource"] == f"0x{RESOURCE:08X}"]
        state_rows[str(number)] = {
            "path": advance_relative(path),
            "sha256": sha256(raw),
            "rom_crc32": f"0x{state_crc:08X}",
            "resource_slots": resource_slots,
            "visible_oam": visible_oam(state),
        }

    target_rows = []
    for jp, spec in TARGETS.items():
        state_number = int(spec["state"])
        live_animation = int(spec["live_animation"])
        center_x = int(spec["center_x"])
        state = parsed_states[state_number]
        slots = state_rows[str(state_number)]["resource_slots"]
        matching_slots = [
            row for row in slots
            if int(row["animation"]) == live_animation and int(row["x"]) == center_x and int(row["y"]) == 136
        ]
        gate(len(matching_slots) == 1, f"{jp}: expected one live sprite-manager slot")
        live = live_match(state, graphics, animations[live_animation], center_x, 136)
        gate(live["result"] == "PASS", f"{jp}: live OBJ/source mismatch {live['exact_tiles']}/{live['tile_count']}")
        target_rows.append({
            "source": jp,
            "translation": spec["ko"],
            "animation_family": spec["animations"],
            "live_state": state_number,
            "live_animation": live_animation,
            "screen_center": [center_x, 136],
            "source_ids": animations[live_animation]["source_ids"],
            "live_match": live,
        })

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_allclear_menu_badges_20260904",
        "result": "PASS",
        "stale_source_rom": {
            "path": advance_relative(OLD_ROM),
            "sha256": sha256(old),
            "crc32": f"0x{old_crc:08X}",
        },
        "current_main_tip": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(main),
            "crc32": f"0x{binascii.crc32(main) & 0xFFFFFFFF:08X}",
        },
        "resource": {
            "address": f"0x{RESOURCE:08X}",
            "file_offset": f"0x{resource_off:08X}",
            "graphics_rel": f"0x{graphics_rel:X}",
            "palette_rel": f"0x{palette_rel:X}",
            "animation_count": animation_count,
            "source_tiles": len(graphics) // 32,
            "resource_bytes": resource_bytes,
            "current_main_byte_exact": True,
        },
        "states": state_rows,
        "targets": target_rows,
        "non_target_live_ss3": {
            "animation": 8,
            "center_x": 72,
            "policy": "leave unchanged; not included in the requested six labels",
        },
        "localization_plan": {
            "font": "Galmuri11.bdf",
            "badge_size": [80, 16],
            "background_policy": "preserve original badge pixels; clear only Japanese face/shade plus the adjacent one-pixel dark contour, restore those pixels from clean sibling-label background samples, then overlay centered Korean glyphs",
            "korean_style": "white face index 14 with one-pixel dark contour index 1; palettes remain unchanged so normal/focus colors continue to follow the native palette selection",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "resource": f"0x{RESOURCE:08X}",
        "targets": {row["source"]: row["translation"] for row in target_rows},
        "live_exact": {row["source"]: f"{row['live_match']['exact_tiles']}/{row['live_match']['tile_count']}" for row in target_rows},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
