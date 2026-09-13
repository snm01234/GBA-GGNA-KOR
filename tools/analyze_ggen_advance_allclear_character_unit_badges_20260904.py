#!/usr/bin/env python3
"""Analyze キャラクター / ユニット badge consumers from the clean-plate follow-up ss1.

The follow-up savestate was captured from the clean-plate candidate.  It proves
that the remaining katakana badges are still sourced from sprite resource
0x08CCFE40.  Animations 22/24 are the longer キャラクター label family and
23/25 the shorter ユニット family; the captured state has live animations
24 and 23 respectively.
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
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_allclear_menu_badges_ko_candidate_20260904 as badge
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
RESOURCE = 0x08CCFE40
CANDIDATE = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges" / "ggen_advance_allclear_menu_badges_ko_followup_candidate_20260904.gba"
STATE = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges" / "ggen_advance_allclear_menu_badges_ko_followup_candidate_20260904.ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_character_unit_badges_20260904.json"

TARGETS: dict[str, dict[str, Any]] = {
    "キャラクター": {"ko": "캐릭터", "animations": [22, 24], "live_animation": 24, "center_x": 72},
    "ユニット": {"ko": "유닛", "animations": [23, 25], "live_animation": 23, "center_x": 168},
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


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
    exact = 0
    total = 0
    bindings = []
    for obj, source_ids in zip(anim["objects"], anim["source_by_object"]):
        sx = center_x + int(obj["x"])
        sy = 136 + int(obj["y"])
        width, height = [int(v) for v in obj["size_px"]]
        matches = [r for r in visible if int(r["x"]) == sx and int(r["y"]) == sy and int(r["width"]) == width and int(r["height"]) == height]
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
        bindings.append({"screen": [sx, sy, width, height], "dest_tile": dest, "palette_bank": int(row["palette_bank"]), "source_ids": source_ids, "exact_tiles": local_exact, "tile_count": len(source_ids)})
    return {"exact_tiles": exact, "tile_count": total, "result": "PASS" if exact == total else "FAIL", "objects": bindings}


def text_bbox(canvas: list[list[int]]) -> list[int]:
    points = [(x, y) for y in range(2, 14) for x in range(4, 76) if canvas[y][x] in (0xB, 0xE)]
    gate(points, "native katakana face mask empty")
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points) + 1, max(y for _, y in points) + 1]


def main() -> int:
    candidate = CANDIDATE.read_bytes()
    main = MAIN_TIP_ROM.read_bytes()
    state_raw = STATE.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    gate(u32(state, 8) == (binascii.crc32(candidate) & 0xFFFFFFFF), "follow-up state CRC does not match candidate")

    off = RESOURCE - ROM_BASE
    kind, pal_count, grel, prel, anim_count = struct.unpack_from("<5I", candidate, off)
    gate((kind, pal_count, grel, prel, anim_count) == (0, 6, 0x0DE4, 0x2BE4, 26), "resource layout drift")
    graphics = candidate[off + grel:off + prel]
    gate(candidate[off:off + grel] == main[off:off + grel], "follow-up changed resource animation records")

    import analyze_ggen_advance_settings_suspend_ui as sprite
    _gr, records = sprite.animation_records(candidate, RESOURCE)
    animations = {i: badge.animation_info(records, i) for i in range(anim_count)}
    canvases = {i: badge.canvas_for(graphics, animations[i]) for i in range(anim_count)}
    gate(animations[22]["source_ids"] == animations[24]["source_ids"], "character duplicate pair drift")
    gate(animations[23]["source_ids"] == animations[25]["source_ids"], "unit duplicate pair drift")

    slots = [r for r in remaining.sprite_slots(state) if r["resource"] == f"0x{RESOURCE:08X}"]
    rows = []
    for jp, spec in TARGETS.items():
        live_anim = int(spec["live_animation"])
        center_x = int(spec["center_x"])
        matching = [r for r in slots if int(r["animation"]) == live_anim and int(r["x"]) == center_x and int(r["y"]) == 136]
        gate(len(matching) == 1, f"{jp}: live sprite-manager slot missing")
        live = live_match(state, graphics, animations[live_anim], center_x)
        gate(live["result"] == "PASS", f"{jp}: live source mismatch")
        bbox = text_bbox(canvases[live_anim])
        rows.append({
            "source": jp,
            "translation": spec["ko"],
            "animation_family": spec["animations"],
            "live_animation": live_anim,
            "screen_center": [center_x, 136],
            "native_text_bbox": bbox,
            "native_text_width": bbox[2] - bbox[0],
            "source_ids": animations[live_anim]["source_ids"],
            "live_match": live,
        })

    # Six-katakana キャラクター is visibly the longer native raster.
    by_source = {row["source"]: row for row in rows}
    gate(by_source["キャラクター"]["native_text_width"] > by_source["ユニット"]["native_text_width"], "katakana semantic width ordering drift")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_allclear_character_unit_badges_20260904",
        "result": "PASS",
        "candidate": {"path": advance_relative(CANDIDATE), "sha256": sha256(candidate), "crc32": f"0x{binascii.crc32(candidate) & 0xFFFFFFFF:08X}"},
        "state": {"path": advance_relative(STATE), "sha256": sha256(state_raw), "resource_slots": slots, "visible_oam": visible_oam(state)},
        "resource": {"address": f"0x{RESOURCE:08X}", "animation_count": anim_count, "animation_records_unchanged_from_main": True},
        "targets": rows,
        "localization_plan": {"font": "Galmuri11.bdf", "translations": {"キャラクター": "캐릭터", "ユニット": "유닛"}, "normal_focus_policy": "patch both duplicate source families 22/24 and 23/25; palettes and animation records remain unchanged"},
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": advance_relative(OUT), "targets": {r["source"]: {"ko": r["translation"], "animations": r["animation_family"], "live": f"{r['live_match']['exact_tiles']}/{r['live_match']['tile_count']}", "width": r["native_text_width"]} for r in rows}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
