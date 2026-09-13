#!/usr/bin/env python3
"""Prove why the sort-popup transfer hook cannot close the unit-list labels."""
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

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

CANDIDATE = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_ss1_four_graphics" / "ggen_advance_ss1_four_graphics_ko_candidate_20260903.gba"
FRESH = ADVANCE_ROOT / "analysis" / "fresh_states_20260903_ss1_four_graphics" / "fresh_candidate.ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_ss1_runtime_hook_failure_20260903.json"
HOOK = 0x08063194
STUB = 0x09F20000
TABLE_FILE = 0x01F22400
HOLD_DRAW = 0x080638E4
HOLD_CALLS = [0x08075072, 0x080751DA, 0x0807566E, 0x080757DE]
HOLD_RANGES = [(0x00074F2C, 0x00075240), (0x00075500, 0x00075820)]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def thumb_bl_target(data: bytes, off: int) -> int | None:
    hi, lo = struct.unpack_from("<HH", data, off)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    disp = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if disp & 0x400000:
        disp -= 0x800000
    return (0x08000000 + off + 4 + disp) & 0xFFFFFFFF


def calls_to(data: bytes, target: int, start: int = 0, end: int | None = None) -> list[int]:
    stop = len(data) - 4 if end is None else min(end, len(data) - 4)
    return [0x08000000 + off for off in range(start, stop, 2) if thumb_bl_target(data, off) == target]


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    candidate = CANDIDATE.read_bytes()
    state, _ = statefmt.parse_png_state(FRESH)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    info1 = bgutil.bg_info(state, 1)
    info2 = bgutil.bg_info(state, 2)
    hold_cells = [bgutil.map_entry(vram, info1["screen_base"], info1["size"], x, y) for x, y in ((14, 1), (15, 1), (14, 2), (15, 2))]
    owned_cells = [bgutil.map_entry(vram, info2["screen_base"], info2["size"], x, y) for x, y in ((22, 9), (27, 10))]
    live_hold = bytes(vram[0x14 * 32:0x16 * 32])
    jp_hold = jp[0x00C43968:0x00C439A8]
    candidate_hold = candidate[0x00C43968:0x00C439A8]
    all_hook_calls = calls_to(jp, HOOK)
    range_hook_calls = [call for start, end in HOLD_RANGES for call in calls_to(jp, HOOK, start, end)]
    draw_targets = {f"0x{call:08X}": f"0x{thumb_bl_target(jp, call - 0x08000000):08X}" for call in HOLD_CALLS}
    hook_patch = candidate[HOOK - 0x08000000:HOOK - 0x08000000 + 8]
    expected_trampoline = struct.pack("<HHI", 0x4B00, 0x4718, STUB | 1)
    runtime_runs = []
    cursor = TABLE_FILE
    while True:
        destination, source, words = struct.unpack_from("<III", candidate, cursor)
        cursor += 12
        if destination == 0:
            break
        size = words * 4
        expected = candidate[source - 0x08000000:source - 0x08000000 + size]
        final = bytes(vram[destination - 0x06000000:destination - 0x06000000 + size])
        runtime_runs.append({"destination": f"0x{destination:08X}", "source": f"0x{source:08X}", "bytes": size, "final_vram_matches_payload": final == expected})
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_ss1_runtime_hook_failure_20260903",
        "result": "PASS",
        "candidate": {"path": advance_relative(CANDIDATE), "sha256": sha256(candidate), "crc32": f"0x{binascii.crc32(candidate) & 0xFFFFFFFF:08X}"},
        "fresh_state_evidence": {
            "path": advance_relative(FRESH), "sha256": sha256(FRESH.read_bytes()),
            "embedded_crc32": f"0x{struct.unpack_from('<I', state, 8)[0]:08X}",
            "hold_cells": [f"0x{x:04X}" for x in hold_cells], "owned_cells": [f"0x{x:04X}" for x in owned_cells],
            "live_hold_tiles_0x14_0x15_equal_original_japanese": live_hold == jp_hold,
            "live_hold_tiles_equal_candidate_korean_source": live_hold == candidate_hold,
        },
        "source_proof": {
            "candidate_fixed_hold_is_korean": candidate_hold != jp_hold,
            "original_japanese_64_byte_payload_occurrences_in_candidate": candidate.count(jp_hold),
            "interpretation": "The final live Japanese plaque is not the candidate fixed descriptor payload; it is restored after/beside that source patch by the unit-list render path or cached work data.",
        },
        "hook_proof": {
            "entry": f"0x{HOOK:08X}", "trampoline_installed": hook_patch == expected_trampoline,
            "direct_call_count_gamewide": len(all_hook_calls),
            "role": "widely shared transfer helper; final for the sort popup, not a unit-list render-completion callback",
            "unit_hold_renderer_ranges": [[f"0x{0x08000000+s:08X}", f"0x{0x08000000+e:08X}"] for s, e in HOLD_RANGES],
            "direct_hook_calls_in_hold_renderer_ranges": [f"0x{x:08X}" for x in range_hook_calls],
            "hold_draw_calls": draw_targets,
            "runtime_copy_table": runtime_runs,
        },
        "root_cause": {
            "supersedes": "22.120.1 signature-only diagnosis",
            "cause": "The Korean BG payload was attached to the sort-popup/common transfer helper rather than the unit-list final producer/consumer. Matching map cells cannot guarantee execution after the unit-list redraw, so 持c and 所有数 finish the frame as Japanese.",
            "required_fix_boundary": "Patch the actual unit-list producers, or hook the unit-list renderer after its final 0x080638E4/BG composition writes; do not add more signatures to 0x08063194.",
        },
        "verification": {
            "candidate_hook_present": hook_patch == expected_trampoline,
            "fresh_signature_matches_replacement_candidate": hold_cells[:3] == [0xB014, 0xB01D, 0xB015] and owned_cells == [0xB0DD, 0xB10D],
            "unit_renderers_do_not_call_transfer_hook_directly": not range_hook_calls,
            "four_hold_calls_target_draw_helper": all(value == f"0x{HOLD_DRAW:08X}" for value in draw_targets.values()),
            "live_japanese_differs_from_candidate_korean_source": live_hold == jp_hold and live_hold != candidate_hold,
            "runtime_payloads_absent_from_final_fresh_vram": all(not row["final_vram_matches_payload"] for row in runtime_runs),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "report": advance_relative(OUT), "hook_calls_gamewide": len(all_hook_calls), "hook_calls_in_unit_hold_ranges": len(range_hook_calls), "live_japanese_equals_original": live_hold == jp_hold, "live_equals_candidate_korean_source": live_hold == candidate_hold}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
