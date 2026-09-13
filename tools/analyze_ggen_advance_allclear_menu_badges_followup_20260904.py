#!/usr/bin/env python3
"""Analyze follow-up all-clear badge state, including disabled menu variants.

The first candidate state proves that the disabled つづきから / おまけ badges
use animations 18 / 19 of the same 0x08CCFE40 sprite resource.  This pass also
records palette/style bindings so the follow-up builder can make a clean
Japanese-free background plate before painting Korean text.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_allclear_menu_badges_20260904 as base
import analyze_ggen_advance_remaining_ui_states_20260902 as remaining
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
RESOURCE = 0x08CCFE40
CANDIDATE_ROM = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges" / "ggen_advance_allclear_menu_badges_ko_candidate_20260904.gba"
STATE = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges" / "ggen_advance_allclear_menu_badges_ko_candidate_20260904.ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_followup_20260904.json"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def animation_info(records: list[tuple[int, bytes]], index: int) -> dict[str, object]:
    blob = b"".join(record for _off, record in records[index:])
    marker = blob.find(b"\x40\x00\x40\x00")
    gate(marker >= 0, f"animation {index} marker missing")
    parsed = sprite.parse_animation_oam(blob[marker:])
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    start = marker + int(parsed["entries_end"])
    ids = list(struct.unpack_from(f"<{total}H", blob, start))
    by_object = []
    cursor = 0
    for obj in parsed["objects"]:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor:cursor + count])
        cursor += count
    gate(cursor == total == 20, f"animation {index} tile count drift")
    return {"objects": parsed["objects"], "source_ids": ids, "source_by_object": by_object}


def live_match(state: bytes, graphics: bytes, anim: dict[str, object], center_x: int) -> dict[str, object]:
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    visible = remaining.visible_oam(state)
    exact = total = 0
    rows = []
    for meta, source_ids in zip(anim["objects"], anim["source_by_object"]):
        sx = center_x + int(meta["x"])
        sy = 136 + int(meta["y"])
        w, h = [int(v) for v in meta["size_px"]]
        matches = [r for r in visible if int(r["x"]) == sx and int(r["y"]) == sy and int(r["width"]) == w and int(r["height"]) == h]
        gate(len(matches) == 1, f"OAM binding drift at {sx},{sy} {w}x{h}")
        row = matches[0]
        dest = int(row["tile"])
        local_exact = 0
        for i, sid in enumerate(source_ids):
            live = obj[(dest + i) * 32:(dest + i + 1) * 32]
            expected = graphics[int(sid) * 32:(int(sid) + 1) * 32]
            local_exact += live == expected
        exact += local_exact
        total += len(source_ids)
        rows.append({"screen": [sx, sy, w, h], "dest_tile": dest, "palette_bank": int(row["palette_bank"]), "source_ids": source_ids, "exact_tiles": local_exact})
    return {"result": "PASS" if exact == total else "FAIL", "exact_tiles": exact, "tile_count": total, "objects": rows}


def main() -> int:
    candidate = CANDIDATE_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    raw_state = STATE.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    state_crc = u32(state, 8)
    gate(state_crc == (binascii.crc32(candidate) & 0xFFFFFFFF), "candidate ss1 CRC mismatch")

    off = RESOURCE - ROM_BASE
    kind, pals, grel, prel, count = struct.unpack_from("<5I", candidate, off)
    gate((kind, pals, grel, prel, count) == (0, 6, 0x0DE4, 0x2BE4, 26), "resource layout drift")
    graphics = candidate[off + grel:off + prel]
    palettes = candidate[off + prel:off + prel + pals * 32]
    _g, records = sprite.animation_records(candidate, RESOURCE)
    anim = {i: animation_info(records, i) for i in range(count)}

    slots = [row for row in remaining.sprite_slots(state) if row["resource"] == f"0x{RESOURCE:08X}"]
    expected_slots = {(40, 9), (120, 18), (200, 19)}
    actual_slots = {(int(row["x"]), int(row["animation"])) for row in slots}
    gate(expected_slots <= actual_slots, f"disabled-menu slots drift: {actual_slots}")

    targets = [
        ("はじめから", "처음부터", 40, 9, "active/focus"),
        ("つづきから", "이어하기", 120, 18, "disabled"),
        ("おまけ", "부록", 200, 19, "disabled"),
    ]
    target_rows = []
    for jp, ko, x, a, style in targets:
        live = live_match(state, graphics, anim[a], x)
        gate(live["result"] == "PASS", f"{jp}: live/source mismatch")
        target_rows.append({"source": jp, "translation": ko, "center_x": x, "animation": a, "style": style, "source_ids": anim[a]["source_ids"], "live_match": live})

    obj_palette = state[statefmt.STATE_PALETTE + 0x200:statefmt.STATE_OAM]
    palette_bindings = {}
    for bank in (10, 11, 12):
        live = obj_palette[bank * 32:(bank + 1) * 32]
        palette_bindings[str(bank)] = [i for i in range(pals) if live == palettes[i * 32:(i + 1) * 32]]
    gate(palette_bindings == {"10": [1], "11": [0], "12": [0]}, f"live palette bindings drift: {palette_bindings}")

    # The current main still contains the unpatched source resource.  It is the
    # correct parent for the follow-up builder; the first candidate is evidence only.
    gate(current[off:off + grel] == candidate[off:off + grel], "resource header/animation records differ between current main and candidate")
    gate(current[off + prel:off + prel + pals * 32] == candidate[off + prel:off + prel + pals * 32], "resource palettes differ")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_allclear_menu_badges_followup_20260904",
        "result": "PASS",
        "candidate_state": {"path": advance_relative(STATE), "sha256": sha256(raw_state), "rom_crc32": f"0x{state_crc:08X}"},
        "candidate_rom": {"path": advance_relative(CANDIDATE_ROM), "sha256": sha256(candidate)},
        "current_main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "resource": {"address": f"0x{RESOURCE:08X}", "animation_count": count, "source_tiles": len(graphics) // 32},
        "resource_slots": slots,
        "targets": target_rows,
        "disabled_mapping": {"つづきから": 18, "おまけ": 19},
        "palette_bindings": palette_bindings,
        "followup_plan": {
            "clean_plate_first": True,
            "text_well": [7, 1, 76, 14],
            "active_background_family": list(range(0, 9)),
            "disabled_background_family": [18, 19, 20, 21],
            "active_korean_face": 14,
            "disabled_korean_face": 4,
            "outline": 1,
            "font": "Galmuri11.bdf",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": advance_relative(OUT), "disabled": report["disabled_mapping"], "live_exact": {row["source"]: f"{row['live_match']['exact_tiles']}/{row['live_match']['tile_count']}" for row in target_rows}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
