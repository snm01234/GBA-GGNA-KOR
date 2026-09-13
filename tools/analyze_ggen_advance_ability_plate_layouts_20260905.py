#!/usr/bin/env python3
"""Reconstruct ability-plate canvases from animation source-id streams."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

ROM_BASE = 0x08000000
ABILITY = 0x083424A0
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_overlays_20260905"
GROUPS = [
    "分身",
    "フェイズシフト装甲",
    "ラミネート装甲",
    "ビームコート",
    "Iフィールド",
    "Pディフェンサー",
    "FFバリア",
    "FFバリア/月光蝶境界",
    "月光蝶",
    "光の翼",
]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_tile(raw: bytes) -> list[list[int]]:
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def palette_rgb(raw: bytes) -> list[tuple[int, int, int]]:
    colors = []
    for i in range(16):
        value = struct.unpack_from("<H", raw, i * 2)[0]
        colors.append(tuple(((value >> s) & 31) * 255 // 31 for s in (0, 5, 10)))
    return colors


def objects_from_ids(ids: list[int]) -> list[dict]:
    objs, width, remaining = [], 0, list(ids)
    while remaining:
        if len(remaining) >= 8:
            take, w, h = 8, 32, 16
        elif len(remaining) >= 4:
            take, w, h = 4, 16, 16
        elif len(remaining) >= 2:
            take, w, h = 2, 8, 16
        else:
            take, w, h = 1, 8, 8
        objs.append({"x": width, "y": 0, "w": w, "h": h, "ids": remaining[:take]})
        remaining = remaining[take:]
        width += w
    return objs


def canvas_from_objects(graphics: bytes, objs: list[dict]) -> list[list[int]]:
    width = max(int(o["x"]) + int(o["w"]) for o in objs)
    height = max(int(o["y"]) + int(o["h"]) for o in objs)
    canvas = [[0] * width for _ in range(height)]
    for obj in objs:
        ids = list(obj["ids"])
        tw, th = int(obj["w"]) // 8, int(obj["h"]) // 8
        for ty in range(th):
            for tx in range(tw):
                tile = decode_tile(graphics[ids[ty * tw + tx] * 32 : (ids[ty * tw + tx] + 1) * 32])
                ox, oy = int(obj["x"]) + tx * 8, int(obj["y"]) + ty * 8
                for py in range(8):
                    canvas[oy + py][ox : ox + 8] = tile[py]
    return canvas


def render_canvas(canvas: list[list[int]], colors: list[tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", (len(canvas[0]), len(canvas)))
    image.putdata([colors[v] for row in canvas for v in row])
    return image


def extract_plate_ids(values: list[int], tile_count: int) -> list[list[int]]:
    """Keep runs of source-tile IDs that look like 16px text strips, allowing shared-tile jumps."""
    commandish = {0, 1, 2, 3, 4, 6, 7, 8, 12, 14, 16, 20, 24, 28, 32, 40, 64, 76, 80, 84, 128, 136, 140, 188, 192, 200, 204, 252, 268}
    plates: list[list[int]] = []
    i = 0
    while i < len(values):
        v = values[i]
        if not (6 <= v < tile_count):
            i += 1
            continue
        run = [v]
        i += 1
        while i < len(values):
            nxt = values[i]
            if not (0 <= nxt < tile_count):
                break
            # Stop on a clear command prologue 64,7 / 64,4 / 64,1.
            if nxt == 64 and i + 1 < len(values) and values[i + 1] in {1, 4, 7}:
                break
            prev = run[-1]
            # Continue through exclusive consecutive IDs, or a short shared-tile hop.
            if nxt == prev + 1 or (6 <= nxt < tile_count and abs(nxt - prev) <= 40 and nxt not in commandish - {64}):
                # Avoid swallowing long command tails of small numbers.
                if nxt <= 5:
                    break
                run.append(nxt)
                i += 1
                continue
            break
        if len(run) >= 4:
            plates.append(run)
        else:
            i = i
    # Dedup identical runs.
    uniq = []
    seen = set()
    for run in plates:
        key = tuple(run)
        if key not in seen:
            seen.add(key)
            uniq.append(run)
    return uniq


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    off = ABILITY - ROM_BASE
    kind, pal_count, gfx_rel, pal_rel, anim_count = struct.unpack_from("<5I", rom, off)
    graphics = rom[off + gfx_rel : off + pal_rel]
    pal = rom[off + pal_rel : off + pal_rel + 32]
    colors = palette_rgb(pal)
    tiles = (pal_rel - gfx_rel) // 32
    rels = [u32(rom, off + 0x14 + i * 4) for i in range(anim_count)]
    starts = [off + 0x14 + rel for rel in rels]
    ends = starts[1:] + [off + gfx_rel]
    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    previews = []
    for index, (a, b) in enumerate(zip(starts, ends)):
        blob = rom[a:b]
        values = list(struct.unpack_from(f"<{len(blob) // 2}H", blob))
        plates = extract_plate_ids(values, tiles)
        canvases = []
        for ids in plates:
            objs = objects_from_ids(ids)
            canvas = canvas_from_objects(graphics, objs)
            canvases.append((ids, objs, canvas))
        row = {
            "anim": index,
            "group": index // 3,
            "label": GROUPS[index // 3],
            "bytes": len(blob),
            "plates": [
                {
                    "ids": ids,
                    "count": len(ids),
                    "unique_sorted": sorted(set(ids)),
                    "size": [len(canvas[0]), len(canvas)],
                }
                for ids, _objs, canvas in canvases
            ],
        }
        rows.append(row)
        if canvases:
            total_w = sum(len(c[2][0]) + 6 for c in canvases) - 6
            height = max(len(c[2]) for c in canvases)
            combined = [[0] * total_w for _ in range(height)]
            x = 0
            for _ids, _objs, canvas in canvases:
                for y, line in enumerate(canvas):
                    combined[y][x : x + len(line)] = line
                x += len(canvas[0]) + 6
            img = render_canvas(combined, colors).resize(
                (len(combined[0]) * 4, len(combined) * 4), Image.Resampling.NEAREST
            )
            img.save(OUT / f"ability_plate_anim_{index:02d}.png")
            previews.append((index, img, plates))

    sheet_h = 8 + sum(im.height + 22 for _i, im, _p in previews)
    sheet = Image.new("RGB", (1100, sheet_h), (16, 16, 20))
    draw = ImageDraw.Draw(sheet)
    y = 4
    for index, img, plates in previews:
        draw.text(
            (8, y),
            f"anim {index:02d} {GROUPS[index // 3]} plates {[p[:8] + (['...'] if len(p) > 8 else []) for p in plates]}",
            fill=(255, 255, 255),
        )
        sheet.paste(img, (8, y + 12))
        y += img.height + 22
    sheet.save(OUT / "ability_plate_layouts_sheet.png")
    (ADVANCE_ROOT / "analysis" / "ggen_advance_ability_plate_layouts_20260905.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
