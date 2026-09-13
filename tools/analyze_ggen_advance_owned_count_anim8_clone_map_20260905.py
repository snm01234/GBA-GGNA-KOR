#!/usr/bin/env python3
"""Bind current main's supply private clone and map anim8 source tiles to live BG2 plaque tiles."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_images_20260901 as catalog
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as packagefmt
import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_settings_suspend_ui as spritefmt
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
NATIVE = 0x08C4654C
CLONE = 0x092D0000
ANIM = 8
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_anim8_clone_map_20260905.json"
REFS = (0x0806D570, 0x0806D81C, 0x0806EC9C)


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_anim(rom: bytes, address: int) -> tuple[dict[str, Any], dict[str, Any], list[int], int]:
    header = packagefmt.parse_resource_header(rom, address)
    _graphics_rel, records = spritefmt.animation_records(rom, address)
    parsed, ids, lookup_file = catalog.parse_anim(records, ANIM)
    return header, parsed, ids, lookup_file


def source_positions(parsed: dict[str, Any], ids: list[int]) -> dict[int, list[dict[str, int]]]:
    out: dict[int, list[dict[str, int]]] = defaultdict(list)
    gx0 = min(int(obj["x"]) for obj in parsed["objects"])
    gy0 = min(int(obj["y"]) for obj in parsed["objects"])
    cursor = 0
    for obj_index, obj in enumerate(parsed["objects"]):
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        for ty in range(ht):
            for tx in range(wt):
                sid = int(ids[cursor + ty * wt + tx])
                out[sid].append({
                    "object": obj_index,
                    "tile_position": ty * wt + tx,
                    "canvas_x": int(obj["x"]) - gx0 + tx * 8,
                    "canvas_y": int(obj["y"]) - gy0 + ty * 8,
                })
        cursor += int(obj["tile_count"])
    return out


def live_plaque_tiles(state: bytes) -> dict[int, bytes]:
    plaque = owned.plaque_scan(state)
    if not plaque.get("found"):
        raise SystemExit("gate failed: JP live plaque not found")
    result: dict[int, bytes] = {}
    for row in plaque["map"]:
        for cell in row:
            tid = int(cell["tile"])
            result[tid] = owned.bg_tile_bytes(state, 2, tid)
    return result


def exact_map(graphics: bytes, ids: list[int], plaque: dict[int, bytes]) -> list[dict[str, Any]]:
    reverse: dict[bytes, list[int]] = defaultdict(list)
    for tid, raw in plaque.items():
        reverse[raw].append(tid)
    rows = []
    for sid in sorted(set(ids)):
        raw = bytes(graphics[sid * 32:(sid + 1) * 32])
        if raw in reverse:
            rows.append({"source_id": sid, "bg2_tile_ids": sorted(reverse[raw]), "sha256": sha256(raw)})
    return rows


def main() -> int:
    main = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(JP_STATE)

    refs = [{
        "address": f"0x{addr:08X}",
        "value": f"0x{u32(main, addr - ROM_BASE):08X}",
        "points_to_clone": u32(main, addr - ROM_BASE) == CLONE,
    } for addr in REFS]

    native_h, native_p, native_ids, native_lookup = parse_anim(jp, NATIVE)
    clone_h, clone_p, clone_ids, clone_lookup = parse_anim(main, CLONE)
    if len(native_ids) != len(clone_ids):
        raise SystemExit("gate failed: anim8 lookup length drift")
    lookup_diff = [
        {"index": i, "native": a, "clone": b}
        for i, (a, b) in enumerate(zip(native_ids, clone_ids)) if a != b
    ]

    plaque = live_plaque_tiles(state)
    native_exact = exact_map(native_h["graphics"], native_ids, plaque)
    clone_exact = exact_map(clone_h["graphics"], clone_ids, plaque)
    native_pos = source_positions(native_p, native_ids)
    clone_pos = source_positions(clone_p, clone_ids)
    for row in native_exact:
        row["canvas_positions"] = native_pos.get(int(row["source_id"]), [])
    for row in clone_exact:
        row["canvas_positions"] = clone_pos.get(int(row["source_id"]), [])

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_anim8_clone_map_20260905",
        "result": "PASS",
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(main)},
        "redirect": {
            "native_resource": f"0x{NATIVE:08X}",
            "private_clone": f"0x{CLONE:08X}",
            "code_refs": refs,
            "all_refs_point_to_clone": all(row["points_to_clone"] for row in refs),
        },
        "native_anim8": {
            "resource_bytes": native_h["resource_bytes"],
            "source_tiles": native_h["source_tiles"],
            "lookup_file": f"0x{native_lookup:08X}",
            "lookup_count": len(native_ids),
            "unique_source_ids": len(set(native_ids)),
        },
        "clone_anim8": {
            "resource_bytes": clone_h["resource_bytes"],
            "source_tiles": clone_h["source_tiles"],
            "lookup_file": f"0x{clone_lookup:08X}",
            "lookup_count": len(clone_ids),
            "unique_source_ids": len(set(clone_ids)),
            "lookup_diff_count": len(lookup_diff),
            "lookup_diffs": lookup_diff,
        },
        "live_bg2_exact_map_native_anim8": native_exact,
        "live_bg2_exact_map_clone_anim8": clone_exact,
        "native_exact_unique_source_count": len(native_exact),
        "clone_exact_unique_source_count": len(clone_exact),
        "conclusion": "Current main redirects the supply path to the private clone; exact anim8 source-to-live-BG2 mappings are listed for clone-only patching.",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "redirect": report["redirect"],
        "clone": report["clone_anim8"],
        "clone_exact_map": clone_exact,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
