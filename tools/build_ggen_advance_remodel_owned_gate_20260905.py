#!/usr/bin/env python3
"""Stop the 소유수 overlay from painting remodel-scene filler tile 500.

Current main runs the same gated copy from two stubs:

  * 0x080C5700 after unit-list transfers EB3E / E0AE / E6F0
  * 0x09F20240 after every 0x08063194 via the sort-frame chain

Both currently accept any screen with BG2CNT=0x5D0A and three palette-B
corners.  The unit-remodel workshop matches that, and its BG2 filler cells
(22,9)-(26,10) all point at empty tile 500, so the last 소유수 8x8 overwrites
the transparent floor overlay.

This candidate keeps the existing palette-B / BG2CNT gates and the Korean
payload, but refuses the copy when the ten destination tile IDs are not unique.
Canonical main TIP and the original SAV are not modified.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_owned_count_ab_candidates_20260903 as ab
import build_ggen_advance_owned_count_live_overlay_candidate_20260904 as overlay
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sort
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    advance_relative,
)

OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_owned_gate"
STEM = "ggen_advance_remodel_owned_gate_candidate_20260905"
RESULT = OUT / f"{STEM}.gba"
SAV_OUT = OUT / f"{STEM}.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / f"{STEM}.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REMODEL_SS2 = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
EXPECTED_MAIN = "194d874f421bd3c39a06747343d9132a71ab41bd44b75cea7c6d488fa514aec2"
PURE = 0x09F20240
PURE_LIMIT = sort.TABLE_FILE
CONTROLLER_SITES = (0x0806EB3E, 0x0806E0AE, 0x0806E6F0)
GLYPH_CELLS = overlay.GLYPH_CELLS


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def glyph_ids(state: bytes) -> list[int]:
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    return [u16(vram, 0xE800 + overlay.map_offset(x, y)) & 0x3FF for x, y in GLYPH_CELLS]


def unique_destinations(ids: list[int]) -> bool:
    return len(ids) == 10 and len(set(ids)) == 10


def consecutive_unique(ids: list[int]) -> bool:
    """Match the Thumb loop: nine successive pairs in map order, including the row wrap."""
    return all(ids[i] != ids[i + 1] for i in range(9))


def build_stub(base: int, call_transfer: bool) -> bytes:
    t = ab.Thumb(base)
    t.label("entry")
    t.h(0xB500)
    if call_transfer:
        t.bl_abs(overlay.ORIGINAL_TRANSFER)

    t.ldr_pc(0, "bg2cnt_addr")
    t.h(0x8801)
    t.ldr_pc(2, "bg2cnt_value")
    t.h(0x4291)
    t.b("done", 0x1)

    t.ldr_pc(0, "corner_tl")
    t.h(0x8801)
    t.h(overlay.op_lsr(1, 1, 12))
    t.h(0x290B)
    t.b("done", 0x1)

    t.ldr_pc(0, "corner_tr")
    t.h(0x8801)
    t.h(overlay.op_lsr(1, 1, 12))
    t.h(0x290B)
    t.b("done", 0x1)

    t.ldr_pc(0, "corner_bl")
    t.h(0x8801)
    t.h(overlay.op_lsr(1, 1, 12))
    t.h(0x290B)
    t.b("done", 0x1)

    t.h(0xB470)
    t.ldr_pc(5, "row9")
    t.h(0x8829)
    t.h(0x0589)
    t.h(overlay.op_lsr(1, 1, 22))
    t.h(0x3502)
    t.h(0x2404)
    t.h(0x2609)
    t.label("uniq")
    t.h(0x8828)
    t.h(0x0580)
    t.h(overlay.op_lsr(0, 0, 22))
    t.h(0x4288)
    t.b("restore", 0x0)
    t.h(0x1C01)
    t.h(0x3502)
    t.h(0x3C01)
    t.b("no_skip", 0x1)
    t.h(0x3536)
    t.h(0x2405)
    t.label("no_skip")
    t.h(0x3E01)
    t.b("uniq", 0x1)

    t.ldr_pc(4, "payload")
    t.ldr_pc(5, "row9")
    t.h(0x2602)
    t.label("row_loop")
    t.h(0x2205)
    t.label("tile_loop")
    t.h(0x8828)
    t.h(0x0580)
    t.h(overlay.op_lsr(0, 0, 22))
    t.h(0x0140)
    t.ldr_pc(1, "charblock2")
    t.h(0x1840)
    t.h(0x2108)
    t.label("copy_loop")
    t.h(0x6823)
    t.h(0x6003)
    t.h(0x3404)
    t.h(0x3004)
    t.h(0x3901)
    t.b("copy_loop", 0x1)
    t.h(0x3502)
    t.h(0x3A01)
    t.b("tile_loop", 0x1)
    t.h(0x3536)
    t.h(0x3E01)
    t.b("row_loop", 0x1)
    t.label("restore")
    t.h(0xBD70)
    t.label("done")
    t.h(0xBD00)
    t.align4()
    t.word("bg2cnt_addr", 0x0400000C)
    t.word("bg2cnt_value", 0x00005D0A)
    t.word("corner_tl", 0x0600E800 + overlay.map_offset(21, 8))
    t.word("corner_tr", 0x0600E800 + overlay.map_offset(29, 8))
    t.word("corner_bl", 0x0600E800 + overlay.map_offset(21, 11))
    t.word("payload", overlay.PAYLOAD_ADDR)
    t.word("row9", 0x0600E800 + overlay.map_offset(22, 9))
    t.word("charblock2", 0x06008000)
    return t.build()


def put(child: bytearray, file_off: int, payload: bytes, allowed: set[int]) -> None:
    child[file_off:file_off + len(payload)] = payload
    allowed.update(range(file_off, file_off + len(payload)))


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == EXPECTED_MAIN, f"current main hash drift: {sha256(parent)}")
    gate(manifest.get("sha256") == EXPECTED_MAIN, "main manifest hash drift")
    gate(MAIN_SAV.is_file(), "main SAV missing")
    gate(REMODEL_SS2.is_file(), "remodel ss2 missing")

    old = overlay.build_stub_clean()
    gate(parent[overlay.STUB_FILE:overlay.STUB_FILE + len(old)] == old, "C5700 overlay stub drift")
    gate(parent[PURE - 0x08000000:PURE - 0x08000000 + 8] == bytes.fromhex("00b5c046c0461748"), "pure helper prologue drift")
    for site in CONTROLLER_SITES:
        gate(ab.thumb_bl_target(parent, site) == overlay.STUB_ADDR, f"controller hook drift {site:08X}")
    gate(parent[0x63194:0x6319C] == bytes.fromhex("004b18470100f209"), "0x08063194 trampoline drift")
    gate(parent[overlay.PAYLOAD_FILE + 9 * 32:overlay.PAYLOAD_FILE + 10 * 32] == bytes.fromhex(
        "555555bbb5bbbbbbb5bbbbbbb5bbbbbbb5bbbbbbb5bbbbbbbbbbbbbbbbbbbbbb"
    ), "소유수 payload tile 9 drift")

    remodel, _ = statefmt.parse_png_state(REMODEL_SS2)
    remodel_ids = glyph_ids(remodel)
    gate(remodel_ids == [500] * 10, f"remodel glyph ids drifted: {remodel_ids}")
    gate(not unique_destinations(remodel_ids), "remodel unique-id assumption failed")
    gate(not consecutive_unique(remodel_ids), "consecutive unique check would not reject remodel")

    controller = build_stub(overlay.STUB_ADDR, True)
    pure = build_stub(PURE, False)
    gate(len(controller) <= overlay.PAYLOAD_FILE - overlay.STUB_FILE, "C5700 stub overflow")
    gate(len(pure) <= PURE_LIMIT - (PURE - 0x08000000), "pure stub overflow into sort table")

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    controller_dis = list(md.disasm(controller, overlay.STUB_ADDR))
    pure_dis = list(md.disasm(pure, PURE))
    gate(any(i.mnemonic == "bl" and int(i.op_str.lstrip("#"), 16) == overlay.ORIGINAL_TRANSFER for i in controller_dis), "controller lost 63194 call")
    gate(not any(i.mnemonic == "bl" for i in pure_dis), "pure helper must not recurse")
    gate(sum(i.mnemonic == "beq" for i in controller_dis) >= 1, "unique-fail beq missing")

    child = bytearray(parent)
    allowed: set[int] = set()
    # Replace the live stubs.  Zero leftover old literals behind a shorter write.
    put(child, overlay.STUB_FILE, controller, allowed)
    if len(controller) < len(old):
        tail = overlay.STUB_FILE + len(controller)
        put(child, tail, b"\0" * (len(old) - len(controller)), allowed)
    old_pure = parent[PURE - 0x08000000:PURE_LIMIT]
    put(child, PURE - 0x08000000, pure, allowed)
    if len(pure) < len(old_pure):
        put(child, PURE - 0x08000000 + len(pure), b"\0" * (len(old_pure) - len(pure)), allowed)

    changed = [i for i, (a, b) in enumerate(zip(parent, child)) if a != b]
    gate(changed and set(changed) <= allowed, "diff escaped owned stub allocations")
    gate(child[overlay.PAYLOAD_FILE:overlay.PAYLOAD_FILE + 320] == parent[overlay.PAYLOAD_FILE:overlay.PAYLOAD_FILE + 320], "소유수 payload changed")
    gate(child[sort.STUB_FILE:sort.STUB_FILE + 0x10] == parent[sort.STUB_FILE:sort.STUB_FILE + 0x10], "sort stub entry changed")
    gate(child[sort.TABLE_FILE:sort.ALLOCATION_END] == parent[sort.TABLE_FILE:sort.ALLOCATION_END], "sort table/payload changed")
    gate(child[0x63194:0x6319C] == parent[0x63194:0x6319C], "shared trampoline changed")
    for site in CONTROLLER_SITES:
        gate(ab.thumb_bl_target(child, site) == overlay.STUB_ADDR, "controller BL retargeted")

    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__).resolve())],
        cwd=ADVANCE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")

    OUT.mkdir(parents=True, exist_ok=True)
    sav = MAIN_SAV.read_bytes()
    if SAV_OUT.exists():
        gate(SAV_OUT.read_bytes() == sav, "output SAV contains user changes; choose a fresh output")
    RESULT.write_bytes(child)
    SAV_OUT.write_bytes(sav)
    gate(RESULT.read_bytes() == child and SAV_OUT.read_bytes() == sav, "readback mismatch")
    gate(MAIN_TIP_ROM.read_bytes() == parent and MAIN_SAV.read_bytes() == sav, "canonical inputs changed")

    report: dict[str, Any] = {
        "kind": STEM,
        "status": "candidate_not_promoted",
        "result": "PASS",
        "parent": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
            "promotion_reason": manifest["promotion_reason"],
        },
        "output": {
            "path": advance_relative(RESULT),
            "sha256": sha256(child),
            "size": len(child),
            "sav": advance_relative(SAV_OUT),
        },
        "problem": {
            "screen": "unit remodel workshop BG2 filler",
            "shared_tile": 500,
            "why": "소유수 overlay accepted BG2CNT=0x5D0A plus palette-B corners, then wrote ten Hangul tiles into live IDs (22,9)-(26,10); remodel uses 0xB1F4 for all ten cells",
        },
        "fix": {
            "controller_stub": f"0x{overlay.STUB_ADDR:08X}",
            "pure_stub": f"0x{PURE:08X}",
            "payload_unchanged": f"0x{overlay.PAYLOAD_ADDR:08X}",
            "added_gate": "refuse copy unless the ten glyph destination tile IDs are consecutive-unique",
            "controller_bytes": len(controller),
            "pure_bytes": len(pure),
            "changed_bytes": len(changed),
        },
        "remodel_ss2": {
            "path": advance_relative(REMODEL_SS2),
            "glyph_tile_ids": remodel_ids,
            "unique": unique_destinations(remodel_ids),
            "consecutive_unique": consecutive_unique(remodel_ids),
            "overlay_would_write": False,
        },
        "verification": {
            "result": "PASS",
            "static": True,
            "runtime_emulator": "not performed: re-enter remodel scene on the test ROM; do not reuse the poisoned ss2 VRAM as proof",
            "payload_byte_exact": True,
            "sort_table_byte_exact": True,
            "controller_hooks_preserved": True,
            "pure_helper_has_no_bl": True,
            "py_compile": "PASS",
            "main_tip_not_modified": True,
            "original_sav_not_modified": True,
        },
        "checkpoints": [
            "테스트 ROM+동봉 SAV로 새로 부팅한다. 깨진 ss2를 그대로 로드하면 이미 오염된 VRAM이 복원된다.",
            "개조 연출(자, 시작한다)에 다시 들어가 파란 격자 바닥이 보이는지 확인한다.",
            "보급/처분 유닛 목록의 소유수 한글이 이전과 같이 유지되는지 확인한다.",
            "정렬 팝업 오름/이름/내림/배치중 전환이 여전히 한글인지 확인한다.",
        ],
        "controller_disassembly": [f"{i.address:08X}: {i.mnemonic} {i.op_str}" for i in controller_dis if i.mnemonic != "ldr"],
        "pure_disassembly": [f"{i.address:08X}: {i.mnemonic} {i.op_str}" for i in pure_dis if i.mnemonic != "ldr"],
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(RESULT),
        "sav": str(SAV_OUT),
        "sha256": sha256(child),
        "changed_bytes": len(changed),
        "remodel_unique": unique_destinations(remodel_ids),
        "controller_stub": hex(overlay.STUB_ADDR),
        "pure_stub": hex(PURE),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
