#!/usr/bin/env python3
"""Identify every turn-banner faction plate and every ability-name label."""
from __future__ import annotations

import json
import struct
import sys
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
DIMS = {
    (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
    (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
    (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
}


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_tile(raw: bytes) -> list[list[int]]:
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def encode_tile(pixels: list[list[int]]) -> bytes:
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            value = pixels[y][x] & 0xF
            index = y * 4 + x // 2
            if x & 1:
                out[index] |= value << 4
            else:
                out[index] |= value
    return bytes(out)


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


def paste_tiles(im: Image.Image, graphics: bytes, colors: list, ids: list[int], x: int, y: int, w: int, ht: int) -> None:
    tw, th = w // 8, ht // 8
    for ty in range(th):
        for tx in range(tw):
            src = ids[ty * tw + tx]
            pix = decode_tile(graphics[src * 32:(src + 1) * 32])
            for py in range(8):
                for px in range(8):
                    xx, yy = x + tx * 8 + px, y + ty * 8 + py
                    if 0 <= xx < im.width and 0 <= yy < im.height:
                        im.putpixel((xx, yy), colors[pix[py][px]])


def scan_oam(blob: bytes, max_tile: int) -> list[dict]:
    hits = []
    for off in range(0, len(blob) - 8, 2):
        attr0, attr1, attr2, pad = struct.unpack_from("<HHHH", blob, off)
        if pad not in (0, 0xFFFF):
            continue
        shape, size = (attr0 >> 14) & 3, (attr1 >> 14) & 3
        dims = DIMS.get((shape, size))
        if dims is None:
            continue
        tile = attr2 & 0x3FF
        tw, th = dims[0] // 8, dims[1] // 8
        count = tw * th
        if tile + count > 0x400:
            continue
        src_off = off + 8
        if src_off + count * 2 > len(blob):
            continue
        ids = list(struct.unpack_from(f"<{count}H", blob, src_off))
        if any(i >= max_tile for i in ids):
            continue
        if len(set(ids)) <= 1 and ids[0] in (0, 6, 7):
            continue
        x = attr1 & 0x1FF
        y = attr0 & 0xFF
        if x >= 256:
            x -= 512
        if y >= 128:
            y -= 256
        hits.append({
            "off": off, "x": x, "y": y, "w": dims[0], "h": dims[1],
            "tile": tile, "pal": (attr2 >> 12) & 0xF, "ids": ids,
        })
    return hits


def stitch_objects(graphics: bytes, colors: list, objs: list[dict], pad: int = 4) -> Image.Image:
    x0 = min(o["x"] for o in objs)
    y0 = min(o["y"] for o in objs)
    x1 = max(o["x"] + o["w"] for o in objs)
    y1 = max(o["y"] + o["h"] for o in objs)
    im = Image.new("RGB", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), colors[0])
    for obj in objs:
        paste_tiles(im, graphics, colors, obj["ids"], pad + obj["x"] - x0, pad + obj["y"] - y0, obj["w"], obj["h"])
    return im


def ability_linear_labels(graphics: bytes, colors: list) -> list[dict]:
    """Group consecutive ink tiles into 16px-tall GBA 1D objects."""
    tiles = len(graphics) // 32
    ink = []
    for i in range(tiles):
        pix = decode_tile(graphics[i * 32:(i + 1) * 32])
        ink.append(any(v not in (0,) for row in pix for v in row))
    labels = []
    i = 0
    while i < tiles:
        if not ink[i]:
            i += 1
            continue
        start = i
        while i < tiles and ink[i]:
            i += 1
        count = i - start
        # Prefer 8-tile (32x16) runs, then 4-tile (16x16), then 2-tile (8x16).
        ids = list(range(start, start + count))
        if count % 8 == 0:
            objs = []
            for n in range(count // 8):
                chunk = ids[n * 8:(n + 1) * 8]
                objs.append({"x": n * 32, "y": 0, "w": 32, "h": 16, "ids": chunk})
        elif count % 4 == 0:
            objs = []
            for n in range(count // 4):
                chunk = ids[n * 4:(n + 1) * 4]
                objs.append({"x": n * 16, "y": 0, "w": 16, "h": 16, "ids": chunk})
        elif count % 2 == 0:
            objs = []
            width = 0
            remaining = ids[:]
            while remaining:
                if len(remaining) >= 8:
                    objs.append({"x": width, "y": 0, "w": 32, "h": 16, "ids": remaining[:8]})
                    remaining = remaining[8:]
                    width += 32
                elif len(remaining) >= 4:
                    objs.append({"x": width, "y": 0, "w": 16, "h": 16, "ids": remaining[:4]})
                    remaining = remaining[4:]
                    width += 16
                else:
                    objs.append({"x": width, "y": 0, "w": 8, "h": 16, "ids": remaining[:2]})
                    remaining = remaining[2:]
                    width += 8
        else:
            continue
        im = stitch_objects(graphics, colors, objs)
        labels.append({"start": start, "count": count, "objects": objs, "image": im})
    return labels


def main() -> int:
    rom = PARENT.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    th = header(rom, TURN)
    ah = header(rom, ABILITY)
    tgfx = rom[th["off"] + th["gfx_rel"]:th["off"] + th["pal_rel"]]
    agfx = rom[ah["off"] + ah["gfx_rel"]:ah["off"] + ah["pal_rel"]]
    tpals = [rom[th["off"] + th["pal_rel"] + i * 32:th["off"] + th["pal_rel"] + (i + 1) * 32] for i in range(th["pal_count"])]
    apal = rom[ah["off"] + ah["pal_rel"]:ah["off"] + ah["pal_rel"] + 32]
    acols = palette_rgb(apal)

    # Ability labels from consecutive ink.
    labels = ability_linear_labels(agfx, acols)
    sheet_w = max(item["image"].width for item in labels) * 4 + 160
    sheet_h = sum(item["image"].height * 4 + 20 for item in labels) + 8
    sheet = Image.new("RGB", (sheet_w, sheet_h), (16, 16, 20))
    draw = ImageDraw.Draw(sheet)
    y = 4
    catalog = []
    for n, item in enumerate(labels):
        scaled = item["image"].resize((item["image"].width * 4, item["image"].height * 4), Image.Resampling.NEAREST)
        draw.text((8, y), f"{n:02d} tiles {item['start']}..{item['start']+item['count']-1} n={item['count']}", fill=(255, 255, 255))
        sheet.paste(scaled, (150, y))
        item["image"].resize((item["image"].width * 6, item["image"].height * 6), Image.Resampling.NEAREST).save(OUT / f"ability_label_{n:02d}.png")
        catalog.append({"index": n, "start": item["start"], "count": item["count"], "width": item["image"].width, "objects": [{k: v for k, v in o.items() if k != "ids"} | {"ids": o["ids"]} for o in item["objects"]]})
        y += scaled.height + 20
    sheet.save(OUT / "ability_labels_sheet.png")

    # Turn: reconstruct live OAM with palettes 0 and 3, plus unused-tile sheet.
    state, _ = statefmt.parse_png_state(PARENT.with_suffix(".ss2"))
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    mapping = json.loads((OUT / "ss2_live_banner_mapping.json").read_text(encoding="utf-8"))
    used = sorted({i for row in mapping for i in row["sources"] if i >= 0})
    unused = [i for i in range(th["tiles"]) if i not in used]
    for pal_i, pal in enumerate(tpals):
        colors = palette_rgb(pal)
        im = Image.new("RGB", (240, 160), colors[0])
        for row in mapping:
            if any(i < 0 for i in row["sources"]):
                # Skip the digit object that is not in this resource.
                if row["oam"] == 0:
                    continue
            paste_tiles(im, tgfx, colors, [max(0, i) for i in row["sources"]], row["x"], row["y"], row["w"], row["h"])
        im.resize((720, 480), Image.Resampling.NEAREST).save(OUT / f"turn_live_pal{pal_i}_x3.png")

    # Unused turn tiles as 16-col sheet per palette 0 and 3.
    for pal_i in (0, 3):
        colors = palette_rgb(tpals[pal_i])
        cols = 16
        rows = (len(unused) + cols - 1) // cols
        im = Image.new("RGB", (cols * 9 + 8, rows * 9 + 8), (12, 12, 16))
        for n, tile in enumerate(unused):
            pix = decode_tile(tgfx[tile * 32:(tile + 1) * 32])
            for py in range(8):
                for px in range(8):
                    im.putpixel((4 + (n % cols) * 9 + px, 4 + (n // cols) * 9 + py), colors[pix[py][px]])
        im.resize((im.width * 3, im.height * 3), Image.Resampling.NEAREST).save(OUT / f"turn_unused_pal{pal_i}_x3.png")

    # Search each turn animation for 64x32 objects whose source ids are not the live 敵軍 set.
    recs = records(rom, TURN)
    live_bottom_left = set(mapping[5]["sources"])
    anim_report = []
    for index, blob in enumerate(recs):
        hits = scan_oam(blob, th["tiles"])
        # Keep only large text-like objects.
        big = [h for h in hits if h["w"] >= 32 and h["h"] >= 16 and len(set(h["ids"]) - {6, 7}) >= 8]
        unique_sets = []
        seen = set()
        for h in big:
            key = tuple(h["ids"])
            if key in seen:
                continue
            seen.add(key)
            unique_sets.append(h)
        anim_report.append({
            "index": index,
            "record_bytes": len(blob),
            "unique_big_objects": len(unique_sets),
            "sample": [
                {"x": h["x"], "y": h["y"], "w": h["w"], "h": h["h"], "id_min": min(h["ids"]), "id_max": max(h["ids"]), "new_vs_live_left": sorted(set(h["ids"]) - live_bottom_left - {6, 7})[:12]}
                for h in unique_sets[:8]
            ],
        })
        if unique_sets:
            colors = palette_rgb(tpals[0 if index in (0, 2) else 3])
            # Prefer objects near live banner layout.
            im = stitch_objects(tgfx, colors, unique_sets[:12])
            im.resize((im.width * 2, im.height * 2), Image.Resampling.NEAREST).save(OUT / f"turn_anim{index}_scan.png")

    # Nearby pointer context for both resources.
    turn_ptr = rom.find(struct.pack("<I", TURN))
    abil_ptr = rom.find(struct.pack("<I", ABILITY))
    report = {
        "ability_labels": catalog,
        "ability_label_count": len(catalog),
        "turn_used_tiles": used,
        "turn_unused_tiles": unused,
        "turn_anim_scan": anim_report,
        "turn_pointer_context": rom[max(0, turn_ptr - 16):turn_ptr + 20].hex(),
        "ability_pointer_context": rom[max(0, abil_ptr - 16):abil_ptr + 20].hex(),
        "turn_ptr": f"0x{turn_ptr:08X}",
        "ability_ptr": f"0x{abil_ptr:08X}",
    }
    (ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_labels_20260905.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "ability_labels": [{k: v for k, v in row.items() if k != "objects"} | {"object_count": len(row["objects"])} for row in catalog],
        "turn_unused_count": len(unused),
        "turn_anim_scan": anim_report,
        "turn_ptr": report["turn_ptr"],
        "ability_ptr": report["ability_ptr"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
