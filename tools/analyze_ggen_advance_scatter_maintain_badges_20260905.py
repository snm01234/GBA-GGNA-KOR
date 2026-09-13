#!/usr/bin/env python3
"""Locate the live BG graphics that draw the 散開 / 維持 command badges in ss2/ss3.

The screenshots place the two badges in native screen x=32..88, y=112..159.
This analyzer binds visible BG tiles in that area to decompressed ROM streams and
reports the palette/state variants needed for normal/focus/disabled rendering.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_action_graphics_scan_20260830 as scan
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST

ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).gba"
STATES = {n: ADVANCE_ROOT / f"SD Gundam GGeneration Advance (Korean).ss{n}" for n in (2, 3)}
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_scatter_maintain_badges_20260905.json"
RECT = (24, 108, 96, 160)


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def live_tiles(state: bytes, layer: int) -> list[dict]:
    info = bg.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    x0, y0, x1, y1 = RECT
    rows = []
    for sy in range(y0 // 8 * 8, y1, 8):
        for sx in range(x0 // 8 * 8, x1, 8):
            wx, wy = sx + info["scroll_x"], sy + info["scroll_y"]
            entry = bg.map_entry(vram, info["screen_base"], info["size"], wx // 8, wy // 8)
            tid = entry & 0x3FF
            bank = (entry >> 12) & 0xF
            if info["color_8bpp"]:
                raw = bytes(vram[info["char_base"] + tid * 64:info["char_base"] + (tid + 1) * 64])
                nonzero = sum(b != 0 for b in raw)
            else:
                raw = bytes(vram[info["char_base"] + tid * 32:info["char_base"] + (tid + 1) * 32])
                nonzero = sum(((b & 0xF) != 0) + ((b >> 4) != 0) for b in raw)
            rows.append({
                "screen": [sx, sy], "tile": tid, "entry": entry, "palette_bank": bank,
                "raw": raw, "sha256": sha256(raw), "nonzero_pixels": nonzero,
                "palette": bytes(pal[bank * 32:(bank + 1) * 32]).hex(),
            })
    return rows


def accepted_streams(rom: bytes) -> list[dict]:
    rows = []
    for off in range(0, len(rom) - 8, 4):
        header = u32(rom, off)
        if (header & 0xFFFF0000) != 0x80000000:
            continue
        body_len = header & 0xFFFF
        if body_len < 16 or off + 4 + body_len > len(rom):
            continue
        try:
            decoded = scan.lzss_decompress(rom[off + 4:off + 4 + body_len])
        except (ValueError, IndexError):
            continue
        if len(decoded) < 32 or len(decoded) % 32 or len(decoded) > 0x20000:
            continue
        rows.append({"off": off, "body_len": body_len, "decoded": decoded})
    return rows


def score_streams(streams: list[dict], raw_tiles: dict[str, bytes]) -> list[dict]:
    """Score only nonblank BG2 target tiles; BG3 is the circuit-board backdrop."""
    wanted = {
        key: raw for key, raw in raw_tiles.items()
        if ":bg2:" in key and len(raw) == 32 and any(raw)
    }
    result = []
    for stream in streams:
        decoded = stream["decoded"]
        lookup = defaultdict(list)
        for i in range(len(decoded) // 32):
            lookup[decoded[i * 32:(i + 1) * 32]].append(i)
        hits = {}
        for key, raw in wanted.items():
            if raw in lookup:
                hits[key] = lookup[raw]
        if hits:
            result.append({
                "offset": stream["off"], "body_len": stream["body_len"],
                "decoded_size": len(decoded), "decoded_tiles": len(decoded) // 32,
                "unique_live_hits": len(hits), "hits": hits,
            })
    return sorted(result, key=lambda r: (r["unique_live_hits"], -r["decoded_tiles"]), reverse=True)[:30]


def main() -> int:
    rom = ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    assert sha256(rom) == manifest["sha256"], "main TIP hash drift"
    crc = binascii.crc32(rom) & 0xFFFFFFFF

    state_reports = {}
    raw_tiles: dict[str, bytes] = {}
    for n, path in STATES.items():
        state, _ = statefmt.parse_png_state(path)
        assert u32(state, 8) == crc, f"ss{n} CRC mismatch"
        dispcnt = u16(state[statefmt.STATE_IO:statefmt.STATE_PALETTE], 0)
        layers = {}
        for layer in range(4):
            info = bg.bg_info(state, layer)
            rows = live_tiles(state, layer)
            unique = {}
            for row in rows:
                key = f"ss{n}:bg{layer}:tile{row['tile']:03X}:pal{row['palette_bank']}"
                raw_tiles.setdefault(key, row["raw"])
                unique.setdefault((row["tile"], row["palette_bank"], row["sha256"]), 0)
                unique[(row["tile"], row["palette_bank"], row["sha256"])] += 1
            layers[str(layer)] = {
                "enabled": bool(dispcnt & (0x100 << layer)),
                "info": info,
                "nonzero_pixel_sum": sum(r["nonzero_pixels"] for r in rows),
                "unique_tiles": [
                    {"tile": t, "palette_bank": p, "sha256": h, "uses": count}
                    for (t, p, h), count in sorted(unique.items())
                ],
                "cells": [{k: v for k, v in r.items() if k not in ("raw", "palette")} for r in rows],
            }
        state_reports[str(n)] = {"dispcnt": f"0x{dispcnt:04X}", "layers": layers}

    streams = accepted_streams(rom)
    scored = score_streams(streams, raw_tiles)
    raw_hits = {}
    for key, raw in raw_tiles.items():
        if len(raw) != 32:
            continue
        hits = []
        start = 0
        while True:
            pos = rom.find(raw, start)
            if pos < 0:
                break
            hits.append(pos)
            start = pos + 1
            if len(hits) >= 16:
                break
        if hits:
            raw_hits[key] = hits

    out = {
        "kind": "ggen_advance_scatter_maintain_badges_20260905",
        "rect": list(RECT),
        "main_tip_sha256": sha256(rom),
        "states": state_reports,
        "stream_count": len(streams),
        "stream_matches": scored,
        "direct_raw_hits": raw_hits,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    matrices = {}
    for n, path in STATES.items():
        state, _ = statefmt.parse_png_state(path)
        rows = live_tiles(state, 2)
        matrix = []
        ys = sorted({r["screen"][1] for r in rows})
        xs = sorted({r["screen"][0] for r in rows})
        by_xy = {tuple(r["screen"]): r for r in rows}
        for y in ys:
            matrix.append([f"{by_xy[(x,y)]['tile']:03X}/p{by_xy[(x,y)]['palette_bank']}" for x in xs])
        matrices[str(n)] = {"xs": xs, "ys": ys, "matrix": matrix}
    print(json.dumps({
        "rect": list(RECT),
        "state_layers": {
            n: {l: {"enabled": x["enabled"], "nonzero": x["nonzero_pixel_sum"], "tiles": len(x["unique_tiles"])} for l, x in s["layers"].items()}
            for n, s in state_reports.items()
        },
        "bg2_matrices": matrices,
        "top_stream_matches": [{k: v for k, v in r.items() if k != "hits"} for r in scored[:12]],
        "top_stream_hit_keys": {hex(r["offset"]): sorted(r["hits"]) for r in scored[:5]},
        "direct_raw_hit_keys": len(raw_hits),
        "out": str(OUT.relative_to(ADVANCE_ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
