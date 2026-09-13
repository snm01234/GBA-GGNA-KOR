#!/usr/bin/env python3
"""Confirm remodel ss2 hits the 소유수 overlay gate and destination tile 500."""
from __future__ import annotations

import struct

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

KO = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
JP = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss2"


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def cell(vram: bytes, x: int, y: int) -> int:
    return u16(vram, 0xE800 + (y * 32 + x) * 2)


def main() -> None:
    ko, _ = statefmt.parse_png_state(KO)
    jp, _ = statefmt.parse_png_state(JP)
    rom = MAIN_TIP_ROM.read_bytes()
    kv = ko[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    jv = jp[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    io = ko[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    print("BG2CNT", hex(u16(io, 0xC)))
    print("sort_gate_E950", hex(u16(kv, 0xE950)), "jp", hex(u16(jv, 0xE950)))
    print("sort_gate_EBAA", hex(u16(kv, 0xEBAA)), "jp", hex(u16(jv, 0xEBAA)))
    print("owned_EA6C", hex(u32(kv, 0xEA6C)), "jp", hex(u32(jv, 0xEA6C)))
    print("owned_EAB4", hex(u32(kv, 0xEAB4)), "jp", hex(u32(jv, 0xEAB4)))
    print("glyph cells KO")
    ids = []
    for y in (9, 10):
        row = []
        for x in range(22, 27):
            c = cell(kv, x, y)
            row.append(f"{x},{y}=0x{c:04X}")
            ids.append(c & 0x3FF)
        print(" ", row)
    print("unique glyph tile ids", sorted(set(ids)))
    print("glyph cells JP")
    for y in (9, 10):
        print(" ", [f"{x},{y}=0x{cell(jv, x, y):04X}" for x in range(22, 27)])
    # plaque-style corners used by later overlays
    for name, x, y in [("tl", 21, 8), ("tr", 29, 8), ("bl", 21, 11), ("br", 29, 11),
                       ("p0", 20, 8), ("p1", 30, 8), ("p2", 20, 11), ("p3", 30, 11)]:
        print(name, "ko", hex(cell(kv, x, y)), "jp", hex(cell(jv, x, y)))
    payload = rom[0xC5A00:0xC5A00 + 320]
    tile500 = kv[0x8000 + 500 * 32:0x8000 + 501 * 32]
    print("payload_len_nonzero", sum(1 for b in payload if b))
    print("tile500_in_c5a00", tile500 in payload)
    print("tile500_index_in_c5a00", payload.find(tile500) // 32 if tile500 in payload else None)
    p2 = rom[0x1F23BE8:0x1F23BE8 + 32]
    print("1F23BE8_eq_tile500", p2 == tile500)
    # How many 09F2 occurrences of this tile
    print("09F2 region size hint", hex(u32(rom, 0x63198)))
    # Search stub literals for 0x5D0A, 0x0600EA6C, tile dest 0x0600BE80
    region = rom[0x1F20000:0x1F26000]
    for needle, label in [
        (b"\x0a\x5d\x00\x00", "BG2CNT_5D0A"),
        (b"\x6c\xea\x00\x06", "addr_0600EA6C"),
        (b"\xb4\xea\x00\x06", "addr_0600EAB4"),
        (b"\x80\xbe\x00\x06", "addr_0600BE80"),
        (b"\x00\x5a\x0c\x08", "payload_080C5A00"),
        (b"\xdd\xb0", "cell_B0DD"),
        (b"\x0e\xf0\x00\x00", "cell_F00E"),
    ]:
        print(label, [hex(0x1F20000 + i) for i in range(len(region) - len(needle)) if region[i:i + len(needle)] == needle][:8])
    cave = rom[0xC5700:0xC6800]
    print("C5700_nonzero", sum(1 for b in cave if b), "tile500_in_cave", tile500 in cave)


if __name__ == "__main__":
    main()
