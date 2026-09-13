#!/usr/bin/env python3
"""Prove live battle-forecast 回避 ownership from the Korean mGBA savestate.

The visible 40x16 badge at (32,112) is two OBJ sprites, not BtlCmd text and
not BG2.  Their OBJ VRAM tiles are byte-identical to sprite resource
0x08A8C004 tiles 35-44.  The same resource stores the live ID badge (tiles
45-54, left untouched) and one more 40x16 Japanese badge at tiles 55-64.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM
import analyze_ggen_advance_mgba_battle_ui_savestate as battle_ss

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_forecast_evade_obj_20260831.json"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

ROM_BASE = 0x08000000
RESOURCE_OFFSET = 0x00A8C004
RESOURCE_ADDRESS = ROM_BASE + RESOURCE_OFFSET
RESOURCE_LITERAL = 0x00039638
GRAPHICS_REL = 0x0FD0
PALETTE_REL = 0x17F0
GRAPHICS_OFFSET = RESOURCE_OFFSET + GRAPHICS_REL
PALETTE_OFFSET = RESOURCE_OFFSET + PALETTE_REL
TILE_COUNT = 65
TILE_BYTES = 32

# Live 1D OBJ destination measured from the current Korean ss1.
EVADE_OAM = ((33, 32, 112, 32, 16, 224, 12), (34, 64, 112, 8, 16, 232, 12))
ID_OAM = ((35, 40, 128, 32, 16, 240, 13), (36, 72, 128, 8, 16, 248, 13))
EVADE_OBJ_TILES = tuple(range(224, 234))
ID_OBJ_TILES = tuple(range(240, 250))
EVADE_SRC_TILES = tuple(range(35, 45))
ID_SRC_TILES = tuple(range(45, 55))
EXTRA_SRC_TILES = tuple(range(55, 65))

STATE_SIZE = 0x61000
STATE_IO = 0x00400
STATE_OAM = 0x00C00
STATE_VRAM = 0x01000
STATE_IWRAM = 0x19000
VRAM_SIZE = 0x18000
OBJ_VRAM = 0x10000
FONT_12_BASE = 0x0008AC40
FONT_12_STRIDE = 18

# 12x12 slots from the identified charmap, used only to name the extra badge.
GLYPH_SLOTS = {
    "回": 0x01B9,
    "避": 0x05C8,
    "継": 0x0295,
    "続": 0x04A4,
    "待": 0x04B7,
    "機": 0x00A8,
    "回2": 0x01A3,
    "復": 0x0519,
}
FACE_INDEX = 11
SHADOW_INDEX = 1
HIGHLIGHT_INDEX = 10
FRAME_INDICES = frozenset({0, 6, 7, 8, 9})
# Paint Korean only inside the well.  Japanese 避 leaks one column into the
# right cap, so erase must include x=32 even though we do not redraw there.
INTERIOR_X = (5, 31)
ERASE_X = (5, 32)
ERASE_Y = (1, 14)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == TILE_BYTES, "4bpp tile must be 32 bytes")
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def encode_tile(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 8 and all(len(row) == 8 for row in pixels), "8x8 tile shape mismatch")
    out = bytearray(TILE_BYTES)
    for y in range(8):
        for x in range(8):
            index = y * 4 + (x >> 1)
            value = pixels[y][x] & 0xF
            if x & 1:
                out[index] = (out[index] & 0x0F) | (value << 4)
            else:
                out[index] = (out[index] & 0xF0) | value
    return bytes(out)


def compose_40x16_1d(tiles: list[list[list[int]]]) -> list[list[int]]:
    gate(len(tiles) == 10, "40x16 badge is ten 8x8 tiles in 1D OBJ order")
    out = [[0] * 40 for _ in range(16)]
    for index in range(4):
        for y in range(8):
            for x in range(8):
                out[y][index * 8 + x] = tiles[index][y][x]
                out[8 + y][index * 8 + x] = tiles[4 + index][y][x]
    for y in range(8):
        for x in range(8):
            out[y][32 + x] = tiles[8][y][x]
            out[8 + y][32 + x] = tiles[9][y][x]
    return out


def split_40x16_1d(pixels: list[list[int]]) -> list[list[list[int]]]:
    gate(len(pixels) == 16 and all(len(row) == 40 for row in pixels), "40x16 pixel shape mismatch")
    tiles = []
    for index in range(4):
        tiles.append([row[index * 8 : index * 8 + 8] for row in pixels[:8]])
    for index in range(4):
        tiles.append([row[index * 8 : index * 8 + 8] for row in pixels[8:]])
    tiles.append([row[32:40] for row in pixels[:8]])
    tiles.append([row[32:40] for row in pixels[8:]])
    return tiles


def glyph12_mask(rom: bytes, slot: int) -> set[tuple[int, int]]:
    raw = rom[FONT_12_BASE + slot * FONT_12_STRIDE : FONT_12_BASE + slot * FONT_12_STRIDE + FONT_12_STRIDE]
    gate(len(raw) == FONT_12_STRIDE, f"12x12 slot overrun: 0x{slot:04X}")
    return {
        (x, y)
        for y in range(12)
        for x in range(12)
        if (raw[(y * 12 + x) // 8] >> ((y * 12 + x) % 8)) & 1
    }


def dice(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def best_glyph_score(face: set[tuple[int, int]], glyph: set[tuple[int, int]], x0: int, x1: int) -> dict[str, Any]:
    best = {"score": 0.0, "ox": 0, "oy": 0}
    for oy in range(-2, 5):
        for ox in range(x0 - 2, x1 - 8):
            shifted = {(x + ox, y + oy) for x, y in glyph}
            window = {(x, y) for x, y in face if x0 <= x <= x1}
            score = dice(window, shifted)
            if score > best["score"]:
                best = {"score": round(score, 6), "ox": ox, "oy": oy}
    return best


def face_pixels(pixels: list[list[int]]) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y, row in enumerate(pixels)
        for x, value in enumerate(row)
        if value == FACE_INDEX and INTERIOR_X[0] <= x <= INTERIOR_X[1]
    }


def parse_state(path: Path) -> bytes:
    data = path.read_bytes()
    gate(data.startswith(b"\x89PNG\r\n\x1a\n"), "savestate is not mGBA PNG-container format")
    pos = 8
    state = None
    while pos + 12 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        if kind == b"gbAs":
            state = zlib.decompress(payload)
        pos += 12 + length
        if kind == b"IEND":
            break
    gate(state is not None and len(state) == STATE_SIZE, "serialized GBA state missing or wrong size")
    return state


def obj_tile(vram: bytes, tile_id: int) -> bytes:
    start = OBJ_VRAM + tile_id * TILE_BYTES
    return bytes(vram[start : start + TILE_BYTES])


def resource_tile(rom: bytes, tile_id: int) -> bytes:
    start = GRAPHICS_OFFSET + tile_id * TILE_BYTES
    return bytes(rom[start : start + TILE_BYTES])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--main", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    state = parse_state(args.state)
    main_rom = args.main.read_bytes()
    jp = args.jp.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM identity drift")
    gate(len(main_rom) == 32 * 1024 * 1024, "main TIP is not 32 MiB")
    gate(sha256(main_rom) == manifest["sha256"], "main TIP/manifest hash mismatch")

    state_crc = u32(state, 0x08)
    main_crc = binascii.crc32(main_rom) & 0xFFFFFFFF
    gate(state_crc == main_crc, f"state ROM CRC 0x{state_crc:08X} != main TIP CRC 0x{main_crc:08X}")

    io = state[STATE_IO : STATE_IO + 0x400]
    oam = state[STATE_OAM:STATE_VRAM]
    vram = state[STATE_VRAM:STATE_IWRAM]
    gate(len(vram) == VRAM_SIZE, "VRAM state size mismatch")
    dispcnt = u16(io, 0)
    gate((dispcnt & 7) == 0, "forecast state is not GBA mode 0")
    gate(bool(dispcnt & 0x0040), "OBJ 1D mapping is off")
    gate(bool(dispcnt & 0x1000), "OBJ is not enabled")

    oam_rows = {row["index"]: row for row in battle_ss.active_oam_rows(oam)}
    for index, x, y, width, height, tile, pal in EVADE_OAM + ID_OAM:
        row = oam_rows[index]
        gate((row["x"], row["y"], row["width"], row["height"], row["tile"], row["palette_bank"]) == (x, y, width, height, tile, pal), f"OAM {index} drift")

    gate(u32(jp, RESOURCE_OFFSET + 0x00) == 0, "sprite resource kind drift")
    gate(u32(jp, RESOURCE_OFFSET + 0x04) == 6, "sprite resource animation/count field drift")
    gate(u32(jp, RESOURCE_OFFSET + 0x08) == GRAPHICS_REL, "sprite graphics relative offset drift")
    gate(u32(jp, RESOURCE_OFFSET + 0x0C) == PALETTE_REL, "sprite palette relative offset drift")
    gate((PALETTE_OFFSET - GRAPHICS_OFFSET) // TILE_BYTES == TILE_COUNT, "sprite tile count drift")
    gate(u32(jp, RESOURCE_LITERAL) == RESOURCE_ADDRESS, "A8C004 pointer literal drift")
    gate(main_rom[RESOURCE_OFFSET:GRAPHICS_OFFSET] == jp[RESOURCE_OFFSET:GRAPHICS_OFFSET], "main A8C004 header/frame table differs from JP")
    # Measured live palettes are the first three 16-color banks (0x60 bytes),
    # matching the 22.79 A8C004 palette gate. Later banks were already divergent.
    gate(main_rom[PALETTE_OFFSET : PALETTE_OFFSET + 0x60] == jp[PALETTE_OFFSET : PALETTE_OFFSET + 0x60], "main A8C004 live palettes differ from JP")

    evade_live = []
    id_live = []
    for obj_tile_id, src_tile in zip(EVADE_OBJ_TILES, EVADE_SRC_TILES, strict=True):
        live = obj_tile(vram, obj_tile_id)
        source = resource_tile(main_rom, src_tile)
        gate(live == source, f"live 回避 OBJ tile {obj_tile_id} != A8C004 tile {src_tile}")
        gate(source == resource_tile(jp, src_tile), f"main 回避 tile {src_tile} already differs from JP")
        evade_live.append({"obj_tile": obj_tile_id, "source_tile": src_tile, "file_offset": f"0x{GRAPHICS_OFFSET + src_tile * TILE_BYTES:08X}"})
    for obj_tile_id, src_tile in zip(ID_OBJ_TILES, ID_SRC_TILES, strict=True):
        live = obj_tile(vram, obj_tile_id)
        source = resource_tile(main_rom, src_tile)
        gate(live == source, f"live ID OBJ tile {obj_tile_id} != A8C004 tile {src_tile}")
        gate(source == resource_tile(jp, src_tile), f"main ID tile {src_tile} already differs from JP")
        id_live.append({"obj_tile": obj_tile_id, "source_tile": src_tile, "file_offset": f"0x{GRAPHICS_OFFSET + src_tile * TILE_BYTES:08X}"})

    extra_tiles = [decode_tile(resource_tile(main_rom, tile_id)) for tile_id in EXTRA_SRC_TILES]
    extra_pixels = compose_40x16_1d(extra_tiles)
    extra_face = face_pixels(extra_pixels)
    evade_pixels = compose_40x16_1d([decode_tile(resource_tile(main_rom, tile_id)) for tile_id in EVADE_SRC_TILES])
    evade_face = face_pixels(evade_pixels)

    evade_scores = {
        "回": best_glyph_score(evade_face, glyph12_mask(jp, GLYPH_SLOTS["回"]), 5, 18),
        "避": best_glyph_score(evade_face, glyph12_mask(jp, GLYPH_SLOTS["避"]), 16, 32),
    }
    extra_pairs = {
        "継続": (
            best_glyph_score(extra_face, glyph12_mask(jp, GLYPH_SLOTS["継"]), 5, 18),
            best_glyph_score(extra_face, glyph12_mask(jp, GLYPH_SLOTS["続"]), 16, 32),
        ),
        "待機": (
            best_glyph_score(extra_face, glyph12_mask(jp, GLYPH_SLOTS["待"]), 5, 18),
            best_glyph_score(extra_face, glyph12_mask(jp, GLYPH_SLOTS["機"]), 16, 32),
        ),
        "回復": (
            best_glyph_score(extra_face, glyph12_mask(jp, GLYPH_SLOTS["回"]), 5, 18),
            best_glyph_score(extra_face, glyph12_mask(jp, GLYPH_SLOTS["復"]), 16, 32),
        ),
    }
    extra_ranked = sorted(
        (
            {
                "source": name,
                "left": left,
                "right": right,
                "mean": round((left["score"] + right["score"]) / 2, 6),
            }
            for name, (left, right) in extra_pairs.items()
        ),
        key=lambda row: row["mean"],
        reverse=True,
    )
    extra_best = extra_ranked[0]
    gate(evade_scores["回"]["score"] >= 0.45 and evade_scores["避"]["score"] >= 0.45, "live badge is not 回避")
    gate(extra_best["mean"] >= 0.40, f"extra 40x16 Japanese badge identity is too weak: {extra_best}")

    extra_translations = {"継続": "계속", "待機": "대기", "回復": "회복"}
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_evade_obj_runtime_trace",
        "result": "PASS",
        "savestate": {
            "path": args.state.name,
            "sha256": sha256(args.state.read_bytes()),
            "rom_crc32": f"0x{state_crc:08X}",
            "matches_current_main_tip": True,
        },
        "main_tip": {"path": args.main.name, "sha256": sha256(main_rom), "crc32": f"0x{main_crc:08X}"},
        "video": {"DISPCNT": f"0x{dispcnt:04X}", "obj_1d_mapping": True, "owner": "OBJ sprites"},
        "resource": {
            "address": f"0x{RESOURCE_ADDRESS:08X}",
            "file_offset": f"0x{RESOURCE_OFFSET:08X}",
            "graphics_file_offset": f"0x{GRAPHICS_OFFSET:08X}",
            "tile_count": TILE_COUNT,
            "pointer_literal": f"0x{RESOURCE_LITERAL:08X}",
        },
        "live_回避": {
            "screen_px": [32, 112, 40, 16],
            "oam": [{"index": spec[0], "x": spec[1], "y": spec[2], "size": [spec[3], spec[4]], "tile": spec[5], "palette_bank": spec[6]} for spec in EVADE_OAM],
            "obj_tiles": list(EVADE_OBJ_TILES),
            "source_tiles": list(EVADE_SRC_TILES),
            "matches": evade_live,
            "glyph_scores": evade_scores,
            "face_index": FACE_INDEX,
            "shadow_fill_index": SHADOW_INDEX,
            "highlight_index": HIGHLIGHT_INDEX,
        },
        "live_ID": {
            "screen_px": [40, 128, 40, 16],
            "oam": [{"index": spec[0], "x": spec[1], "y": spec[2], "size": [spec[3], spec[4]], "tile": spec[5], "palette_bank": spec[6]} for spec in ID_OAM],
            "obj_tiles": list(ID_OBJ_TILES),
            "source_tiles": list(ID_SRC_TILES),
            "matches": id_live,
            "preserve": True,
            "note": "ID badge uses a different interior palette and must not be Koreanized.",
        },
        "similar_40x16": {
            "source_tiles": list(EXTRA_SRC_TILES),
            "file_offset": f"0x{GRAPHICS_OFFSET + EXTRA_SRC_TILES[0] * TILE_BYTES:08X}",
            "ranked_identities": extra_ranked,
            "identified_source": extra_best["source"],
            "translation": extra_translations[extra_best["source"]],
        },
        "patch_plan": {
            "回避": {"source_tiles": list(EVADE_SRC_TILES), "translation": "회피", "font": "Galmuri11.bdf native"},
            extra_best["source"]: {"source_tiles": list(EXTRA_SRC_TILES), "translation": extra_translations[extra_best["source"]], "font": "Galmuri11.bdf native"},
            "ID": {"source_tiles": list(ID_SRC_TILES), "preserve": True},
        },
        "verification": {
            "result": "PASS",
            "state_crc_matches_main_tip": True,
            "回避_obj_tiles_byte_match_A8C004": True,
            "ID_obj_tiles_byte_match_A8C004": True,
            "A8C004_header_palette_literal_gated": True,
            "回避_12x12_glyph_match": True,
            "extra_40x16_identified": extra_best["source"],
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "out": str(args.out),
                "回避": evade_scores,
                "extra": extra_best,
                "owner": "OBJ / 0x08A8C004 tiles 35-44",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
