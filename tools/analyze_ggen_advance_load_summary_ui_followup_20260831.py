#!/usr/bin/env python3
"""Read-only follow-up analysis for the post-stage/load-summary fixed BG labels.

Uses the approved main TIP plus the supplied mGBA ss1.  It reports every
non-transparent tile-column segment in the five visible fixed-label bands of
resource 0x08C7994C, so the Japanese データロード / ゲームモード ownership can
be separated instead of inferred from the screenshot text.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import MAIN_TIP_ROM

RESOURCE = 0x08C7994C
STATE = ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
OUT = ROOT / "analysis" / "ggen_advance_load_summary_ui_followup_20260831.json"

BANDS = {
    "top_title": (1, 4),
    "clear_row": (4, 7),
    "next_row": (7, 10),
    "play_and_mode_row": (10, 13),
    "load_row": (13, 18),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile size drift")
    pixels = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            pixels[y][x] = (value >> (4 * (x & 1))) & 0x0F
    return pixels


def stitch(resource: dict, atlas: bytes) -> list[list[int]]:
    width, height = int(resource["width"]), int(resource["height"])
    canvas = [[0] * (width * 8) for _ in range(height * 8)]
    for ty in range(height):
        for tx in range(width):
            tile_id = int(resource["cells"][ty * width + tx]) & 0x03FF
            raw = atlas[tile_id * 32 : (tile_id + 1) * 32]
            tile = decode_tile(raw)
            for y in range(8):
                canvas[ty * 8 + y][tx * 8 : tx * 8 + 8] = tile[y]
    return canvas


def runs(values: list[int]) -> list[tuple[int, int]]:
    if not values:
        return []
    out: list[tuple[int, int]] = []
    start = previous = values[0]
    for value in values[1:]:
        if value != previous + 1:
            out.append((start, previous + 1))
            start = value
        previous = value
    out.append((start, previous + 1))
    return out


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    resource = bg.parse_bg_resource(rom, RESOURCE)
    off = int(resource["file_offset"])
    tiles_rel = int(resource["tiles_relative_offset"])
    comp_len = int(resource["compressed_tile_length"])
    atlas = bg.custom_lzss_decompress(rom[off + tiles_rel : off + tiles_rel + comp_len])
    gate(len(atlas) == int(resource["decoded_tiles"]) * 32, "decoded atlas size drift")
    canvas = stitch(resource, atlas)

    state, _chunks = statefmt.parse_png_state(STATE)
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    bg1cnt = struct.unpack_from("<H", io, 10)[0]
    screenblock = (bg1cnt >> 8) & 31
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    live_cells = [
        struct.unpack_from("<H", vram, screenblock * 0x800 + (y * 32 + x) * 2)[0]
        for y in range(20) for x in range(30)
    ]
    gate(all((a & 0x03FF) == (int(b) & 0x03FF) for a, b in zip(live_cells, resource["cells"])), "state/source tilemap mismatch")

    report_bands = {}
    for name, (ty0, ty1) in BANDS.items():
        cols = []
        tile_counts = []
        for tx in range(30):
            counter = Counter()
            for py in range(ty0 * 8, ty1 * 8):
                for px in range(tx * 8, tx * 8 + 8):
                    counter[canvas[py][px]] += 1
            if sum(v for k, v in counter.items() if k != 0):
                cols.append(tx)
                tile_counts.append({
                    "x": tx,
                    "tile_ids": [
                        f"0x{(int(resource['cells'][ty * 30 + tx]) & 0x03FF):03X}"
                        for ty in range(ty0, ty1)
                    ],
                    "nonzero": {str(k): v for k, v in sorted(counter.items()) if k != 0},
                })
        pixel_cols = [
            px for px in range(30 * 8)
            if any(canvas[py][px] != 0 for py in range(ty0 * 8, ty1 * 8))
        ]
        report_bands[name] = {
            "tile_y_range": [ty0, ty1],
            "nontransparent_column_runs": [[a, b] for a, b in runs(cols)],
            "nontransparent_pixel_x_runs": [[a, b] for a, b in runs(pixel_cols)],
            "columns": tile_counts,
        }

    payload = {
        "schema_version": 1,
        "kind": "ggen_advance_load_summary_ui_followup_20260831",
        "result": "PASS",
        "resource": f"0x{RESOURCE:08X}",
        "decoded_tiles": int(resource["decoded_tiles"]),
        "state_tilemap_exact": True,
        "bands": report_bands,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(OUT),
        "runs": {key: value["nontransparent_column_runs"] for key, value in report_bands.items()},
        "pixel_runs": {key: value["nontransparent_pixel_x_runs"] for key, value in report_bands.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
