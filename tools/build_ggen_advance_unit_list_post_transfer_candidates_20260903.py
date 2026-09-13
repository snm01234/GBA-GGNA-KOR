#!/usr/bin/env python3
"""Build corrected unit-list candidates at the screen-specific post-transfer callsite.

The previous 22.120.6 candidates patched VRAM from the compositor epilogue at
0x08077A34.  User runtime measurement proved both were visually unchanged.
Static caller tracing now explains why: the unit-list owner at 0x08079EF8 calls
compositor 0x080776D8 first and only later calls 0x08063194 at 0x08079F32.
That helper performs the final screen transfer, so any VRAM writes made from the
compositor epilogue can be overwritten afterwards.

This follow-up replaces the exact unit-list callsite 0x08079F32 (not the shared
0x08063194 helper) with an absolute trampoline.  The far stub first invokes the
existing current-main 0x08063194 transfer path, then applies the Korean VRAM
payload, and finally reproduces the two overwritten instructions before
resuming at 0x08079F3A with condition flags intact.

Two isolated test candidates are emitted:
  1. cached normal/focus 持 -> 지 only;
  2. 所有数 -> 보유수 only.

Canonical main TIP is never overwritten.
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

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sortpatch
import build_ggen_advance_unit_list_finalizer_candidates_20260903 as prior
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

OUT_ROOT = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_unit_list_post_transfer"
HOLD_ROM = OUT_ROOT / "ggen_advance_unit_list_hold_post_transfer_candidate_20260903.gba"
HOLD_SAV = OUT_ROOT / "ggen_advance_unit_list_hold_post_transfer_candidate_20260903.sav"
OWNED_ROM = OUT_ROOT / "ggen_advance_unit_list_owned_count_post_transfer_candidate_20260903.gba"
OWNED_SAV = OUT_ROOT / "ggen_advance_unit_list_owned_count_post_transfer_candidate_20260903.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_unit_list_post_transfer_candidates_20260903.json"

ROM_BASE = 0x08000000
CURRENT_MAIN_SHA256 = prior.CURRENT_MAIN_SHA256
EXPECTED_JP_SHA256 = prior.EXPECTED_JP_SHA256

# Exact screen-specific sequence in the unit-list owner:
#   08079EF8 bl 080776D8   ; compose rows/detail into work buffers
#   ...
#   08079F32 bl 08063194   ; final screen transfer
#   08079F36 ldrh r0,[r6]
#   08079F38 cmp r0,#2
#   08079F3A beq 08079F3E
# The old finalizer ran before this transfer and was therefore overwritten.
CALL_FILE = 0x00079F32
CALL_ADDR = ROM_BASE + CALL_FILE
CALL_EXPECTED8 = bytes.fromhex("e9f72ff930880228")
ORIGINAL_TRANSFER = 0x08063194
RESUME_ADDR = 0x08079F3A
COMPOSITOR_CALL = 0x08079EF8
COMPOSITOR_START = 0x080776D8

# Reuse the same zero-filled private expansion allocation as the failed
# candidate.  It is still untouched in canonical main because 22.120.6 was
# never promoted.
STUB_FILE = prior.STUB_FILE
TABLE_FILE = prior.TABLE_FILE
DATA_FILE = prior.DATA_FILE
ALLOC_END = prior.ALLOC_END
STUB_ADDR = ROM_BASE + STUB_FILE
TABLE_ADDR = ROM_BASE + TABLE_FILE
DATA_ADDR = ROM_BASE + DATA_FILE

BG2CNT_ADDR = prior.BG2CNT_ADDR
BG2CNT_VALUE = prior.BG2CNT_VALUE
SCREEN_WORD1_ADDR = prior.SCREEN_WORD1_ADDR
SCREEN_WORD1_VALUE = prior.SCREEN_WORD1_VALUE
SCREEN_WORD2_ADDR = prior.SCREEN_WORD2_ADDR
SCREEN_WORD2_VALUE = prior.SCREEN_WORD2_VALUE

HOLD_B_DEST = prior.HOLD_B_DEST
HOLD_A_DEST = prior.HOLD_A_DEST
HOLD_B_SOURCE = prior.HOLD_B_SOURCE
HOLD_A_SOURCE = prior.HOLD_A_SOURCE
HOLD_WORDS = prior.HOLD_WORDS


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def thumb_bl_target(data: bytes | bytearray, address: int) -> int | None:
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


def build_post_transfer_stub() -> bytes:
    """Call current-main final transfer first, then apply the private table."""
    t = thumbutil._Thumb(STUB_ADDR)
    t.label("entry")

    # We arrive by absolute BX, not BL.  Preserve r4 because the caller keeps
    # it live across 0x08079F32.  Set LR explicitly to the known instruction
    # immediately after the absolute call sequence and BX into 0x08063194.
    t.h(0xB410)  # push {r4}
    t.ldr_pc(2, "transfer_return")
    t.h(0x4696)  # mov lr, r2
    t.ldr_pc(3, "original_transfer")
    t.h(0x4718)  # bx r3

    # The sequence above is exactly five 16-bit instructions from STUB_ADDR,
    # so 0x09F2300A is the first instruction reached when the transfer returns.
    t.label("after_transfer")

    # Gate after the transfer, when VRAM contains the final unit-list frame.
    t.ldr_pc(0, "bg2cnt_addr")
    t.h(0x8801)  # ldrh r1,[r0]
    t.ldr_pc(2, "bg2cnt_value")
    t.h(op_cmp_reg(1, 2))
    t.b("done", 0x1)  # bne

    t.ldr_pc(0, "screen_word1_addr")
    t.h(op_ldr_word(1, 0))
    t.ldr_pc(2, "screen_word1_value")
    t.h(op_cmp_reg(1, 2))
    t.b("done", 0x1)

    t.ldr_pc(0, "screen_word2_addr")
    t.h(op_ldr_word(1, 0))
    t.ldr_pc(2, "screen_word2_value")
    t.h(op_cmp_reg(1, 2))
    t.b("done", 0x1)

    # {destination, source, word_count}, dest=0 terminator.
    t.ldr_pc(4, "table")
    t.label("table_loop")
    t.h(op_ldr_word(0, 4, 0))
    t.h(0x2800)  # cmp r0,#0
    t.b("done", 0x0)
    t.h(op_ldr_word(1, 4, 4))
    t.h(op_ldr_word(2, 4, 8))
    t.label("copy_loop")
    t.h(op_ldr_word(3, 1, 0))
    t.h(op_str_word(3, 0, 0))
    t.h(0x3004)  # adds r0,#4
    t.h(0x3104)  # adds r1,#4
    t.h(0x3A01)  # subs r2,#1
    t.b("copy_loop", 0x1)
    t.h(0x340C)  # adds r4,#12
    t.b("table_loop")

    t.label("done")
    t.h(0xBC10)  # pop {r4}

    # Reproduce the two instructions overwritten together with the BL call.
    # The following absolute LDR/BX does not alter flags, so the original BEQ
    # at 0x08079F3A observes the CMP result exactly as before.
    t.h(0x8830)  # ldrh r0,[r6]
    t.h(0x2802)  # cmp r0,#2
    t.ldr_pc(3, "resume")
    t.h(0x4718)  # bx r3

    t.align4()
    t.word("transfer_return", (STUB_ADDR + 0x0A) | 1)
    t.word("original_transfer", ORIGINAL_TRANSFER | 1)
    t.word("bg2cnt_addr", BG2CNT_ADDR)
    t.word("bg2cnt_value", BG2CNT_VALUE)
    t.word("screen_word1_addr", SCREEN_WORD1_ADDR)
    t.word("screen_word1_value", SCREEN_WORD1_VALUE)
    t.word("screen_word2_addr", SCREEN_WORD2_ADDR)
    t.word("screen_word2_value", SCREEN_WORD2_VALUE)
    t.word("table", TABLE_ADDR)
    t.word("resume", RESUME_ADDR | 1)
    result = t.build()
    gate(result[:2] == bytes.fromhex("10b4"), "stub push encoding drift")
    return result


def make_table(entries: list[tuple[int, int, int]]) -> bytes:
    out = bytearray()
    for destination, source, words in entries:
        gate(destination and source and words > 0, "invalid table row")
        out.extend(struct.pack("<III", destination, source, words))
    out.extend(b"\0" * 12)
    gate(len(out) <= DATA_FILE - TABLE_FILE, "table overflow")
    return bytes(out)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    result: list[list[str]] = []
    start = prev = offsets[0]
    for value in offsets[1:]:
        if value != prev + 1:
            result.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
            start = value
        prev = value
    result.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return result


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
    gate(parent[CALL_FILE:CALL_FILE + 8] == CALL_EXPECTED8, "unit-list post-transfer callsite drift")
    gate(all(value == 0 for value in parent[STUB_FILE:ALLOC_END]), "private allocation not zero-filled")
    gate(len(stub) <= TABLE_FILE - STUB_FILE, "stub overflow")
    table = make_table(entries)
    gate(DATA_FILE + len(payload) <= ALLOC_END, "payload overflow")

    candidate = bytearray(parent)
    candidate[CALL_FILE:CALL_FILE + 8] = sortpatch.make_trampoline(0, STUB_ADDR)
    candidate[STUB_FILE:STUB_FILE + len(stub)] = stub
    candidate[TABLE_FILE:TABLE_FILE + len(table)] = table
    if payload:
        candidate[DATA_FILE:DATA_FILE + len(payload)] = payload
    output = bytes(candidate)

    changed = [index for index, (before, after) in enumerate(zip(parent, output)) if before != after]
    allowed = set(range(CALL_FILE, CALL_FILE + 8))
    allowed.update(range(STUB_FILE, STUB_FILE + len(stub)))
    allowed.update(range(TABLE_FILE, TABLE_FILE + len(table)))
    allowed.update(range(DATA_FILE, DATA_FILE + len(payload)))
    gate(changed and set(changed) <= allowed, f"{kind} changes escaped post-transfer allocation")

    output_rom.parent.mkdir(parents=True, exist_ok=True)
    output_rom.write_bytes(output)
    shutil.copy2(MAIN_SAV, output_sav)
    gate(output_sav.read_bytes() == MAIN_SAV.read_bytes(), f"{kind} SAV copy drift")

    return {
        "kind": kind,
        "rom": advance_relative(output_rom),
        "sha256": sha256(output),
        "crc32": f"0x{binascii.crc32(output) & 0xFFFFFFFF:08X}",
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
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))

    gate(sha256(parent) == main_manifest["sha256"], "main TIP hash/manifest drift")
    gate(sha256(parent) == CURRENT_MAIN_SHA256, f"unexpected current main {sha256(parent)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(struct.unpack_from("<I", state, 8)[0] == (binascii.crc32(parent) & 0xFFFFFFFF), "ss1/main CRC drift")
    gate(parent[CALL_FILE:CALL_FILE + 8] == CALL_EXPECTED8, "post-transfer callsite bytes drift")
    gate(thumb_bl_target(parent, CALL_ADDR) == ORIGINAL_TRANSFER, "0x08079F32 no longer calls 0x08063194")
    gate(thumb_bl_target(parent, COMPOSITOR_CALL) == COMPOSITOR_START, "unit-list compositor call drift")
    gate(all(value == 0 for value in parent[STUB_FILE:ALLOC_END]), "private allocation already used")

    # Current main's shared helper is itself a promoted absolute trampoline for
    # sort-popup support.  Calling the helper remains required; we patch only
    # the unit-list caller and run after that helper returns.
    gate(parent[0x00063194:0x0006319C] == bytes.fromhex("004b18470100f209"), "current 0x08063194 trampoline drift")

    current_b = parent[HOLD_B_SOURCE - ROM_BASE:HOLD_B_SOURCE - ROM_BASE + 64]
    current_a = parent[HOLD_A_SOURCE - ROM_BASE:HOLD_A_SOURCE - ROM_BASE + 64]
    jp_b = jp[HOLD_B_SOURCE - ROM_BASE:HOLD_B_SOURCE - ROM_BASE + 64]
    jp_a = jp[HOLD_A_SOURCE - ROM_BASE:HOLD_A_SOURCE - ROM_BASE + 64]
    gate(current_b != jp_b and current_a != jp_a, "current C439 sources are not Korean")

    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    gate(struct.unpack_from("<H", io, 0x0C)[0] == BG2CNT_VALUE, "BG2CNT state signature drift")
    gate(u32(vram, SCREEN_WORD1_ADDR - 0x06000000) == SCREEN_WORD1_VALUE, "screen word1 drift")
    gate(u32(vram, SCREEN_WORD2_ADDR - 0x06000000) == SCREEN_WORD2_VALUE, "screen word2 drift")

    with ZipFile(FONT_ZIP) as archive:
        font11 = fontpair.load_bdf(archive, "Galmuri11.bdf")
    owned_runs, owned_blob, owned_report = prior.build_owned_payload(state, font11)

    stub = build_post_transfer_stub()
    gate(len(stub) < TABLE_FILE - STUB_FILE, "post-transfer stub unexpectedly large")

    hold_entries = [
        (HOLD_B_DEST, HOLD_B_SOURCE, HOLD_WORDS),
        (HOLD_A_DEST, HOLD_A_SOURCE, HOLD_WORDS),
    ]
    hold_result = emit_candidate(
        parent,
        stub,
        kind="hold_post_transfer_only",
        output_rom=HOLD_ROM,
        output_sav=HOLD_SAV,
        entries=hold_entries,
        payload=b"",
        details={
            "translation": {"持": "지"},
            "source_policy": "reuse current-main approved C439 Korean B/A payloads byte-exact",
            "cache_destinations": [f"0x{HOLD_B_DEST:08X}", f"0x{HOLD_A_DEST:08X}"],
            "c_suffix_untouched": True,
        },
    )

    owned_entries: list[tuple[int, int, int]] = []
    cursor = 0
    for destination, run_payload, _ids in owned_runs:
        owned_entries.append((destination, DATA_ADDR + cursor, len(run_payload) // 4))
        cursor += len(run_payload)
    gate(cursor == len(owned_blob), "owned payload cursor drift")
    owned_result = emit_candidate(
        parent,
        stub,
        kind="owned_count_post_transfer_only",
        output_rom=OWNED_ROM,
        output_sav=OWNED_SAV,
        entries=owned_entries,
        payload=owned_blob,
        details=owned_report,
    )

    # Static execution proof for the corrected boundary.
    for result in (hold_result, owned_result):
        built = (ADVANCE_ROOT / result["rom"]).read_bytes()
        gate(built[CALL_FILE:CALL_FILE + 8] == sortpatch.make_trampoline(0, STUB_ADDR), "callsite trampoline verification failed")
        gate(built[STUB_FILE:STUB_FILE + len(stub)] == stub, "stub verification failed")

    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__))],
        cwd=ADVANCE_ROOT,
        capture_output=True,
        text=True,
    )
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_post_transfer_candidates_20260903",
        "result": "PASS",
        "runtime_feedback": {
            "supply_totals_candidate": "PASS: 보급포인트/총유닛수 confirmed by user",
            "22.120.6_hold_finalizer": "FAIL: no visible change",
            "22.120.6_owned_count_finalizer": "FAIL: no visible change",
        },
        "root_cause_correction": {
            "failed_boundary": "0x08077A34 compositor epilogue",
            "reason": "0x08079EF8 invokes compositor 0x080776D8, but the same owner later invokes 0x08063194 at 0x08079F32; that later transfer can overwrite VRAM changes made from the compositor epilogue",
            "corrected_boundary": "replace only the unit-list 0x08079F32 transfer callsite; invoke existing 0x08063194 first, then patch VRAM after it returns",
            "shared_helper_itself_unchanged": True,
            "callsite_sequence": [
                "0x08079EF8 -> 0x080776D8 compositor",
                "0x08079F32 -> 0x08063194 final transfer",
                "post-transfer Korean VRAM patch",
                "resume at original 0x08079F3A branch with CMP flags preserved",
            ],
        },
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(parent),
            "state": advance_relative(STATE),
            "state_sha256": sha256(STATE.read_bytes()),
        },
        "architecture": {
            "hook_file_offset": f"0x{CALL_FILE:08X}",
            "hook_address": f"0x{CALL_ADDR:08X}",
            "original_target": f"0x{ORIGINAL_TRANSFER:08X}",
            "stub": f"0x{STUB_ADDR:08X}",
            "table": f"0x{TABLE_ADDR:08X}",
            "private_data": f"0x{DATA_ADDR:08X}",
            "resume": f"0x{RESUME_ADDR:08X}",
            "stub_bytes": len(stub),
            "screen_gate": {
                "BG2CNT": f"0x{BG2CNT_VALUE:04X}",
                f"0x{SCREEN_WORD1_ADDR:08X}": f"0x{SCREEN_WORD1_VALUE:08X}",
                f"0x{SCREEN_WORD2_ADDR:08X}": f"0x{SCREEN_WORD2_VALUE:08X}",
            },
        },
        "candidates": {
            "hold": hold_result,
            "owned_count": owned_result,
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_match": True,
            "main_tip_not_modified": True,
            "unit_list_compositor_call_verified": True,
            "post_compositor_transfer_call_verified": True,
            "shared_0x08063194_helper_not_modified": True,
            "private_allocation_zero_in_main": True,
            "screen_signature_matches_current_ss1": True,
            "overwritten_ldrh_cmp_reproduced": True,
            "original_beq_flags_preserved": True,
            "main_sav_copied_byte_exact": True,
            "py_compile": "PASS",
            "runtime_measurement": "pending user verification; enter unit list fresh from copied SAV",
        },
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "manifest": advance_relative(MANIFEST),
        "root_cause": report["root_cause_correction"],
        "hold": {key: hold_result[key] for key in ("rom", "sha256", "sav", "changed_bytes")},
        "owned_count": {key: owned_result[key] for key in ("rom", "sha256", "sav", "changed_bytes")},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
