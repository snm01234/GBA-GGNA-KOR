#!/usr/bin/env python3
"""Prove active コンティニュー normal/focus ownership from allclear.ss1.

Disabled コンティニュー is already Koreanized as animation 21.  The captured
allclear.ss1 loads the same 0x08CCFE40 resource with live animation 6 at the
right-hand continue slot.  Animations 6/15 share source tiles and remain
byte-exact with the Japan ROM, so both normal and focus consume the still-
Japanese raster through native palettes.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_remaining_ui_states_20260902 as remaining
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_allclear_menu_badges_ko_candidate_20260904 as badge
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
RESOURCE = 0x08CCFE40
STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_continue_active_badges_20260905.json"
OUT_PREVIEW = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_allclear_continue_active" / "ggen_advance_allclear_continue_active_survey_20260905.png"

TARGETS: dict[str, dict[str, Any]] = {
    "コンティニュー": {"ko": "컨티뉴", "animations": [6, 15], "live_animation": 6, "center_x": 168},
}
NON_TARGETS = {
    8: "BGM",
    17: "BGM[duplicate]",
    20: "ロード[disabled]",
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def load_resource(rom: bytes) -> tuple[bytes, bytes, dict[int, dict[str, Any]], dict[int, list[list[int]]]]:
    off = RESOURCE - ROM_BASE
    kind, pal_count, grel, prel, anim_count = struct.unpack_from("<5I", rom, off)
    gate((kind, pal_count, grel, prel, anim_count) == (0, 6, 0x0DE4, 0x2BE4, 26), "resource layout drift")
    graphics = rom[off + grel:off + prel]
    palettes = rom[off + prel:off + prel + pal_count * 32]
    _gr, records = sprite.animation_records(rom, RESOURCE)
    animations = {i: badge.animation_info(records, i) for i in range(anim_count)}
    canvases = {i: badge.canvas_for(graphics, animations[i]) for i in range(anim_count)}
    return graphics, palettes, animations, canvases


def face_points(canvas: list[list[int]], values: set[int]) -> set[tuple[int, int]]:
    return {(x, y) for y in range(2, 14) for x in range(4, 76) if canvas[y][x] in values}


def bbox(points: set[tuple[int, int]]) -> list[int]:
    gate(points, "native katakana face mask empty")
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points) + 1, max(y for _, y in points) + 1]


def visible_oam(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    rows = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            rows.append(row)
    return rows


def live_match(state: bytes, graphics: bytes, anim: dict[str, Any], center_x: int) -> dict[str, Any]:
    obj_vram = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    visible = visible_oam(state)
    exact = total = 0
    bindings = []
    for obj, source_ids in zip(anim["objects"], anim["source_by_object"]):
        sx = center_x + int(obj["x"])
        sy = 136 + int(obj["y"])
        width, height = [int(v) for v in obj["size_px"]]
        matches = [
            row for row in visible
            if int(row["x"]) == sx and int(row["y"]) == sy
            and int(row["width"]) == width and int(row["height"]) == height
        ]
        gate(len(matches) == 1, f"ambiguous live OAM at {sx},{sy} {width}x{height}")
        row = matches[0]
        dest = int(row["tile"])
        local_exact = 0
        for local, sid in enumerate(source_ids):
            live = bytes(obj_vram[(dest + local) * 32:(dest + local + 1) * 32])
            expected = graphics[int(sid) * 32:(int(sid) + 1) * 32]
            local_exact += live == expected
        exact += local_exact
        total += len(source_ids)
        bindings.append({
            "screen": [sx, sy, width, height],
            "dest_tile": dest,
            "palette_bank": int(row["palette_bank"]),
            "source_ids": source_ids,
            "exact_tiles": local_exact,
            "tile_count": len(source_ids),
        })
    return {"result": "PASS" if exact == total else "FAIL", "exact_tiles": exact, "tile_count": total, "objects": bindings}


def main() -> int:
    main_rom = MAIN_TIP_ROM.read_bytes()
    jp_rom = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main_rom) == manifest["sha256"], "parent is not current main TIP")
    graphics, palettes, animations, canvases = load_resource(main_rom)
    jp_graphics, _jp_palettes, jp_animations, jp_canvases = load_resource(jp_rom)
    gate(all(animations[i]["source_ids"] == jp_animations[i]["source_ids"] for i in range(26)), "animation source lookup drifted from Japan ROM")
    gate(animations[6]["source_ids"] == animations[15]["source_ids"], "continue duplicate pair drift")
    gate(canvases[6] == jp_canvases[6] == canvases[15] == jp_canvases[15], "active continue raster is no longer Japan-identical")
    gate(canvases[21] != jp_canvases[21], "disabled continue was not already Koreanized")

    state_raw = STATE.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    current_crc = binascii.crc32(main_rom) & 0xFFFFFFFF
    gate(u32(state, 8) == current_crc, "allclear.ss1 CRC does not match current main")

    slots = [row for row in remaining.sprite_slots(state) if row["resource"] == f"0x{RESOURCE:08X}"]
    rows = []
    for jp, spec in TARGETS.items():
        live_anim = int(spec["live_animation"])
        center_x = int(spec["center_x"])
        matching = [
            row for row in slots
            if int(row["animation"]) == live_anim and int(row["x"]) == center_x and int(row["y"]) == 136
        ]
        gate(len(matching) == 1, f"{jp}: live sprite-manager slot missing")
        live = live_match(state, graphics, animations[live_anim], center_x)
        gate(live["result"] == "PASS", f"{jp}: live source mismatch")
        palettes_used = sorted({obj["palette_bank"] for obj in live["objects"]})
        gate(len(palettes_used) == 1, f"{jp}: live palette-bank split")
        jp_face = face_points(jp_canvases[live_anim], {0xB, 0xE})
        box = bbox(jp_face)
        rows.append({
            "source": jp,
            "translation": spec["ko"],
            "animation_family": spec["animations"],
            "live_animation": live_anim,
            "screen_center": [center_x, 136],
            "native_text_bbox": box,
            "native_text_width": box[2] - box[0],
            "live_palette_bank": palettes_used[0],
            "source_ids": animations[live_anim]["source_ids"],
            "live_match": live,
            "raster_byte_exact_with_japan": True,
            "disabled_korean_sibling": 21,
        })

    by_source = {row["source"]: row for row in rows}
    gate(by_source["コンティニュー"]["live_palette_bank"] in (10, 11), "continue live palette is not a native normal/focus bank")
    gate(by_source["コンティニュー"]["native_text_width"] == 68, "active continue native width drift")

    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    scale = 4
    sheet_rows = [
        ("JP 21 コンティニュー disabled", jp_canvases[21], 0),
        ("KO 21 컨티뉴 disabled", canvases[21], 0),
        ("current 6 normal pal0", canvases[6], 0),
        ("current 15 focus pal1", canvases[15], 1),
        ("current 8 BGM leave", canvases[8], 0),
        ("current 20 ロード disabled leave", canvases[20], 0),
    ]
    row_h = 16 * scale
    sheet = Image.new("RGB", (80 * scale + 280, len(sheet_rows) * (row_h + 8) + 30), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), "active continue badge ownership (6/15 still Japanese)", fill=(255, 255, 255))
    y = 28
    for label, canvas, pal in sheet_rows:
        sheet.paste(badge.canvas_image(canvas, palettes[pal * 32:(pal + 1) * 32], scale), (0, y))
        draw.text((80 * scale + 10, y + 20), label, fill=(235, 235, 235))
        y += row_h + 8
    sheet.save(OUT_PREVIEW)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_allclear_continue_active_badges_20260905",
        "result": "PASS",
        "current_main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(main_rom), "crc32": f"0x{current_crc:08X}"},
        "japan_rom": {"path": advance_relative(ORIGINAL_ROM), "sha256": sha256(jp_rom)},
        "state": {
            "path": advance_relative(STATE),
            "sha256": sha256(state_raw),
            "rom_crc32": f"0x{u32(state, 8):08X}",
            "crc_matches_current_main": True,
            "resource_slots": slots,
            "visible_oam": visible_oam(state),
        },
        "resource": {"address": f"0x{RESOURCE:08X}", "animation_count": 26, "animation_records_unchanged_from_japan": True},
        "targets": rows,
        "non_targets_left_unchanged": {str(index): label for index, label in NON_TARGETS.items()},
        "mapping_evidence": {
            "screen_order": "left animation 14 is already-Korean 로드; right animation 6 is still-Japanese コンティニュー",
            "duplicate_source_pair": [6, 15],
            "disabled_korean_sibling": 21,
            "captured_live_palette_bank": by_source["コンティニュー"]["live_palette_bank"],
        },
        "localization_plan": {
            "font": "Galmuri11.bdf",
            "translations": {"コンティニュー": "컨티뉴"},
            "normal_focus_policy": "patch duplicate source family 6/15 using the verified clean plate; palettes and animation records remain unchanged; disabled animation 21 and BGM/ロード leftovers stay untouched",
        },
        "preview": advance_relative(OUT_PREVIEW),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "preview": advance_relative(OUT_PREVIEW),
        "targets": {
            row["source"]: {
                "ko": row["translation"],
                "animations": row["animation_family"],
                "live": f"{row['live_match']['exact_tiles']}/{row['live_match']['tile_count']}",
                "width": row["native_text_width"],
                "palette_bank": row["live_palette_bank"],
            }
            for row in rows
        },
        "leave_unchanged": NON_TARGETS,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
