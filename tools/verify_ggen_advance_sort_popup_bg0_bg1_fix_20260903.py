#!/usr/bin/env python3
"""Verify the measured BG0 focus fix and emit a compatible ascending-focus state."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_sort_popup_state6_candidate_20260903 as builder
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

CAPTURE = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup" / "ggen_advance_sort_popup_state6_ko_candidate_20260903.ss1"
ROM = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup" / "ggen_advance_sort_popup_state6_ko_candidate_20260903.gba"
OUT_STATE = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup" / "ggen_advance_sort_popup_bg0_focus_fixed_test_20260903.ss1"
OUT_PREVIEW = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup" / "ggen_advance_sort_popup_bg0_focus_fixed_test_20260903.png"
OUT_REPORT = ADVANCE_ROOT / "analysis" / "ggen_advance_sort_popup_bg0_bg1_fix_verification_20260903.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    state, _chunks = statefmt.parse_png_state(CAPTURE)
    rom = ROM.read_bytes()
    rom_crc = binascii.crc32(rom) & 0xFFFFFFFF
    patched = bytearray(state)
    info = bgutil.bg_info(state, 0)
    if info["cnt"] != 0x4C00 or info["screen_base"] != 12 * 0x800:
        raise SystemExit("measured BG0 binding drift")
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    cells = [
        bgutil.map_entry(vram, info["screen_base"], info["size"], 16 + dx, 8 + dy)
        for dy in range(2) for dx in range(5)
    ]
    if cells != list(range(0xE154, 0xE15E)):
        raise SystemExit(f"measured ascending map drift: {[hex(value) for value in cells]}")
    payload = rom[builder.FOCUS_FILES["오름"]:builder.FOCUS_FILES["오름"] + 10 * 32]
    for index, cell in enumerate(cells):
        tile_id = cell & 0x3FF
        dest = statefmt.STATE_VRAM + info["char_base"] + tile_id * 32
        patched[dest:dest + 32] = payload[index * 32:(index + 1) * 32]
    struct.pack_into("<I", patched, 8, rom_crc)
    OUT_STATE.write_bytes(builder.replace_state_chunk(CAPTURE, bytes(patched)))

    # Preserve the captured frame, then repaint the popup layers from the
    # patched state so the measured BG0 Korean focus is directly reviewable.
    frame = Image.open(CAPTURE).convert("RGBA")
    bg2 = builder.render_layer_native(bytes(patched), 2)
    bg0 = builder.render_layer_native(bytes(patched), 0)
    frame.alpha_composite(bg2.crop((64, 32, 176, 120)), (64, 32))
    frame.alpha_composite(bg0.crop((64, 32, 176, 120)), (64, 32))
    frame.resize((960, 640), Image.Resampling.NEAREST).save(OUT_PREVIEW)

    stub = rom[builder.STUB_FILE:builder.STUB_FILE + len(builder.STUB)]
    bg0_addresses = (0x06006212, 0x06006220, 0x06006292, 0x060062A0, 0x06006312)
    bg1_addresses = (0x06007212, 0x06007220, 0x06007292, 0x060072A0, 0x06007312)
    live_after = b"".join(
        patched[statefmt.STATE_VRAM + (cell & 0x3FF) * 32:statefmt.STATE_VRAM + (cell & 0x3FF) * 32 + 32]
        for cell in cells
    )
    checks = {
        "candidate_contains_all_BG0_focus_map_addresses": all(struct.pack("<I", value) in stub for value in bg0_addresses),
        "candidate_contains_all_BG1_focus_map_addresses": all(struct.pack("<I", value) in stub for value in bg1_addresses),
        "candidate_has_ten_palette_E_checks": stub.count(bytes.fromhex("180b0e28")) == 10,
        "measured_BG0_payload_matches_Korean_after_patch": live_after == payload,
        "derived_state_crc_matches_candidate": struct.unpack_from("<I", patched, 8)[0] == rom_crc,
    }
    if not all(checks.values()):
        raise SystemExit(f"verification failed: {checks}")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_sort_popup_bg0_bg1_fix_verification_20260903",
        "result": "PASS",
        "candidate": {"path": advance_relative(ROM), "sha256": sha256(rom), "crc32": f"0x{rom_crc:08X}"},
        "measured_source_state": {"path": advance_relative(CAPTURE), "sha256": sha256(CAPTURE.read_bytes())},
        "derived_test_state": {"path": advance_relative(OUT_STATE), "sha256": sha256(OUT_STATE.read_bytes())},
        "preview": advance_relative(OUT_PREVIEW),
        "measured_target": {
            "layer": "BG0",
            "map_address": "0x06006220",
            "palette_bank": "E",
            "tile_ids": [f"0x{cell & 0x3FF:03X}" for cell in cells],
            "payload_bytes": len(payload),
        },
        "checks": checks,
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "candidate_sha256": sha256(rom),
        "test_state": advance_relative(OUT_STATE),
        "preview": advance_relative(OUT_PREVIEW),
        "report": advance_relative(OUT_REPORT),
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
