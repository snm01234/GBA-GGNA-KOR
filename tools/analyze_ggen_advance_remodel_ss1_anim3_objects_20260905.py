#!/usr/bin/env python3
"""Dump C64140 / 092D8000 animation-3 object boxes and shared-tile overlap."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spr
import analyze_ggen_advance_settings_suspend_ui as spritefmt
import build_ggen_advance_turn_ability_overlays_20260905 as raster
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM

OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_ss1_badges"
KO_RES = 0x092D8000
JP_RES = 0x08C64140


def parse_anim(rom, addr, index):
    header = spr.parse_resource_header(rom, addr)
    _rel, records = spritefmt.animation_records(rom, addr)
    record = records[index][1]
    marker = spr.find_marker(record)
    sliced = record[marker:]
    parsed = spritefmt.parse_animation_oam(sliced)
    total = sum(int(o["tile_count"]) for o in parsed["objects"])
    blob = b"".join(item[1] for item in records[index:])[marker:]
    ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
    return header, parsed, ids


def object_ids(parsed, ids):
    cursor = 0
    rows = []
    for obj in parsed["objects"]:
        count = int(obj["tile_count"])
        rows.append(ids[cursor:cursor + count])
        cursor += count
    return rows


def main():
    ko = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    items = []
    for tag, rom, addr in (("ko", ko, KO_RES), ("jp", jp, JP_RES)):
        header, parsed, ids = parse_anim(rom, addr, 3)
        grouped = object_ids(parsed, ids)
        pal = raster.palette_rgb(header["palettes"][32:64] if header["palette_count"] > 1 else header["palettes"][:32])
        other_ids = set()
        for anim in range(header["animation_count"]):
            if anim == 3:
                continue
            try:
                _h, p, a_ids = parse_anim(rom, addr, anim)
            except Exception:
                continue
            other_ids.update(a_ids)
        objects = []
        for obj, src in zip(parsed["objects"], grouped):
            canvas = spr.stitch(header["graphics"], parsed, ids, [obj["index"]])
            shared = [tid for tid in src if tid in other_ids]
            objects.append({
                "index": obj["index"],
                "x": obj["x"],
                "y": obj["y"],
                "size": obj["size_px"],
                "source_ids": src,
                "shared_with_other_anims": shared,
            })
            im = raster.render_canvas(canvas, pal).resize(
                (max(8, len(canvas[0]) * 3), max(8, len(canvas) * 3)), Image.Resampling.NEAREST
            )
            labeled = Image.new("RGB", (im.width + 80, im.height + 16), (20, 20, 20))
            d = ImageDraw.Draw(labeled)
            d.text((2, 2), f"{tag} o{obj['index']} ({obj['x']},{obj['y']}) {obj['size_px']}", fill="white")
            labeled.paste(im, (80, 14))
            items.append((f"{tag} o{obj['index']}", labeled))
        full = spr.stitch(header["graphics"], parsed, ids, list(range(len(parsed["objects"]))))
        raster.render_canvas(full, pal).resize((len(full[0]) * 2, len(full) * 2), Image.Resampling.NEAREST).save(
            OUT / f"{tag}_anim3_full.png"
        )
        report[tag] = {
            "address": hex(addr),
            "source_tiles": header["source_tiles"],
            "objects": objects,
            "all_source_ids": ids,
        }
    from ggen_ss_tiles_common_20260905 import gallery
    gallery(items, OUT / "anim3_objects.png", 1)
    (OUT / "anim3_objects.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        tag: [
            (o["index"], o["x"], o["y"], o["size"], len(o["shared_with_other_anims"]))
            for o in report[tag]["objects"]
        ]
        for tag in report
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
