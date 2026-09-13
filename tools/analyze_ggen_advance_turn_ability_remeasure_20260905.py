#!/usr/bin/env python3
"""Re-measure turn-banner Japanese red ink and stitch each ability animation fully."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
PARENT = (
    ADVANCE_ROOT
    / "outputs"
    / "20260905_ggen_advance_stage_titles"
    / "ggen_advance_stage_entry_titles_ko_candidate_20260905.gba"
)
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_overlays_20260905"
TURN = 0x08165044
ABILITY = 0x083424A0
FACE = {6, 7, 8, 9}
OUTLINE = {15}
SHADOW = {1, 4, 5}


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_tile(raw: bytes) -> list[list[int]]:
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def palette_rgb(raw: bytes) -> list[tuple[int, int, int]]:
    return [tuple(((u16(raw, i * 2) >> s) & 31) * 255 // 31 for s in (0, 5, 10)) for i in range(16)]


def header(rom: bytes, address: int) -> dict[str, int]:
    off = address - ROM_BASE
    kind, pal_count, gfx_rel, pal_rel, anim_count = struct.unpack_from("<5I", rom, off)
    return {
        "off": off, "pal_count": pal_count, "gfx_rel": gfx_rel, "pal_rel": pal_rel,
        "anim_count": anim_count, "tiles": (pal_rel - gfx_rel) // 32,
    }


def records(rom: bytes, address: int) -> list[bytes]:
    h = header(rom, address)
    rels = [u32(rom, h["off"] + 0x14 + i * 4) for i in range(h["anim_count"])]
    starts = [h["off"] + 0x14 + rel for rel in rels]
    ends = starts[1:] + [h["off"] + h["gfx_rel"]]
    return [rom[a:b] for a, b in zip(starts, ends)]


def consecutive_runs(blob: bytes, tile_count: int, min_len: int = 4) -> list[tuple[int, int]]:
    values = list(struct.unpack_from(f"<{len(blob)//2}H", blob))
    runs = []
    i = 0
    while i < len(values):
        start = values[i]
        if start >= tile_count:
            i += 1
            continue
        length = 1
        while i + length < len(values) and values[i + length] == start + length < tile_count:
            length += 1
        if length >= min_len:
            runs.append((start, length))
        i += max(length, 1)
    # unique by start, keep longest
    best: dict[int, int] = {}
    for start, length in runs:
        best[start] = max(best.get(start, 0), length)
    merged = sorted(best.items())
    # merge runs separated by at most 2 tiles
    out = []
    for start, length in merged:
        if out and start <= out[-1][0] + out[-1][1] + 2:
            end = max(out[-1][0] + out[-1][1], start + length)
            out[-1] = (out[-1][0], end - out[-1][0])
        else:
            out.append((start, length))
    return out


def objects_from_run(start: int, count: int) -> list[dict]:
    ids = list(range(start, start + count))
    objs, width, remaining = [], 0, ids
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
                tile = decode_tile(graphics[ids[ty * tw + tx] * 32:(ids[ty * tw + tx] + 1) * 32])
                ox, oy = int(obj["x"]) + tx * 8, int(obj["y"]) + ty * 8
                for py in range(8):
                    canvas[oy + py][ox:ox + 8] = tile[py]
    return canvas


def bbox(canvas: list[list[int]], indices: set[int]) -> tuple[int, int, int, int] | None:
    pts = [(x, y) for y, row in enumerate(canvas) for x, v in enumerate(row) if v in indices]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def stroke_width(canvas: list[list[int]], indices: set[int]) -> dict[str, float]:
    h, w = len(canvas), len(canvas[0])
    rows, cols = [], []
    for y in range(h):
        run = 0
        lengths = []
        for x in range(w):
            if canvas[y][x] in indices:
                run += 1
            elif run:
                lengths.append(run)
                run = 0
        if run:
            lengths.append(run)
        if lengths:
            rows.extend(lengths)
    for x in range(w):
        run = 0
        lengths = []
        for y in range(h):
            if canvas[y][x] in indices:
                run += 1
            elif run:
                lengths.append(run)
                run = 0
        if run:
            lengths.append(run)
        if lengths:
            cols.extend(lengths)
    def stats(values: list[int]) -> dict[str, float]:
        if not values:
            return {"min": 0, "median": 0, "max": 0}
        values = sorted(values)
        return {"min": values[0], "median": values[len(values)//2], "max": values[-1], "n": len(values)}
    return {"horizontal_runs": stats(rows), "vertical_runs": stats(cols)}


def render_canvas(canvas: list[list[int]], colors: list[tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", (len(canvas[0]), len(canvas)))
    image.putdata([colors[v] for row in canvas for v in row])
    return image


def main() -> int:
    rom = PARENT.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    th = header(rom, TURN)
    ah = header(rom, ABILITY)
    tgfx = rom[th["off"] + th["gfx_rel"]:th["off"] + th["pal_rel"]]
    agfx = rom[ah["off"] + ah["gfx_rel"]:ah["off"] + ah["pal_rel"]]
    tpal = rom[th["off"] + th["pal_rel"] + 3 * 32:th["off"] + th["pal_rel"] + 4 * 32]
    apal = rom[ah["off"] + ah["pal_rel"]:ah["off"] + ah["pal_rel"] + 32]
    tcols = palette_rgb(tpal)
    acols = palette_rgb(apal)

    state, _ = statefmt.parse_png_state(PARENT.with_suffix(".ss2"))
    mapping = json.loads((OUT / "ss2_live_banner_mapping.json").read_text(encoding="utf-8"))
    # Reconstruct full live banner in palette indices.
    x0 = min(row["x"] for row in mapping if row["oam"] != 0)
    y0 = min(row["y"] for row in mapping if row["oam"] != 0)
    x1 = max(row["x"] + row["w"] for row in mapping if row["oam"] != 0)
    y1 = max(row["y"] + row["h"] for row in mapping if row["oam"] != 0)
    banner = [[0] * (x1 - x0) for _ in range(y1 - y0)]
    for row in mapping:
        if row["oam"] == 0:
            continue
        ids = [max(0, i) for i in row["sources"]]
        tw, tht = row["w"] // 8, row["h"] // 8
        for ty in range(tht):
            for tx in range(tw):
                src = ids[ty * tw + tx]
                tile = decode_tile(tgfx[src * 32:(src + 1) * 32])
                ox = row["x"] - x0 + tx * 8
                oy = row["y"] - y0 + ty * 8
                for py in range(8):
                    for px in range(8):
                        if 0 <= oy + py < len(banner) and 0 <= ox + px < len(banner[0]):
                            banner[oy + py][ox + px] = tile[py][px]

    regions = {
        "turn": (mapping[6]["x"] - x0, mapping[6]["y"] - y0, mapping[6]["x"] - x0 + mapping[6]["w"], mapping[6]["y"] - y0 + mapping[6]["h"]),
        "enemy": (mapping[5]["x"] - x0, mapping[5]["y"] - y0, mapping[5]["x"] - x0 + 40, mapping[5]["y"] - y0 + mapping[5]["h"]),
        "attack": (mapping[4]["x"] - x0, mapping[4]["y"] - y0, mapping[3]["x"] - x0 + mapping[3]["w"], mapping[3]["y"] - y0 + mapping[3]["h"]),
    }
    turn_metrics = {}
    for name, (rx0, ry0, rx1, ry1) in regions.items():
        crop = [row[rx0:rx1] for row in banner[ry0:ry1]]
        counts = Counter(v for row in crop for v in row if v)
        turn_metrics[name] = {
            "box": [rx0, ry0, rx1, ry1],
            "size": [rx1 - rx0, ry1 - ry0],
            "index_counts": {str(k): int(v) for k, v in sorted(counts.items())},
            "face_bbox": bbox(crop, FACE),
            "outline_bbox": bbox(crop, OUTLINE),
            "shadow_bbox": bbox(crop, SHADOW),
            "face_stroke": stroke_width(crop, FACE),
            "all_ink_bbox": bbox(crop, set(range(1, 16))),
        }
        render_canvas(crop, tcols).resize(((rx1-rx0)*4, (ry1-ry0)*4), Image.Resampling.NEAREST).save(OUT / f"jp_turn_{name}_x4.png")

    recs = records(rom, ABILITY)
    ability_rows = []
    sheet_h = 8
    previews = []
    for index, blob in enumerate(recs):
        runs = consecutive_runs(blob, ah["tiles"], min_len=4)
        # Prefer the longest merged run; if several, concatenate nearby into one canvas left-to-right.
        canvases = []
        for start, count in runs:
            objs = objects_from_run(start, count)
            canvases.append((start, count, canvas_from_objects(agfx, objs), objs))
        if not canvases:
            ability_rows.append({"anim": index, "runs": [], "record_bytes": len(blob)})
            continue
        # Build a combined strip if multiple runs.
        total_w = sum(len(c[2][0]) + 4 for c in canvases) - 4
        height = max(len(c[2]) for c in canvases)
        combined = [[0] * total_w for _ in range(height)]
        x = 0
        for start, count, canvas, objs in canvases:
            for y, row in enumerate(canvas):
                combined[y][x:x + len(row)] = row
            x += len(canvas[0]) + 4
        img = render_canvas(combined, acols)
        scaled = img.resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST)
        scaled.save(OUT / f"ability_anim_{index:02d}_full.png")
        previews.append((index, scaled, runs))
        sheet_h += scaled.height + 18
        ability_rows.append({
            "anim": index,
            "group": index // 3,
            "frame": index % 3,
            "record_bytes": len(blob),
            "runs": [{"start": s, "count": c, "width": len(cv[0]), "height": len(cv)} for s, c, cv, _o in canvases],
            "combined_size": [total_w, height],
        })

    sheet = Image.new("RGB", (900, sheet_h), (16, 16, 20))
    draw = ImageDraw.Draw(sheet)
    y = 4
    groups = [
        "分身", "フェイズシフト装甲", "ラミネート装甲", "ビームコート", "Iフィールド",
        "Pディフェンサー", "FFバリア", "group7", "月光蝶", "光の翼",
    ]
    for index, scaled, runs in previews:
        label = f"anim {index:02d}  group {index//3} {groups[index//3]}  runs {runs}"
        draw.text((8, y), label, fill=(255, 255, 255))
        sheet.paste(scaled, (8, y + 12))
        y += scaled.height + 18
    sheet.save(OUT / "ability_anims_full_sheet.png")

    report = {"turn_metrics": turn_metrics, "ability_animations": ability_rows}
    (ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_remeasure_20260905.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "turn_metrics": turn_metrics,
        "ability_groups": [
            {
                "group": g,
                "label": groups[g],
                "frames": [row for row in ability_rows if row.get("group") == g],
            }
            for g in range(10)
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
