#!/usr/bin/env python3
"""Connect CFC4 E0518 maps to intermediate VRAM 0x06007000 in JP ss1."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from analyze_ggen_advance_fixed_word_semantics_20260830 import parse_map
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
TABLE = 0x000E0518
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_intermediate_vram_20260905.json"
INTERMEDIATE = 0x7000
BASE_INDEX = 2
TILE_ADD = 0x201
PAL = 0xB000


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]

def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def transformed(src: int) -> int:
    return (((src & 0x3FF) + TILE_ADD) & 0x3FF) | (src & 0x0C00) | PAL


def main() -> int:
    rom = ORIGINAL_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(JP_STATE)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    plaque = owned.plaque_scan(state)
    if not plaque.get("found"):
        raise SystemExit("gate failed: plaque missing")

    ptr = u32(rom, TABLE + BASE_INDEX * 4)
    res = parse_map(rom, ptr)
    if res is None:
        raise SystemExit("gate failed: base map missing")
    w,h = int(res["width"]), int(res["height"])
    cells = [int(c) for c in res["cells"]]
    base_compare=[]
    exact=0
    for y in range(h):
        for x in range(w):
            src=cells[y*w+x]
            live=u16(vram,INTERMEDIATE+(y*32+x)*2)
            want=transformed(src)
            same=live==want
            exact+=same
            if not same and len(base_compare)<120:
                base_compare.append({"xy":[x,y],"source":f"0x{src:04X}","expected":f"0x{want:04X}","state":f"0x{live:04X}"})

    # Snapshot intermediate rectangles around the final plaque coordinate and nearby likely CFC4 placements.
    rects={}
    for name,(x0,y0,x1,y1) in {
        "plaque_coords":(20,6,32,13),
        "D082_area":(24,6,32,12),
        "full_right":(16,0,32,20),
    }.items():
        rects[name]=[
            [f"0x{u16(vram,INTERMEDIATE+(y*32+x)*2):04X}" for x in range(x0,x1)]
            for y in range(y0,y1)
        ]

    # Search exact 9x4 final plaque map-cell tile pattern anywhere in 0x06007000 as cells,
    # first exact, then ignoring palette.
    final=[[int(cell["cell"],16) for cell in row] for row in plaque["map"]]
    exact_hits=[]; tile_hits=[]
    for y0 in range(20-4+1):
        for x0 in range(32-9+1):
            ok=True; tok=True
            for yy in range(4):
                for xx in range(9):
                    iv=u16(vram,INTERMEDIATE+((y0+yy)*32+x0+xx)*2)
                    fv=final[yy][xx]
                    ok &= iv==fv
                    tok &= (iv&0x3FF)==(fv&0x3FF)
            if ok: exact_hits.append([x0,y0])
            if tok: tile_hits.append([x0,y0])

    report={
        "schema_version":1,
        "kind":"ggen_advance_owned_count_intermediate_vram_20260905",
        "result":"PASS",
        "source":{"rom":advance_relative(ORIGINAL_ROM),"state":advance_relative(JP_STATE)},
        "base_map":{"index":BASE_INDEX,"pointer":f"0x{ptr:08X}","size":[w,h],"expected_transform_exact_cells":exact,"total":w*h,"mismatches_sample":base_compare},
        "intermediate_vram":"0x06007000",
        "rects":rects,
        "final_plaque_exact_hits_in_intermediate":exact_hits,
        "final_plaque_tile_only_hits_in_intermediate":tile_hits,
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"PASS","out":advance_relative(OUT),"base_exact":exact,"base_total":w*h,"exact_hits":exact_hits,"tile_hits":tile_hits,"D082_area":rects["D082_area"]},ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
