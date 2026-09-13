#!/usr/bin/env python3
"""Identify remodel ss2 BG2 tile 500: ROM owner, palette, and shared-hook risk."""
from __future__ import annotations

import struct
from collections import Counter
from pathlib import Path

from PIL import Image

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM

OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_ss2_bg"
KO_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss2"


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def rgb555(value: int) -> tuple[int, int, int]:
    return tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))


def render_tile(raw: bytes, pal: bytes, bank: int, path: Path) -> None:
    image = Image.new("RGB", (64, 64))
    pixels = image.load()
    for y in range(8):
        for x in range(8):
            packed = raw[y * 4 + x // 2]
            colour = (packed >> (4 * (x & 1))) & 15
            rgb = rgb555(u16(pal, (bank * 16 + colour) * 2))
            for dy in range(8):
                for dx in range(8):
                    pixels[x * 8 + dx, y * 8 + dy] = rgb
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def context(rom: bytes, off: int) -> dict:
    window = rom[max(0, off - 16):off + 48]
    return {
        "offset": f"0x{off:08X}",
        "gba": f"0x{0x08000000 + off:08X}",
        "pre4": [f"0x{u32(rom, o):08X}" for o in range(max(0, off - 16), off, 4)],
        "at": f"0x{u32(rom, off):08X}" if off + 4 <= len(rom) else None,
        "head": rom[off:off + 32].hex(),
    }


def find_all(rom: bytes, payload: bytes) -> list[int]:
    hits = []
    pos = 0
    while True:
        pos = rom.find(payload, pos)
        if pos < 0:
            break
        hits.append(pos)
        pos += 1
    return hits


def main() -> None:
    ko, _ = statefmt.parse_png_state(KO_STATE)
    jp, _ = statefmt.parse_png_state(JP_STATE)
    ko_rom = MAIN_TIP_ROM.read_bytes()
    jp_rom = ORIGINAL_ROM.read_bytes()
    ko_vram = ko[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    jp_vram = jp[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = ko[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    info = bg.bg_info(ko, 2)
    payload = bytes(ko_vram[info["char_base"] + 500 * 32:info["char_base"] + 501 * 32])
    jp_payload = bytes(jp_vram[info["char_base"] + 500 * 32:info["char_base"] + 501 * 32])
    banks = Counter()
    cells = []
    for y in range(32):
        for x in range(32):
            cell = bg.map_entry(ko_vram, info["screen_base"], info["size"], x, y)
            if (cell & 0x3FF) == 500:
                banks[cell >> 12] += 1
                if len(cells) < 8:
                    cells.append({"x": x, "y": y, "cell": f"0x{cell:04X}"})
    hits_ko = find_all(ko_rom, payload)
    hits_jp = find_all(jp_rom, payload)
    jp_hits_of_jp_tile = find_all(jp_rom, jp_payload)
    # Shared transfer trampoline still present?
    helper = bytes(ko_rom[0x63194:0x6319C])
    ptr_09f2 = u32(ko_rom, 0x63198) if helper[:2] == bytes.fromhex("004b") else None
    # Scan IWRAM live sprite resources.
    iwram = ko[statefmt.STATE_IWRAM:]
    resources = []
    for i in range(100):
        off = 0x1F98 + i * 40
        p = u32(iwram, off)
        if 0x08000000 <= p < 0x0A000000:
            resources.append({"slot": i, "ptr": f"0x{p:08X}"})
    print("TILE500")
    print("ko_payload", payload.hex())
    print("jp_payload", jp_payload.hex())
    print("palette_banks", dict(banks))
    print("sample_cells", cells)
    print("ko_rom_hits", [hex(h) for h in hits_ko])
    print("payload_in_jp_rom", [hex(h) for h in hits_jp])
    print("jp_empty_tile_hits_in_jp_rom_count", len(jp_hits_of_jp_tile))
    print("helper_63194", helper.hex())
    print("helper_ptr", hex(ptr_09f2) if ptr_09f2 else None)
    print("resources", resources)
    for off in hits_ko:
        print("CTX", context(ko_rom, off))
        # walk back to a plausible resource header
        for delta in range(0, 0x800, 4):
            base = off - delta
            if base < 0:
                break
            hdr = u32(ko_rom, base)
            if hdr in (2, 0x80000000 | (hdr & 0xFFFF)) or (16 <= (hdr & 0xFFFF) <= 0xFF00 and hdr >> 16 in (0, 2, 0x8000)):
                if delta < 64:
                    print(" nearby_hdr", hex(base), hex(hdr), "delta", hex(delta))
    bank = banks.most_common(1)[0][0] if banks else 0
    render_tile(payload, pal, bank, OUT / f"ko_tile500_bank{bank}.png")
    render_tile(payload, pal, 0, OUT / "ko_tile500_bank0.png")
    render_tile(payload, pal, 0xB, OUT / "ko_tile500_bankB.png")
    # Compare charblock2 tile-by-tile.
    diffs = []
    for tid in range(1024):
        a = ko_vram[0x8000 + tid * 32:0x8000 + tid * 32 + 32]
        b = jp_vram[0x8000 + tid * 32:0x8000 + tid * 32 + 32]
        if a != b:
            diffs.append(tid)
    print("charblock2_diff_tids", diffs)
    print("charblock2_diff_count", len(diffs))
    # BG2 map identity
    ko_map = ko_vram[info["screen_base"]:info["screen_base"] + 0x1000]
    jp_map = jp_vram[info["screen_base"]:info["screen_base"] + 0x1000]
    print("bg2_map_identical", ko_map == jp_map)
    bg3 = bg.bg_info(ko, 3)
    print("bg3_map_identical", ko_vram[bg3["screen_base"]:bg3["screen_base"] + 0x800] == jp_vram[bg3["screen_base"]:bg3["screen_base"] + 0x800])


if __name__ == "__main__":
    main()
