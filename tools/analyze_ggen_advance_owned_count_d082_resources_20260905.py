#!/usr/bin/env python3
"""Resolve the CFC4 D082 tilemap-blit source candidates from E0518.

D082 calls 0x0800269C at tile coordinates (25,7) with r3 =
status_table[r5 + 3], where r5 is returned by 0x08007794.  Enumerate the
structurally valid E0518 maps reachable through that formula and compare their
mapped atlas tile payloads with the live JP BG2 plaque.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_status_ui_tile_overlay_poc as status
from analyze_ggen_advance_fixed_word_semantics_20260830 import parse_map
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
STATUS_TABLE = 0x000E0518
D082_X = 25
D082_Y = 7
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_d082_resources_20260905.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_atlas(data: bytes) -> tuple[int, bytes]:
    ptr = u32(data, STATUS_TABLE)
    off = ptr - ROM_BASE
    header = u32(data, off)
    if not (header & 0x80000000):
        raise SystemExit(f"gate failed: status atlas 0x{ptr:08X} not compressed")
    body_len = header & 0xFFFF
    atlas = status.lzss_decompress(data[off + 4:off + 4 + body_len])
    return ptr, atlas


def tile_payload(atlas: bytes, cell: int) -> bytes:
    tid = cell & 0x3FF
    return bytes(atlas[tid * 32:(tid + 1) * 32])


def live_plaque(state: bytes) -> dict[str, Any]:
    p = owned.plaque_scan(state)
    if not p.get("found"):
        raise SystemExit("gate failed: live plaque not found")
    return p


def compare_map_to_plaque(atlas: bytes, resource: dict[str, Any], plaque: dict[str, Any]) -> dict[str, Any]:
    w, h = int(resource["width"]), int(resource["height"])
    cells = [int(c) for c in resource["cells"]]
    rows = [cells[y*w:(y+1)*w] for y in range(h)]
    # D082 places map origin at (25,7). Compare overlap with plaque x=21..29,y=8..11.
    px0, py0 = int(plaque["x0"]), int(plaque["y0"])
    px1, py1 = px0 + int(plaque["width"]), py0 + int(plaque["height"])
    overlap = []
    exact = 0
    total = 0
    for ry in range(h):
        sy = D082_Y + ry
        if not (py0 <= sy < py1):
            continue
        for rx in range(w):
            sx = D082_X + rx
            if not (px0 <= sx < px1):
                continue
            pcell = plaque["map"][sy - py0][sx - px0]
            live_raw = owned.bg_tile_bytes(_STATE, 2, int(pcell["tile"]))
            src_raw = tile_payload(atlas, rows[ry][rx])
            same = live_raw == src_raw
            total += 1
            exact += same
            overlap.append({
                "screen_xy": [sx, sy],
                "resource_xy": [rx, ry],
                "resource_cell": f"0x{rows[ry][rx]:04X}",
                "resource_tile": rows[ry][rx] & 0x3FF,
                "live_tile": int(pcell["tile"]),
                "byte_exact": same,
            })
    return {
        "width": w,
        "height": h,
        "overlap_cell_count": total,
        "byte_exact_overlap_count": exact,
        "byte_exact_ratio": exact / total if total else 0.0,
        "overlap": overlap,
    }


def main() -> int:
    global _STATE
    jp = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    _STATE, _ = statefmt.parse_png_state(JP_STATE)
    plaque = live_plaque(_STATE)
    jp_ptr, jp_atlas = decode_atlas(jp)
    cur_ptr, cur_atlas = decode_atlas(current)

    entries = []
    # r5 is byte-sized in CFC4. Enumerate conservative 0..63; index=r5+3.
    for r5 in range(64):
        index = r5 + 3
        table_off = STATUS_TABLE + index * 4
        ptr = u32(jp, table_off)
        if not (ROM_BASE <= ptr < ROM_BASE + len(jp)):
            continue
        resource = parse_map(jp, ptr)
        if resource is None:
            continue
        w, h = int(resource["width"]), int(resource["height"])
        if not (1 <= w <= 32 and 1 <= h <= 20):
            continue
        cmp = compare_map_to_plaque(jp_atlas, resource, plaque)
        entries.append({
            "r5": r5,
            "resource_index": index,
            "resource_pointer": f"0x{ptr:08X}",
            "resource_file_offset": f"0x{ptr-ROM_BASE:08X}",
            **cmp,
        })
    entries.sort(key=lambda r: (r["byte_exact_overlap_count"], r["overlap_cell_count"], -r["r5"]), reverse=True)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_d082_resources_20260905",
        "result": "PASS",
        "source": {
            "jp_rom": advance_relative(ORIGINAL_ROM),
            "current_main": advance_relative(MAIN_TIP_ROM),
            "jp_state": advance_relative(JP_STATE),
            "jp_status_atlas": f"0x{jp_ptr:08X}",
            "current_status_atlas": f"0x{cur_ptr:08X}",
        },
        "callsite": {"address": "0x0806D082", "blitter": "0x0800269C", "screen_xy_tiles": [D082_X, D082_Y], "resource_formula": "E0518[r5+3]"},
        "plaque": {"rect": [plaque["x0"], plaque["y0"], plaque["width"], plaque["height"]]},
        "candidates": entries,
        "best": entries[0] if entries else None,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "top": [{k: r[k] for k in ("r5","resource_index","resource_pointer","width","height","overlap_cell_count","byte_exact_overlap_count","byte_exact_ratio")} for r in entries[:20]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
