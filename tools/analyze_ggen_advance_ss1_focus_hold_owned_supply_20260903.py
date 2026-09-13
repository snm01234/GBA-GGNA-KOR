#!/usr/bin/env python3
"""Audit the current-main ss1 mixed 持/지 path and the three residual labels.

This is a read-only runtime/source audit for the user-list screen represented by
`SD Gundam GGeneration Advance (Korean).ss1`.

Questions closed here:
- why the focused Aile Strike row can still show Japanese 持 while a normal row
  already shows Korean 지;
- whether the live Japanese focused 持 is the currently patched C439 payload;
- whether 所有数 is a simple raw-ROM/static-atlas tile copy;
- whether 補給ポイント / 総ユニット数 already have a safe isolated static owner.
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

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import analyze_ggen_advance_unit_list_hold_fixed_graphics_20260830 as holdaudit
import build_ggen_advance_ss1_four_graphics_ko_candidate_20260903 as four
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_ss1_focus_hold_owned_supply_20260903.json"

ROM_BASE = 0x08000000
HOLD_VARIANTS = {
    "normal_B": {"graphic": 0x00C43968, "descriptor": 0x00C43954, "live_tiles": [0x014, 0x015]},
    "focus_A": {"graphic": 0x00C439BC, "descriptor": 0x00C439A8, "live_tiles": [0x023, 0x024]},
}
OWNED_TILES = [0x0DD, 0x0DE, 0x0DF, 0x0E0, 0x0E1, 0x108, 0x0E4, 0x0E5, 0x0E6, 0x0E7, 0x0E8, 0x10D]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def find_all(data: bytes, pattern: bytes) -> list[int]:
    rows: list[int] = []
    start = 0
    while True:
        hit = data.find(pattern, start)
        if hit < 0:
            return rows
        rows.append(hit)
        start = hit + 1


def bg_tile(state: bytes, layer: int, tile: int) -> bytes:
    info = bgutil.bg_info(state, layer)
    gate(not info["color_8bpp"], f"BG{layer} unexpectedly 8bpp")
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    off = info["char_base"] + tile * 32
    return bytes(vram[off:off + 32])


def map_cell(state: bytes, layer: int, x: int, y: int) -> dict[str, Any]:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    cell = bgutil.map_entry(vram, info["screen_base"], info["size"], x, y)
    return {"x": x, "y": y, "cell": f"0x{cell:04X}", "tile": f"0x{cell & 0x3FF:03X}", "palette": (cell >> 12) & 0xF}


def variant_report(state: bytes, main: bytes, jp: bytes, name: str, spec: dict[str, Any]) -> dict[str, Any]:
    off = int(spec["graphic"])
    live = b"".join(bg_tile(state, 1, int(tile)) for tile in spec["live_tiles"])
    jp_payload = jp[off:off + holdaudit.GRAPHIC_BYTES]
    ko_payload = main[off:off + holdaudit.GRAPHIC_BYTES]
    gate(len(live) == holdaudit.GRAPHIC_BYTES, f"{name} live payload size drift")
    return {
        "descriptor": f"0x{ROM_BASE + int(spec['descriptor']):08X}",
        "graphic_file_offset": f"0x{off:08X}",
        "live_bg1_tiles": [f"0x{int(tile):03X}" for tile in spec["live_tiles"]],
        "main_c439_is_korean": ko_payload != jp_payload,
        "live_equals_original_japanese": live == jp_payload,
        "live_equals_current_main_c439": live == ko_payload,
        "japanese_payload_occurrences_in_current_main": [f"0x{x:08X}" for x in find_all(main, jp_payload)],
        "main_c439_sha256": sha256(ko_payload),
        "jp_c439_sha256": sha256(jp_payload),
        "live_sha256": sha256(live),
    }


def main() -> int:
    current = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(current) == manifest["sha256"], "main TIP hash/manifest drift")
    state, _chunks = statefmt.parse_png_state(STATE)
    state_crc = struct.unpack_from("<I", state, 8)[0]
    rom_crc = binascii.crc32(current) & 0xFFFFFFFF
    gate(state_crc == rom_crc, f"state CRC 0x{state_crc:08X} != current main 0x{rom_crc:08X}")

    hold = {name: variant_report(state, current, jp, name, spec) for name, spec in HOLD_VARIANTS.items()}
    gate(all(row["main_c439_is_korean"] for row in hold.values()), "current main C439 hold variants are not both Korean")
    gate(all(row["live_equals_original_japanese"] for row in hold.values()), "expected cached Japanese C439 geometry not present in live BG1 tiles")
    gate(all(not row["live_equals_current_main_c439"] for row in hold.values()), "live BG1 unexpectedly equals Korean C439 payload")
    gate(all(not row["japanese_payload_occurrences_in_current_main"] for row in hold.values()), "raw Japanese C439 pair still occurs in current main")

    # Selected/focus row uses palette-E A variant at x=14; the normal row uses a
    # different map/tile composition.  Record both without assuming the exact
    # final normal-row producer before it is separately traced.
    row_cells = {
        "focused_Aile_Strike": [map_cell(state, 1, 14, 1), map_cell(state, 1, 15, 1), map_cell(state, 1, 14, 2), map_cell(state, 1, 15, 2)],
        "normal_MC": [map_cell(state, 1, 14, 3), map_cell(state, 1, 15, 3), map_cell(state, 1, 14, 4), map_cell(state, 1, 15, 4)],
    }

    owned_rows = []
    for tile in OWNED_TILES:
        payload = bg_tile(state, 2, tile)
        hits = find_all(current, payload)
        owned_rows.append({
            "tile": f"0x{tile:03X}",
            "sha256": sha256(payload),
            "raw_occurrences_in_current_main": [f"0x{x:08X}" for x in hits[:64]],
            "raw_occurrence_count": len(hits),
        })
    unique_owned = [row for row in owned_rows if row["tile"] not in {"0x108", "0x10D"}]
    gate(all(row["raw_occurrence_count"] == 0 for row in unique_owned), "non-generic 所有数 tile unexpectedly has raw ROM duplicate")

    # Supply package was already relocated to a private 32 MiB owner.  The
    # existing four-graphics builder parses/rebuilds animation 8 only; record
    # its fixed allocation so the isolated follow-up builder can use it.
    gate(four.SUPPLY_ADDRESS == 0x092D0000 and four.SUPPLY_FILE == 0x012D0000, "supply private owner drift")

    result = {
        "schema_version": 1,
        "kind": "ggen_advance_ss1_focus_hold_owned_supply_20260903",
        "result": "PASS",
        "source": {
            "state": advance_relative(STATE),
            "state_sha256": sha256(STATE.read_bytes()),
            "embedded_crc32": f"0x{state_crc:08X}",
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
            "main_tip_crc32": f"0x{rom_crc:08X}",
            "state_matches_current_main": True,
        },
        "hold": {
            "row_map_cells": row_cells,
            "c439_variants": hold,
            "proven_fact": "Both current-main C439 持 variants are already Korean, but the live BG1 cache still contains exact original-Japanese A/B C439 bitmaps and the raw Japanese 64-byte pairs occur zero times in the current ROM.",
            "interpretation": "The focused Aile row is exercising a focus/cache/composition producer distinct from the already-patched direct C439 payload path. The normal MC row can therefore be Korean while the focused row remains Japanese. The final generator of the focus copy is still the next tracing boundary; blindly repatching C439 would not fix it.",
            "known_draw_helper": "0x080638E4",
            "known_hold_calls": ["0x08075072", "0x080751DA", "0x0807566E", "0x080757DE"],
        },
        "owned_count": {
            "translation": {"所有数": "보유수"},
            "bg2_live_tiles": owned_rows,
            "finding": "The non-generic live label tiles have no byte-exact raw occurrence in the current ROM, so 所有数 is not a simple in-place raw-tile owner. The previous post-copy overlay was therefore not a durable ownership fix; the final BG2 compositor/producer must be traced or hooked at its true completion point.",
        },
        "bottom_supply": {
            "translations": {"補給ポイント": "보급포인트", "総ユニット数": "총유닛수"},
            "private_resource_address": f"0x{four.SUPPLY_ADDRESS:08X}",
            "private_resource_file_offset": f"0x{four.SUPPLY_FILE:08X}",
            "animation": 8,
            "finding": "A safe static owner is already known: only animation 8 lookup is remapped to private appended source tiles; animations 0-7, existing source tiles and palettes stay byte-exact. It was excluded from main 22.120.4, so its Japanese display in current main is expected.",
        },
        "next_actions": [
            "Build an isolated current-main candidate containing only 0x092D0000 animation-8 보급포인트/총유닛수 changes and keep it unpromoted until runtime verification.",
            "Trace the focused-row producer that materializes JP C439 A/B geometry into BG1 despite Korean C439 ROM payloads; do not modify C439 again until that owner is closed.",
            "Trace the final BG2 producer/compositor for the 12 所有数 tiles and patch that owner rather than the shared 0x08063194 transfer hook.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "report": advance_relative(OUT),
        "state_matches_current_main": True,
        "focus_hold_live_is_japanese": hold["focus_A"]["live_equals_original_japanese"],
        "focus_c439_in_rom_is_korean": hold["focus_A"]["main_c439_is_korean"],
        "owned_non_generic_raw_duplicates": sum(int(row["raw_occurrence_count"]) for row in unique_owned),
        "bottom_supply_owner": f"0x{four.SUPPLY_ADDRESS:08X}",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
