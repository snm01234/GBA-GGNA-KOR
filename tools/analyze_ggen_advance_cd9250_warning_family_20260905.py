#!/usr/bin/env python3
"""Inspect 0x08CD9250 warning family: lookups, consumers, tile sharing, palettes."""
from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path

from PIL import Image

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_ss3_no_unit_warning_20260905 as dump
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

RESOURCE = 0x08CD9250
ROM_BASE = 0x08000000
OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_no_unit_warning"
JSON_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_cd9250_warning_family_20260905.json"


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def pointer_hits(data, address):
    needle = struct.pack("<I", address)
    hits = []
    cursor = 0
    while True:
        found = data.find(needle, cursor)
        if found < 0:
            return hits
        hits.append(found)
        cursor = found + 1


def zero_runs(data, start, end, min_size=0x1000):
    runs = []
    i = start
    while i < end:
        if data[i] != 0:
            i += 1
            continue
        j = i
        while j < end and data[j] == 0:
            j += 1
        if j - i >= min_size:
            runs.append((i, j, j - i))
        i = j
    runs.sort(key=lambda r: r[2], reverse=True)
    return runs[:12]


def parse_anim(rom, address, anim):
    gfx_rel, records = sprite.animation_records(rom, address)
    start, record = records[anim]
    marker = analysis.find_marker(record)
    sliced = record[marker:]
    parsed = sprite.parse_animation_oam(sliced)
    total = sum(int(o["tile_count"]) for o in parsed["objects"])
    blob = b"".join(item[1] for item in records[anim:])[marker:]
    ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
    lookup_rel = (start + marker + int(parsed["entries_end"])) - (address - ROM_BASE)
    by_object = []
    cursor = 0
    for obj in parsed["objects"]:
        n = int(obj["tile_count"])
        by_object.append(ids[cursor : cursor + n])
        cursor += n
    return parsed, ids, by_object, lookup_rel, gfx_rel


def text_object_indices(parsed):
    return [i for i, o in enumerate(parsed["objects"]) if o["size_px"] == [64, 32]]


def main():
    rom = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    header = analysis.parse_resource_header(rom, RESOURCE)
    jp_header = analysis.parse_resource_header(jp, RESOURCE)
    OUT.mkdir(parents=True, exist_ok=True)
    pal = header["palettes"]
    colors = [dump.rgb555(struct.unpack_from("<H", pal, i * 2)[0]) for i in range(16)]
    family = []
    all_text_ids = []
    all_chrome_ids = []
    for anim in range(header["animation_count"]):
        parsed, ids, by_object, lookup_rel, gfx_rel = parse_anim(rom, RESOURCE, anim)
        text_idx = text_object_indices(parsed)
        text_ids = [sid for i in text_idx for sid in by_object[i]]
        chrome_ids = [sid for i, obj_ids in enumerate(by_object) if i not in text_idx for sid in obj_ids]
        canvas = analysis.stitch(header["graphics"], parsed, ids, text_idx)
        dump.canvas_image(canvas, colors, 5).save(OUT / f"cd9250_anim{anim}_text.png")
        full = analysis.stitch(header["graphics"], parsed, ids, list(range(len(parsed["objects"]))))
        dump.canvas_image(full, colors, 3).save(OUT / f"cd9250_anim{anim}_full.png")
        counts = Counter(c for row in canvas for c in row)
        family.append({
            "anim": anim,
            "objects": parsed["object_count"],
            "text_objects": text_idx,
            "text_source_ids": text_ids,
            "chrome_source_ids": sorted(set(chrome_ids)),
            "lookup_rel": hex(lookup_rel),
            "text_size": [len(canvas[0]), len(canvas)],
            "index_counts": counts.most_common(),
            "text_unique_vs_chrome": sorted(set(text_ids) - set(chrome_ids)),
            "text_shared_with_chrome": sorted(set(text_ids) & set(chrome_ids)),
        })
        all_text_ids.extend(text_ids)
        all_chrome_ids.extend(chrome_ids)
        print(f"anim {anim} text objs {text_idx} unique {sorted(set(text_ids))} counts {counts.most_common(8)}")

    consumers = pointer_hits(rom, RESOURCE)
    orig_same = rom[RESOURCE - ROM_BASE:RESOURCE - ROM_BASE + header["resource_bytes"]] == jp[RESOURCE - ROM_BASE:RESOURCE - ROM_BASE + jp_header["resource_bytes"]]
    runs = zero_runs(rom, 0x01200000, 0x02000000, 0x4000)
    report = {
        "resource": hex(RESOURCE),
        "source_tiles": header["source_tiles"],
        "resource_bytes": header["resource_bytes"],
        "original_byte_exact": orig_same,
        "consumers": [hex(x) for x in consumers],
        "consumer_count": len(consumers),
        "anims": family,
        "all_text_unique_vs_all_chrome": sorted(set(all_text_ids) - set(all_chrome_ids)),
        "text_ids_shared_across_anims": {
            "anim0_vs_1": sorted(set(family[0]["text_source_ids"]) & set(family[1]["text_source_ids"])),
            "anim0_vs_2": sorted(set(family[0]["text_source_ids"]) & set(family[2]["text_source_ids"])),
            "anim1_vs_2": sorted(set(family[1]["text_source_ids"]) & set(family[2]["text_source_ids"])),
        },
        "zero_runs_12M_32M": [[hex(a), hex(b), hex(n)] for a, b, n in runs],
        "palette0": colors,
    }
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "consumers": report["consumers"],
        "original_byte_exact": orig_same,
        "text_sharing": report["text_ids_shared_across_anims"],
        "unique_text": report["all_text_unique_vs_all_chrome"],
        "zero_runs": report["zero_runs_12M_32M"][:6],
        "out": advance_relative(JSON_OUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
