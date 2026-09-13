#!/usr/bin/env python3
"""Trace the post-load confirmation popup in the fresh mGBA ss1 state.

The popup has two 80x16 command rows plus a frame.  The upper row is the
normal/yellow ロード実行 entry and the lower row is the focused/blue
キャンセル entry in the supplied state.  This analyzer binds the live OBJ
VRAM tiles back to ROM resource candidates without modifying the ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_STATE = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_followup_candidate_20260831.ss1"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_load_confirm_popup_state_20260831.json"

FRAME_TILES = list(range(0, 26))
FOCUS_TILES = list(range(26, 46))
NORMAL_TILES = list(range(46, 66))


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def find_all(data: bytes, needle: bytes, limit: int = 64) -> list[int]:
    hits: list[int] = []
    start = 0
    while len(hits) < limit:
        found = data.find(needle, start)
        if found < 0:
            break
        hits.append(found)
        start = found + 1
    return hits


def try_kind2(rom: bytes, offset: int) -> dict[str, Any] | None:
    if not (0 <= offset <= len(rom) - 16):
        return None
    kind, dimensions, header_bytes, map_bytes, graphics_rel, graphics_bytes, palette_rel, palette_bytes = struct.unpack_from("<8H", rom, offset)
    if kind != 2 or header_bytes not in (0x10, 0x14):
        return None
    width, height = dimensions & 0xFF, dimensions >> 8
    if not (1 <= width <= 64 and 1 <= height <= 64):
        return None
    if graphics_bytes == 0 or graphics_bytes % 32:
        return None
    if graphics_rel < header_bytes or offset + graphics_rel + graphics_bytes > len(rom):
        return None
    return {
        "kind": 2,
        "offset": offset,
        "address": ROM_BASE + offset,
        "size": [width, height],
        "graphics_offset": offset + graphics_rel,
        "graphics_bytes": graphics_bytes,
        "tile_count": graphics_bytes // 32,
        "palette_offset": offset + palette_rel,
        "palette_bytes": palette_bytes,
    }


def try_kind0_sprite(rom: bytes, offset: int) -> dict[str, Any] | None:
    if not (0 <= offset <= len(rom) - 0x18):
        return None
    if u32(rom, offset) != 0 or u32(rom, offset + 4) != 6:
        return None
    graphics_rel = u32(rom, offset + 8)
    palette_rel = u32(rom, offset + 0x0C)
    animation_count = u32(rom, offset + 0x10)
    if not (1 <= animation_count <= 64):
        return None
    if not (0x18 <= graphics_rel < palette_rel <= 0x10000):
        return None
    if (palette_rel - graphics_rel) % 32:
        return None
    if offset + palette_rel > len(rom):
        return None
    rel_table_end = offset + 0x14 + animation_count * 4
    if rel_table_end > offset + graphics_rel:
        return None
    return {
        "kind": 0,
        "offset": offset,
        "address": ROM_BASE + offset,
        "graphics_offset": offset + graphics_rel,
        "graphics_bytes": palette_rel - graphics_rel,
        "tile_count": (palette_rel - graphics_rel) // 32,
        "palette_offset": offset + palette_rel,
        "animation_count": animation_count,
    }


def nearest_resources(rom: bytes, hit: int) -> list[dict[str, Any]]:
    found: dict[tuple[int, int], dict[str, Any]] = {}
    for back in range(0, 0x5000, 2):
        offset = hit - back
        if offset < 0:
            break
        for parser in (try_kind2, try_kind0_sprite):
            row = parser(rom, offset)
            if row is None:
                continue
            start = int(row["graphics_offset"])
            end = start + int(row["graphics_bytes"])
            if start <= hit < end:
                row = dict(row)
                row["tile_index"] = (hit - start) // 32
                found[(int(row["kind"]), int(row["offset"]))] = row
        if len(found) >= 6:
            break
    return sorted(found.values(), key=lambda row: (abs(hit - int(row["graphics_offset"])), int(row["offset"])))[:8]


def live_tile(obj: bytes, tile: int) -> bytes:
    start = tile * 32
    gate(start + 32 <= len(obj), f"OBJ tile {tile} outside live OBJ VRAM")
    return bytes(obj[start:start + 32])


def scan_lzss(jp: bytes, lookup: dict[bytes, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for off in range(0, min(len(jp), 0x01000000) - 8, 4):
        header = u32(jp, off)
        if (header & 0xFFFF0000) != 0x80000000:
            continue
        body_len = header & 0xFFFF
        if body_len < 16 or off + 4 + body_len > len(jp):
            continue
        try:
            decoded = scan.lzss_decompress(jp[off + 4:off + 4 + body_len])
        except (ValueError, IndexError):
            continue
        if len(decoded) < 32 or len(decoded) % 32 or len(decoded) // 32 > 4096:
            continue
        matched: list[dict[str, Any]] = []
        for tile in range(len(decoded) // 32):
            label = lookup.get(decoded[tile * 32:tile * 32 + 32])
            if label is not None:
                matched.append({"label": label, "decoded_tile": tile})
        if matched:
            rows.append({"offset": off, "address": ROM_BASE + off, "decoded_tiles": len(decoded) // 32, "matched": matched})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    gate(args.state.is_file(), f"state missing: {args.state}")
    state, chunks = statefmt.parse_png_state(args.state)
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    palette = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    obj = vram[statefmt.OBJ_VRAM:]
    dispcnt = u16(io, 0)
    gate(dispcnt & 0x1000, "OBJ layer disabled in state")
    gate(dispcnt & 0x40, "state is not OBJ 1D mapping")

    visible = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            visible.append(row)
    gate(len(visible) == 14, f"unexpected popup visible OAM count: {len(visible)}")
    gate([int(row["tile"]) for row in visible[8:11]] == [26, 34, 42], "focus row OAM tile ownership drift")
    gate([int(row["tile"]) for row in visible[11:14]] == [46, 54, 62], "normal row OAM tile ownership drift")

    jp = JP_ROM.read_bytes()
    main_rom = MAIN_TIP_ROM.read_bytes()
    groups = {
        "frame": FRAME_TILES,
        "focus_cancel": FOCUS_TILES,
        "normal_load_execute": NORMAL_TILES,
    }
    lookup: dict[bytes, str] = {}
    reports: dict[str, Any] = {}
    for group, tiles in groups.items():
        group_rows = []
        for tile in tiles:
            raw = live_tile(obj, tile)
            label = f"{group}[{tile - tiles[0]}]"
            lookup.setdefault(raw, label)
            jp_hits = find_all(jp, raw)
            main_hits = find_all(main_rom, raw)
            group_rows.append({
                "obj_tile": tile,
                "sha256": sha256(raw),
                "jp_hits": jp_hits,
                "main_hits": main_hits,
                "jp_resources": [nearest_resources(jp, hit) for hit in jp_hits[:8]],
            })
        blob = b"".join(live_tile(obj, tile) for tile in tiles)
        reports[group] = {
            "obj_tiles": tiles,
            "blob_sha256": sha256(blob),
            "jp_blob_hits": find_all(jp, blob),
            "main_blob_hits": find_all(main_rom, blob),
            "tiles": group_rows,
        }

    lzss = scan_lzss(jp, lookup)
    result = {
        "schema_version": 1,
        "kind": "ggen_advance_load_confirm_popup_state_20260831",
        "result": "PASS",
        "state": {
            "path": str(args.state.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "sha256": sha256(args.state.read_bytes()),
            "chunks": [row["kind"] for row in chunks],
            "dispcnt": f"0x{dispcnt:04X}",
            "obj_mapping": "1D",
            "visible_oam": visible,
        },
        "semantic_binding": {
            "focus_blue": {"label": "キャンセル", "obj_tiles": FOCUS_TILES, "palette_bank": 1, "screen_rect": [88, 84, 80, 16]},
            "normal_yellow": {"label": "ロード実行", "obj_tiles": NORMAL_TILES, "palette_bank": 0, "screen_rect": [88, 68, 80, 16]},
            "frame": {"obj_tiles": FRAME_TILES, "palette_bank": 2},
        },
        "palette_banks": {
            str(bank): [f"0x{u16(palette, 0x200 + (bank * 16 + index) * 2):04X}" for index in range(16)]
            for bank in (0, 1, 2)
        },
        "rom_match": reports,
        "lzss_matches": lzss,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "state_sha256": result["state"]["sha256"],
        "visible_oam": [(row["index"], row["x"], row["y"], row["tile"], row["palette_bank"]) for row in visible],
        "group_blob_hits": {key: {"jp": value["jp_blob_hits"], "main": value["main_blob_hits"]} for key, value in reports.items()},
        "lzss_matches": lzss,
        "out": str(args.out),
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
