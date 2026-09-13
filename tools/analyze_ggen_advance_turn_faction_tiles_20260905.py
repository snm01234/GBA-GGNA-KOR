#!/usr/bin/env python3
"""Find 自軍 / 友軍 unique tiles in turn-banner resource 0x08165044."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as sprite
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

ROM_BASE = 0x08000000
TURN = 0x08165044
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_overlays_20260905"
DIMS = {
    (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
    (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
    (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
}
ENEMY_UNIQUE = set(range(108, 124))
ENEMY_SHARED = {56, 57, 58, 62, 63, 64, 69, 70, 71, 76, 77, 78}
FILLER = {6, 7}


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
    colors = []
    for i in range(16):
        value = struct.unpack_from("<H", raw, i * 2)[0]
        colors.append(tuple(((value >> s) & 31) * 255 // 31 for s in (0, 5, 10)))
    return colors


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


def scan_64x32(blob: bytes, tile_count: int) -> list[dict]:
    hits = []
    for off in range(0, len(blob) - 8, 2):
        attr0, attr1, attr2, pad = struct.unpack_from("<HHHH", blob, off)
        if pad not in (0, 0xFFFF):
            continue
        shape, size = (attr0 >> 14) & 3, (attr1 >> 14) & 3
        dims = DIMS.get((shape, size))
        if dims != (64, 32):
            continue
        src_off = off + 8
        if src_off + 32 * 2 > len(blob):
            continue
        ids = list(struct.unpack_from("<32H", blob, src_off))
        if any(i >= tile_count for i in ids):
            continue
        if len(set(ids) - FILLER) < 8:
            continue
        x = attr1 & 0x1FF
        y = attr0 & 0xFF
        if x >= 256:
            x -= 512
        if y >= 128:
            y -= 256
        hits.append({"off": off, "x": x, "y": y, "ids": ids})
    # unique by id tuple
    uniq = []
    seen = set()
    for hit in hits:
        key = tuple(hit["ids"])
        if key not in seen:
            seen.add(key)
            uniq.append(hit)
    return uniq


def render_ids(graphics: bytes, colors: list, ids: list[int], w: int, h: int) -> Image.Image:
    tw, th = w // 8, h // 8
    im = Image.new("RGB", (w, h), colors[0])
    for ty in range(th):
        for tx in range(tw):
            src = ids[ty * tw + tx]
            pix = decode_tile(graphics[src * 32:(src + 1) * 32])
            for py in range(8):
                for px in range(8):
                    im.putpixel((tx * 8 + px, ty * 8 + py), colors[pix[py][px]])
    return im


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    h = header(rom, TURN)
    gfx = rom[h["off"] + h["gfx_rel"]:h["off"] + h["pal_rel"]]
    pal0 = rom[h["off"] + h["pal_rel"]:h["off"] + h["pal_rel"] + 32]
    pal3 = rom[h["off"] + h["pal_rel"] + 3 * 32:h["off"] + h["pal_rel"] + 4 * 32]
    recs = records(rom, TURN)
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for index, blob in enumerate(recs):
        hits = scan_64x32(blob, h["tiles"])
        pal = pal0 if index in (0, 2) else pal3
        colors = palette_rgb(pal)
        rows = []
        for n, hit in enumerate(hits):
            ids = hit["ids"]
            unique = sorted(set(ids) - FILLER - ENEMY_UNIQUE - ENEMY_SHARED)
            vs_enemy = sorted(set(ids) - FILLER)
            img = render_ids(gfx, colors, ids, 64, 32)
            scaled = img.resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST)
            scaled.save(OUT / f"turn_anim{index}_obj{n:02d}_64x32.png")
            rows.append({
                "n": n, "x": hit["x"], "y": hit["y"],
                "ids": ids,
                "unique_vs_enemy_template": unique,
                "all_nonfiller": vs_enemy,
            })
        report.append({"anim": index, "bytes": len(blob), "objects": rows})
    (ADVANCE_ROOT / "analysis" / "ggen_advance_turn_faction_tiles_20260905.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps([
        {
            "anim": row["anim"],
            "count": len(row["objects"]),
            "samples": [
                {
                    "n": o["n"], "x": o["x"], "y": o["y"],
                    "unique_vs_enemy_template": o["unique_vs_enemy_template"],
                    "id_min_max": [min(o["ids"]), max(o["ids"])],
                }
                for o in row["objects"][:8]
            ],
        }
        for row in report
    ], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
