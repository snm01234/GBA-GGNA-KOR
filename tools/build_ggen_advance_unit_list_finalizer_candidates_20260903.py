#!/usr/bin/env python3
"""Build isolated unit-list runtime-finalizer candidates from the current main TIP.

This deliberately does not reuse the failed 0x08063194 shared-transfer hook.
The hook is placed at the final epilogue of the full unit-list compositor
(0x080776D8..0x08077A42), after its row/detail draw calls have completed.

Two independent candidates are emitted:
  1. focused/normal cached 持 -> 지 repair only;
  2. 所有数 -> 보유수 repair only.

Both are test candidates.  The canonical main TIP is never overwritten.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as drawutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sortpatch
import build_ggen_advance_ss1_four_graphics_ko_candidate_20260903 as old_ss1
import patch_ggen_advance_map_script_inline_poc as thumbutil
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"

OUT_ROOT = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_unit_list_finalizer"
HOLD_ROM = OUT_ROOT / "ggen_advance_unit_list_hold_finalizer_candidate_20260903.gba"
HOLD_SAV = OUT_ROOT / "ggen_advance_unit_list_hold_finalizer_candidate_20260903.sav"
OWNED_ROM = OUT_ROOT / "ggen_advance_unit_list_owned_count_finalizer_candidate_20260903.gba"
OWNED_SAV = OUT_ROOT / "ggen_advance_unit_list_owned_count_finalizer_candidate_20260903.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_unit_list_finalizer_candidates_20260903.json"

ROM_BASE = 0x08000000
CURRENT_MAIN_SHA256 = "0b6df278befa5b7e55cd79097ccbbc6b05dc8b3ecaf50ee6efe3391ed6569989"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

# Full unit-list compositor: one direct caller at 0x08079EF8.  Hook its final
# epilogue, after all visible row/detail composition inside the function.
COMPOSITOR_START = 0x080776D8
COMPOSITOR_CALL = 0x08079EF8
HOOK_FILE = 0x00077A34
HOOK_ADDR = ROM_BASE + HOOK_FILE
HOOK_EXPECTED = bytes.fromhex("0eb038bc9846a146")
CONT_ADDR = 0x08077A3C

# Private expansion allocation.  0x01F23000 begins immediately after the old
# 22.120.x unit-overlay allocation end and is zero-filled in the current main.
STUB_FILE = 0x01F23000
TABLE_FILE = 0x01F23200
DATA_FILE = 0x01F23400
ALLOC_END = 0x01F24000
STUB_ADDR = ROM_BASE + STUB_FILE
TABLE_ADDR = ROM_BASE + TABLE_FILE
DATA_ADDR = ROM_BASE + DATA_FILE

# Exact live screen signature from the user's current-main ss1.  It is based
# on BG2CNT plus two unit-screen BG2 map pairs, rather than the focus row, so a
# cursor move does not disable the finalizer.
BG2CNT_ADDR = 0x0400000C
BG2CNT_VALUE = 0x00005D0A
SCREEN_WORD1_ADDR = 0x0600EA6C
SCREEN_WORD1_VALUE = 0xB0DEB0DD
SCREEN_WORD2_ADDR = 0x0600EAB4
SCREEN_WORD2_VALUE = 0xB10DB0E8

# Cached 8x16 持 slots observed in the supplied state.  Current-main C439
# sources are already Korean, so the finalizer reuses those approved payloads
# byte-exact instead of rasterizing another copy.
HOLD_B_DEST = 0x06000280
HOLD_A_DEST = 0x06000460
HOLD_B_SOURCE = 0x08C43968
HOLD_A_SOURCE = 0x08C439BC
HOLD_WORDS = 16

OWNED_TILE_IDS = [0x0DD, 0x0DE, 0x0DF, 0x0E0, 0x0E1, 0x108, 0x0E4, 0x0E5, 0x0E6, 0x0E7, 0x0E8, 0x10D]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def thumb_bl_target(data: bytes, address: int) -> int | None:
    off = address - ROM_BASE
    h1, h2 = struct.unpack_from("<HH", data, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    disp = ((h1 & 0x07FF) << 12) | ((h2 & 0x07FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (address + 4 + disp) & 0xFFFFFFFF


def op_ldr_word(rt: int, rn: int, byte_offset: int = 0) -> int:
    gate(0 <= rt <= 7 and 0 <= rn <= 7, "LDR low register drift")
    gate(byte_offset % 4 == 0 and 0 <= byte_offset <= 124, "LDR immediate drift")
    return 0x6800 | ((byte_offset // 4) << 6) | (rn << 3) | rt


def op_str_word(rt: int, rn: int, byte_offset: int = 0) -> int:
    gate(0 <= rt <= 7 and 0 <= rn <= 7, "STR low register drift")
    gate(byte_offset % 4 == 0 and 0 <= byte_offset <= 124, "STR immediate drift")
    return 0x6000 | ((byte_offset // 4) << 6) | (rn << 3) | rt


def op_cmp_reg(rn: int, rm: int) -> int:
    gate(0 <= rn <= 7 and 0 <= rm <= 7, "CMP register drift")
    return 0x4280 | (rm << 3) | rn


def build_finalizer_stub() -> bytes:
    """Build the common table-copy finalizer stub at STUB_ADDR."""
    t = thumbutil._Thumb(STUB_ADDR)
    t.label("entry")

    # Screen gate 1: BG2CNT.
    t.ldr_pc(0, "bg2cnt_addr")
    t.h(0x8801)  # ldrh r1, [r0]
    t.ldr_pc(2, "bg2cnt_value")
    t.h(op_cmp_reg(1, 2))
    t.b("epilogue", 0x1)  # bne

    # Screen gate 2/3: exact map pairs around 所有数.
    t.ldr_pc(0, "screen_word1_addr")
    t.h(op_ldr_word(1, 0, 0))
    t.ldr_pc(2, "screen_word1_value")
    t.h(op_cmp_reg(1, 2))
    t.b("epilogue", 0x1)

    t.ldr_pc(0, "screen_word2_addr")
    t.h(op_ldr_word(1, 0, 0))
    t.ldr_pc(2, "screen_word2_value")
    t.h(op_cmp_reg(1, 2))
    t.b("epilogue", 0x1)

    # Table rows are {destination, source, word_count}, terminated by dest=0.
    t.ldr_pc(4, "table")
    t.label("table_loop")
    t.h(op_ldr_word(0, 4, 0))     # ldr r0, [r4]
    t.h(0x2800)                    # cmp r0, #0
    t.b("epilogue", 0x0)         # beq
    t.h(op_ldr_word(1, 4, 4))     # ldr r1, [r4, #4]
    t.h(op_ldr_word(2, 4, 8))     # ldr r2, [r4, #8]
    t.label("copy_loop")
    t.h(op_ldr_word(3, 1, 0))     # ldr r3, [r1]
    t.h(op_str_word(3, 0, 0))     # str r3, [r0]
    t.h(0x3004)                    # adds r0, #4
    t.h(0x3104)                    # adds r1, #4
    t.h(0x3A01)                    # subs r2, #1
    t.b("copy_loop", 0x1)        # bne
    t.h(0x340C)                    # adds r4, #12
    t.b("table_loop")

    # Reproduce the four instructions replaced at 0x08077A34, then resume at
    # 0x08077A3C (mov sl,r5; pop r4-r7; pop r0; bx r0).
    t.label("epilogue")
    t.h(0xB00E)  # add sp, #0x38
    t.h(0xBC38)  # pop {r3,r4,r5}
    t.h(0x4698)  # mov r8, r3
    t.h(0x46A1)  # mov sb, r4
    t.ldr_pc(0, "cont")
    t.h(0x4700)  # bx r0

    t.align4()
    t.word("bg2cnt_addr", BG2CNT_ADDR)
    t.word("bg2cnt_value", BG2CNT_VALUE)
    t.word("screen_word1_addr", SCREEN_WORD1_ADDR)
    t.word("screen_word1_value", SCREEN_WORD1_VALUE)
    t.word("screen_word2_addr", SCREEN_WORD2_ADDR)
    t.word("screen_word2_value", SCREEN_WORD2_VALUE)
    t.word("table", TABLE_ADDR)
    t.word("cont", CONT_ADDR | 1)
    return t.build()


def build_owned_payload(state: bytes, font11: fontpair.BdfFont) -> tuple[list[tuple[int, bytes, list[int]]], bytes, dict[str, Any]]:
    pixels, binding = drawutil.layer_pixels(state, 2)
    before = [row[:] for row in pixels]
    cleared = 0
    for y in range(73, 87):
        for x in range(176, 224):
            if pixels[y][x] in (5, 10):
                pixels[y][x] = 11
                cleared += 1
    raster = sortpatch.draw_text(pixels, "보유수", 182, 74, font11, face=10, contour=5)
    rows = old_ss1.changed_layer_tiles(state, 2, before, pixels)
    gate([tile for _dest, _raw, tile in rows] == OWNED_TILE_IDS, "current ss1 所有数 tile set drift")
    runs = old_ss1.group_bg_runs(rows)
    result_runs: list[tuple[int, bytes, list[int]]] = []
    blob = bytearray()
    for run in runs:
        payload = b"".join(raw for _dest, raw, _tile in run)
        result_runs.append((run[0][0], payload, [tile for _dest, _raw, tile in run]))
        blob.extend(payload)
    gate(len(blob) == len(OWNED_TILE_IDS) * 32, "owned payload byte count drift")
    return result_runs, bytes(blob), {
        "translation": {"所有数": "보유수"},
        "binding": binding,
        "tile_ids": [f"0x{x:03X}" for x in OWNED_TILE_IDS],
        "runs": [
            {"destination": f"0x{dest:08X}", "bytes": len(payload), "tiles": [f"0x{x:03X}" for x in ids]}
            for dest, payload, ids in result_runs
        ],
        "source_pixels_cleared": cleared,
        "font": "Galmuri11.bdf native 12x12",
        "face_index": 10,
        "contour_index": 5,
        **raster,
    }


def make_table(entries: list[tuple[int, int, int]]) -> bytes:
    out = bytearray()
    for destination, source, words in entries:
        gate(destination and source and words > 0, "invalid finalizer table row")
        out.extend(struct.pack("<III", destination, source, words))
    out.extend(b"\0" * 12)
    gate(len(out) <= DATA_FILE - TABLE_FILE, "finalizer table overflow")
    return bytes(out)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    out: list[list[str]] = []
    start = prev = offsets[0]
    for value in offsets[1:]:
        if value != prev + 1:
            out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
            start = value
        prev = value
    out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return out


def emit_candidate(
    parent: bytes,
    stub: bytes,
    *,
    kind: str,
    output_rom: Path,
    output_sav: Path,
    entries: list[tuple[int, int, int]],
    payload: bytes,
    details: dict[str, Any],
) -> dict[str, Any]:
    gate(all(value == 0 for value in parent[STUB_FILE:ALLOC_END]), "finalizer allocation not zero-filled in parent")
    gate(len(stub) <= TABLE_FILE - STUB_FILE, "finalizer stub overflow")
    table = make_table(entries)
    gate(DATA_FILE + len(payload) <= ALLOC_END, "finalizer data overflow")

    candidate = bytearray(parent)
    candidate[HOOK_FILE:HOOK_FILE + 8] = sortpatch.make_trampoline(0, STUB_ADDR)
    candidate[STUB_FILE:STUB_FILE + len(stub)] = stub
    candidate[TABLE_FILE:TABLE_FILE + len(table)] = table
    if payload:
        candidate[DATA_FILE:DATA_FILE + len(payload)] = payload
    output = bytes(candidate)

    changed = [i for i, (a, b) in enumerate(zip(parent, output)) if a != b]
    allowed = set(range(HOOK_FILE, HOOK_FILE + 8))
    allowed.update(range(STUB_FILE, STUB_FILE + len(stub)))
    allowed.update(range(TABLE_FILE, TABLE_FILE + len(table)))
    allowed.update(range(DATA_FILE, DATA_FILE + len(payload)))
    gate(changed and set(changed) <= allowed, f"{kind} changes escaped finalizer allocation")

    crc = binascii.crc32(output) & 0xFFFFFFFF
    output_rom.parent.mkdir(parents=True, exist_ok=True)
    output_rom.write_bytes(output)
    shutil.copy2(MAIN_SAV, output_sav)
    gate(output_sav.read_bytes() == MAIN_SAV.read_bytes(), f"{kind} SAV copy drift")

    return {
        "kind": kind,
        "rom": advance_relative(output_rom),
        "sha256": sha256(output),
        "crc32": f"0x{crc:08X}",
        "sav": advance_relative(output_sav),
        "changed_bytes": len(changed),
        "changed_ranges": changed_ranges(changed),
        "table_entries": [
            {"destination": f"0x{d:08X}", "source": f"0x{s:08X}", "words": w, "bytes": w * 4}
            for d, s, w in entries
        ],
        "payload_bytes": len(payload),
        "details": details,
        "status": "test_candidate_main_tip_not_promoted",
    }


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    state, _chunks = statefmt.parse_png_state(STATE)
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))

    gate(sha256(parent) == manifest["sha256"], "main TIP hash/manifest drift")
    gate(sha256(parent) == CURRENT_MAIN_SHA256, f"unexpected current main {sha256(parent)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(struct.unpack_from("<I", state, 8)[0] == (binascii.crc32(parent) & 0xFFFFFFFF), "current ss1 does not match main CRC")
    gate(parent[HOOK_FILE:HOOK_FILE + 8] == HOOK_EXPECTED, "unit-list final compositor epilogue drift")
    gate(thumb_bl_target(parent, COMPOSITOR_CALL) == COMPOSITOR_START, "unit-list final compositor caller drift")
    gate(all(value == 0 for value in parent[STUB_FILE:ALLOC_END]), "private finalizer allocation already used")

    # Current main has already-approved Korean C439 graphics while the supplied
    # state still contains exact Japanese cached copies at the two VRAM slots.
    current_b = parent[HOLD_B_SOURCE - ROM_BASE:HOLD_B_SOURCE - ROM_BASE + 64]
    current_a = parent[HOLD_A_SOURCE - ROM_BASE:HOLD_A_SOURCE - ROM_BASE + 64]
    jp_b = jp[HOLD_B_SOURCE - ROM_BASE:HOLD_B_SOURCE - ROM_BASE + 64]
    jp_a = jp[HOLD_A_SOURCE - ROM_BASE:HOLD_A_SOURCE - ROM_BASE + 64]
    gate(current_b != jp_b and current_a != jp_a, "current C439 sources are not Korean")
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    gate(vram[HOLD_B_DEST - 0x06000000:HOLD_B_DEST - 0x06000000 + 64] == jp_b, "live B cache no longer matches JP")
    gate(vram[HOLD_A_DEST - 0x06000000:HOLD_A_DEST - 0x06000000 + 64] == jp_a, "live A cache no longer matches JP")

    # Screen signature gate measured from current ss1.
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    gate(struct.unpack_from("<H", io, 0x0C)[0] == BG2CNT_VALUE, "BG2CNT signature drift")
    gate(u32(vram, SCREEN_WORD1_ADDR - 0x06000000) == SCREEN_WORD1_VALUE, "unit screen word1 signature drift")
    gate(u32(vram, SCREEN_WORD2_ADDR - 0x06000000) == SCREEN_WORD2_VALUE, "unit screen word2 signature drift")

    with ZipFile(FONT_ZIP) as archive:
        font11 = fontpair.load_bdf(archive, "Galmuri11.bdf")
    owned_runs, owned_blob, owned_report = build_owned_payload(state, font11)

    stub = build_finalizer_stub()
    gate(len(stub) < TABLE_FILE - STUB_FILE, "stub unexpectedly large")

    # Candidate 1: only repair the stale normal/focus C439 caches using the
    # already-approved current-main C439 Korean payloads.
    hold_entries = [
        (HOLD_B_DEST, HOLD_B_SOURCE, HOLD_WORDS),
        (HOLD_A_DEST, HOLD_A_SOURCE, HOLD_WORDS),
    ]
    hold_result = emit_candidate(
        parent,
        stub,
        kind="hold_finalizer_only",
        output_rom=HOLD_ROM,
        output_sav=HOLD_SAV,
        entries=hold_entries,
        payload=b"",
        details={
            "translation": {"持": "지"},
            "source_policy": "reuse current-main approved C439 B/A Korean 8x16 payloads byte-exact",
            "c_suffix_untouched": True,
            "cache_destinations": [f"0x{HOLD_B_DEST:08X}", f"0x{HOLD_A_DEST:08X}"],
            "main_sources": [f"0x{HOLD_B_SOURCE:08X}", f"0x{HOLD_A_SOURCE:08X}"],
        },
    )

    # Candidate 2: only repair the runtime-composed 所有数 tiles at the same
    # final compositor boundary.  Its Korean tiles live in private expansion.
    owned_entries: list[tuple[int, int, int]] = []
    cursor = 0
    for destination, run_payload, _ids in owned_runs:
        owned_entries.append((destination, DATA_ADDR + cursor, len(run_payload) // 4))
        cursor += len(run_payload)
    gate(cursor == len(owned_blob), "owned data cursor drift")
    owned_result = emit_candidate(
        parent,
        stub,
        kind="owned_count_finalizer_only",
        output_rom=OWNED_ROM,
        output_sav=OWNED_SAV,
        entries=owned_entries,
        payload=owned_blob,
        details=owned_report,
    )

    # Static instruction sanity: the trampoline is aligned and the shared stub
    # returns to the untouched original epilogue continuation.
    gate(HOOK_ADDR % 4 == 0, "hook address lost word alignment")
    gate(sortpatch.make_trampoline(0, STUB_ADDR)[:4] == bytes.fromhex("00480047"), "aligned trampoline encoding drift")

    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__))],
        cwd=ADVANCE_ROOT,
        capture_output=True,
        text=True,
    )
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_finalizer_candidates_20260903",
        "result": "PASS",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(parent),
            "state": advance_relative(STATE),
            "state_sha256": sha256(STATE.read_bytes()),
            "state_crc_matches_main": True,
        },
        "architecture": {
            "rejected_old_hook": "0x08063194 shared transfer helper",
            "new_hook": f"0x{HOOK_ADDR:08X}",
            "new_hook_role": "final epilogue of full unit-list compositor 0x080776D8..0x08077A42",
            "compositor_direct_caller": f"0x{COMPOSITOR_CALL:08X}",
            "stub": f"0x{STUB_ADDR:08X}",
            "table": f"0x{TABLE_ADDR:08X}",
            "private_data": f"0x{DATA_ADDR:08X}",
            "screen_gate": {
                "BG2CNT": f"0x{BG2CNT_VALUE:04X}",
                f"0x{SCREEN_WORD1_ADDR:08X}": f"0x{SCREEN_WORD1_VALUE:08X}",
                f"0x{SCREEN_WORD2_ADDR:08X}": f"0x{SCREEN_WORD2_VALUE:08X}",
            },
            "stub_bytes": len(stub),
            "epilogue_continuation": f"0x{CONT_ADDR:08X}",
        },
        "candidates": {
            "hold": hold_result,
            "owned_count": owned_result,
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_match": True,
            "main_tip_not_modified": MAIN_TIP_ROM.read_bytes() == parent,
            "current_C439_sources_are_Korean": True,
            "current_ss1_cached_C439_sources_are_Japanese": True,
            "hook_epilogue_exact_match": True,
            "compositor_direct_call_verified": True,
            "private_allocation_zero_before_build": True,
            "screen_signature_exact": True,
            "hold_candidate_only_hook_stub_table_changes": True,
            "owned_candidate_only_hook_stub_table_private_payload_changes": True,
            "main_sav_copied_byte_exact": True,
            "py_compile": "PASS",
            "runtime_measurement": "pending user verification; boot each candidate with its copied SAV and enter the unit list fresh rather than judging from an older ss1 VRAM cache",
        },
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "manifest": advance_relative(MANIFEST),
        "hook": f"0x{HOOK_ADDR:08X}",
        "stub_bytes": len(stub),
        "hold": {"rom": hold_result["rom"], "sha256": hold_result["sha256"], "sav": hold_result["sav"], "changed_bytes": hold_result["changed_bytes"]},
        "owned_count": {"rom": owned_result["rom"], "sha256": owned_result["sha256"], "sav": owned_result["sav"], "changed_bytes": owned_result["changed_bytes"]},
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
