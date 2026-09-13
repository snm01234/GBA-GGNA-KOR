#!/usr/bin/env python3
"""Instrument unit-list 12x12 text callsites to trace the 所有数 producer.

The live 所有数 plaque is proven to contain the native 12x12 glyph masks at
x=177..212/y=74..85 on BG2, but static ROM searches do not expose a raw owner.
This diagnostic patches only direct calls to the three 12x12 text front-ends
(and CA0) in the four unit/status renderer families most closely connected to
the screen: 0x0801E8D4, 0x0806CFC4, 0x0806DE80 and 0x0806C10C.

Each wrapper records call count, actual r1/r2 coordinates, r3 format/text
pointer and the first two caller stack arguments.  It then recreates four stack
arguments and invokes the original renderer with the original r0-r4 values.
No visual payload is changed and the canonical main TIP is never overwritten.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
STATE = ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ROOT / "outputs" / "20260903_ggen_advance_owned_count_text_trace"
OUT_ROM = OUT_DIR / "ggen_advance_owned_count_text_trace_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_owned_count_text_trace_candidate_20260903.sav"
MANIFEST = ROOT / "analysis" / "ggen_advance_owned_count_text_trace_candidate_20260903.json"

EXPECTED_MAIN_SHA256 = "84bffce9627ccf99a1fa98dfe11db5a945276ab688d225c844b99881606c875d"
ROM_BASE = 0x08000000
CAVE_FILE = 0x000C5700
CAVE_LIMIT = 0x000C6800
WRAPPER_SIZE = 0x60
TRACE_BASE = 0x0203DA00
RECORD_SIZE = 0x18
TRACE_SIZE = 0x400

TARGET_NAMES = {
    0x08000CA0: "CA0",
    0x08000D10: "D10",
    0x08000FC4: "FC4",
    0x08000708: "F708",
}

CALLS = [
    # 0x0801E8D4 right-pane redraw family
    ("E8D4_CA0_E9E4", 0x0801E9E4, 0x08000CA0),
    ("E8D4_CA0_E9FA", 0x0801E9FA, 0x08000CA0),
    ("E8D4_D10_EA16", 0x0801EA16, 0x08000D10),
    ("E8D4_D10_EA3C", 0x0801EA3C, 0x08000D10),
    ("E8D4_D10_EA54", 0x0801EA54, 0x08000D10),
    ("E8D4_D10_EA80", 0x0801EA80, 0x08000D10),
    ("E8D4_D10_EAB0", 0x0801EAB0, 0x08000D10),
    ("E8D4_D10_EAE2", 0x0801EAE2, 0x08000D10),
    # 0x0806CFC4 current D350 screen composition family
    ("CFC4_CA0_D0C2", 0x0806D0C2, 0x08000CA0),
    ("CFC4_D10_D0D4", 0x0806D0D4, 0x08000D10),
    ("CFC4_D10_D0FE", 0x0806D0FE, 0x08000D10),
    ("CFC4_D10_D118", 0x0806D118, 0x08000D10),
    ("CFC4_D10_D132", 0x0806D132, 0x08000D10),
    ("CFC4_D10_D14C", 0x0806D14C, 0x08000D10),
    ("CFC4_D10_D162", 0x0806D162, 0x08000D10),
    ("CFC4_D10_D172", 0x0806D172, 0x08000D10),
    ("CFC4_D10_D190", 0x0806D190, 0x08000D10),
    ("CFC4_D10_D1AA", 0x0806D1AA, 0x08000D10),
    ("CFC4_CA0_D1E2", 0x0806D1E2, 0x08000CA0),
    ("CFC4_CA0_D22A", 0x0806D22A, 0x08000CA0),
    ("CFC4_D10_D244", 0x0806D244, 0x08000D10),
    ("CFC4_CA0_D25C", 0x0806D25C, 0x08000CA0),
    # 0x0806DE80 auxiliary status-number family
    ("DE80_FC4_DEEA", 0x0806DEEA, 0x08000FC4),
    ("DE80_FC4_DF2A", 0x0806DF2A, 0x08000FC4),
    ("DE80_F708_DF6A", 0x0806DF6A, 0x08000708),
    ("DE80_F708_DFA8", 0x0806DFA8, 0x08000708),
    # 0x0806C10C sibling split/list/detail renderer
    ("C10C_CA0_C26E", 0x0806C26E, 0x08000CA0),
    ("C10C_D10_C288", 0x0806C288, 0x08000D10),
    ("C10C_CA0_C2A6", 0x0806C2A6, 0x08000CA0),
    ("C10C_D10_C2CC", 0x0806C2CC, 0x08000D10),
    ("C10C_D10_C2E4", 0x0806C2E4, 0x08000D10),
    ("C10C_D10_C2FC", 0x0806C2FC, 0x08000D10),
    ("C10C_D10_C314", 0x0806C314, 0x08000D10),
    ("C10C_D10_C32A", 0x0806C32A, 0x08000D10),
    ("C10C_D10_C33E", 0x0806C33E, 0x08000D10),
    ("C10C_D10_C35A", 0x0806C35A, 0x08000D10),
    ("C10C_D10_C372", 0x0806C372, 0x08000D10),
    ("C10C_CA0_C3EA", 0x0806C3EA, 0x08000CA0),
    ("C10C_D10_C404", 0x0806C404, 0x08000D10),
    ("C10C_CA0_C454", 0x0806C454, 0x08000CA0),
]


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
    offset = target - (address + 4)
    gate(offset % 2 == 0, "BL displacement misaligned")
    imm = offset >> 1
    gate(-0x400000 <= imm < 0x400000, f"BL out of range 0x{address:08X}->0x{target:08X}")
    s = (imm >> 21) & 1
    return struct.pack("<HH", 0xF000 | (s << 10) | ((imm >> 11) & 0x3FF), 0xF800 | (imm & 0x7FF))


def str_word_imm(rd: int, rn: int, byte_off: int) -> int:
    gate(byte_off % 4 == 0 and 0 <= byte_off <= 124, "STR immediate out of range")
    return 0x6000 | ((byte_off // 4) << 6) | (rn << 3) | rd


def build_wrapper(base: int, record: int, target: int) -> bytes:
    """96-byte wrapper preserving r0-r4, return registers/flags and 8 stack args."""
    gate(base % 4 == 0 and record % 4 == 0, "wrapper/record alignment drift")
    out = bytearray()
    h = lambda x: out.extend(struct.pack("<H", x))
    h(0xB51F)  # push {r0-r4,lr}; original caller stack args start at sp+24
    h(0x4816)  # ldr r0,[pc,#0x58] -> record literal at +0x5C
    h(0x6801); h(0x3101); h(0x6001)  # ++record.count
    h(0x9901); h(str_word_imm(1, 0, 4))   # original r1 / x
    h(0x9902); h(str_word_imm(1, 0, 8))   # original r2 / y
    h(0x9903); h(str_word_imm(1, 0, 12))  # original r3 / text-format pointer
    h(0x9906); h(str_word_imm(1, 0, 16))  # caller stack0
    h(0x9907); h(str_word_imm(1, 0, 20))  # caller stack1
    h(0xB088)  # sub sp,#32
    # Recreate eight caller stack arguments.  This is deliberately wider than
    # the visible two recorded words because formatted-text helpers may consume
    # additional varargs depending on the control stream in r3.
    for i in range(8):
        h(0x9800 | (14 + i))
        h(0x9000 | i)
    # Restore original register arguments from saved frame (now +32 shifted).
    h(0x9808); h(0x9909); h(0x9A0A); h(0x9B0B)
    out.extend(encode_thumb_bl(base + len(out), target))
    h(0xB008)  # remove copied 8 stack args (32 bytes)
    h(0xB004)  # discard saved r0-r3, leaving saved r4/lr
    h(0xBD10)  # pop {r4,pc}; r0-r3 and flags are original renderer returns
    gate(len(out) <= 0x5C, f"wrapper code too large: {len(out)}")
    out.extend(b"\x00" * (0x5C - len(out)))
    out.extend(struct.pack("<I", record))
    gate(len(out) == WRAPPER_SIZE, f"wrapper size drift: {len(out)}")
    return bytes(out)


def parse_state_ewram(path: Path) -> bytes:
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
    state, _chunks = sf.parse_png_state(path)
    return state[0x21000:0x61000]


def main() -> int:
    parent = ROM.read_bytes()
    gate(sha256(parent) == EXPECTED_MAIN_SHA256, "current main hash drift")
    gate(STATE.exists() and SAV.exists(), "baseline state/SAV missing")
    gate(len(CALLS) * RECORD_SIZE <= TRACE_SIZE, "trace record region overflow")
    gate(all(b == 0 for b in parent[CAVE_FILE:CAVE_LIMIT]), "wrapper cave is not zero-filled")

    ewram = parse_state_ewram(STATE)
    trace_off = TRACE_BASE - 0x02000000
    gate(all(b == 0 for b in ewram[trace_off:trace_off + TRACE_SIZE]), "trace EWRAM is nonzero in baseline state")
    refs = []
    for off in range(0, len(parent) - 3, 4):
        value = u32(parent, off)
        if TRACE_BASE <= value < TRACE_BASE + TRACE_SIZE:
            refs.append((off, value))
    gate(not refs, f"aligned ROM refs into trace region: {refs[:8]}")

    child = bytearray(parent)
    cursor = CAVE_FILE
    rows = []
    for index, (name, site, expected) in enumerate(CALLS):
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
            "renderer": TARGET_NAMES[expected],
            "callsite": f"0x{site:08X}",
            "original_target": f"0x{expected:08X}",
            "record": f"0x{record:08X}",
            "wrapper": f"0x{wrapper:08X}",
        })
        cursor += WRAPPER_SIZE

    gate(cursor <= CAVE_LIMIT, f"wrapper cursor overflow 0x{cursor:08X}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(child)
    shutil.copyfile(SAV, OUT_SAV)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_text_trace_candidate_20260903",
        "result": "PASS",
        "source_sha256": sha256(parent),
        "output": {"path": str(OUT_ROM.relative_to(ROOT)), "sha256": sha256(child)},
        "sav": {"path": str(OUT_SAV.relative_to(ROOT)), "sha256": sha256(OUT_SAV.read_bytes()), "byte_exact": OUT_SAV.read_bytes() == SAV.read_bytes()},
        "trace": {"base": f"0x{TRACE_BASE:08X}", "record_size": RECORD_SIZE, "size": TRACE_SIZE, "fields": ["count", "r1_x", "r2_y", "r3_text_or_format", "stack0", "stack1"]},
        "calls": rows,
        "evidence": {
            "live_owned_label": "native 12x12 所有数 face matches at x=177..212/y=74..85; interior Dice 0.99315",
            "purpose": "identify the executing text front-end/callsite and its actual source pointer without another guessed VRAM overwrite"
        },
        "verification": {
            "result": "PASS",
            "main_tip_not_modified": True,
            "baseline_trace_zero": True,
            "trace_region_no_aligned_rom_refs": True,
            "all_original_call_targets_verified": True,
            "wrapper_cave_zero_before_build": True,
            "runtime_measurement": "pending: fresh boot with copied SAV, enter the same unit list and save one stable ss1"
        }
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result":"PASS","rom":str(OUT_ROM),"sha256":sha256(child),"sav":str(OUT_SAV),"manifest":str(MANIFEST),"calls":len(rows),"cave_end":f"0x{ROM_BASE+cursor:08X}"},ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
