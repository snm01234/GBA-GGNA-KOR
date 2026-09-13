#!/usr/bin/env python3
"""Build several isolated A/B candidates for unit-list 所有数 -> 보유수.

All variants are rebased on the *current* canonical main TIP and also carry the
user-runtime-approved unit-list 持 -> 지 pointer redirect.  The main TIP itself
is never modified.

Candidates deliberately exercise different ownership hypotheses:
  A. patch only the active relocated 12x12 font slots (0x09000000 font),
  B. patch only the original/native 12x12 font slots (0x0808AC40 font),
  C. patch both font copies,
  D. post-overlay the measured Korean BG2 tiles after the two 0x0801E8D4
     unit-list/right-pane callsites,
  E. post-overlay after the two 0x0806D350 transfer calls (0x0806D384/D398).

The font-slot variants are diagnostic by design: replacing 所/有/数 slots is
not suitable for promotion until other consumers are audited.  They are useful
for proving which 12x12 font copy the live renderer consumes.
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
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_ko_poc as fontops
import build_ggen_advance_situation_menu_ko_poc as situation
import build_ggen_advance_ss1_four_graphics_ko_candidate_20260903 as old_ss1
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sortpatch
import build_ggen_advance_unit_list_finalizer_candidates_20260903 as old_finalizer
import build_ggen_advance_unified_rom_poc as unified
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

ROM_BASE = 0x08000000
CURRENT_MAIN_SHA256 = "2afa997b78d634150299143bf8d0ba74bea3d42172653a81e024287404184120"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
PRIOR_OWNED_CANDIDATE = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_unit_list_finalizer" / "ggen_advance_unit_list_owned_count_finalizer_candidate_20260903.gba"
PRIOR_OWNED_PAYLOAD_FILE = 0x01F23400
PRIOR_OWNED_PAYLOAD_BYTES = 384

OUT_ROOT = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_owned_count_ab"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_ab_candidates_20260903.json"

# Runtime-approved 持 owner redirects, user-confirmed on the prior main.
HOLD_REFS = {
    0x080752E8: 0x08C43954,
    0x08075450: 0x08C43954,
    0x080758EC: 0x08C439A8,
    0x08075A54: 0x08C439A8,
}
HOLD_OLD = {
    0x080752E8: 0x08C490B8,
    0x08075450: 0x08C490B8,
    0x080758EC: 0x08C4910C,
    0x08075A54: 0x08C4910C,
}

JP_SLOTS = {"所": 0x03C1, "有": 0x0685, "数": 0x0427}
KO_BY_JP = {"所": "보", "有": "유", "数": "수"}
NATIVE_FONT_FILE = fontops.FONT_12X12_BASE
FONT_STRIDE = fontops.FONT_12X12_STRIDE
FONT_SIZE = fontops.FONT_12X12_COUNT * FONT_STRIDE

# Overlay code/data allocations are private and zero in the current main.
WRAPPER_FILE = 0x000C5700
WRAPPER_ADDR = ROM_BASE + WRAPPER_FILE
WRAPPER_LIMIT = 0x000C5800
TABLE_FILE = 0x01F24000
TABLE_ADDR = ROM_BASE + TABLE_FILE
PAYLOAD_FILE = 0x01F24100
PAYLOAD_ADDR = ROM_BASE + PAYLOAD_FILE
ALLOC_END = 0x01F24400

E8D4_SITES = [0x0801F54C, 0x0801F73E]
E8D4_TARGET = 0x0801E8D4
D350_TRANSFER_SITES = [0x0806D384, 0x0806D398]
TRANSFER_TARGET = 0x08063194


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
    gate((address | target) & 1 == 0, "Thumb BL alignment drift")
    offset = target - (address + 4)
    gate(offset % 2 == 0, "Thumb BL displacement misaligned")
    imm = offset >> 1
    gate(-0x400000 <= imm < 0x400000, f"Thumb BL out of range 0x{address:08X}->0x{target:08X}")
    s = (imm >> 21) & 1
    imm10 = (imm >> 11) & 0x3FF
    imm11 = imm & 0x7FF
    return struct.pack("<HH", 0xF000 | (s << 10) | imm10, 0xF800 | imm11)


def pack_bool_image(image) -> bytes:
    # fontpair.render_12x12_basic returns a 12x12 PIL image.
    return fontops.pack_12x12(image)


def apply_hold_fix(data: bytearray) -> None:
    for address, expected in HOLD_OLD.items():
        off = address - ROM_BASE
        gate(u32(data, off) == expected, f"current main hold literal drift @0x{address:08X}")
        struct.pack_into("<I", data, off, HOLD_REFS[address])


def build_font_glyphs() -> dict[str, bytes]:
    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
        out = {}
        for jp_char, ko_char in KO_BY_JP.items():
            image = fontpair.render_12x12_basic(ko_char, font)
            raw = pack_bool_image(image)
            gate(len(raw) == FONT_STRIDE and any(raw), f"blank/invalid glyph {ko_char}")
            out[jp_char] = raw
        return out


def patch_font_slots(data: bytearray, base: int, glyphs: dict[str, bytes]) -> list[dict[str, Any]]:
    rows = []
    for jp_char, slot in JP_SLOTS.items():
        off = base + slot * FONT_STRIDE
        before = bytes(data[off : off + FONT_STRIDE])
        data[off : off + FONT_STRIDE] = glyphs[jp_char]
        rows.append({
            "source_char": jp_char,
            "replacement_char": KO_BY_JP[jp_char],
            "slot": f"0x{slot:04X}",
            "file_offset": f"0x{off:08X}",
            "before_sha256": sha256(before),
            "after_sha256": sha256(glyphs[jp_char]),
        })
    return rows


class Thumb:
    def __init__(self, base: int) -> None:
        self.base = base
        self.ops: list[tuple[str, Any]] = []

    def label(self, name: str) -> None: self.ops.append(("label", name))
    def h(self, value: int) -> None: self.ops.append(("h", value & 0xFFFF))
    def bl_abs(self, target: int) -> None: self.ops.append(("bl_abs", target))
    def b(self, name: str, cond: int | None = None) -> None: self.ops.append(("b", (name, cond)))
    def ldr_pc(self, rt: int, name: str) -> None: self.ops.append(("ldr_pc", (rt, name)))
    def align4(self) -> None: self.ops.append(("align4", None))
    def word(self, name: str, value: int) -> None: self.ops.append(("word", (name, value & 0xFFFFFFFF)))

    def build(self) -> bytes:
        labels: dict[str, int] = {}
        for _ in range(3):
            addr = self.base
            labels.clear()
            for kind, payload in self.ops:
                if kind == "label": labels[payload] = addr; continue
                if kind == "align4":
                    if addr & 3: addr += 2
                    continue
                if kind == "word":
                    if addr & 3: addr += 2
                    labels[payload[0]] = addr; addr += 4; continue
                addr += 4 if kind == "bl_abs" else 2
        out = bytearray(); addr = self.base
        for kind, payload in self.ops:
            if kind == "label": continue
            if kind == "align4":
                if addr & 3: out.extend(struct.pack("<H", 0x46C0)); addr += 2
                continue
            if kind == "word":
                if addr & 3: out.extend(struct.pack("<H", 0x46C0)); addr += 2
                out.extend(struct.pack("<I", payload[1])); addr += 4; continue
            if kind == "h": out.extend(struct.pack("<H", payload)); addr += 2; continue
            if kind == "bl_abs": out.extend(encode_thumb_bl(addr, int(payload))); addr += 4; continue
            if kind == "b":
                name, cond = payload; target = labels[name]; delta = target - (addr + 4)
                gate(delta % 2 == 0, "Thumb branch misaligned"); imm = delta >> 1
                if cond is None:
                    gate(-1024 <= imm < 1024, "Thumb B out of range"); half = 0xE000 | (imm & 0x7FF)
                else:
                    gate(-128 <= imm < 128, "Thumb Bcond out of range"); half = 0xD000 | (cond << 8) | (imm & 0xFF)
                out.extend(struct.pack("<H", half)); addr += 2; continue
            if kind == "ldr_pc":
                rt, name = payload; target = labels[name]; pc = (addr + 4) & ~3; delta = target - pc
                gate(delta % 4 == 0 and 0 <= delta <= 1020, f"LDR literal out of range {name}")
                out.extend(struct.pack("<H", 0x4800 | (rt << 8) | (delta // 4))); addr += 2; continue
            raise AssertionError(kind)
        return bytes(out)


def build_overlay_wrapper(original_target: int) -> bytes:
    t = Thumb(WRAPPER_ADDR)
    t.h(0xB510)                  # push {r4,lr}
    t.bl_abs(original_target)    # original function
    t.h(0xB401)                  # push {r0} preserve return
    t.ldr_pc(4, "table")         # r4 = copy table
    t.label("table_loop")
    t.h(0x6820)                  # ldr r0,[r4,#0] dest
    t.h(0x2800)                  # cmp r0,#0
    t.b("done", 0x0)            # beq
    t.h(0x6861)                  # ldr r1,[r4,#4] src
    t.h(0x68A2)                  # ldr r2,[r4,#8] words
    t.label("copy_loop")
    t.h(0x680B)                  # ldr r3,[r1]
    t.h(0x6003)                  # str r3,[r0]
    t.h(0x3104)                  # adds r1,#4
    t.h(0x3004)                  # adds r0,#4
    t.h(0x3A01)                  # subs r2,#1
    t.b("copy_loop", 0x1)       # bne
    t.h(0x340C)                  # adds r4,#12
    t.b("table_loop")
    t.label("done")
    t.h(0xBC01)                  # pop {r0}
    t.h(0xBC10)                  # pop {r4}
    t.h(0xBC02)                  # pop {r1}=saved lr
    t.h(0x4708)                  # bx r1
    t.align4()
    t.word("table", TABLE_ADDR)
    blob = t.build()
    gate(len(blob) <= WRAPPER_LIMIT - WRAPPER_FILE, "overlay wrapper overflow")
    return blob


def make_copy_table(runs: list[tuple[int, bytes, list[int]]]) -> tuple[bytes, bytes, list[dict[str, Any]]]:
    table = bytearray(); payload = bytearray(); rows = []
    cursor = 0
    for dest, raw, tiles in runs:
        src = PAYLOAD_ADDR + cursor
        words = len(raw) // 4
        gate(len(raw) % 4 == 0 and words, "invalid overlay run")
        table.extend(struct.pack("<III", dest, src, words))
        payload.extend(raw)
        rows.append({"destination": f"0x{dest:08X}", "source": f"0x{src:08X}", "bytes": len(raw), "tiles": [f"0x{x:03X}" for x in tiles]})
        cursor += len(raw)
    table.extend(b"\0" * 12)
    gate(TABLE_FILE + len(table) <= PAYLOAD_FILE, "copy table overflow")
    gate(PAYLOAD_FILE + len(payload) <= ALLOC_END, "overlay payload overflow")
    return bytes(table), bytes(payload), rows


def changed_ranges(parent: bytes, child: bytes) -> list[list[str]]:
    pos = [i for i, (a, b) in enumerate(zip(parent, child)) if a != b]
    if not pos: return []
    rows = []; start = prev = pos[0]
    for p in pos[1:]:
        if p != prev + 1:
            rows.append([f"0x{start:08X}", f"0x{prev + 1:08X}"]); start = p
        prev = p
    rows.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return rows


def emit(name: str, parent: bytes, child: bytearray, details: dict[str, Any]) -> dict[str, Any]:
    out_rom = OUT_ROOT / f"ggen_advance_owned_count_{name}_candidate_20260903.gba"
    out_sav = OUT_ROOT / f"ggen_advance_owned_count_{name}_candidate_20260903.sav"
    out_rom.parent.mkdir(parents=True, exist_ok=True)
    output = bytes(child)
    out_rom.write_bytes(output)
    shutil.copy2(MAIN_SAV, out_sav)
    gate(out_sav.read_bytes() == MAIN_SAV.read_bytes(), f"SAV copy drift {name}")
    changed = sum(a != b for a, b in zip(parent, output))
    return {
        "name": name,
        "rom": advance_relative(out_rom),
        "sha256": sha256(output),
        "sav": advance_relative(out_sav),
        "changed_bytes_vs_current_main": changed,
        "changed_ranges": changed_ranges(parent, output),
        "details": details,
        "status": "AB_test_candidate_main_tip_not_promoted",
    }


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == CURRENT_MAIN_SHA256, f"current main changed: {sha256(parent)}")
    gate(main_manifest.get("sha256") == CURRENT_MAIN_SHA256, "main manifest hash drift")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "JP ROM hash drift")
    gate(MAIN_SAV.is_file() and STATE.is_file(), "SAV/state input missing")

    active_addr, active_font_file = situation.active_font12_location(parent)
    gate(active_addr == 0x09000000, f"active font address drift 0x{active_addr:08X}")
    gate(active_font_file != NATIVE_FONT_FILE, "active/native font unexpectedly identical location")
    gate(active_font_file + FONT_SIZE <= len(parent), "active font overrun")

    # The three Japanese slots are currently byte-identical in native + active
    # font copies.  That makes A/B interpretation straightforward.
    for slot in JP_SLOTS.values():
        a = parent[active_font_file + slot * FONT_STRIDE : active_font_file + (slot + 1) * FONT_STRIDE]
        n = parent[NATIVE_FONT_FILE + slot * FONT_STRIDE : NATIVE_FONT_FILE + (slot + 1) * FONT_STRIDE]
        gate(a == n, f"active/native Japanese slot already diverged 0x{slot:04X}")

    glyphs = build_font_glyphs()

    # Reuse the exact 384-byte Galmuri11 `보유수` payload produced by the prior
    # static-PASS finalizer candidate.  The user's later runtime result rejected
    # only that candidate's hook boundary, not the raster itself.  The current
    # root ss1 may now belong to a different newly-promoted main, so rebuilding
    # the raster from that mutable state would be less deterministic.
    gate(PRIOR_OWNED_CANDIDATE.is_file(), "prior owned-count payload candidate missing")
    prior_owned = PRIOR_OWNED_CANDIDATE.read_bytes()
    payload_blob = prior_owned[PRIOR_OWNED_PAYLOAD_FILE : PRIOR_OWNED_PAYLOAD_FILE + PRIOR_OWNED_PAYLOAD_BYTES]
    gate(len(payload_blob) == PRIOR_OWNED_PAYLOAD_BYTES and any(payload_blob), "prior owned-count payload missing/blank")
    run_specs = [
        (0x06009BA0, payload_blob[0x000:0x0A0], [0x0DD, 0x0DE, 0x0DF, 0x0E0, 0x0E1]),
        (0x06009C80, payload_blob[0x0A0:0x140], [0x0E4, 0x0E5, 0x0E6, 0x0E7, 0x0E8]),
        (0x0600A100, payload_blob[0x140:0x160], [0x108]),
        (0x0600A1A0, payload_blob[0x160:0x180], [0x10D]),
    ]
    gate(sum(len(raw) for _dest, raw, _ids in run_specs) == 384, "owned run split drift")
    table_blob, payload_blob2, table_rows = make_copy_table(run_specs)
    gate(payload_blob == payload_blob2, "owned payload table reconstruction drift")
    payload_report = {
        "translation": {"所有数": "보유수"},
        "source": advance_relative(PRIOR_OWNED_CANDIDATE),
        "source_file_offset": f"0x{PRIOR_OWNED_PAYLOAD_FILE:08X}",
        "payload_bytes": len(payload_blob),
        "font": "Galmuri11.bdf native 12x12",
        "face_index": 10,
        "contour_index": 5,
        "note": "prior visual payload reused byte-exact; only hook/ownership hypotheses differ",
    }

    # Current main private allocations used by the overlay candidates must be clean.
    gate(all(v == 0 for v in parent[WRAPPER_FILE:WRAPPER_LIMIT]), "wrapper cave occupied in current main")
    gate(all(v == 0 for v in parent[TABLE_FILE:ALLOC_END]), "overlay data allocation occupied in current main")

    results: dict[str, Any] = {}

    def base_with_hold() -> bytearray:
        d = bytearray(parent); apply_hold_fix(d); return d

    # A: active relocated font only.
    a = base_with_hold()
    a_rows = patch_font_slots(a, active_font_file, glyphs)
    results["A_active_font"] = emit("A_active_font", parent, a, {
        "hypothesis": "live 所有数 consumes active relocated 12x12 font at 0x09000000",
        "font_address": f"0x{active_addr:08X}", "font_file": f"0x{active_font_file:08X}", "slot_patches": a_rows,
        "promotion_safe": False, "reason": "global JP slot substitution diagnostic",
    })

    # B: original native font only.
    b = base_with_hold()
    b_rows = patch_font_slots(b, NATIVE_FONT_FILE, glyphs)
    results["B_native_font"] = emit("B_native_font", parent, b, {
        "hypothesis": "live 所有数 still consumes original 0x0808AC40 12x12 font copy",
        "font_address": f"0x{ROM_BASE + NATIVE_FONT_FILE:08X}", "font_file": f"0x{NATIVE_FONT_FILE:08X}", "slot_patches": b_rows,
        "promotion_safe": False, "reason": "global JP slot substitution diagnostic",
    })

    # C: both copies.
    c = base_with_hold()
    c_rows = patch_font_slots(c, active_font_file, glyphs) + patch_font_slots(c, NATIVE_FONT_FILE, glyphs)
    results["C_both_fonts"] = emit("C_both_fonts", parent, c, {
        "hypothesis": "renderer may select/copy either 12x12 font copy depending on setup path",
        "slot_patches": c_rows, "promotion_safe": False, "reason": "global JP slot substitution diagnostic",
    })

    # D: actual unit-list/right-pane redraw callsites -> post overlay.
    d = base_with_hold(); wrapper_d = build_overlay_wrapper(E8D4_TARGET)
    d[WRAPPER_FILE:WRAPPER_FILE + len(wrapper_d)] = wrapper_d
    d[TABLE_FILE:TABLE_FILE + len(table_blob)] = table_blob
    d[PAYLOAD_FILE:PAYLOAD_FILE + len(payload_blob)] = payload_blob
    for site in E8D4_SITES:
        gate(thumb_bl_target(parent, site) == E8D4_TARGET, f"E8D4 callsite drift 0x{site:08X}")
        d[site - ROM_BASE:site - ROM_BASE + 4] = encode_thumb_bl(site, WRAPPER_ADDR)
    results["D_post_E8D4"] = emit("D_post_E8D4", parent, d, {
        "hypothesis": "所有数 belongs to/right after 0x0801E8D4 right-pane redraw",
        "hook_callsites": [f"0x{x:08X}" for x in E8D4_SITES], "original_target": f"0x{E8D4_TARGET:08X}",
        "copy_runs": table_rows, "payload": payload_report, "promotion_safe": False,
    })

    # E: D350 setup transfer(s) -> post overlay.  This tests the measured D6xx
    # controller/queue boundary independently from E8D4.
    e = base_with_hold(); wrapper_e = build_overlay_wrapper(TRANSFER_TARGET)
    e[WRAPPER_FILE:WRAPPER_FILE + len(wrapper_e)] = wrapper_e
    e[TABLE_FILE:TABLE_FILE + len(table_blob)] = table_blob
    e[PAYLOAD_FILE:PAYLOAD_FILE + len(payload_blob)] = payload_blob
    for site in D350_TRANSFER_SITES:
        gate(thumb_bl_target(parent, site) == TRANSFER_TARGET, f"D350 transfer call drift 0x{site:08X}")
        e[site - ROM_BASE:site - ROM_BASE + 4] = encode_thumb_bl(site, WRAPPER_ADDR)
    results["E_post_D350_transfer"] = emit("E_post_D350_transfer", parent, e, {
        "hypothesis": "所有数 is finalized by the D350/CFC4 queued transfer cycle",
        "hook_callsites": [f"0x{x:08X}" for x in D350_TRANSFER_SITES], "original_target": f"0x{TRANSFER_TARGET:08X}",
        "copy_runs": table_rows, "payload": payload_report, "promotion_safe": False,
    })

    # Static verification of common hold redirect and candidate-specific effects.
    for key, row in results.items():
        data = (ADVANCE_ROOT / row["rom"]).read_bytes()
        for site, target in HOLD_REFS.items():
            gate(u32(data, site - ROM_BASE) == target, f"{key}: hold redirect missing @0x{site:08X}")
    for key in ("D_post_E8D4", "E_post_D350_transfer"):
        data = (ADVANCE_ROOT / results[key]["rom"]).read_bytes()
        sites = E8D4_SITES if key == "D_post_E8D4" else D350_TRANSFER_SITES
        for site in sites:
            gate(thumb_bl_target(data, site) == WRAPPER_ADDR, f"{key}: wrapper BL drift @0x{site:08X}")

    compile_result = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__))], cwd=ADVANCE_ROOT, capture_output=True, text=True)
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_ab_candidates_20260903",
        "result": "PASS",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent),
            "promotion_reason": main_manifest.get("promotion_reason"),
            "active_12x12_font_address": f"0x{active_addr:08X}", "active_12x12_font_file": f"0x{active_font_file:08X}",
            "native_12x12_font_file": f"0x{NATIVE_FONT_FILE:08X}",
        },
        "common_to_all_candidates": {
            "hold_fix": "user-runtime-approved 持 -> 지 duplicate-owner pointer redirect",
            "hold_refs": {f"0x{k:08X}": f"0x{v:08X}" for k, v in HOLD_REFS.items()},
            "owned_translation": "所有数 -> 보유수",
        },
        "candidates": results,
        "recommended_test_order": ["A_active_font", "B_native_font", "C_both_fonts", "D_post_E8D4", "E_post_D350_transfer"],
        "interpretation": {
            "A_only_works": "live renderer consumes active relocated 0x09000000 font; later make a scoped source/token patch instead of global slot replacement",
            "B_only_works": "screen consumes original/native font copy unexpectedly",
            "C_only_works": "both font copies participate during setup/redraw",
            "D_works": "E8D4 is a durable post-render ownership boundary",
            "E_works": "D350/CFC4 transfer cycle is the durable ownership boundary",
            "none_work": "producer is outside these two font copies and both tested post-render boundaries; use argument-trace state next",
        },
        "verification": {"result": "PASS", "main_tip_not_modified": True, "py_compile": "PASS", "runtime_measurement": "pending user A/B verification"},
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "main": sha256(parent), "manifest": advance_relative(MANIFEST), "candidates": {k: {"rom": v["rom"], "sha256": v["sha256"], "changed_bytes": v["changed_bytes_vs_current_main"]} for k, v in results.items()}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
