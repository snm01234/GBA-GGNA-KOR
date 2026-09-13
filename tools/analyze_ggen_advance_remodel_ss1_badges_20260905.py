#!/usr/bin/env python3
"""Bind remodel-screen ss1 badge tiles and compare JP rounded chrome vs KO.

Korean.ss1 is the unit-remodel workshop.  Japan.ss1 is the same screen family
on a different unit.  This pass dumps live BG/OBJ owners for the aptitude,
armor, move, hold, and remaining-count plaques, and compares E0518 / C5A5DC
copies against the Japanese rounded chrome.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_states_20260902 as remain
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_status_ui_tile_overlay_poc as status
import build_ggen_advance_turn_ability_overlays_20260905 as raster
import render_ggen_ss_tiles_20260905 as fullrender
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_ss1_badges"
ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_remodel_ss1_badges_20260905.json"
TABLE = 0x000E0518
C5 = 0x00C5A5DC
# Status-family maps previously bound to the requested labels.
E0518_TARGETS = {
    21: "運動",
    23: "威力",
    24: "命中",
    25: "装甲",
    27: "反応",
    40: "lower_status_panel",
    41: "汎用",
    42: "宇宙",
    43: "地上",
    44: "万能",
    45: "水陸",
    46: "飛行",
    12: "持_resource12",
}
# Bottom-panel crops in screen pixels.  Korean GM Custom vs Japanese Super
# Gundam share the same chrome, not the same unit, so these boxes are wide.
CROPS = {
    "bottom_panel": (0, 80, 240, 160),
    "aptitude_row": (80, 104, 200, 136),
    "hold_remaining": (40, 128, 240, 160),
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def find_all(hay: bytes, needle: bytes, limit: int = 12) -> list[int]:
    hits: list[int] = []
    start = 0
    while len(hits) < limit:
        pos = hay.find(needle, start)
        if pos < 0:
            return hits
        hits.append(pos)
        start = pos + 1
    return hits


def atlas_of(rom: bytes) -> tuple[int, bytes]:
    ptr = u32(rom, TABLE)
    off = ptr - 0x08000000
    header = u32(rom, off)
    decoded = status.lzss_decompress(rom[off + 4 : off + 4 + (header & 0xFFFF)])
    return ptr, decoded


def corner_signature(canvas: list[list[int]]) -> dict[str, Any]:
    h, w = len(canvas), len(canvas[0])
    def cell(x: int, y: int) -> int:
        return canvas[y][x]
    corners = {
        "tl": [cell(x, y) for y in range(2) for x in range(2)],
        "tr": [cell(w - 2 + x, y) for y in range(2) for x in range(2)],
        "bl": [cell(x, h - 2 + y) for y in range(2) for x in range(2)],
        "br": [cell(w - 2 + x, h - 2 + y) for y in range(2) for x in range(2)],
    }
    top_unique = len(set(canvas[0]))
    bottom_unique = len(set(canvas[-1]))
    left_col = [row[0] for row in canvas]
    right_col = [row[-1] for row in canvas]
    rectangular = top_unique == 1 and bottom_unique == 1 and len(set(left_col[2:-2])) <= 2
    return {
        "size": [w, h],
        "corners": corners,
        "top_row_unique": top_unique,
        "bottom_row_unique": bottom_unique,
        "left_col": left_col,
        "right_col": right_col,
        "looks_rectangular": rectangular,
        "nonzero": sum(v != 0 for row in canvas for v in row),
    }


def decode_tile_bytes(raw: bytes) -> list[list[int]]:
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def live_bg_tiles(state: bytes, layer: int, box: tuple[int, int, int, int]) -> dict[str, Any]:
    info = bg.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    x0, y0, x1, y1 = box
    cells = []
    live: dict[int, bytes] = {}
    for ty in range(y0 // 8, (y1 + 7) // 8):
        for tx in range(x0 // 8, (x1 + 7) // 8):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], tx, ty)
            tid = cell & 0x3FF
            raw = bytes(vram[info["char_base"] + tid * 32 : info["char_base"] + tid * 32 + 32])
            cells.append({"tx": tx, "ty": ty, "cell": f"0x{cell:04X}", "tid": tid, "unique": len(set(raw))})
            if len(set(raw)) > 1:
                live[tid] = raw
    return {"info": {**info, "cnt_hex": f"0x{info['cnt']:04X}"}, "cells": cells, "live": live}


def obj_entries(state: bytes) -> list[dict[str, Any]]:
    oam = state[statefmt.STATE_OAM : statefmt.STATE_VRAM]
    dispcnt = u16(state, statefmt.STATE_IO)
    rows = []
    for index in range(128):
        e = statefmt.parse_oam_entry(oam, index)
        a0 = int(e["attr0"], 16)
        if a0 & 0x300 == 0x200:
            continue
        if not (e["x"] < 240 and e["y"] < 160 and e["x"] + e["width"] > 0 and e["y"] + e["height"] > 80):
            continue
        tiles = []
        stride = e["width"] // 8 if dispcnt & 0x40 else 32
        for sy in range(e["height"] // 8):
            for sx in range(e["width"] // 8):
                tid = e["tile"] + sy * stride + sx
                raw = bytes(
                    state[
                        statefmt.STATE_VRAM + 0x10000 + tid * 32 :
                        statefmt.STATE_VRAM + 0x10000 + (tid + 1) * 32
                    ]
                )
                tiles.append({"tid": tid, "sha": sha256(raw), "unique": len(set(raw)), "raw": raw})
        rows.append({**e, "tiles": tiles})
    return rows


def rom_hits(rom: bytes, raw: bytes) -> list[str]:
    return [f"0x{off:08X}" for off in find_all(rom, raw, 8)]


def main() -> int:
    main = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    assert sha256(main) == meta["sha256"]
    ko_state, _ = statefmt.parse_png_state(ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1")
    jp_state, _ = statefmt.parse_png_state(ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1")
    OUT.mkdir(parents=True, exist_ok=True)

    ko_frame = fullrender.render(ko_state)
    jp_frame = fullrender.render(jp_state)
    ko_frame.resize((720, 480), Image.Resampling.NEAREST).save(OUT / "korean_ss1_composite.png")
    jp_frame.resize((720, 480), Image.Resampling.NEAREST).save(OUT / "japan_ss1_composite.png")
    pair = Image.new("RGB", (480, 160))
    pair.paste(ko_frame, (0, 0))
    pair.paste(jp_frame, (240, 0))
    pair.resize((1440, 480), Image.Resampling.NEAREST).save(OUT / "ko_jp_ss1_side_by_side.png")
    for name, (x0, y0, x1, y1) in CROPS.items():
        crop = Image.new("RGB", ((x1 - x0) * 2, y1 - y0))
        crop.paste(ko_frame.crop((x0, y0, x1, y1)), (0, 0))
        crop.paste(jp_frame.crop((x0, y0, x1, y1)), (x1 - x0, 0))
        crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.NEAREST).save(OUT / f"crop_{name}.png")

    for n, st in (("ko", ko_state), ("jp", jp_state)):
        for layer in range(4):
            bg.render_bg(st, bg.bg_info(st, layer), OUT / f"{n}_bg{layer}.png")

    ko_ptr, ko_atlas = atlas_of(main)
    jp_ptr, jp_atlas = atlas_of(jp)
    e0518 = []
    gallery = []
    ko_pal = raster.palette_rgb(ko_state[statefmt.STATE_PALETTE + 11 * 32 : statefmt.STATE_PALETTE + 12 * 32])
    jp_pal = raster.palette_rgb(jp_state[statefmt.STATE_PALETTE + 11 * 32 : statefmt.STATE_PALETTE + 12 * 32])
    for idx, label in E0518_TARGETS.items():
        jp_obj = sem.parse_map(jp, u32(jp, TABLE + idx * 4))
        ko_obj = sem.parse_map(main, u32(main, TABLE + idx * 4))
        if jp_obj is None or ko_obj is None:
            continue
        jp_c = sem.stitch(jp_atlas, jp_obj)
        ko_c = sem.stitch(ko_atlas, ko_obj)
        changed = sum(a != b for ra, rb in zip(jp_c, ko_c) for a, b in zip(ra, rb))
        row = {
            "resource": idx,
            "label": label,
            "size": [jp_obj["width"], jp_obj["height"]],
            "jp_cells": [c & 0x3FF for c in jp_obj["cells"]],
            "ko_cells": [c & 0x3FF for c in ko_obj["cells"]],
            "map_same": jp_obj["cells"] == ko_obj["cells"],
            "changed_pixels": changed,
            "jp_chrome": corner_signature(jp_c),
            "ko_chrome": corner_signature(ko_c),
        }
        e0518.append(row)
        gallery.append((f"jp r{idx} {label}", raster.render_canvas(jp_c, jp_pal)))
        gallery.append((f"ko r{idx} {label}", raster.render_canvas(ko_c, ko_pal)))

    from ggen_ss_tiles_common_20260905 import gallery as save_gallery

    save_gallery(gallery, OUT / "e0518_jp_ko.png", 4)

    ko_slots = remain.sprite_slots(ko_state)
    jp_slots = remain.sprite_slots(jp_state)
    ko_obj = obj_entries(ko_state)
    jp_obj = obj_entries(jp_state)

    def summarize_obj(rows: list[dict[str, Any]], rom: bytes) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            tile_hits = []
            for tile in row["tiles"]:
                if tile["unique"] <= 1:
                    continue
                tile_hits.append({
                    "tid": tile["tid"],
                    "sha": tile["sha"][:16],
                    "rom": rom_hits(rom, tile["raw"])[:6],
                    "e0518_ko": (ko_atlas.find(tile["raw"]) // 32) if tile["raw"] in ko_atlas else None,
                    "e0518_jp": (jp_atlas.find(tile["raw"]) // 32) if tile["raw"] in jp_atlas else None,
                })
            out.append({
                "index": row["index"],
                "x": row["x"],
                "y": row["y"],
                "width": row["width"],
                "height": row["height"],
                "tile": row["tile"],
                "palette_bank": row["palette_bank"],
                "attr0": row["attr0"],
                "hits": tile_hits,
            })
        return out

    bg_report = {}
    for name, st, rom in (("ko", ko_state, main), ("jp", jp_state, jp)):
        layers = {}
        for layer in range(4):
            case = live_bg_tiles(st, layer, (0, 80, 240, 160))
            live = case["live"]
            atlas = ko_atlas if name == "ko" else jp_atlas
            owners = {}
            e0518_hits = 0
            for tid, raw in live.items():
                in_atlas = raw in atlas
                if in_atlas:
                    e0518_hits += 1
                owners[str(tid)] = {
                    "rom": rom_hits(rom, raw)[:6],
                    "e0518": (atlas.find(raw) // 32) if in_atlas else None,
                }
            layers[str(layer)] = {
                "info": case["info"],
                "live_unique_tiles": len(live),
                "e0518_exact_hits": e0518_hits,
                "owners_sample": {k: owners[k] for k in list(owners)[:80]},
                "busy_cells": [c for c in case["cells"] if c["unique"] > 1][:80],
            }
        bg_report[name] = layers

    # Direct byte compare of known UNIT/TYPE tiles between JP atlas and KO atlas.
    known = {
        **{k: v["tiles"] for k, v in status.UNIT_LABELS.items()},
        **{k: v["tiles"] for k, v in status.TYPE_LABELS.items()},
        **{k: v["tiles"] for k, v in status.LOWER_STATUS_LABELS.items()},
    }
    known_compare = []
    for text, tiles in known.items():
        ids = [tid for row in tiles for tid in row]
        jp_c = [[0] * (len(tiles[0]) * 8) for _ in range(len(tiles) * 8)]
        ko_c = [[0] * (len(tiles[0]) * 8) for _ in range(len(tiles) * 8)]
        for ty, row in enumerate(tiles):
            for tx, tid in enumerate(row):
                jp_tile = decode_tile_bytes(jp_atlas[tid * 32 : (tid + 1) * 32])
                ko_tile = decode_tile_bytes(ko_atlas[tid * 32 : (tid + 1) * 32])
                for y in range(8):
                    jp_c[ty * 8 + y][tx * 8 : tx * 8 + 8] = jp_tile[y]
                    ko_c[ty * 8 + y][tx * 8 : tx * 8 + 8] = ko_tile[y]
        known_compare.append({
            "text": text,
            "tiles": ids,
            "changed_pixels": sum(a != b for ra, rb in zip(jp_c, ko_c) for a, b in zip(ra, rb)),
            "jp_chrome": corner_signature(jp_c),
            "ko_chrome": corner_signature(ko_c),
            "identical": jp_c == ko_c,
        })
        gallery.append((f"known jp {text}", raster.render_canvas(jp_c, jp_pal)))
        gallery.append((f"known ko {text}", raster.render_canvas(ko_c, ko_pal)))
    save_gallery(gallery, OUT / "known_labels_jp_ko.png", 3)

    # C5A5DC raw tiles around the previously identified 残り回数 / 持 range.
    c5_gallery = []
    c5_compare = []
    for off in range(0x00C5CB00, 0x00C5D300, 32):
        jp_raw = jp[off : off + 32]
        ko_raw = main[off : off + 32]
        if jp_raw == bytes(32) and ko_raw == bytes(32):
            continue
        if jp_raw == ko_raw:
            continue
        c5_compare.append({
            "offset": f"0x{off:08X}",
            "changed_bytes": sum(a != b for a, b in zip(jp_raw, ko_raw)),
        })
    # Stitch previously used 남은횟수 8x2 from C5A5DC.
    remain_off = [
        0xC5BBF0, 0xC5D110, 0xC5D130, 0xC5D150, 0xC5D1D0, 0xC5D1F0, 0xC5D210, 0xC5D230,
        0xC5C4D0, 0xC5D170, 0xC5D190, 0xC5D1B0, 0xC5D250, 0xC5D270, 0xC5D290, 0xC5D2B0,
    ]
    for name, rom, pal in (("jp", jp, jp_pal), ("ko", main, ko_pal)):
        raw = b"".join(rom[o : o + 32] for o in remain_off)
        canvas = sem.stitch(raw, {"width": 8, "height": 2, "cells": list(range(16))})
        c5_gallery.append((f"c5 remain {name}", raster.render_canvas(canvas, pal)))
        if name == "ko":
            remain_ko = corner_signature(canvas)
        else:
            remain_jp = corner_signature(canvas)
    save_gallery(c5_gallery, OUT / "c5_remaining_jp_ko.png", 3)

    report = {
        "kind": "ggen_advance_remodel_ss1_badges_20260905",
        "main_sha256": sha256(main),
        "jp_sha256": sha256(jp),
        "e0518": {"ko_ptr": hex(ko_ptr), "jp_ptr": hex(jp_ptr), "resources": e0518},
        "known_label_tiles": known_compare,
        "sprite_slots": {"ko": ko_slots, "jp": jp_slots},
        "obj_bottom": {"ko": summarize_obj(ko_obj, main), "jp": summarize_obj(jp_obj, jp)},
        "bg_bottom": bg_report,
        "c5_changed_tiles": c5_compare[:80],
        "c5_remaining_count": {"jp": remain_jp, "ko": remain_ko},
        "ko_state_crc": hex(u32(ko_state, 8)),
        "jp_state_crc": hex(u32(jp_state, 8)),
    }
    ANALYSIS.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "e0518_rectangular_ko": [
            r["label"] for r in e0518 if r["ko_chrome"]["looks_rectangular"] and not r["jp_chrome"]["looks_rectangular"]
        ],
        "known_rectangular_ko": [
            r["text"] for r in known_compare if r["ko_chrome"]["looks_rectangular"] and not r["jp_chrome"]["looks_rectangular"]
        ],
        "known_still_jp": [r["text"] for r in known_compare if r["identical"]],
        "ko_slots": sorted({s["resource"] for s in ko_slots}),
        "jp_slots": sorted({s["resource"] for s in jp_slots}),
        "ko_obj": [(r["index"], r["x"], r["y"], r["width"], r["height"], r["tile"]) for r in report["obj_bottom"]["ko"]],
        "jp_obj": [(r["index"], r["x"], r["y"], r["width"], r["height"], r["tile"]) for r in report["obj_bottom"]["jp"]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
