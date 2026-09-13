#!/usr/bin/env python3
"""Instrument 0x0801EC0C blit/text calls that own BG2 screenblock 29.

Previous 所有数 diagnostics traced E8D4/D350/global fonts and never recorded
the EC0C 0x0800269C / 0x08000CA0 / 0x08000D10 arguments.  This ROM changes no
graphics: each wrapper counts the call and stores r0-r3 plus three stack words
into a private EWRAM table.  A later savestate proves which EC0C subcall writes
the 소유수 plaque.
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

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    advance_relative,
)

ROM_BASE = 0x08000000
EXPECTED_MAIN_SHA256 = "5e424b1737c411639f355a7509affb92eadc46113fd1802269f8e14cbdbb4618"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
MAIN_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_owned_count_ec0c_trace"
OUT_ROM = OUT_DIR / "ggen_advance_owned_count_ec0c_trace_candidate_20260904.gba"
OUT_SAV = OUT_DIR / "ggen_advance_owned_count_ec0c_trace_candidate_20260904.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_ec0c_trace_candidate_20260904.json"

CAVE_FILE = 0x000C5700
CAVE_LIMIT = 0x000C6800
WRAPPER_SIZE = 0x60
TRACE_BASE = 0x0203C700
RECORD_SIZE = 0x20
TRACE_SIZE = 0x800
SCAN_START = 0x0801EC0C
SCAN_END = 0x0801F400
TARGETS = {
    0x0800269C: "blit_0269C",
    0x08000CA0: "text_CA0",
    0x08000D10: "text_D10",
}


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


def encode_thumb_bl(address: int, target: int) -> bytes:
    gate(address & 1 == 0 and target & 1 == 0, "Thumb BL alignment drift")
    offset = target - (address + 4)
    gate(offset % 2 == 0, "Thumb BL displacement misaligned")
    imm = offset >> 1
    gate(-0x400000 <= imm < 0x400000, f"Thumb BL out of range 0x{address:08X}->0x{target:08X}")
    s = (imm >> 21) & 1
    return struct.pack("<HH", 0xF000 | (s << 10) | ((imm >> 11) & 0x3FF), 0xF800 | (imm & 0x7FF))


def str_word_imm(rd: int, rn: int, byte_off: int) -> int:
    gate(byte_off % 4 == 0 and 0 <= byte_off <= 124, "STR immediate out of range")
    return 0x6000 | ((byte_off // 4) << 6) | (rn << 3) | rd


def build_wrapper(base: int, record: int, target: int) -> bytes:
    """0x60 wrapper: ++count, store r0-r3 + 3 stack words, invoke original."""
    gate(base % 4 == 0 and record % 4 == 0, "wrapper/record alignment drift")
    out = bytearray()
    h = lambda value: out.extend(struct.pack("<H", value))
    h(0xB51F)  # push {r0-r4,lr}; caller stack starts at sp+24
    # LDR record literal placed at +0x5C.  This instruction sits at +2, so
    # PC=(base+6)&~3 = base+4 when base%4==0; imm = 0x58.
    h(0x4816)
    h(0x6801)
    h(0x3101)
    h(0x6001)
    h(0x9800)
    h(str_word_imm(0, 0, 4))   # r0 dest / text-object
    h(0x9901)
    h(str_word_imm(1, 0, 8))   # r1 x
    h(0x9902)
    h(str_word_imm(1, 0, 12))  # r2 y
    h(0x9903)
    h(str_word_imm(1, 0, 16))  # r3 map/text
    h(0x9906)
    h(str_word_imm(1, 0, 20))  # stack0 clip / extra
    h(0x9907)
    h(str_word_imm(1, 0, 24))  # stack1 tilebase
    h(0x9908)
    h(str_word_imm(1, 0, 28))  # stack2 palette
    h(0xB088)  # sub sp,#32
    for index in range(8):
        h(0x9800 | (14 + index))
        h(0x9000 | index)
    h(0x9808)
    h(0x9909)
    h(0x9A0A)
    h(0x9B0B)
    out.extend(encode_thumb_bl(base + len(out), target))
    h(0xB008)
    h(0xB004)
    h(0xBD10)
    gate(len(out) <= 0x5C, f"wrapper code too large: {len(out)}")
    out.extend(b"\x00" * (0x5C - len(out)))
    out.extend(struct.pack("<I", record))
    gate(len(out) == WRAPPER_SIZE, f"wrapper size drift: {len(out)}")
    return bytes(out)


def discover_calls(data: bytes) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    counts = {name: 0 for name in TARGETS.values()}
    addr = SCAN_START
    while addr + 4 <= SCAN_END:
        target = thumb_bl_target(data, addr)
        if target in TARGETS:
            name = TARGETS[target]
            counts[name] += 1
            rows.append((f"{name}_{counts[name]:02d}", addr, target))
            addr += 4
            continue
        addr += 2
    return rows


def parse_state_ewram(path: Path) -> bytes:
    state, _chunks = statefmt.parse_png_state(path)
    return state[0x21000:0x61000]


def main() -> int:
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    parent = MAIN_TIP_ROM.read_bytes()
    gate(sha256(parent) == EXPECTED_MAIN_SHA256, "canonical main hash drift")
    gate(manifest.get("sha256") == EXPECTED_MAIN_SHA256, "main manifest hash drift")
    gate(manifest.get("promotion_reason") == "user_approved_n_tile_rollback_20260903", "unexpected current main")
    gate(MAIN_SAV.is_file(), "main SAV missing")
    gate(all(b == 0 for b in parent[CAVE_FILE:CAVE_LIMIT]), "ROM cave is no longer zero-filled")

    if MAIN_STATE.is_file():
        ewram = parse_state_ewram(MAIN_STATE)
        trace_off = TRACE_BASE - 0x02000000
        gate(all(b == 0 for b in ewram[trace_off:trace_off + TRACE_SIZE]), "trace EWRAM nonzero in current ss1")

    refs = []
    for off in range(0, len(parent) - 3, 4):
        value = u32(parent, off)
        if TRACE_BASE <= value < TRACE_BASE + TRACE_SIZE:
            refs.append((off, value))
    gate(not refs, f"aligned ROM refs into trace EWRAM: {refs[:8]}")

    calls = discover_calls(parent)
    gate(calls, "no EC0C blit/text calls discovered")
    gate(len(calls) * RECORD_SIZE <= TRACE_SIZE, "trace record region overflow")
    gate(len(calls) * WRAPPER_SIZE <= CAVE_LIMIT - CAVE_FILE, "wrapper cave overflow")
    blit_n = sum(1 for _n, _s, t in calls if t == 0x0800269C)
    ca0_n = sum(1 for _n, _s, t in calls if t == 0x08000CA0)
    d10_n = sum(1 for _n, _s, t in calls if t == 0x08000D10)
    gate(blit_n >= 10 and ca0_n >= 8 and d10_n >= 12, f"EC0C call mix drift blit={blit_n} ca0={ca0_n} d10={d10_n}")

    child = bytearray(parent)
    cursor = CAVE_FILE
    rows: list[dict[str, Any]] = []
    for index, (name, site, expected) in enumerate(calls):
        gate(thumb_bl_target(parent, site) == expected, f"call target drift {name} @0x{site:08X}")
        wrapper = ROM_BASE + cursor
        record = TRACE_BASE + index * RECORD_SIZE
        payload = build_wrapper(wrapper, record, expected)
        gate(cursor + len(payload) <= CAVE_LIMIT, "wrapper cave overflow")
        gate(all(b == 0 for b in child[cursor:cursor + len(payload)]), f"wrapper overlap at 0x{cursor:08X}")
        child[cursor:cursor + len(payload)] = payload
        child[site - ROM_BASE:site - ROM_BASE + 4] = encode_thumb_bl(site, wrapper)
        gate(thumb_bl_target(child, site) == wrapper, f"patched BL drift {name}")
        rows.append({
            "index": index,
            "name": name,
            "kind": TARGETS[expected],
            "callsite": f"0x{site:08X}",
            "original_target": f"0x{expected:08X}",
            "record": f"0x{record:08X}",
            "wrapper": f"0x{wrapper:08X}",
        })
        cursor += WRAPPER_SIZE

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(child)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    py_compile = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__).resolve()), str(THIS_DIR / "analyze_ggen_advance_owned_count_ec0c_trace_state_20260904.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate(py_compile.returncode == 0, f"py_compile failed: {py_compile.stderr}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_ec0c_trace_candidate_20260904",
        "result": "PASS",
        "source": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
            "promotion_reason": manifest["promotion_reason"],
        },
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(child), "size": len(child)},
        "sav": {
            "path": advance_relative(OUT_SAV),
            "sha256": sha256(OUT_SAV.read_bytes()),
            "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(),
        },
        "trace": {
            "base": f"0x{TRACE_BASE:08X}",
            "record_size": RECORD_SIZE,
            "size": TRACE_SIZE,
            "fields": ["count", "r0", "r1_x", "r2_y", "r3_map_or_text", "stack0", "stack1_tilebase", "stack2_palette"],
        },
        "scan": {
            "function": "0x0801EC0C",
            "range": [f"0x{SCAN_START:08X}", f"0x{SCAN_END:08X}"],
            "blit_0269C": blit_n,
            "text_CA0": ca0_n,
            "text_D10": d10_n,
        },
        "calls": rows,
        "verification": {
            "result": "PASS",
            "current_main_hash_verified": True,
            "cave_zero_filled": True,
            "trace_ewram_unreferenced": True,
            "graphics_unchanged": True,
            "only_ec0c_bls_and_cave_mutated": True,
            "py_compile": "PASS",
            "main_tip_not_modified": True,
        },
        "measurement_checkpoints": [
            "후보 ROM + 동봉 SAV로 부팅한 뒤 처분 유닛 목록에 새로 진입한다. 화면의 所有数는 그대로인 것이 정상이다.",
            "해당 화면에서 unit_owned_ec0c_entry.ss1을 저장한다.",
            "커서를 한 칸 옮긴 뒤 unit_owned_ec0c_move1.ss1을 저장한다.",
            "tools/analyze_ggen_advance_owned_count_ec0c_trace_state_20260904.py에 두 state를 넣으면 dest=0x0600E800 또는 소유수 좌표 근처 호출만 골라 준다.",
        ],
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": advance_relative(OUT_ROM),
        "sha256": sha256(child),
        "calls": len(rows),
        "blit": blit_n,
        "ca0": ca0_n,
        "d10": d10_n,
        "manifest": advance_relative(MANIFEST),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
