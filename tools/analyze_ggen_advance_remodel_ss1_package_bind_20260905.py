#!/usr/bin/env python3
"""Bind remodel ss1 live OBJ tiles to resident sprite packages."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spr
import analyze_ggen_advance_remaining_ui_states_20260902 as remain
import analyze_ggen_advance_settings_suspend_ui as spritefmt
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_turn_ability_overlays_20260905 as raster
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM

OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_ss1_badges"
ROM_BASE = 0x08000000


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def decode_tile(raw):
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def try_header(rom, address):
    off = address - ROM_BASE
    if off < 0 or off + 0x14 > len(rom):
        return None
    kind, pal_count, gfx_rel, pal_rel, anim_count = struct.unpack_from("<5I", rom, off)
    if kind != 0 or pal_count not in range(1, 17) or anim_count not in range(1, 65):
        return None
    if not (0x14 <= gfx_rel < pal_rel) or (pal_rel - gfx_rel) % 32:
        return None
    if off + pal_rel + pal_count * 32 > len(rom):
        return None
    return {
        "address": address,
        "off": off,
        "pal_count": pal_count,
        "gfx_rel": gfx_rel,
        "pal_rel": pal_rel,
        "anim_count": anim_count,
        "graphics": rom[off + gfx_rel:off + pal_rel],
        "palettes": rom[off + pal_rel:off + pal_rel + pal_count * 32],
    }


def lookup_hits(graphics, live_lookup):
    hits = []
    for src in range(len(graphics) // 32):
        raw = graphics[src * 32:(src + 1) * 32]
        if raw in live_lookup:
            hits.append((src, live_lookup[raw]))
    return hits


def stitch_ids(graphics, parsed, ids):
    objects = parsed["objects"]
    canvas_w = max(int(o["x"]) + int(o["size_px"][0]) for o in objects) - min(int(o["x"]) for o in objects)
    canvas_h = max(int(o["y"]) + int(o["size_px"][1]) for o in objects) - min(int(o["y"]) for o in objects)
    x0 = min(int(o["x"]) for o in objects)
    y0 = min(int(o["y"]) for o in objects)
    canvas = [[0] * canvas_w for _ in range(canvas_h)]
    cursor = 0
    for obj in objects:
        wt, ht = int(obj["size_px"][0]) // 8, int(obj["size_px"][1]) // 8
        count = wt * ht
        src = ids[cursor:cursor + count]
        cursor += count
        for ty in range(ht):
            for tx in range(wt):
                tid = src[ty * wt + tx]
                if tid * 32 + 32 > len(graphics):
                    continue
                tile = decode_tile(graphics[tid * 32:(tid + 1) * 32])
                ox = int(obj["x"]) - x0 + tx * 8
                oy = int(obj["y"]) - y0 + ty * 8
                for yy in range(8):
                    if 0 <= oy + yy < canvas_h:
                        for xx in range(8):
                            if 0 <= ox + xx < canvas_w:
                                canvas[oy + yy][ox + xx] = tile[yy][xx]
    return canvas, x0, y0


def main():
    ko = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    ko_state, _ = statefmt.parse_png_state(ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1")
    jp_state, _ = statefmt.parse_png_state(ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1")
    ko_obj = ko_state[statefmt.STATE_VRAM + 0x10000:statefmt.STATE_IWRAM]
    jp_obj = jp_state[statefmt.STATE_VRAM + 0x10000:statefmt.STATE_IWRAM]
    OUT.mkdir(parents=True, exist_ok=True)

    def live_map(objvram):
        lookup = {}
        for tid in range(len(objvram) // 32):
            raw = bytes(objvram[tid * 32:(tid + 1) * 32])
            if len(set(raw)) > 1:
                lookup.setdefault(raw, []).append(tid)
        return lookup

    ko_live = live_map(ko_obj)
    jp_live = live_map(jp_obj)
    ko_slots = remain.sprite_slots(ko_state)
    jp_slots = remain.sprite_slots(jp_state)
    report = {"ko_slots": ko_slots, "jp_slots": jp_slots, "packages": []}
    items = []

    def inspect(tag, rom, live, slots):
        addrs = sorted({int(s["resource"], 16) for s in slots})
        for addr in addrs:
            header = try_header(rom, addr)
            row = {"tag": tag, "address": hex(addr), "resident": [s for s in slots if int(s["resource"], 16) == addr]}
            if header is None:
                row["header"] = None
                report["packages"].append(row)
                continue
            graphics = header["graphics"]
            hits = lookup_hits(graphics, live)
            row["header"] = {k: header[k] for k in ("pal_count", "gfx_rel", "pal_rel", "anim_count") }
            row["source_tiles"] = len(graphics) // 32
            row["live_source_hits"] = len(hits)
            row["hit_source_ids"] = [src for src, _ in hits[:80]]
            pal = raster.palette_rgb(header["palettes"][:32])
            try:
                _rel, records = spritefmt.animation_records(rom, addr)
            except Exception as exc:
                row["anim_error"] = str(exc)
                report["packages"].append(row)
                continue
            anims = []
            for index in range(header["anim_count"]):
                record = records[index][1]
                marker = spr.find_marker(record)
                if marker is None:
                    anims.append({"animation": index, "error": "no marker"})
                    continue
                try:
                    sliced = record[marker:]
                    parsed = spritefmt.parse_animation_oam(sliced)
                    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
                    blob = b"".join(item[1] for item in records[index:])[marker:]
                    if parsed["entries_end"] + total * 2 > len(blob):
                        anims.append({"animation": index, "error": "lookup truncated"})
                        continue
                    ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
                except Exception as exc:
                    anims.append({"animation": index, "error": str(exc)})
                    continue
                exact = sum(graphics[sid * 32:(sid + 1) * 32] in live for sid in ids if sid * 32 + 32 <= len(graphics))
                canvas, x0, y0 = stitch_ids(graphics, parsed, ids)
                path = OUT / f"{tag}_{addr:08X}_anim{index}.png"
                raster.render_canvas(canvas, pal).resize(
                    (max(8, len(canvas[0]) * 2), max(8, len(canvas) * 2)), Image.Resampling.NEAREST
                ).save(path)
                anims.append({
                    "animation": index,
                    "objects": [
                        {"i": o["index"], "x": o["x"], "y": o["y"], "size": o["size_px"]}
                        for o in parsed["objects"]
                    ],
                    "source_ids": ids,
                    "exact_live_ids": exact,
                    "origin": [x0, y0],
                    "preview": str(path.name),
                })
                items.append((f"{tag} {addr:X} a{index} live={exact}", raster.render_canvas(canvas, pal)))
            row["animations"] = anims
            report["packages"].append(row)

    inspect("ko", ko, ko_live, ko_slots)
    inspect("jp", jp, jp_live, jp_slots)
    from ggen_ss_tiles_common_20260905 import gallery
    gallery(items, OUT / "package_anims.png", 2)
    (OUT / "package_bind.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = []
    for row in report["packages"]:
        best = 0
        if row.get("animations"):
            best = max((a.get("exact_live_ids") or 0) for a in row["animations"])
        summary.append((row["tag"], row["address"], row.get("live_source_hits"), best, row.get("header", {}).get("anim_count") if row.get("header") else None))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
