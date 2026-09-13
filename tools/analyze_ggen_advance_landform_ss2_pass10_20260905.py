#!/usr/bin/env python3
"""Parse LANDFORM resource around 0xE3100 and find live 海 string pointer."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass10_20260905.json"
ROM_BASE = 0x08000000
GFX = 0x000E3154


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    rom = MAIN_TIP_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    ewram = state[0x21000:0x61000]
    iwram = state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + 0x8000]

    region = []
    for off in range(0xE2F80, 0xE3160):
        parsed = sem.parse_map(japan, ROM_BASE + off)
        if parsed and 1 <= parsed["width"] <= 20 and 1 <= parsed["height"] <= 12:
            region.append(
                {
                    "offset": hex(off),
                    "w": parsed["width"],
                    "h": parsed["height"],
                    "tiles": [hex(c) for c in parsed["cells"][:16]],
                    "tile_ids": [c & 0x3FF for c in parsed["cells"][:16]],
                    "banks": sorted({c >> 12 for c in parsed["cells"]}),
                }
            )

    # Direct kind-2 style header used by ss tiles
    directs = []
    for off in range(0xE2E00, 0xE3200, 2):
        if u16(japan, off) != 2:
            continue
        w, h = japan[off + 2], japan[off + 3]
        mr = u16(japan, off + 4)
        gr = u16(japan, off + 8)
        size = u16(japan, off + 10)
        pr = u16(japan, off + 12)
        if not (1 <= w <= 32 and 1 <= h <= 16):
            continue
        directs.append({"offset": hex(off), "w": w, "h": h, "mr": mr, "gr": hex(gr), "size": size, "pr": hex(pr), "abs_gfx": hex(off + gr) if off + gr < len(japan) else None})

    needles = {
        "08357016": struct.pack("<I", 0x08357016),
        "e0e100": bytes.fromhex("E0 E1 00"),
        "08e3100": struct.pack("<I", 0x080E3100),
        "08e3154": struct.pack("<I", 0x080E3154),
        "08e3060": struct.pack("<I", 0x080E3060),
    }
    hits = {}
    for name, needle in needles.items():
        found = []
        for label, blob in ("jp", japan), ("main", rom), ("ewram", ewram), ("iwram", iwram):
            pos = 0
            while len(found) < 8:
                hit = blob.find(needle, pos)
                if hit < 0:
                    break
                found.append(f"{label}:{hex(hit)}")
                pos = hit + 1
        hits[name] = found

    # Table 0xD87BC entries
    list_badges = []
    for i in range(13):
        ptr = u32(japan, 0xD87BC + i * 4)
        parsed = sem.parse_map(japan, ptr)
        list_badges.append(
            {
                "i": i,
                "ptr": hex(ptr),
                "w": None if not parsed else parsed["width"],
                "h": None if not parsed else parsed["height"],
                "tiles": None if not parsed else [c & 0x3FF for c in parsed["cells"][:12]],
            }
        )

    report = {
        "maps_near_gfx": region[:40],
        "directs": directs,
        "hits": hits,
        "list_badges": list_badges,
        "hex_e30c0": japan[0xE30C0:0xE3158].hex(),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("maps", json.dumps(region[:15], indent=2))
    print("directs", directs)
    print("hits", json.dumps(hits, indent=2))
    print("list_badges", json.dumps(list_badges, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
