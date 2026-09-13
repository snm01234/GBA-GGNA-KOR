#!/usr/bin/env python3
"""Build a non-visual execution-trace ROM for the unresolved unit-list screen.

This candidate intentionally does not alter 持/所有数 graphics.  Instead it
instruments the proven 0x0806Dxxx screen-controller family and both normal/focus
row callback tables.  Each instrumented call increments one 32-bit counter in a
small EWRAM trace area.  A later savestate can therefore prove which lifecycle,
transfer, and row-callback paths actually executed without guessing a final
VRAM hook point.

The wrappers live in a verified zero-filled ROM cave near the original code, so
all replaced Thumb BL instructions remain in range.  Each wrapper preserves the
original r0-r3 arguments, r4, LR, return registers, and post-call condition flags.
Canonical main TIP is never overwritten.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
CURRENT_MAIN_SHA256 = "0b6df278befa5b7e55cd79097ccbbc6b05dc8b3ecaf50ee6efe3391ed6569989"
MAIN_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"

OUT_ROOT = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_unit_list_execution_trace"
OUT_ROM = OUT_ROOT / "ggen_advance_unit_list_execution_trace_candidate_20260903.gba"
OUT_SAV = OUT_ROOT / "ggen_advance_unit_list_execution_trace_candidate_20260903.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_unit_list_execution_trace_candidate_20260903.json"

# Verified 0x00-filled gap: 0x080C56AC..0x080C6CAD.  The next referenced object
# starts at 0x080C6CAC, so stay comfortably below it.
CAVE_FILE = 0x000C5700
CAVE_ADDR = ROM_BASE + CAVE_FILE
CAVE_LIMIT_FILE = 0x000C6800
WRAPPER_SIZE = 0x20

# Current ss1 has a continuous zero EWRAM run from 0x0200D2B1 through the end.
# 0x0203D800..0x0203D9FF has no aligned ROM literal reference in current main.
TRACE_BASE = 0x0203D800
TRACE_SIZE = 0x200
DIRECT_BASE = TRACE_BASE + 0x10
NORMAL_BASE = TRACE_BASE + 0x80
FOCUS_BASE = TRACE_BASE + 0x100

NORMAL_TABLE_FILE = 0x00D591AC
FOCUS_TABLE_FILE = 0x00D59218
CALLBACK_COUNT = 27

# Calls proven to belong to the same screen family as the user-approved
# 0x092D0000 supply package, plus every 0x08063194 transfer call in the local
# D6xx/E6xx controller range.
DIRECT_CALLS: list[tuple[str, int, int]] = [
    ("lifecycle_D3C4_to_D458", 0x0806D3C4, 0x0806D458),
    ("lifecycle_D3CA_to_D830", 0x0806D3CA, 0x0806D830),
    ("lifecycle_D3E2_to_D580", 0x0806D3E2, 0x0806D580),
    ("lifecycle_D3E8_to_D904", 0x0806D3E8, 0x0806D904),
    ("lifecycle_D3EE_to_D67C", 0x0806D3EE, 0x0806D67C),
    ("lifecycle_D402_to_D41C", 0x0806D402, 0x0806D41C),
    ("supply_anim8_D7A0_to_63CAC", 0x0806D7A0, 0x08063CAC),
    ("unit_list_D86C_to_77818", 0x0806D86C, 0x08077818),
    ("transfer_D654", 0x0806D654, 0x08063194),
    ("transfer_D750", 0x0806D750, 0x08063194),
    ("transfer_DA60", 0x0806DA60, 0x08063194),
    ("transfer_DAEC", 0x0806DAEC, 0x08063194),
    ("transfer_DD40", 0x0806DD40, 0x08063194),
    ("transfer_E0AE", 0x0806E0AE, 0x08063194),
    ("transfer_E1BA", 0x0806E1BA, 0x08063194),
    ("transfer_E244", 0x0806E244, 0x08063194),
    ("transfer_E352", 0x0806E352, 0x08063194),
    ("transfer_E6F0", 0x0806E6F0, 0x08063194),
    ("transfer_EB3E", 0x0806EB3E, 0x08063194),
    ("transfer_EC86", 0x0806EC86, 0x08063194),
    ("transfer_ED32", 0x0806ED32, 0x08063194),
    ("transfer_EDA4", 0x0806EDA4, 0x08063194),
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
    gate(address & 1 == 0 and target & 1 == 0, "Thumb BL address alignment drift")
    offset = target - (address + 4)
    gate(offset % 2 == 0, "Thumb BL displacement misaligned")
    imm = offset >> 1
    gate(-0x400000 <= imm < 0x400000, f"Thumb BL out of range 0x{address:08X}->0x{target:08X}")
    s = (imm >> 21) & 1
    imm10 = (imm >> 11) & 0x3FF
    imm11 = imm & 0x7FF
    return struct.pack("<HH", 0xF000 | (s << 10) | imm10, 0xF800 | imm11)


def build_wrapper(base: int, counter: int, target: int) -> bytes:
    """32-byte ARMv4T wrapper preserving args/returns around an original call."""
    gate(base % 4 == 0, "wrapper base must be word aligned")
    gate(counter % 4 == 0, "counter must be word aligned")
    gate(target & 1 == 0, "direct wrapper target should be even code address")
    out = bytearray()
    out.extend(struct.pack("<H", 0xB51F))  # push {r0,r1,r2,r3,r4,lr}
    out.extend(struct.pack("<H", 0x4806))  # ldr r0,[pc,#24] -> counter literal @ +0x1C
    out.extend(struct.pack("<H", 0x6801))  # ldr r1,[r0]
    out.extend(struct.pack("<H", 0x3101))  # adds r1,#1
    out.extend(struct.pack("<H", 0x6001))  # str r1,[r0]
    out.extend(struct.pack("<H", 0x9800))  # ldr r0,[sp,#0]
    out.extend(struct.pack("<H", 0x9901))  # ldr r1,[sp,#4]
    out.extend(struct.pack("<H", 0x9A02))  # ldr r2,[sp,#8]
    out.extend(struct.pack("<H", 0x9B03))  # ldr r3,[sp,#12]
    out.extend(encode_thumb_bl(base + len(out), target))
    out.extend(struct.pack("<H", 0xB004))  # add sp,#16; leave saved r4,lr
    out.extend(struct.pack("<H", 0xBD10))  # pop {r4,pc}
    out.extend(struct.pack("<H", 0x46C0))  # word-align literal
    out.extend(struct.pack("<I", counter))
    gate(len(out) == WRAPPER_SIZE, f"wrapper size drift {len(out)}")
    return bytes(out)


def callback_values(data: bytes, table_file: int) -> list[int]:
    values = [u32(data, table_file + i * 4) for i in range(CALLBACK_COUNT)]
    for i, ptr in enumerate(values):
        gate(ptr & 1 == 1 and ROM_BASE <= (ptr & ~1) < ROM_BASE + len(data), f"callback[{i}] pointer drift 0x{ptr:08X}")
    return values


def state_ewram() -> bytes:
    state, _chunks = statefmt.parse_png_state(MAIN_STATE)
    return state[0x21000:0x61000]


def changed_ranges(parent: bytes, child: bytes) -> list[list[str]]:
    changed = [i for i, (a, b) in enumerate(zip(parent, child)) if a != b]
    if not changed:
        return []
    out: list[list[str]] = []
    start = prev = changed[0]
    for pos in changed[1:]:
        if pos != prev + 1:
            out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
            start = pos
        prev = pos
    out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return out


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    gate(sha256(parent) == CURRENT_MAIN_SHA256, "canonical main hash drift")
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(manifest.get("sha256") == CURRENT_MAIN_SHA256, "main manifest hash drift")
    gate(MAIN_SAV.is_file(), "main SAV missing")
    gate(MAIN_STATE.is_file(), "current ss1 missing")

    # Prove private allocations against both ROM and the supplied live state.
    gate(all(b == 0 for b in parent[CAVE_FILE:CAVE_LIMIT_FILE]), "ROM cave is no longer zero-filled")
    ewram = state_ewram()
    trace_off = TRACE_BASE - 0x02000000
    gate(all(b == 0 for b in ewram[trace_off:trace_off + TRACE_SIZE]), "trace EWRAM region nonzero in current ss1")
    refs = []
    for off in range(0, len(parent) - 3, 4):
        value = u32(parent, off)
        if TRACE_BASE <= value < TRACE_BASE + TRACE_SIZE:
            refs.append((off, value))
    gate(not refs, f"aligned ROM references into trace EWRAM: {refs[:8]}")

    normal = callback_values(parent, NORMAL_TABLE_FILE)
    focus = callback_values(parent, FOCUS_TABLE_FILE)
    for name, site, expected in DIRECT_CALLS:
        gate(thumb_bl_target(parent, site) == expected, f"direct call drift {name} @0x{site:08X}")

    child = bytearray(parent)
    cursor = CAVE_FILE
    wrapper_rows: list[dict[str, Any]] = []

    def allocate(kind: str, label: str, counter: int, target: int) -> int:
        nonlocal cursor
        gate(cursor % 4 == 0, "cave cursor alignment drift")
        wrapper_file = cursor
        wrapper_addr = ROM_BASE + wrapper_file
        payload = build_wrapper(wrapper_addr, counter, target & ~1)
        gate(all(b == 0 for b in child[wrapper_file:wrapper_file + len(payload)]), f"wrapper overlap at 0x{wrapper_file:08X}")
        child[wrapper_file:wrapper_file + len(payload)] = payload
        cursor += WRAPPER_SIZE
        wrapper_rows.append({
            "kind": kind,
            "label": label,
            "wrapper_file": f"0x{wrapper_file:08X}",
            "wrapper_address": f"0x{wrapper_addr:08X}",
            "counter_address": f"0x{counter:08X}",
            "original_target": f"0x{target:08X}",
        })
        return wrapper_addr

    direct_rows: list[dict[str, Any]] = []
    for index, (name, site, expected) in enumerate(DIRECT_CALLS):
        counter = DIRECT_BASE + index * 4
        wrapper = allocate("direct_call", name, counter, expected)
        child[site - ROM_BASE:site - ROM_BASE + 4] = encode_thumb_bl(site, wrapper)
        gate(thumb_bl_target(child, site) == wrapper, f"patched direct BL drift {name}")
        direct_rows.append({
            "index": index,
            "name": name,
            "callsite": f"0x{site:08X}",
            "original_target": f"0x{expected:08X}",
            "counter_address": f"0x{counter:08X}",
            "wrapper_address": f"0x{wrapper:08X}",
        })

    callback_rows: dict[str, list[dict[str, Any]]] = {"normal": [], "focus": []}
    for table_name, table_file, values, counter_base in (
        ("normal", NORMAL_TABLE_FILE, normal, NORMAL_BASE),
        ("focus", FOCUS_TABLE_FILE, focus, FOCUS_BASE),
    ):
        for index, original_ptr in enumerate(values):
            counter = counter_base + index * 4
            wrapper = allocate(f"{table_name}_callback", f"{table_name}[{index}]", counter, original_ptr)
            struct.pack_into("<I", child, table_file + index * 4, wrapper | 1)
            callback_rows[table_name].append({
                "index": index,
                "table_file": f"0x{table_file + index * 4:08X}",
                "original_pointer": f"0x{original_ptr:08X}",
                "counter_address": f"0x{counter:08X}",
                "wrapper_pointer": f"0x{wrapper | 1:08X}",
            })

    gate(cursor <= CAVE_LIMIT_FILE, f"trace wrappers overflow ROM cave: 0x{cursor:08X}")

    # Static disassembly sanity: wrappers have fixed prologue/epilogue and each
    # internal BL resolves to the requested original target.
    for row in wrapper_rows:
        off = int(row["wrapper_file"], 16)
        addr = int(row["wrapper_address"], 16)
        gate(child[off:off + 2] == bytes.fromhex("1fb5"), f"wrapper push drift {row['label']}")
        gate(child[off + 0x18:off + 0x1A] == bytes.fromhex("10bd"), f"wrapper pop drift {row['label']}")
        gate(thumb_bl_target(child, addr + 0x12) == (int(row["original_target"], 16) & ~1), f"wrapper target BL drift {row['label']}")
        gate(u32(child, off + 0x1C) == int(row["counter_address"], 16), f"wrapper counter literal drift {row['label']}")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(child)
    shutil.copyfile(MAIN_SAV, OUT_SAV)

    changed = sum(1 for a, b in zip(parent, child) if a != b)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_execution_trace_candidate_20260903",
        "result": "PASS",
        "status": "diagnostic_candidate_main_tip_not_promoted",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(parent),
            "main_tip_manifest_match": True,
            "current_state": advance_relative(MAIN_STATE),
        },
        "output": {
            "rom": advance_relative(OUT_ROM),
            "rom_sha256": sha256(child),
            "sav": advance_relative(OUT_SAV),
            "sav_sha256": sha256(OUT_SAV.read_bytes()),
            "changed_bytes": changed,
            "changed_ranges": changed_ranges(parent, child),
        },
        "trace_memory": {
            "base": f"0x{TRACE_BASE:08X}",
            "bytes": TRACE_SIZE,
            "direct_counter_base": f"0x{DIRECT_BASE:08X}",
            "normal_callback_counter_base": f"0x{NORMAL_BASE:08X}",
            "focus_callback_counter_base": f"0x{FOCUS_BASE:08X}",
            "current_ss1_region_zero": True,
            "aligned_rom_pointer_refs": 0,
        },
        "rom_cave": {
            "file_start": f"0x{CAVE_FILE:08X}",
            "address_start": f"0x{CAVE_ADDR:08X}",
            "allocation_end": f"0x{cursor:08X}",
            "limit": f"0x{CAVE_LIMIT_FILE:08X}",
            "main_was_zero": True,
            "wrapper_size": WRAPPER_SIZE,
            "wrapper_count": len(wrapper_rows),
        },
        "direct_calls": direct_rows,
        "callbacks": callback_rows,
        "wrapper_policy": {
            "visual_graphics_modified": False,
            "preserve_r0_r3_arguments": True,
            "preserve_r4": True,
            "preserve_original_return_registers": True,
            "preserve_post_original_call_flags": True,
            "armv4t_safe": True,
            "halfword_literal_trampoline_used": False,
        },
        "verification": {
            "result": "PASS",
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == CURRENT_MAIN_SHA256,
            "all_direct_original_targets_verified": True,
            "all_callback_original_targets_verified": True,
            "trace_ewram_zero_in_current_ss1": True,
            "trace_ewram_no_aligned_rom_refs": True,
            "rom_cave_zero_before_build": True,
            "all_wrapper_internal_bl_targets_verified": True,
            "sav_byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(),
            "runtime_measurement": "pending: cold boot candidate with copied SAV, enter the unit list, move focus, then capture ss1 states for counter analysis",
        },
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": str(OUT_ROM),
        "sha256": sha256(child),
        "sav": str(OUT_SAV),
        "manifest": str(MANIFEST),
        "wrappers": len(wrapper_rows),
        "cave_end": f"0x{cursor:08X}",
        "changed_bytes": changed,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
