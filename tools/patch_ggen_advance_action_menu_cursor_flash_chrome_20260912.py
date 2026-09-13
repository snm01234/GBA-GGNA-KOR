#!/usr/bin/env python3
"""Restore action-menu green chrome without bringing the 1-frame well hole back.

Do not promote this candidate.  Current main TIP stays byte-exact.

ss8 of the first 20260912 cursor-flash candidate shows only the 4x2 command
labels on BG0; the 6-wide chrome cells are 0000.  That candidate skipped the
whole frame blit when 0x0801550C's 5th argument was 0, so left-side / cursor
redraws never wrote tiles 0x2E0-0x2EC.

This follow-up:

* still does not start the cursor-path DMA3 fill of BG0 (NOP at 0x080154A4);
* restores the original 0x08015532 branch so flag 0 again selects the 6-wide
  frame resource;
* replaces only the frame ``bl 0x0800269C`` at 0x08015558 with a wrapper that
  blits every map cell except source tile id 7 when flag == 0, and tail-calls
  the original blitter when flag != 0.

Tile 7 is the transparent well.  Skipping those writes keeps the previous
labels; chrome / edges still stamp.  11-wide frames keep punching wells.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256

OUT = ROOT / "outputs" / "20260912_ggen_advance_action_menu_cursor_flash"
WORK = OUT / "ggen_advance_action_menu_cursor_flash_chrome_followup_20260912.gba"
MANIFEST = OUT / "manifest_chrome_followup.json"
FIRST_CANDIDATE = OUT / "ggen_advance_action_menu_cursor_flash_candidate_20260912.gba"
FIRST_SS8 = OUT / "ggen_advance_action_menu_cursor_flash_candidate_20260912.ss8"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"

ROM_BASE = 0x08000000
THUMB_NOP = bytes((0xC0, 0x46))
DMA_ENABLE = 0x000154A4
DMA_OLD = bytes((0x91, 0x60))
BEQ_FRAME = 0x00015532
BEQ_OLD = bytes((0x00, 0xD0))
FRAME_BLIT = 0x08015558
ORIG_BLIT = 0x0800269C
CELL_WRITE = 0x08001984

# Unused tail of the 0x080C5700 overlay reservation (payload ends 0x080C5B40,
# cave end 0x080C6800).  In-range of the 0x08015558 Thumb BL.
STUB_FILE = 0x000C6700
STUB_ADDR = ROM_BASE + STUB_FILE
STUB_LIMIT = 0x000C6800

BEQ = 0
BGE = 0xA


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


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


def b_imm11(address: int, target: int) -> bytes:
    off = (target - (address + 4)) >> 1
    gate(-1024 <= off < 1024, f"B out of range 0x{address:08X}->0x{target:08X}")
    return struct.pack("<H", 0xE000 | (off & 0x7FF))


def bcond(cond: int, address: int, target: int) -> bytes:
    off = (target - (address + 4)) >> 1
    gate(-128 <= off < 128, f"Bcond out of range 0x{address:08X}->0x{target:08X}")
    return struct.pack("<H", 0xD000 | (cond << 8) | (off & 0xFF))


def compose_cell(cell: int, tile_base: int = 0x2E0, pal: int = 0xB) -> int:
    """Match 0x0800269C's screen-entry mix for clip == 0."""
    tile = (cell + tile_base) & 0x03FF
    flip = cell & 0x0C00
    pal_bits = (cell + ((pal << 28) >> 16)) & 0xF000
    return (tile | flip | pal_bits) & 0xFFFF


class Asm:
    def __init__(self, base: int) -> None:
        self.base = base
        self.buf = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str, str]] = []

    def addr(self) -> int:
        return self.base + len(self.buf)

    def label(self, name: str) -> None:
        self.labels[name] = self.addr()

    def h(self, *halfs: int) -> None:
        for value in halfs:
            self.buf.extend(struct.pack("<H", value & 0xFFFF))

    def bl(self, target: int) -> None:
        self.buf.extend(encode_thumb_bl(self.addr(), target))

    def b(self, name: str) -> None:
        self.fixups.append((len(self.buf), "b", name))
        self.buf.extend(b"\x00\x00")

    def bcc(self, cond: int, name: str) -> None:
        self.fixups.append((len(self.buf), f"c{cond}", name))
        self.buf.extend(b"\x00\x00")

    def align4(self) -> None:
        if len(self.buf) & 2:
            self.h(0x46C0)

    def word(self, value: int) -> None:
        self.align4()
        self.buf.extend(struct.pack("<I", value & 0xFFFFFFFF))

    def patch(self) -> bytes:
        for off, kind, name in self.fixups:
            target = self.labels[name]
            addr = self.base + off
            if kind == "b":
                blob = b_imm11(addr, target)
            else:
                blob = bcond(int(kind[1:]), addr, target)
            self.buf[off : off + 2] = blob
        return bytes(self.buf)


def assemble_stub(base: int) -> bytes:
    """Flag-aware frame blit: skip source tile 7 when 5th arg == 0."""
    a = Asm(base)
    a.label("entry")
    a.h(0xB410)  # push {r4}
    a.h(0x9C06)  # ldr r4, [sp, #0x18]  ; 1550C flag at +0x14, plus saved r4
    a.h(0x2C00)  # cmp r4, #0
    a.bcc(BEQ, "skip7")
    a.h(0xBC10)  # pop {r4}
    a.h(0xB410)  # push {r4}
    a.h(0x4C00)  # ldr r4, [pc, #0]  ; patched below to the 269C literal
    lit_ldr = len(a.buf) - 2
    a.h(0x46A4)  # mov ip, r4
    a.h(0xBC10)  # pop {r4}
    a.h(0x4760)  # bx ip
    a.align4()
    a.label("lit_269c")
    a.word(ORIG_BLIT | 1)
    lit_off = a.labels["lit_269c"]
    ldr_addr = base + lit_ldr
    pc = (ldr_addr + 4) & ~3
    imm = lit_off - pc
    gate(imm >= 0 and imm % 4 == 0 and imm < 1024, f"269C literal unencodable imm={imm}")
    struct.pack_into("<H", a.buf, lit_ldr, 0x4C00 | (imm // 4))

    a.label("skip7")
    a.h(0xBC10)  # pop {r4}  ; restore table pointer
    a.h(0xB5F0)  # push {r4, r5, r6, r7, lr}
    a.h(0xB083)  # sub sp, #12
    a.h(0x9000)  # str r0, [sp]       dest
    a.h(0x9101)  # str r1, [sp, #4]   x
    a.h(0x9202)  # str r2, [sp, #8]   y
    a.h(0x781E)  # ldrb r6, [r3]      width
    a.h(0x785F)  # ldrb r7, [r3, #1]  height
    a.h(0x1D1C)  # adds r4, r3, #4    cells
    a.h(0x2500)  # movs r5, #0        row
    a.label("row")
    a.h(0x42BD)  # cmp r5, r7
    a.bcc(BGE, "done")
    a.h(0x2300)  # movs r3, #0        col
    a.label("col")
    a.h(0x42B3)  # cmp r3, r6
    a.bcc(BGE, "nextrow")
    a.h(0x8821)  # ldrh r1, [r4]
    a.h(0x3402)  # adds r4, #2
    a.h(0x1C08)  # adds r0, r1, #0
    a.h(0x0580)  # lsls r0, r0, #22
    a.h(0x0D80)  # lsrs r0, r0, #22
    a.h(0x2807)  # cmp r0, #7
    a.bcc(BEQ, "nextcol")
    a.h(0x9A09)  # ldr r2, [sp, #0x24]  tile_base
    a.h(0x188A)  # adds r2, r1, r2
    a.h(0x2001)  # movs r0, #1
    a.h(0x0280)  # lsls r0, r0, #10
    a.h(0x3801)  # subs r0, #1          0x03FF
    a.h(0x4002)  # ands r2, r0
    a.h(0x20C0)  # movs r0, #0xC0
    a.h(0x0100)  # lsls r0, r0, #4      0x0C00
    a.h(0x4008)  # ands r0, r1
    a.h(0x4302)  # orrs r2, r0
    a.h(0x980A)  # ldr r0, [sp, #0x28]  pal
    a.h(0x0700)  # lsls r0, r0, #28
    a.h(0x0C00)  # lsrs r0, r0, #16
    a.h(0x1840)  # adds r0, r0, r1
    a.h(0x21F0)  # movs r1, #0xF0
    a.h(0x0209)  # lsls r1, r1, #8      0xF000
    a.h(0x4008)  # ands r0, r1
    a.h(0x4302)  # orrs r2, r0
    a.h(0x0412)  # lsls r2, r2, #16
    a.h(0x0C12)  # lsrs r2, r2, #16
    a.h(0x4694)  # mov ip, r2
    a.h(0x9800)  # ldr r0, [sp]
    a.h(0x9901)  # ldr r1, [sp, #4]
    a.h(0x18C9)  # adds r1, r1, r3
    a.h(0x9A02)  # ldr r2, [sp, #8]
    a.h(0x1952)  # adds r2, r2, r5
    a.h(0x4663)  # mov r3, ip
    a.h(0xB408)  # push {r3}
    a.bl(CELL_WRITE)
    a.h(0xBC08)  # pop {r3}
    a.label("nextcol")
    a.h(0x3301)  # adds r3, #1
    a.b("col")
    a.label("nextrow")
    a.h(0x3501)  # adds r5, #1
    a.b("row")
    a.label("done")
    a.h(0xB003)  # add sp, #12
    a.h(0xBDF0)  # pop {r4, r5, r6, r7, pc}
    return a.patch()


def disasm(rom: bytes, addr: int, size: int) -> list[dict[str, str]]:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    rows = []
    for ins in md.disasm(rom[addr - ROM_BASE : addr - ROM_BASE + size], addr):
        row = {"address": f"0x{ins.address:08X}", "op": f"{ins.mnemonic} {ins.op_str}"}
        target = thumb_bl_target(rom, ins.address)
        if target is not None:
            row["bl"] = f"0x{target:08X}"
        rows.append(row)
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")
    gate(parent[BEQ_FRAME : BEQ_FRAME + 2] == BEQ_OLD, "0x08015532 beq encoding drift")
    gate(parent[DMA_ENABLE : DMA_ENABLE + 2] == DMA_OLD, "0x080154A4 DMA enable drift")
    gate(thumb_bl_target(parent, FRAME_BLIT) == ORIG_BLIT, "0x08015558 frame blit target drift")
    gate(
        encode_thumb_bl(FRAME_BLIT, ORIG_BLIT) == parent[FRAME_BLIT - ROM_BASE : FRAME_BLIT - ROM_BASE + 4],
        "Thumb BL encoder does not match the live 0x08015558 encoding",
    )
    gate(u16(parent, 0x00015530) == 0x2800, "cmp r0,#0 before frame-blit branch drift")
    gate(set(parent[STUB_FILE:STUB_LIMIT]) <= {0}, "0x080C6700 overlay tail is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(compose_cell(0x4000) == 0xF2E0, "chrome 0x4000 mix drift")
    gate(compose_cell(0x0007) == 0xB2E7, "well 0x0007 mix drift")
    gate(compose_cell(0x440A) == 0xF6EA, "flipped chrome 0x440A mix drift")

    stub = assemble_stub(STUB_ADDR)
    gate(len(stub) <= STUB_LIMIT - STUB_FILE, f"stub overflow {len(stub)}")
    gate(len(stub) % 2 == 0, "stub is not Thumb-aligned")

    candidate = bytearray(parent)
    candidate[DMA_ENABLE : DMA_ENABLE + 2] = THUMB_NOP
    candidate[FRAME_BLIT - ROM_BASE : FRAME_BLIT - ROM_BASE + 4] = encode_thumb_bl(FRAME_BLIT, STUB_ADDR)
    candidate[STUB_FILE : STUB_FILE + len(stub)] = stub

    changed = [i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new]
    allowed = {DMA_ENABLE, DMA_ENABLE + 1}
    allowed.update(range(FRAME_BLIT - ROM_BASE, FRAME_BLIT - ROM_BASE + 4))
    allowed.update(range(STUB_FILE, STUB_FILE + len(stub)))
    gate(set(changed) <= allowed, f"unexpected writes {sorted(set(changed) - allowed)[:20]}")
    gate(candidate[BEQ_FRAME : BEQ_FRAME + 2] == BEQ_OLD, "frame-select beq must stay original")
    gate(thumb_bl_target(candidate, FRAME_BLIT) == STUB_ADDR, "frame blit was not retargeted")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")

    OUT.mkdir(parents=True, exist_ok=True)
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, WORK.with_suffix(".sav"))

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_action_menu_cursor_flash_chrome_followup_20260912",
        "status": "candidate_not_promoted",
        "promotion": "not applied; current main TIP unchanged",
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "first_candidate": {
            "path": advance_relative(FIRST_CANDIDATE) if FIRST_CANDIDATE.exists() else None,
            "ss8": advance_relative(FIRST_SS8) if FIRST_SS8.exists() else None,
            "ss8_proof": "BG0 at tx=4..7, ty=3..16 is labels only; surrounding cells 0000 (no 0x2E0 chrome)",
        },
        "output": {"path": advance_relative(WORK), "sha256": sha256(bytes(candidate)), "size": len(candidate)},
        "sav": {"path": advance_relative(WORK.with_suffix(".sav")), "copied_from": advance_relative(MAIN_SAV)},
        "patches": [
            {
                "address": "0x080154A4",
                "before": DMA_OLD.hex(),
                "after": THUMB_NOP.hex(),
                "effect": "cursor refresh no longer DMA-fills BG0 0x0600D800 with tile 0",
            },
            {
                "address": "0x08015558",
                "before": encode_thumb_bl(FRAME_BLIT, ORIG_BLIT).hex(),
                "after": encode_thumb_bl(FRAME_BLIT, STUB_ADDR).hex(),
                "effect": "frame blit goes through skip-tile-7 wrapper when 5th arg == 0",
            },
            {
                "address": f"0x{STUB_ADDR:08X}",
                "size": len(stub),
                "effect": "flag!=0 tail-calls 0x0800269C; flag==0 writes non-7 cells via 0x08001984",
            },
        ],
        "disasm_after": {
            "cursor_dma": disasm(bytes(candidate), 0x08015496, 0x20),
            "frame_call": disasm(bytes(candidate), 0x0801552E, 0x30),
            "stub": disasm(bytes(candidate), STUB_ADDR, len(stub) + 4),
        },
        "verification": {
            "result": "PASS",
            "changed_bytes": len(changed),
            "frame_beq_unmodified": True,
            "main_tip_unmodified": True,
            "runtime_emulator": "not run; static Thumb identity, compose mix, and allowlist only",
        },
        "test_plan": [
            "Load the chrome follow-up ROM and copied SAV, not main TIP and not the first candidate.",
            "Open a unit action menu on the left side of the map (6-wide frame).",
            "Confirm the green rounded chrome is present around 이동/대열/…",
            "Move the D-pad up/down several times and confirm badges no longer vanish for a frame.",
            "Open the menu on the right side (11-wide) and confirm chrome plus see-through extra well.",
        ],
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "output": report["output"],
                "sav": report["sav"],
                "stub": {"address": f"0x{STUB_ADDR:08X}", "size": len(stub)},
                "verification": report["verification"],
                "promotion": report["promotion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
